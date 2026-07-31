"""
TestAgentProtocol — AgentProtocol backed by a FakeBus.

Records every Message injected into the 'OVOS bus' so tests can assert on it.

Reverse routing
---------------
In a live deployment the agent protocol (OVOSProtocol in ovos-bus-client/hpm.py)
subscribes to the OVOS bus and routes outgoing messages back to the originating
satellite by inspecting ``message.context["destination"]``.

TestAgentProtocol replicates this behaviour verbatim so that test assertions
against ``SatelliteNode.internal_bus`` match what a real satellite would receive.

Reference: ovos-bus-client/ovos_bus_client/hpm.py — OVOSProtocol.register_bus_handlers(),
           OVOSProtocol.handle_send(), OVOSProtocol.handle_internal_mycroft()
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from hivemind_plugin_manager.protocols import AgentProtocol


@dataclass
class TestAgentProtocol(AgentProtocol):
    """AgentProtocol backed by FakeBus; records injected messages and provides
    downstream routing so satellites receive skill responses via HiveMind."""

    bus: FakeBus = field(default_factory=FakeBus)
    injected: List[Message] = field(default_factory=list)

    def __post_init__(self):
        # shutdown() must be able to put the bus back exactly as it was, so
        # keep both the original emit and our own wrapper. Two protocols can
        # share one bus (e.g. a shared MiniCroft): each unwraps only its own
        # layer, and only while its wrapper is still the installed one.
        _orig_emit = self.bus.emit
        self._orig_emit = _orig_emit

        def _recording_emit(msg):
            if isinstance(msg, str):
                try:
                    msg = Message.deserialize(msg)
                except Exception as exc:
                    # Not a Message — it is still forwarded untouched, but a
                    # silent pass hid malformed emissions from the test author.
                    LOG.warning(
                        "TestAgentProtocol: could not deserialize a bus "
                        "emission, recording skipped: %s", exc)
            if isinstance(msg, Message):
                self.injected.append(msg)
            _orig_emit(msg)

        self.bus.emit = _recording_emit
        self._recording_emit = _recording_emit

        # Mirror OVOSProtocol.register_bus_handlers() — enables reverse routing
        # (OVOS bus messages → satellite) matching live deployment behaviour.
        self.register_bus_handlers()

    # -----------------------------------------------------------------------
    # Reverse routing — ported verbatim from
    # ovos-bus-client/ovos_bus_client/hpm.py (OVOSProtocol)
    # -----------------------------------------------------------------------

    def register_bus_handlers(self) -> None:
        """Subscribe to the agent bus for downstream routing.

        Exact port of OVOSProtocol.register_bus_handlers().
        Two paths:
        1. ``hive.send.downstream`` — explicit routing request from an OVOS component.
        2. ``message`` (catch-all) — route any message whose ``destination`` context
           matches a connected satellite peer back to that peer.
        """
        LOG.debug("TestAgentProtocol: registering bus handlers for downstream routing")
        self.bus.on("hive.send.downstream", self.handle_send)
        self.bus.on("message", self.handle_internal_mycroft)

    # -----------------------------------------------------------------------
    # natural_language_query — the AgentProtocol seam QUERY/CASCADE consume.
    # Streams speak replies correlated by a fresh query_id (query-scoped
    # session keeps them from being reverse-routed to the satellite).
    # -----------------------------------------------------------------------
    def natural_language_query(self, utterance: str, lang: str,
                               timeout: float = 10.0,
                               raise_on_timeout: bool = False):
        """Stream speak replies from the test bus, correlated by a fresh
        query-scoped session.

        Yields each answer chunk, then a final ``None`` end-of-query sentinel
        once ``ovos.utterance.handled`` arrives.

        The default behaviour matches production
        (``OVOSAgentProtocol.natural_language_query``): a timeout yields
        ``None`` — the same sentinel as a clean empty answer — because the
        ``AgentProtocol`` contract uses it to trigger escalation. Keeping that
        shape is what makes escalation testable through this harness.

        Args:
            utterance:        The query text.
            lang:             BCP-47 language tag.
            timeout:          Seconds to wait for the next chunk (production
                              uses 10.0).
            raise_on_timeout: Test-ergonomics opt-in. When ``True``, a timeout
                              raises ``TimeoutError`` instead of yielding
                              ``None``, so a stalled agent is distinguishable
                              from an empty answer.

        Raises:
            TimeoutError: Only when *raise_on_timeout* is ``True``.
        """
        import queue
        import uuid
        qid = uuid.uuid4().hex
        q: "queue.Queue" = queue.Queue()

        def _on_speak(msg):
            if isinstance(msg, str):
                try:
                    msg = Message.deserialize(msg)
                except Exception:
                    return
            if msg.msg_type == "speak" and msg.context.get("query_id") == qid:
                q.put(msg.data.get("utterance", ""))

        def _on_done(msg):
            if isinstance(msg, str):
                try:
                    msg = Message.deserialize(msg)
                except Exception:
                    return
            if msg.context.get("query_id") == qid:
                q.put(None)

        self.bus.on("speak", _on_speak)
        self.bus.on("ovos.utterance.handled", _on_done)
        try:
            self.bus.emit(Message(
                "recognizer_loop:utterance",
                {"utterances": [utterance], "lang": lang},
                {"query_id": qid, "session": {"session_id": qid}},
            ))
            while True:
                try:
                    chunk = q.get(timeout=timeout)
                except queue.Empty:
                    if raise_on_timeout:
                        raise TimeoutError(
                            f"TestAgentProtocol.natural_language_query: no reply "
                            f"chunk and no 'ovos.utterance.handled' within "
                            f"{timeout}s for utterance {utterance!r}"
                        )
                    # Production contract: a stalled agent looks like an empty
                    # answer so the caller can escalate.
                    yield None
                    return
                if chunk is None:
                    yield None
                    return
                yield chunk
        finally:
            self.bus.remove("speak", _on_speak)
            self.bus.remove("ovos.utterance.handled", _on_done)

    def handle_send(self, message: Message) -> None:
        """Route an explicit ``hive.send.downstream`` request.

        Exact port of ``OVOSAgentProtocol.handle_send()`` from
        hivemind-ovos-agent-plugin. The dispatch rules are, in order:

        1. ``PROPAGATE`` / ``BROADCAST`` — fan out to every connected peer.
        2. ``ESCALATE`` — ignored; only a slave may escalate.
        3. anything else with a ``peer`` — sent to that peer alone. This
           includes ``QUERY`` and ``CASCADE``: they are targeted here, not
           dropped and not fanned out.
        4. anything else without a ``peer`` — nothing to do.
        """
        payload = message.data.get("payload")
        peer = message.data.get("peer")
        msg_type = message.data["msg_type"]

        hmessage = HiveMessage(msg_type, payload=payload, target_peers=[peer])

        if msg_type in [HiveMessageType.PROPAGATE, HiveMessageType.BROADCAST]:
            # Fan out to every connected satellite. CASCADE is deliberately
            # NOT in this list: upstream fans out PROPAGATE/BROADCAST only.
            for p, client in self.clients.items():
                client.send(hmessage)
        elif msg_type == HiveMessageType.ESCALATE:
            # Only slaves can escalate; ignore silently when we are the master
            pass
        elif peer:
            if peer in self.clients:
                self.clients[peer].send(hmessage)
            else:
                LOG.error(f"hive.send.downstream: peer '{peer}' is not connected")
                self.bus.emit(
                    message.forward(
                        "hive.client.send.error",
                        {"error": "That client is not connected", "peer": peer},
                    )
                )

    def handle_internal_mycroft(self, message: str) -> None:
        """Forward OVOS bus messages to satellite clients when they are the destination.

        Exact port of OVOSProtocol.handle_internal_mycroft() from ovos-bus-client/hpm.py.

        The ``message`` bus event carries the raw serialised JSON string (FakeBus
        emits ``ee.emit("message", message.serialize())``).  Client isolation is
        enforced here: each satellite only receives messages whose ``destination``
        context matches its peer ID.
        """
        message = Message.deserialize(message)
        target_peers = message.context.get("destination") or []
        if not isinstance(target_peers, list):
            target_peers = [target_peers]

        if target_peers:
            for peer, client in self.clients.items():
                if peer in target_peers:
                    LOG.debug(f"TestAgentProtocol: routing {message.msg_type} → {peer}")
                    message.context["source"] = "hive"
                    msg = HiveMessage(
                        HiveMessageType.BUS,
                        source_peer=peer,
                        target_peers=target_peers,
                        payload=message,
                    )
                    client.send(msg)

    # -----------------------------------------------------------------------
    # Assertion helpers
    # -----------------------------------------------------------------------

    def last_injected(self, msg_type: str) -> Optional[Message]:
        """Return the last Message of ``msg_type`` seen on the agent bus."""
        matches = [m for m in self.injected if m.msg_type == msg_type]
        return matches[-1] if matches else None

    def assert_injected(self, msg_type: str, count: int = 1):
        """Assert exactly ``count`` messages of ``msg_type`` on the agent bus."""
        matches = [m for m in self.injected if m.msg_type == msg_type]
        assert len(matches) == count, (
            f"Expected {count}x '{msg_type}' on agent bus, got {len(matches)}. "
            f"All injected: {[m.msg_type for m in self.injected]}"
        )

    def assert_not_injected(self, msg_type: str):
        """Assert ``msg_type`` was never emitted on the agent bus."""
        matches = [m for m in self.injected if m.msg_type == msg_type]
        assert not matches, (
            f"Expected '{msg_type}' NOT on agent bus, but got {len(matches)}."
        )

    def clear(self):
        """Reset all recorded messages."""
        self.injected.clear()

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    def shutdown(self) -> None:
        """Undo everything :meth:`__post_init__` installed on the bus.

        Removes the ``hive.send.downstream`` and ``message`` handlers and
        restores the original ``bus.emit``. Without this, a bus that outlives
        the protocol (a shared ``FakeBus`` or a MiniCroft) keeps routing
        through a dead protocol and keeps growing ``injected``.

        Safe to call twice, and safe when another protocol wrapped the same
        bus afterwards — in that case the emit wrapper is left alone, because
        removing a middle layer would break the outer one.
        """
        for event, handler in (("hive.send.downstream", self.handle_send),
                               ("message", self.handle_internal_mycroft)):
            try:
                self.bus.remove(event, handler)
            except Exception as exc:
                LOG.warning("TestAgentProtocol.shutdown: removing %r handler "
                            "failed: %s", event, exc)

        wrapper = getattr(self, "_recording_emit", None)
        orig = getattr(self, "_orig_emit", None)
        if wrapper is not None and orig is not None and self.bus.emit is wrapper:
            self.bus.emit = orig
        self._recording_emit = None
        self._orig_emit = None
