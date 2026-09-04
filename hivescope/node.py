"""
MasterNode and SatelliteNode — the two actor types in the test harness.

InProcessHiveShim acts as the HiveMessageBusClient-compatible object that
HiveMindSlaveProtocol requires, without any WebSocket involvement.
"""
import json
import logging
import threading
from collections import deque
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.fakebus import FakeBus
from pyee.base import EventEmitter

from hivemind_bus_client.encryption import SupportedEncodings, SupportedCiphers
from hivemind_bus_client.identity import NodeIdentity
from hivemind_bus_client.message import HiveMessage, HiveMessageType
from hivemind_bus_client.serialization import decode_bitstring  # used in _instrument_master
from hivemind_core.protocol import (
    HiveMindClientConnection,
    HiveMindListenerProtocol,
)
from hivemind_plugin_manager.protocols import ClientCallbacks

from hivescope.database import InMemoryClientDatabase
from hivescope.plugins.agent import TestAgentProtocol
from hivescope.plugins.binary import TestBinaryProtocol
from hivescope.plugins.network import TestNetworkProtocol
from hivescope.recorder import MessageRecorder, RecordedMessage
from hivescope.utils import make_identity, remove_identity_tmpdir

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Non-reentrant in-process delivery pump
# ---------------------------------------------------------------------------
#
# A real WebSocket write returns before the peer reads the frame: delivery is
# asynchronous, so a handler that sends never runs inside the sender's own call
# stack. The in-process shim has no socket — a "send" reaches the peer by
# calling straight into its receive path — so without care a handler's outbound
# send re-enters the very send that is still on the stack.
#
# hivemind-bus-client's ``NoiseTransport.send_message`` holds a single,
# non-reentrant ``_send_lock`` across the whole wire-send (encrypt + every
# raw_send chunk) so a message's frames stay contiguous and its Noise nonces
# stay ordered. If a send re-enters ``send_message`` on the same transport from
# the same thread — a master relaying a frame down to a peer whose handler then
# sends back on that connection (``_relay_downstream`` -> ``conn.send``) — the
# second acquire blocks on a lock the thread already holds. Deadlock.
#
# The cure is to model the socket: a delivery started while another delivery is
# in progress on this thread is queued and runs only after the outer one has
# fully returned and released ``_send_lock``. Every top-level entry point — a
# satellite's ``send()``/``connect()`` handshake and a master's
# ``send_to_satellite``/``send_to_all``/``emit_on_bus`` — funnels its work
# through :func:`_deliver`, which roots the pump OUTSIDE any ``send_message``.
# ``_receive_raw`` (the only thing hivemind-core's ``raw_send`` calls, always
# from inside a ``send_message``) therefore always finds the pump already
# draining and merely enqueues, so the wire-send returns and the lock is free
# before the peer's handler runs. The queue is FIFO and drained in order, so
# the frames of one message — and messages relative to one another — arrive in
# the order they were sent, as Noise's in-order transport requires.
#
# The pump is thread-local: all in-process traffic runs on the caller's thread,
# and a per-thread queue keeps two threads driving separate topologies from
# sharing state.

_pump = threading.local()


def _deliver(action) -> None:
    """Run ``action`` once every delivery already in flight on this thread has
    returned.

    The first call on the thread drains the queue to completion; a call made
    while that drain is running only appends, so no delivery ever executes
    inside another delivery's ``send_message`` (and thus never re-enters its
    ``_send_lock``). Order is preserved: actions run in the order enqueued.
    """
    queue = getattr(_pump, "queue", None)
    if queue is None:
        queue = _pump.queue = deque()
    queue.append(action)
    if getattr(_pump, "draining", False):
        return
    _pump.draining = True
    try:
        while queue:
            queue.popleft()()
    finally:
        _pump.draining = False


# ---------------------------------------------------------------------------
# InProcessHiveShim
# ---------------------------------------------------------------------------

class InProcessHiveShim:
    """
    Minimal stand-in for HiveMessageBusClient as required by HiveMindSlaveProtocol.

    - emit(HiveMessage)  → routes upstream to the master's handle_message()
    - on(event, func)    → registers on the internal EventEmitter
    - emitter            → the EventEmitter that dispatches inbound messages
    - crypto_key, cipher, json_encoding, handshake_event, session_id, password
      — all the attributes SlaveProtocol reads off a client during the
      handshake and connection lifecycle. `password` is read off the shim's
      identity, the same way `useragent` and `site_id` are — a real client
      keeps credentials on itself rather than on the node identity, and the
      shim has no separate credential store to mirror that with.
    """

    def __init__(self, identity: NodeIdentity, satellite_ref: "SatelliteNode"):
        self.identity = identity
        self._satellite = satellite_ref
        self.emitter = EventEmitter()
        self.crypto_key: Optional[str] = None
        self.json_encoding: SupportedEncodings = SupportedEncodings.JSON_HEX
        self.cipher: SupportedCiphers = SupportedCiphers.AES_GCM
        self.handshake_event = threading.Event()
        self._session_id: str = str(uuid4())
        # HiveMindSlaveProtocol._should_use_noise() checks this against the
        # server's advertised max_protocol_version to select the Noise path
        self.max_protocol_version: int = 3

    # --- properties accessed by HiveMindSlaveProtocol ---

    @property
    def useragent(self) -> str:
        return self.identity.name

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def password(self) -> str:
        """The password for the link to the master.

        A real client keeps its credentials on the client rather than on the
        node identity, because they say how to reach one particular master
        and are not part of who the node is. This shim has no separate
        credential store, so it reports the identity's — the same way it
        reports the useragent and the site.
        """
        return self.identity.password

    @property
    def site_id(self) -> Optional[str]:
        return self.identity.site_id

    @site_id.setter
    def site_id(self, val: str):
        self.identity.site_id = val

    # --- message API ---

    def emit(self, message: Union[HiveMessage, Message]):
        """Send a HiveMessage upstream to the master."""
        if isinstance(message, Message):
            message = HiveMessage(HiveMessageType.BUS, payload=message)
        self._satellite.send(message)

    def on(self, event_name: str, func):
        """Register an inbound-message handler."""
        self.emitter.on(event_name, func)

    def remove(self, event_name: str, func):
        self.emitter.remove_listener(event_name, func)


# ---------------------------------------------------------------------------
# MasterNode
# ---------------------------------------------------------------------------

class MasterNode:
    """
    Wraps a HiveMindListenerProtocol with TestAgentProtocol, TestBinaryProtocol,
    and TestNetworkProtocol.  No network server is started.
    """

    def __init__(self,
                 name: str,
                 identity: NodeIdentity,
                 db: InMemoryClientDatabase,
                 agent_protocol: TestAgentProtocol,
                 binary_protocol: TestBinaryProtocol,
                 network_protocol: TestNetworkProtocol,
                 hm_protocol: HiveMindListenerProtocol,
                 recorder: MessageRecorder):
        self.name = name
        self.identity = identity
        self.db = db
        self.agent_protocol = agent_protocol
        self.binary_protocol = binary_protocol
        self.network_protocol = network_protocol
        self.hm_protocol = hm_protocol
        self.recorder = recorder

    @classmethod
    def create(cls,
               name: str,
               require_crypto: bool = True,
               handshake_enabled: bool = True,
               agent_protocol: "TestAgentProtocol" = None,
               use_loopback: bool = False,
               db: "Any" = None) -> "MasterNode":
        """Build a master node.

        There is deliberately no ``**kwargs`` catch-all: an unknown keyword
        must raise ``TypeError`` instead of being silently discarded, because
        a typo like ``requires_crypto=False`` would otherwise misconfigure the
        node and the test would still pass.

        ``require_crypto`` and ``handshake_enabled`` are accepted-and-ignored
        under v3-Noise-only — the Noise handshake is mandatory and always
        encrypted; kept for caller compatibility.
        """
        identity = make_identity(name)
        # Default to the in-memory store; callers may inject a real
        # ClientDatabase-compatible backend (e.g. a migrated sqlite/redis
        # plugin DB) to exercise the full DB → policy → session path.
        if db is None:
            db = InMemoryClientDatabase()
        agent = agent_protocol if agent_protocol is not None else TestAgentProtocol()
        binary = TestBinaryProtocol(agent_protocol=agent)
        hm_proto = HiveMindListenerProtocol(
            identity=identity,
            db=db,
            agent_protocol=agent,
            binary_data_protocol=binary,
            peer=f"{name}:0.0.0.0",
        )
        # Use LoopbackNetworkProtocol (real WebSocket) if use_loopback=True,
        # otherwise use TestNetworkProtocol (in-process wiring)
        recorder = MessageRecorder(name=name)
        if use_loopback:
            from hivescope.plugins.loopback import LoopbackNetworkProtocol
            # The recorder is passed so undecodable frames land in the record
            # list instead of only in the log.
            network = LoopbackNetworkProtocol(hm_protocol=hm_proto,
                                              recorder=recorder)
        else:
            network = TestNetworkProtocol(hm_protocol=hm_proto)
        _instrument_master(hm_proto, recorder)
        return cls(name=name, identity=identity, db=db,
                   agent_protocol=agent, binary_protocol=binary,
                   network_protocol=network, hm_protocol=hm_proto,
                   recorder=recorder)

    # --- satellite management ---

    def register_satellite(self,
                           key: str,
                           password: Optional[str] = None,
                           is_admin: bool = False,
                           can_escalate: bool = True,
                           can_propagate: bool = True,
                           can_broadcast: bool = True,
                           allowed_types: Optional[List[str]] = None,
                           msg_blacklist: Optional[List[str]] = None,
                           skill_blacklist: Optional[List[str]] = None,
                           intent_blacklist: Optional[List[str]] = None):
        """Pre-populate the DB so a satellite with this key can connect."""
        self.db.add_client(
            name="test-satellite",
            key=key,
            password=password,
            admin=is_admin,
            can_escalate=can_escalate,
            can_propagate=can_propagate,
            can_broadcast=can_broadcast,
            allowed_types=allowed_types,
            message_blacklist=msg_blacklist,
            skill_blacklist=skill_blacklist,
            intent_blacklist=intent_blacklist,
        )

    # --- sending to connected satellites ---

    def send_to_satellite(self, peer: str, message: HiveMessage):
        """Directly send a HiveMessage to a connected satellite by peer id."""
        conn = self.hm_protocol.clients.get(peer)
        if conn is None:
            raise KeyError(
                f"No connected client with peer '{peer}'. "
                f"Connected peers: {list(self.hm_protocol.clients)}"
            )
        # Root the delivery pump here, outside conn.send's send_message, so a
        # peer handler woken by this frame enqueues its own sends instead of
        # re-entering the transport's _send_lock (relay fan-out deadlock).
        _deliver(lambda: conn.send(message))

    def send_to_all(self, message: HiveMessage):
        """Broadcast a HiveMessage to all currently connected satellites."""
        def _broadcast():
            for peer, conn in list(self.hm_protocol.clients.items()):
                conn.send(message)
        _deliver(_broadcast)

    def emit_on_bus(self, message: Message):
        """Emit an OVOS message on the internal agent bus (simulates a skill response)."""
        _deliver(lambda: self.agent_protocol.bus.emit(message))

    # --- waiting / assertion ---

    def wait_for(self, msg_type: str,
                 direction: Optional[str] = None,
                 timeout: float = 5.0) -> Optional[RecordedMessage]:
        return self.recorder.wait_for(msg_type, direction=direction, timeout=timeout)

    def connected_peers(self) -> List[str]:
        return list(self.hm_protocol.clients.keys())

    # --- cleanup ---

    def cleanup(self):
        """Release the temp files this node's identity created."""
        remove_identity_tmpdir(self.identity)


# ---------------------------------------------------------------------------
# SatelliteNode
# ---------------------------------------------------------------------------

class SatelliteNode:
    """
    Wraps HiveMindSlaveProtocol via an InProcessHiveShim.
    No WebSocket client is created.
    """

    def __init__(self,
                 name: str,
                 identity: NodeIdentity,
                 internal_bus: FakeBus,
                 shim: InProcessHiveShim,
                 slave_protocol,            # HiveMindSlaveProtocol
                 recorder: MessageRecorder):
        self.name = name
        self.identity = identity
        self.internal_bus = internal_bus
        self.shim = shim
        self.slave_protocol = slave_protocol
        self.recorder = recorder

        # Set by connect()
        self._connection: Optional[HiveMindClientConnection] = None
        self._master: Optional[MasterNode] = None

    @classmethod
    def create(cls, name: str, site_id: Optional[str] = None,
               shared_bus: bool = False,
               bus: Optional[FakeBus] = None) -> "SatelliteNode":
        # Import here to avoid circular import at module level
        from hivemind_bus_client.protocol import HiveMindSlaveProtocol

        identity = make_identity(name, site_id=site_id or f"{name}-site")
        bus = bus or FakeBus()
        recorder = MessageRecorder(name=name)

        # shim acts as the HiveMessageBusClient for the slave protocol
        shim = InProcessHiveShim(identity=identity, satellite_ref=None)

        slave = HiveMindSlaveProtocol(
            hm=shim,
            identity=identity,
            shared_bus=shared_bus,
            site_id=identity.site_id or "unknown",
        )
        slave.bind(bus)
        # Propagate shared_bus to the internal protocol (HiveMindSlaveProtocol.bind()
        # creates internal_protocol but does not forward shared_bus to it)
        slave.internal_protocol.share_bus = shared_bus

        node = cls(name=name, identity=identity, internal_bus=bus,
                   shim=shim, slave_protocol=slave, recorder=recorder)
        shim._satellite = node  # now wire the back-reference
        return node

    # --- connection ---

    def connect(self, master: MasterNode,
                is_admin: bool = False,
                can_escalate: bool = True,
                can_propagate: bool = True,
                can_broadcast: bool = True,
                allowed_types: Optional[List[str]] = None,
                msg_blacklist: Optional[List[str]] = None,
                skill_blacklist: Optional[List[str]] = None,
                intent_blacklist: Optional[List[str]] = None):
        """
        Wire this satellite to master in-process and complete the handshake.
        After this call the satellite is fully connected and crypto is active.
        """
        # Store master reference BEFORE connect_satellite so that send()
        # works during the synchronous handshake exchange that follows.
        self._master = master

        master.register_satellite(
            key=self.identity.access_key,
            password=self.identity.password,
            is_admin=is_admin,
            can_escalate=can_escalate,
            can_propagate=can_propagate,
            can_broadcast=can_broadcast,
            allowed_types=allowed_types,
            msg_blacklist=msg_blacklist,
            skill_blacklist=skill_blacklist,
            intent_blacklist=intent_blacklist,
        )

        # connect_satellite sets self._connection and calls handle_new_client;
        # the handshake completes synchronously inside that call. Route it
        # through the delivery pump so it roots outside any send_message, the
        # same as every other traffic-generating entry point.
        _deliver(lambda: master.network_protocol.connect_satellite(satellite=self))

        # For RSA-only mode (no password), slave never calls start_handshake
        # automatically — do it here as the real client would via wait_for_handshake.
        if not self.shim.handshake_event.is_set():
            _deliver(self.slave_protocol.start_handshake)

        if not self.shim.handshake_event.is_set():
            raise RuntimeError(
                f"Handshake did not complete for satellite {self.name!r}. "
                "Ensure the satellite has a password set (password-based handshake) "
                "or that it is a v3-capable client (Noise handshake is always on)."
            )

    def wait_for_handshake(self, timeout: float = 5.0) -> bool:
        """Block until the handshake completes; return True if it did.

        The handshake event lives on the shim, which the slave protocol sets
        when crypto negotiation finishes.
        """
        return self.shim.handshake_event.wait(timeout=timeout)

    def disconnect(self):
        """Disconnect from the master."""
        if self._connection and self._master:
            self._master.hm_protocol.handle_client_disconnected(self._connection)

    def cleanup(self):
        """Release the temp files this node's identity created."""
        remove_identity_tmpdir(self.identity)

    # --- sending ---

    def send(self, message: Union[HiveMessage, Message]):
        """Send a message upstream to the connected master."""
        if isinstance(message, Message):
            # Inject session so master doesn't reject it as the 'default' session
            if "session" not in message.context:
                sess = Session(session_id=self.shim.session_id,
                               site_id=self.identity.site_id or "unknown")
                message.context["session"] = sess.serialize()
            message = HiveMessage(HiveMessageType.BUS, payload=message)
        # Guard BEFORE recording: a send that never happened must not appear
        # in the recorder as an outbound message.
        if self._master is None or self._connection is None:
            raise RuntimeError(
                f"Satellite {self.name!r} is not connected to any master."
            )
        self.recorder.record("out", message.msg_type, message._payload, "master")
        _deliver(lambda: self._master.hm_protocol.handle_message(message, self._connection))

    # --- receiving (called by master's send_msg) ---

    def _receive_raw(self, payload: Union[str, bytes], is_binary: bool):
        """
        Called by HiveMindClientConnection.send_msg when master sends downstream.
        Decodes, records, then dispatches through the slave protocol's handlers.
        """
        if self._connection is None:
            # Connection not yet established (shouldn't normally happen)
            return

        peer = self._connection.peer

        # self._connection is the master's HiveMindClientConnection, shared
        # in-process for framing/session bookkeeping; it carries the master's
        # own Noise transport (the responder's cipher states), not the
        # satellite's (the initiator's). Decrypting a v3 session with the
        # wrong side's transport always fails AEAD authentication, so decode
        # borrows the satellite's own transport for the duration of the call.
        client_transport = getattr(self.shim, "noise_transport", None)
        saved_transport = self._connection.noise_transport
        if client_transport is not None:
            self._connection.noise_transport = client_transport
        try:
            message = self._connection.decode(payload)
        except Exception as exc:
            log.exception("[%s] _receive_raw decode error: %s", self.name, exc)
            # Record the failure so a test waiting on a message fails fast with
            # the decode error in the record list instead of on timeout.
            self.recorder.record("in", "_decode_error", {"error": str(exc)}, peer)
            return
        finally:
            self._connection.noise_transport = saved_transport

        self.recorder.record("in", message.msg_type, message._payload, peer)

        # Dispatch through the slave protocol's registered handlers. raw_send
        # reaches here from inside NoiseTransport.send_message, so this must not
        # run a handler synchronously (the handler's own outbound send would
        # re-enter the held _send_lock); _deliver enqueues it behind the send
        # in progress and it runs once that send has returned.
        _deliver(lambda: self.shim.emitter.emit(message.msg_type, message))

    def _on_disconnect(self, code: int = 1000, reason: str = ""):
        conn = self._connection
        master = self._master
        self._connection = None
        self._master = None
        # Mirror production behavior: WebSocket on_close → handle_client_disconnected.
        # Guard against re-entry (handle_client_disconnected calls client.disconnect()
        # at the end, which would call _on_disconnect again; by the time that second
        # call arrives, _connection/_master are already None so the guard is False).
        if conn and master and conn.peer in master.hm_protocol.clients:
            master.hm_protocol.handle_client_disconnected(conn)

    # --- waiting / assertion ---

    def wait_for(self, msg_type: str,
                 direction: str = "in",
                 timeout: float = 5.0) -> Optional[RecordedMessage]:
        return self.recorder.wait_for(msg_type, direction=direction, timeout=timeout)

    def wait_for_bus(self, ovos_type: str, timeout: float = 5.0) -> Optional[Message]:
        """Wait for an OVOS message type to arrive on the internal bus."""
        event = threading.Event()
        result: List[Message] = []

        def handler(msg):
            result.append(msg)
            event.set()

        self.internal_bus.once(ovos_type, handler)
        try:
            event.wait(timeout=timeout)
        finally:
            # A `once` listener that never fired stays registered forever and
            # would capture an unrelated later message.
            try:
                self.internal_bus.remove(ovos_type, handler)
            except (ValueError, KeyError):
                pass  # already fired and self-removed
        return result[0] if result else None

    @property
    def peer(self) -> Optional[str]:
        return self._connection.peer if self._connection else None


# ---------------------------------------------------------------------------
# Instrumentation helpers
# ---------------------------------------------------------------------------

def _instrument_master(hm_proto: HiveMindListenerProtocol,
                       recorder: MessageRecorder):
    """
    Monkey-patch HiveMindListenerProtocol to record every inbound message
    and every outbound send to a satellite.
    """
    _orig_handle = hm_proto.handle_message

    def _recording_handle(message: HiveMessage, client: HiveMindClientConnection):
        recorder.record("in", message.msg_type, message._payload, client.peer)
        _orig_handle(message, client)

    hm_proto.handle_message = _recording_handle

    _orig_new_client = hm_proto.handle_new_client

    def _recording_new_client(client: HiveMindClientConnection):
        # Wrap send_msg so outbound messages are recorded with actual HiveMessage type.
        # We do this before handle_new_client so the HELLO/HANDSHAKE are captured.
        _orig_send_msg = client.send_msg

        def _recording_send_msg(payload, is_bin):
            # Best-effort decode to get msg_type for the record.
            try:
                if isinstance(payload, bytes):
                    msg = decode_bitstring(payload)
                    msg_type = msg.msg_type
                else:
                    if "ciphertext" in payload:
                        msg_type = "_encrypted"
                    else:
                        parsed = json.loads(payload)
                        msg_type = parsed.get("msg_type", "_unknown")
            except Exception:
                msg_type = "_raw"
            recorder.record("out", msg_type, payload, client.peer)
            _orig_send_msg(payload, is_bin)

        client.send_msg = _recording_send_msg
        _orig_new_client(client)

    hm_proto.handle_new_client = _recording_new_client

    # Record bus injections separately
    _orig_inject = hm_proto.handle_inject_agent_msg

    def _recording_inject(message: Message, client: HiveMindClientConnection):
        recorder.record("bus_inject", message.msg_type, message, client.peer)
        _orig_inject(message, client)

    hm_proto.handle_inject_agent_msg = _recording_inject
