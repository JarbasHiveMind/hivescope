"""
Protocol-level assertion helpers for hivescope e2e tests.

Each helper targets one or more ``HiveMessageType`` values and raises
``AssertionError`` with a diagnostic message (actual recorder contents,
peer lists, etc.) on failure.

All 13 HiveMessageType values are covered:

Ready (core routing implemented):
  HANDSHAKE  — assert_handshake_complete, assert_encryption_match
  HELLO      — assert_hello_received
  BUS        — assert_bus_message_routed
  SHARED_BUS — assert_shared_bus_received
  BROADCAST  — assert_broadcast_delivered, assert_broadcast_blocked
  PROPAGATE  — assert_propagate_delivered
  ESCALATE   — assert_escalate_delivered
  INTERCOM   — assert_intercom_delivered
  BINARY     — assert_binary_delivered
  PING       — assert_ping_responded
  ACL (all)  — assert_acl_enforced

Pending (core routing not yet implemented; helpers scaffold the check):
  QUERY      — assert_query_routed        (xfail: core#74 / ws#88)
  CASCADE    — assert_cascade_routed      (xfail: core#74 / ws#88)
  RENDEZVOUS — assert_rendezvous_handled  (xfail: ws#103)

Generic:
  assert_passthrough_message_delivered — asserts an unhandled/user-land
  message type traverses the mesh untouched. Takes the ``HiveMessageType``
  as an argument, so it works for any type with no core-side handler.

Usage::

    from hivescope.assertions import (
        assert_handshake_complete,
        assert_bus_message_routed,
        assert_broadcast_delivered,
    )
"""

import time
from typing import Any, Dict, List, Optional

from hivescope.node import MasterNode, SatelliteNode
from hivemind_bus_client.message import HiveMessageType

# Policy-model deny codes (stable strings; mirrored from hivemind-plugin-manager)
ACL_DISALLOWED_TYPE = "acl_disallowed_type"
SESSION_ID_DEFAULT_FORBIDDEN = "session_id_default_forbidden"

# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def recorder_mark() -> float:
    """Return a timestamp mark comparable with ``RecordedMessage.timestamp``.

    Take one just before a probe emission and pass it as ``since=`` to an
    assertion helper, so only traffic caused by that probe is examined.
    """
    return time.monotonic()


def _find(recorder, msg_type_value: str, direction: Optional[str] = None):
    return [
        r for r in recorder.snapshot()
        if r.msg_type == msg_type_value
        and (direction is None or r.direction == direction)
    ]


def _find_broadcast_inner(recorder, inner_msg_type: str):
    """Inbound broadcasts of *inner_msg_type*, wrapped or bare.

    A current core forwards the BROADCAST envelope with the payload still
    inside it, so the record's own ``msg_type`` is ``broadcast`` and the type
    being asked about sits in ``payload["msg_type"]``. A pre-#216 core
    unwrapped it and the record's own type was the inner one. Accept both so
    the assertion pins delivery rather than one core's framing.
    """
    found = []
    for r in recorder.snapshot():
        if r.direction != "in":
            continue
        if r.msg_type == inner_msg_type:
            found.append(r)
        elif (r.msg_type == HiveMessageType.BROADCAST.value
              and isinstance(r.payload, dict)
              and r.payload.get("msg_type") == inner_msg_type):
            found.append(r)
    return found


# Message types that are connection setup or keepalive, never payload traffic.
_NON_PAYLOAD_TYPES = (
    HiveMessageType.HANDSHAKE.value,
    HiveMessageType.HELLO.value,
    HiveMessageType.PING.value,
)


def _inner_payload(record) -> dict:
    """Return the inner OVOS payload dict of a recorded BUS message."""
    return record.payload if isinstance(record.payload, dict) else {}


def _is_policy_denied(record) -> bool:
    """True when *record* is a ``hive.policy.denied`` response."""
    return _inner_payload(record).get("type") == "hive.policy.denied"


# HiveMessageType values, as strings — passing one of these as *msg_type* is
# a caller bug: these helpers correlate against the OVOS message type carried
# INSIDE a denied BUS message (e.g. "speak"), not the HiveMind envelope type.
_HIVE_MESSAGE_TYPE_VALUES = frozenset(t.value for t in HiveMessageType)


def _denied_records(satellite, msg_type: Optional[str] = None,
                    strict: bool = True):
    """Return ``hive.policy.denied`` records received by *satellite*.

    Raises:
        ValueError: if *msg_type* is a ``HiveMessageType`` value (e.g.
            ``"bus"``, ``"escalate"``) instead of an OVOS message type (e.g.
            ``"speak"``). Denials echo the OVOS type carried inside the BUS
            envelope, never the envelope type itself, so passing a
            HiveMessageType value here can never match and silently hides a
            broken test.

    When *msg_type* is given, a denial matches only if it echoes that type.
    hivemind-core echoes it in ``data["denied_type"]``
    (``HiveMindListenerProtocol._send_policy_denied``); ``data["msg_type"]``
    and ``data["type"]`` are accepted as well for other policy backends.

    Denials that carry no type at all are ambiguous: they could belong to any
    message the satellite sent. ``strict=True`` (the default) drops them, so a
    typed assertion can never pass on unrelated traffic. ``strict=False``
    keeps them, but only when no typed denial matched — that way a correct
    typed denial is always preferred over an untyped guess.
    """
    if msg_type in _HIVE_MESSAGE_TYPE_VALUES:
        raise ValueError(
            f"_denied_records: msg_type={msg_type!r} is a HiveMessageType "
            "value, not an OVOS message type. Pass the OVOS message type "
            "that was denied (e.g. 'speak'), not the HiveMind envelope type "
            "('bus', 'escalate', ...) that carried it."
        )
    typed = []
    untyped = []
    for r in satellite.recorder.snapshot():
        if r.direction != "in" or r.msg_type != HiveMessageType.BUS.value:
            continue
        payload = _inner_payload(r)
        if payload.get("type") != "hive.policy.denied":
            continue
        if msg_type is None:
            typed.append((r, payload))
            continue
        data = payload.get("data") or {}
        reported = (data.get("denied_type") or data.get("msg_type")
                    or data.get("type"))
        if reported is None:
            untyped.append((r, payload))
        elif reported == msg_type:
            typed.append((r, payload))
    if typed or msg_type is None or strict:
        return typed
    return untyped


# ─────────────────────────────────────────────────────────────────────────────
# HANDSHAKE (shake)
# ─────────────────────────────────────────────────────────────────────────────

def assert_handshake_complete(
    master: MasterNode,
    satellite: SatelliteNode,
    timeout: float = 5.0,
) -> None:
    """Assert that *satellite* has completed its handshake with *master*.

    Checks:
    - ``satellite.shim.noise_transport`` is set (v3 Noise session negotiated)
    - ``satellite.shim.handshake_event`` is set
    - master's ``connected_peers()`` includes this satellite
    """
    errors: List[str] = []

    # Wait up to *timeout* for the handshake event; loopback mode completes
    # the handshake on the server thread, so the check must not be instant.
    satellite.shim.handshake_event.wait(timeout=timeout)

    # hivemind-core is v3-Noise-only (no legacy fallback, HiveMind-core#309):
    # negotiated crypto lives in the shim's Noise transport, never in the
    # removed shim.crypto_key.
    if getattr(satellite.shim, "noise_transport", None) is None:
        errors.append("satellite.shim.noise_transport is None (no Noise session negotiated)")

    if not satellite.shim.handshake_event.is_set():
        errors.append(
            f"satellite.shim.handshake_event not set after {timeout}s "
            "(handshake not complete)"
        )

    connected_peers = master.connected_peers()
    if satellite.peer not in connected_peers:
        errors.append(
            f"satellite peer '{satellite.peer}' not in master.connected_peers: {connected_peers}"
        )

    if errors:
        raise AssertionError("Handshake not complete:\n  " + "\n  ".join(errors))


def assert_encryption_match(
    master: MasterNode,
    satellite: SatelliteNode,
) -> None:
    """Assert that both sides agreed on the same cipher and json-encoding.

    Looks up the master-side ``HiveMindClientConnection`` for the satellite's
    peer and compares ``cipher`` / ``json_encoding`` with the satellite shim.
    """
    errors: List[str] = []

    master_conn = next(
        (c for c in master.hm_protocol.clients.values() if c.peer == satellite.peer),
        None,
    )
    if master_conn is None:
        raise AssertionError(
            f"satellite peer '{satellite.peer}' not registered at master; "
            "cannot compare encryption settings"
        )

    if master_conn.cipher != satellite.shim.cipher:
        errors.append(
            f"cipher mismatch: master={master_conn.cipher}, satellite={satellite.shim.cipher}"
        )

    # HiveMindClientConnection uses .encoding; shim uses .json_encoding — both hold SupportedEncodings
    master_encoding = getattr(master_conn, "encoding", getattr(master_conn, "json_encoding", None))
    satellite_encoding = getattr(satellite.shim, "json_encoding", getattr(satellite.shim, "encoding", None))
    if master_encoding != satellite_encoding:
        errors.append(
            f"encoding mismatch: master={master_encoding}, satellite={satellite_encoding}"
        )

    if errors:
        raise AssertionError("Encryption mismatch:\n  " + "\n  ".join(errors))


# ─────────────────────────────────────────────────────────────────────────────
# HELLO (hello)
# ─────────────────────────────────────────────────────────────────────────────

def assert_hello_received(
    master: MasterNode,
    count: int = 1,
) -> None:
    """Assert that master recorded *count* inbound HELLO announcements."""
    matches = _find(master.recorder, HiveMessageType.HELLO.value, direction="in")
    if len(matches) != count:
        raise AssertionError(
            f"Expected {count} HELLO message(s) at master, got {len(matches)}.\n"
            f"All inbound: {[r.msg_type for r in master.recorder.snapshot() if r.direction == 'in']}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# BUS (bus)
# ─────────────────────────────────────────────────────────────────────────────

def assert_bus_message_routed(
    master: MasterNode,
    count: int = 1,
) -> None:
    """Assert that *count* BUS messages reached the master's agent bus."""
    matches = _find(master.recorder, HiveMessageType.BUS.value, direction="in")
    if len(matches) != count:
        raise AssertionError(
            f"Expected {count} BUS message(s) at master, got {len(matches)}.\n"
            f"All records: {master.recorder.snapshot()}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# SHARED_BUS (shared_bus)
# ─────────────────────────────────────────────────────────────────────────────

def assert_shared_bus_received(
    node,
    count: int = 1,
    direction: Optional[str] = None,
) -> None:
    """Assert that *node* recorded *count* SHARED_BUS messages."""
    matches = _find(node.recorder, HiveMessageType.SHARED_BUS.value, direction=direction)
    if len(matches) != count:
        raise AssertionError(
            f"Expected {count} SHARED_BUS message(s) (direction={direction!r}), "
            f"got {len(matches)}.\nAll records: {node.recorder.snapshot()}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# BROADCAST (broadcast)
# ─────────────────────────────────────────────────────────────────────────────

def assert_broadcast_delivered(
    *recipients,
    count: int = 1,
    inner_msg_type: Optional[str] = None,
) -> None:
    """Assert that the BROADCAST reached every node in *recipients*.

    Since HiveMind-core#216 a forwarded BROADCAST keeps its envelope
    (``_rewrap``, HIVEMIND-NODE-1 §3.3): a recipient records a ``broadcast``
    carrying the inner payload, not the bare inner message. Older cores
    unwrapped it and recorded the inner type directly, so ``inner_msg_type``
    matches either shape.

    Args:
        recipients: Nodes that should have received the broadcast.
        count: Expected number of messages at each recipient.
        inner_msg_type: If given, only count messages with this type
            (e.g. ``HiveMessageType.BUS.value``).
    """
    errors: List[str] = []
    for node in recipients:
        if inner_msg_type:
            matches = _find_broadcast_inner(node.recorder, inner_msg_type)
            label = f"BROADCAST(inner={inner_msg_type})"
        else:
            # Count inbound payload messages only: connection-setup and
            # keepalive traffic (HANDSHAKE, HELLO, PING) and policy-denied
            # responses are not broadcast deliveries. Pass *inner_msg_type*
            # for an exact match — this fallback is a best-effort filter.
            matches = [
                r for r in node.recorder.snapshot()
                if r.direction == "in"
                and r.msg_type not in _NON_PAYLOAD_TYPES
                and not _is_policy_denied(r)
            ]
            label = "BROADCAST(any inbound payload message)"
        if len(matches) != count:
            errors.append(
                f"Node '{node.recorder.name}': expected {count} {label}, got {len(matches)}.\n"
                f"  All records: {node.recorder.snapshot()}"
            )
    if errors:
        raise AssertionError("Broadcast not fully delivered:\n  " + "\n  ".join(errors))


def assert_broadcast_blocked(
    node,
) -> None:
    """Assert that *node* did NOT receive any BROADCAST (ACL blocked)."""
    matches = _find(node.recorder, HiveMessageType.BROADCAST.value, direction="in")
    if matches:
        raise AssertionError(
            f"Node '{node.recorder.name}' received {len(matches)} BROADCAST message(s) "
            "but should have been blocked by ACL."
        )


# ─────────────────────────────────────────────────────────────────────────────
# PROPAGATE (propagate)
# ─────────────────────────────────────────────────────────────────────────────

def assert_propagate_delivered(
    *recipients,
    count: int = 1,
) -> None:
    """Assert that every node in *recipients* recorded *count* inbound PROPAGATE messages."""
    errors: List[str] = []
    for node in recipients:
        matches = _find(node.recorder, HiveMessageType.PROPAGATE.value, direction="in")
        if len(matches) != count:
            errors.append(
                f"Node '{node.recorder.name}': expected {count} PROPAGATE, got {len(matches)}"
            )
    if errors:
        raise AssertionError("Propagate not fully delivered:\n  " + "\n  ".join(errors))


# ─────────────────────────────────────────────────────────────────────────────
# ESCALATE (escalate)
# ─────────────────────────────────────────────────────────────────────────────

def assert_escalate_delivered(
    master: MasterNode,
    count: int = 1,
) -> None:
    """Assert that master received *count* inbound ESCALATE messages (forwarded up-chain)."""
    matches = _find(master.recorder, HiveMessageType.ESCALATE.value, direction="in")
    if len(matches) != count:
        raise AssertionError(
            f"Expected {count} ESCALATE message(s) at master, got {len(matches)}.\n"
            f"All records: {master.recorder.snapshot()}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# INTERCOM (intercom)
# ─────────────────────────────────────────────────────────────────────────────

def assert_intercom_delivered(
    recipient: SatelliteNode,
    count: int = 1,
) -> None:
    """Assert that *recipient* satellite received *count* inbound INTERCOM messages."""
    matches = _find(recipient.recorder, HiveMessageType.INTERCOM.value, direction="in")
    if len(matches) != count:
        raise AssertionError(
            f"Expected {count} INTERCOM message(s) at '{recipient.recorder.name}', "
            f"got {len(matches)}.\nAll records: {recipient.recorder.snapshot()}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# BINARY (bin)
# ─────────────────────────────────────────────────────────────────────────────

def assert_binary_delivered(
    master: MasterNode,
    expected_payload: Optional[bytes] = None,
    count: int = 1,
) -> None:
    """Assert that master received *count* BINARY messages.

    Checks the master node's recorder for inbound BINARY messages.
    If *expected_payload* is given, also checks the ``TestBinaryProtocol``
    handler calls (only works for typed binary payloads such as RAW_AUDIO,
    STT_AUDIO_TRANSCRIBE etc.; UNDEFINED-typed binary payloads are handled
    at the recorder level only since core drops untyped binary data).
    """
    # Primary check: recorder (works for all bin_types)
    matches = _find(master.recorder, HiveMessageType.BINARY.value, direction="in")
    if len(matches) != count:
        raise AssertionError(
            f"Expected {count} BINARY message(s) at master recorder, got {len(matches)}.\n"
            f"All records: {master.recorder.snapshot()}"
        )

    # Secondary: if expected_payload is given, the payload must actually match,
    # either in a typed binary-protocol call or in the recorded raw payload.
    if expected_payload is not None:
        typed_calls = [c for c in master.binary_protocol.calls
                       if c.data == expected_payload]
        recorded = [r for r in matches if r.payload == expected_payload]
        if not typed_calls and not recorded:
            raise AssertionError(
                f"BINARY payload mismatch: expected {expected_payload!r} was not "
                f"seen.\n"
                f"  Typed binary protocol calls: "
                f"{[getattr(c, 'data', None) for c in master.binary_protocol.calls]}\n"
                f"  Recorded BINARY payloads: {[r.payload for r in matches]}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# ACL / policy-admission helpers
# ─────────────────────────────────────────────────────────────────────────────

def assert_acl_enforced(
    master: MasterNode,
    satellite: SatelliteNode,
    msg_type: str,
    allowed: bool = False,
    strict: bool = True,
) -> None:
    """Assert policy-admission enforcement for *msg_type* on *satellite*.

    When ``allowed=False`` (default): verifies that the satellite received a
    ``hive.policy.denied`` response (meaning ``MessageTypeACLPolicy`` denied
    the message) and that no ``bus_inject`` record for *msg_type* appears at
    master (the message was never forwarded to the OVOS bus).

    When ``allowed=True``: verifies BOTH that no denial for *msg_type* came
    back AND that the message WAS recorded at master's ``bus_inject`` level
    for this satellite's peer.  "No denial" alone is not evidence of delivery
    — a message that was silently dropped also produces no denial.

    For the policy model (``MessageTypeACLPolicy`` + ``OVOSAgentPolicy``):

    - A satellite whose ``allowed_types`` excludes ``msg_type`` will be denied
      with code ``ACL_DISALLOWED_TYPE``; use ``allowed=False`` (default).
    - A satellite whose ``allowed_types`` includes ``msg_type`` will be allowed;
      use ``allowed=True``.

    For richer deny-code or session-mutation assertions, use
    :func:`assert_policy_denied` and :func:`assert_session_blacklists_injected`
    directly.

    Note: ``bus_inject`` records are created by the harness instrumentation
    hook on ``handle_inject_agent_msg`` — they exist whether or not the policy
    subsequently allowed the message.  The ``hive.policy.denied`` signal at the
    satellite is the canonical "was denied" indicator.
    """
    # A policy-denied message causes the master to send hive.policy.denied
    # back to the satellite (recorded as inbound at the satellite). Only
    # denials that concern *msg_type* count.
    denied_responses = [r for r, _ in _denied_records(satellite, msg_type,
                                                      strict=strict)]

    if allowed:
        if denied_responses:
            raise AssertionError(
                f"ACL: expected '{msg_type}' to be allowed, but satellite received "
                f"{len(denied_responses)} hive.policy.denied response(s).\n"
                f"Denied responses: {denied_responses}"
            )
        peer = satellite.peer
        injected = [
            r for r in master.recorder.snapshot()
            if r.direction == "bus_inject" and r.msg_type == msg_type
            and (peer is None or r.peer == peer)
        ]
        if not injected:
            raise AssertionError(
                f"ACL: expected '{msg_type}' to be allowed, but master recorded "
                f"no bus_inject for it (peer={peer!r}) — the message was never "
                f"delivered to the agent bus.\n"
                f"All master records: {master.recorder.snapshot()}"
            )
    else:
        if not denied_responses:
            raise AssertionError(
                f"ACL violation: '{msg_type}' was NOT blocked — "
                f"satellite received no hive.policy.denied response.\n"
                f"Inbound records at satellite: {satellite.recorder.snapshot()}"
            )


def assert_policy_denied(
    master: MasterNode,
    satellite: SatelliteNode,
    msg_type: str,
    deny_code: Optional[str] = None,
    strict: bool = True,
) -> None:
    """Assert that *msg_type* sent by *satellite* was denied by the policy chain.

    Verifies that the satellite received a ``hive.policy.denied`` response
    from the master.  If *deny_code* is given, also checks that the denial
    carries that specific stable code (e.g. ``"acl_disallowed_type"``).

    Args:
        master:     The master node (unused in the check, kept for signature
                    parity with other helpers).
        satellite:  The satellite that sent the message.
        msg_type:   The OVOS message type that should have been denied. The
                    denial must echo it in ``data["denied_type"]``.
        deny_code:  Optional stable deny code to verify.  If ``None``, any
                    matching ``hive.policy.denied`` response satisfies the
                    assertion.
        strict:     ``True`` (default) requires the denial to echo *msg_type*.
                    Set ``False`` to also accept a denial that names no type —
                    such a denial cannot be correlated with *msg_type*, so the
                    assertion then proves only "something was denied".
    """
    # The satellite should have received a HiveMessage whose inner BUS payload
    # has msg_type "hive.policy.denied".  The recorder stores the raw payload
    # dict for inbound "bus" records.
    inbound_bus = [
        r for r in satellite.recorder.snapshot()
        if r.direction == "in" and r.msg_type == HiveMessageType.BUS.value
    ]

    # Correlate the denial with the message type under test via the echoed
    # denied_type; see _denied_records for the strict/loose rule.
    denied_responses = _denied_records(satellite, msg_type, strict=strict)

    if not denied_responses:
        raise AssertionError(
            f"assert_policy_denied: no hive.policy.denied response received "
            f"at satellite for '{msg_type}'.\n"
            f"Inbound records: {inbound_bus}"
        )

    if deny_code is not None:
        found_code = False
        for _, payload in denied_responses:
            # HiveMessage._payload["data"] holds the Mycroft Message's data dict
            data = payload.get("data", {})
            if str(data.get("code", "")) == deny_code:
                found_code = True
                break
        if not found_code:
            actual_codes = [p.get("data", {}).get("code") for _, p in denied_responses]
            raise AssertionError(
                f"assert_policy_denied: satellite received hive.policy.denied "
                f"but not with code={deny_code!r}.\n"
                f"Actual codes seen: {actual_codes}"
            )


def assert_session_blacklists_injected(
    master: MasterNode,
    satellite: SatelliteNode,
    msg_type: str,
    expected_skills: Optional[List[str]] = None,
    expected_intents: Optional[List[str]] = None,
) -> None:
    """Assert that the policy chain injected skill/intent blacklists into the
    session of a bus-injected message.

    This asserts the ``OVOSAgentPolicy`` + ``AddBlacklistedSkill`` /
    ``AddBlacklistedIntent`` mutation path: the message reached the agent bus
    (was allowed by ``MessageTypeACLPolicy``) AND its
    ``context["session"]["blacklisted_skills"]`` / ``["blacklisted_intents"]``
    contain the expected values.

    Checks the ``bus_inject`` records at *master* for the first *msg_type*
    message and inspects its serialised ``context.session``.

    Args:
        master:            The master node.
        satellite:         The satellite that sent the message; its ``peer`` is
                           used to filter bus_inject records so only records from
                           this satellite are inspected.
        msg_type:          The OVOS message type that was allowed.
        expected_skills:   Skills that must appear in
                           ``context["session"]["blacklisted_skills"]``.
        expected_intents:  Intents that must appear in
                           ``context["session"]["blacklisted_intents"]``.
    """
    peer = satellite.peer
    if peer is None:
        raise AssertionError(
            f"assert_session_blacklists_injected: satellite "
            f"'{satellite.name}' has no peer — it is disconnected, so its "
            "bus_inject records cannot be identified. Assert before "
            "disconnecting the satellite."
        )
    bus_injected = [
        r for r in master.recorder.snapshot()
        if r.direction == "bus_inject" and r.msg_type == msg_type
        and r.peer == peer
    ]
    if not bus_injected:
        raise AssertionError(
            f"assert_session_blacklists_injected: no bus_inject record for "
            f"'{msg_type}' at master (peer={peer!r}) — the message was not forwarded to the bus.\n"
            f"All records: {master.recorder.snapshot()}"
        )

    record = bus_injected[-1]
    # payload is a Message instance for bus_inject records (see _recording_inject)
    message = record.payload
    errors: List[str] = []

    session = {}
    if hasattr(message, "context") and isinstance(message.context, dict):
        session = message.context.get("session") or {}

    if expected_skills:
        actual_skills = list(session.get("blacklisted_skills") or [])
        missing = [s for s in expected_skills if s not in actual_skills]
        if missing:
            errors.append(
                f"blacklisted_skills missing {missing}; actual={actual_skills}"
            )

    if expected_intents:
        actual_intents = list(session.get("blacklisted_intents") or [])
        missing = [i for i in expected_intents if i not in actual_intents]
        if missing:
            errors.append(
                f"blacklisted_intents missing {missing}; actual={actual_intents}"
            )

    if errors:
        raise AssertionError(
            "assert_session_blacklists_injected: session mutation missing:\n  "
            + "\n  ".join(errors)
        )


# ─────────────────────────────────────────────────────────────────────────────
# Generic helpers
# ─────────────────────────────────────────────────────────────────────────────

def assert_message_routed(
    node,
    msg_type: str,
    count: int = 1,
    direction: Optional[str] = None,
    timeout: float = 2.0,
) -> None:
    """Assert that *count* messages of *msg_type* were routed through *node*.

    Args:
        node: MasterNode or SatelliteNode with a MessageRecorder.
        msg_type: HiveMessageType name or value string (e.g. ``"BUS"`` or ``"bus"``).
        count: Expected number of messages.
        direction: Optional ``"in"`` or ``"out"`` filter.
        timeout: Seconds to wait for the messages to arrive. Needed in
            loopback mode, where messages land on the server thread.
    """
    # Wait until the expected count is reached or the timeout lapses.
    deadline = time.monotonic() + timeout
    while len(_find(node.recorder, msg_type, direction)) < count:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if not _find(node.recorder, msg_type, direction):
            node.recorder.wait_for(msg_type, direction=direction,
                                   timeout=remaining)
        else:
            time.sleep(min(0.02, remaining))

    messages = node.recorder.snapshot()
    if direction:
        messages = [m for m in messages if m.direction == direction]
    matching = [m for m in messages if m.msg_type == msg_type]
    if len(matching) != count:
        raise AssertionError(
            f"Expected {count} '{msg_type}' messages (direction={direction!r}), "
            f"got {len(matching)}.\n"
            f"All messages: {[m.msg_type for m in node.recorder.snapshot()]}"
        )


def assert_message_received_by(node, msg_type: str, count: int = 1) -> None:
    """Convenience wrapper: assert *count* inbound *msg_type* at *node*."""
    assert_message_routed(node, msg_type, count=count, direction="in")


def assert_message_sent_by(node, msg_type: str, count: int = 1) -> None:
    """Convenience wrapper: assert *count* outbound *msg_type* from *node*."""
    assert_message_routed(node, msg_type, count=count, direction="out")


def assert_client_registered(master: MasterNode, peer: str) -> None:
    """Assert that *peer* is in master's ``connected_peers()``."""
    connected = master.connected_peers()
    if peer not in connected:
        raise AssertionError(
            f"Peer '{peer}' not registered in master. Connected peers: {connected}"
        )


def assert_client_not_registered(master: MasterNode, peer: str) -> None:
    """Assert that *peer* is NOT in master's ``connected_peers()``."""
    connected = master.connected_peers()
    if peer in connected:
        raise AssertionError(
            f"Peer '{peer}' IS registered in master but should not be. "
            f"Connected peers: {connected}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# PENDING — QUERY, CASCADE, PING, RENDEZVOUS
#
# These helpers are honest scaffolds for message types whose core routing is
# not yet implemented. Tests that use them MUST be decorated with:
#
#   @pytest.mark.xfail(reason="...", strict=False)
#
# The helpers will raise AssertionError (xfail) until core lands the routing.
# See templates/test_template_query.py et al. for ready-to-copy examples.
# ─────────────────────────────────────────────────────────────────────────────

def assert_query_routed(
    master: MasterNode,
    count: int = 1,
) -> None:
    """Assert that *count* QUERY messages were routed by master.

    .. note::
        PENDING — QUERY routing is not yet implemented in hivemind-core.
        Track: `hivemind-core#74 <https://github.com/JarbasHiveMind/HiveMind-core/pull/74>`_
        and `hivemind-websocket-client#88 <https://github.com/JarbasHiveMind/hivemind-websocket-client/pull/88>`_.
        Tests using this helper should be marked ``@pytest.mark.xfail(strict=False)``.
    """
    matches = _find(master.recorder, HiveMessageType.QUERY.value)
    if len(matches) != count:
        raise AssertionError(
            f"[PENDING] Expected {count} QUERY message(s) routed by master, "
            f"got {len(matches)}. QUERY routing is not yet in hivemind-core "
            f"(core#74 / ws#88).\nAll records: {master.recorder.snapshot()}"
        )


def assert_cascade_routed(
    *nodes,
    count: int = 1,
) -> None:
    """Assert that every node in *nodes* received *count* CASCADE messages.

    .. note::
        PENDING — CASCADE routing is not yet implemented in hivemind-core.
        Track: `hivemind-core#74 <https://github.com/JarbasHiveMind/HiveMind-core/pull/74>`_
        and `hivemind-websocket-client#88 <https://github.com/JarbasHiveMind/hivemind-websocket-client/pull/88>`_.
        Tests using this helper should be marked ``@pytest.mark.xfail(strict=False)``.
    """
    errors: List[str] = []
    for node in nodes:
        matches = _find(node.recorder, HiveMessageType.CASCADE.value)
        if len(matches) != count:
            errors.append(
                f"Node '{node.recorder.name}': expected {count} CASCADE, got {len(matches)}"
            )
    if errors:
        raise AssertionError(
            "[PENDING] CASCADE not fully delivered (core#74 / ws#88):\n  "
            + "\n  ".join(errors)
        )


def _ping_flood_id(record) -> Optional[Any]:
    """Best-effort extraction of ``flood_id`` from a recorded PING/PROPAGATE."""
    payload = record.payload
    if isinstance(payload, dict):
        if "flood_id" in payload:
            return payload["flood_id"]
        inner = payload.get("payload")
        if isinstance(inner, dict) and "flood_id" in inner:
            return inner["flood_id"]
    return None


def assert_ping_responded(
    master: MasterNode,
    satellite: SatelliteNode,
    timeout: float = 2.0,
    since: Optional[float] = None,
) -> None:
    """Assert that a PING from *satellite* produced a responsive PING back.

    There is no ``PONG`` message type in HiveMind. A node answers a PING flood
    by sending **its own** PING (same ``flood_id``) wrapped in a ``PROPAGATE``
    to every peer — see ``HiveMindListenerProtocol.handle_ping_message``. So
    the response this helper looks for is an inbound ``PROPAGATE`` (or bare
    ``PING``) record at the satellite.

    Checks, in order:

    1. the satellite sent a PING (bare, or wrapped in a PROPAGATE),
    2. the master recorded it inbound,
    3. the satellite recorded the master's responsive PING inbound.

    A bare ``PING`` is *not* routed by hivemind-core: only the inner PING of a
    ``PROPAGATE`` reaches ``handle_ping_message``. Send
    ``HiveMessage(PROPAGATE, payload=HiveMessage(PING, {"flood_id": ...}))``.

    Args:
        master:    The master node.
        satellite: The satellite that sent the PING.
        timeout:   Seconds to wait for the responsive PING at the satellite.
        since:     Only records at or after this ``time.monotonic()`` mark
                   count. Pass :func:`recorder_mark` taken just before the
                   probe emission, so a second back-to-back probe cannot pass
                   on a leftover response from a previous one. When the probe
                   payload carries ``flood_id``, the response is additionally
                   correlated by that id — an unrelated PING/PROPAGATE record
                   in the same window does not satisfy the assertion.
    """
    ping_types = (HiveMessageType.PING.value, HiveMessageType.PROPAGATE.value)

    def _since(records):
        if since is None:
            return records
        return [r for r in records if r.timestamp >= since]

    ping_out = _since([r for r in satellite.recorder.snapshot()
                        if r.direction == "out" and r.msg_type in ping_types])
    ping_in = _since([r for r in master.recorder.snapshot()
                       if r.direction == "in" and r.msg_type in ping_types])
    if not ping_out or not ping_in:
        raise AssertionError(
            f"PING was not delivered: satellite sent {len(ping_out)} "
            f"PING/PROPAGATE record(s), master received {len(ping_in)}.\n"
            f"Satellite records: {satellite.recorder.snapshot()}"
        )

    flood_id = _ping_flood_id(ping_out[0])

    def _matching_response():
        candidates = _since([r for r in satellite.recorder.snapshot()
                              if r.direction == "in" and r.msg_type in ping_types])
        if flood_id is None:
            return candidates
        return [r for r in candidates if _ping_flood_id(r) == flood_id]

    deadline = time.monotonic() + timeout
    while True:
        response = _matching_response()
        if response:
            return
        if time.monotonic() >= deadline:
            break
        time.sleep(0.02)

    raise AssertionError(
        f"PING round-trip incomplete: the satellite never received a "
        f"responsive PING (an inbound PROPAGATE carrying a PING"
        f"{f' with flood_id={flood_id!r}' if flood_id is not None else ''}) "
        f"within {timeout}s. A bare PING is dropped by hivemind-core — wrap "
        f"it in a PROPAGATE.\nSatellite records: {satellite.recorder.snapshot()}"
    )


def assert_rendezvous_handled(
    master: MasterNode,
    count: int = 1,
) -> None:
    """Assert that *count* RENDEZVOUS messages were handled by master.

    .. note::
        PENDING — RENDEZVOUS is reserved for rendezvous-nodes; routing is not
        yet implemented in hivemind-websocket-client.
        Track: `hivemind-websocket-client#103 <https://github.com/JarbasHiveMind/hivemind-websocket-client/pull/103>`_.
        Tests using this helper should be marked ``@pytest.mark.xfail(strict=False)``.
    """
    matches = _find(master.recorder, HiveMessageType.RENDEZVOUS.value)
    if len(matches) != count:
        raise AssertionError(
            f"[PENDING] Expected {count} RENDEZVOUS message(s) at master, "
            f"got {len(matches)}. RENDEZVOUS routing pending (ws#103).\n"
            f"All records: {master.recorder.snapshot()}"
        )


def assert_passthrough_message_delivered(
    node,
    message_type,
    count: int = 1,
    direction: Optional[str] = None,
) -> None:
    """Assert that *count* messages of *message_type* were passed through *node*
    untouched.

    Use this for message types with no core-side handler (e.g. RENDEZVOUS,
    which has a wire code but is not routed by hivemind-core): core is
    expected to forward the payload without inspection. Verify the routing
    status against the matrix in ``LIBRARY.md``.
    """
    matches = _find(node.recorder, message_type.value, direction=direction)
    if len(matches) != count:
        raise AssertionError(
            f"Expected {count} {message_type.name} message(s) (direction={direction!r}) "
            f"at '{node.recorder.name}', got {len(matches)}.\n"
            f"All records: {node.recorder.snapshot()}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# OVOS-BRIDGE-1 conformance assertions
#
# Each helper directly implements one normative clause from the three specs:
#   OVOS-BRIDGE-1  (bus bridge / opaque relay)
#   OVOS-SESSION-1 (session wire shape)
#   OVOS-SESSION-2 (state ownership)
#
# Assertions that operate on bus_inject records (the OVOS bus side) read
# the Message objects stored by _recording_inject in node.py.
# Assertions that operate on inbound/outbound HiveMessage records read the
# raw payload dict stored by the recorder.
# ─────────────────────────────────────────────────────────────────────────────


def assert_msg1_envelope(master: MasterNode, msg_type: str, count: int = 1) -> None:
    """Assert that bus-injected messages conform to the OVOS-MSG-1 envelope.

    BRIDGE-1 §2: "A bridge MUST conform to OVOS-MSG-1 for all bus emissions."

    Checks that every ``bus_inject`` record for *msg_type* at *master* carries:
    - a non-empty ``msg_type`` field (the OVOS message topic)
    - a ``context`` dict (routing envelope present)

    Args:
        master:    The master node.
        msg_type:  The OVOS bus message type to check (e.g. ``"speak"``).
        count:     Minimum number of conformant injections required (default 1).
    """
    injected = [
        r for r in master.recorder.snapshot()
        if r.direction == "bus_inject" and r.msg_type == msg_type
    ]
    if len(injected) < count:
        raise AssertionError(
            f"assert_msg1_envelope: expected at least {count} bus_inject record(s) "
            f"for '{msg_type}', found {len(injected)}.\n"
            f"All records: {master.recorder.snapshot()}"
        )
    errors: List[str] = []
    for r in injected:
        msg = r.payload
        # payload is a Message instance for bus_inject records
        if not getattr(msg, "msg_type", None):
            errors.append(f"record {r!r}: missing or empty msg_type on Message")
        if not isinstance(getattr(msg, "context", None), dict):
            errors.append(f"record {r!r}: context is not a dict (got {type(getattr(msg, 'context', None)).__name__})")
    if errors:
        raise AssertionError(
            "assert_msg1_envelope: OVOS-MSG-1 envelope violations:\n  "
            + "\n  ".join(errors)
        )


def assert_source_stamped(
    master: MasterNode,
    satellite: SatelliteNode,
    other_satellites: Optional[List[SatelliteNode]] = None,
) -> None:
    """Assert inbound bus messages carry a unique, stable ``context.source`` for *satellite*.

    BRIDGE-1 §3.1: "On receiving a message from an external participant, the bridge
    MUST ensure the resulting bus Message carries a unique identifier for that
    participant in context.source."

    Checks:
    - Every ``bus_inject`` record from *satellite* carries a non-empty
      ``context["source"]``.
    - All records from the same satellite share the same source value (stable).
    - If *other_satellites* is given, their sources are distinct from this
      satellite's source (unique across peers).

    Args:
        master:           The master node.
        satellite:        The satellite whose injections are inspected.
        other_satellites: Optional list of other connected satellites; if given,
                          their source values must differ from *satellite*'s.
    """
    peer = satellite.peer
    my_records = [
        r for r in master.recorder.snapshot()
        if r.direction == "bus_inject" and r.peer == peer
    ]
    if not my_records:
        raise AssertionError(
            f"assert_source_stamped: no bus_inject records from peer={peer!r}.\n"
            f"All records: {master.recorder.snapshot()}"
        )

    errors: List[str] = []
    sources = set()
    for r in my_records:
        msg = r.payload
        src = (getattr(msg, "context", {}) or {}).get("source")
        if not src:
            errors.append(f"record {r!r}: context.source absent or empty")
        else:
            sources.add(src)

    if len(sources) > 1:
        errors.append(
            f"source not stable — multiple values seen across records: {sources}"
        )

    if errors:
        raise AssertionError(
            "assert_source_stamped: BRIDGE-1 §3.1 source-stamping failures:\n  "
            + "\n  ".join(errors)
        )

    my_source = next(iter(sources)) if sources else None

    if other_satellites and my_source:
        for other in other_satellites:
            other_peer = other.peer
            other_records = [
                r for r in master.recorder.snapshot()
                if r.direction == "bus_inject" and r.peer == other_peer
            ]
            for r in other_records:
                msg = r.payload
                src = (getattr(msg, "context", {}) or {}).get("source")
                if src and src == my_source:
                    errors.append(
                        f"source collision: satellite '{satellite.name}' and "
                        f"'{other.name}' share source={my_source!r} — sources MUST be distinct"
                    )
                    break

    if errors:
        raise AssertionError(
            "assert_source_stamped: BRIDGE-1 §3.1 source uniqueness failures:\n  "
            + "\n  ".join(errors)
        )


def assert_destination_routed(
    master: MasterNode,
    target_satellite: SatelliteNode,
    other_satellites: List[SatelliteNode],
    msg_type: str,
    timeout: float = 2.0,
    settle: float = 0.2,
    since: Optional[float] = None,
) -> None:
    """Assert an outbound message reaches only *target_satellite* and not others.

    BRIDGE-1 §3.2: "The bridge MUST relay the Message to the corresponding
    external participant" when ``context.destination`` matches.  A message
    destined for one satellite MUST NOT be delivered to others (no cross-talk).

    Checks:
    - *target_satellite* recorded at least one inbound message of *msg_type*.
    - None of *other_satellites* recorded an inbound message of *msg_type*.

    The master emits a BUS message with ``context.destination`` set to
    *target_satellite*'s peer and the bridge must route it accordingly.  This
    helper inspects the satellite recorders directly; the bus emission itself
    is the caller's responsibility.

    Args:
        master:            The master node (unused in the check; kept for
                           signature parity and future extension).
        target_satellite:  The satellite that should receive the message.
        other_satellites:  Satellites that must NOT receive the message.
        msg_type:          HiveMessage type value to look for at the satellites
                           (typically ``HiveMessageType.BUS.value``).
        timeout:           Seconds to wait for the target to receive the message.
        settle:            Seconds to wait after the target receipt so a delayed
                           misroute can still surface.
        since:             Only traffic recorded at or after this
                           ``time.monotonic()`` mark counts as cross-talk. Pass
                           :func:`recorder_mark` taken just before the emit for
                           an exact window. When omitted, the window opens
                           ``settle`` seconds before the target's own receipt,
                           so earlier history never counts.
    """
    # Wait for target
    recv = target_satellite.recorder.wait_for(msg_type, direction="in", timeout=timeout)
    if recv is None:
        raise AssertionError(
            f"assert_destination_routed: '{target_satellite.name}' did NOT receive "
            f"a '{msg_type}' message within {timeout}s.\n"
            f"Records: {target_satellite.recorder.snapshot()}"
        )

    # A delayed misroute can land just after the target receipt; give it a
    # moment to surface before declaring no cross-talk (BRIDGE-1 §3.2).
    if settle > 0:
        time.sleep(settle)

    # Only traffic from this probe counts. Counting the whole history made the
    # check fail on any earlier unrelated delivery — and pass for the wrong
    # reason when the probe itself never arrived anywhere.
    window_start = since if since is not None else (recv.timestamp - max(settle, 0.0))

    errors: List[str] = []
    for other in other_satellites:
        matches = [
            r for r in other.recorder.snapshot()
            if r.direction == "in" and r.msg_type == msg_type
            and r.timestamp >= window_start
        ]
        if matches:
            errors.append(
                f"'{other.name}' received {len(matches)} '{msg_type}' message(s) "
                "but should not have (destination routing cross-talk)"
            )
    if errors:
        raise AssertionError(
            "assert_destination_routed: BRIDGE-1 §3.2 routing failures:\n  "
            + "\n  ".join(errors)
        )


def assert_session_inbound_preserved(
    master: MasterNode,
    satellite: SatelliteNode,
    expected_session: dict,
) -> None:
    """Assert the satellite's session CONTENTS are preserved into the bus
    context on injection.

    BRIDGE-1 §4.1 (inbound): "The bridge MUST extract the session from the
    external payload and place it in the bus Message context."

    Checks that the last ``bus_inject`` record from *satellite* has each key
    of *expected_session* present and equal in ``context["session"]``.

    ``session_id`` is deliberately NOT accepted here: since hivemind-core
    NATs a non-admin's declared session_id to ``f"{conn_nonce}:{declared}"``
    before it reaches the bus (HIVEMIND-BRIDGE-1 §4), it is never preserved
    verbatim and an exact-match check on it would be a caller bug baked into
    the harness. Use :func:`assert_session_id_natted` for the id, and this
    helper only for the session's other fields (lang, location, units, ...).

    Args:
        master:           The master node.
        satellite:        The satellite that sent the message.
        expected_session: Dict of session fields (excluding ``session_id``)
                          that must be present and equal in the injected
                          message's context.session.
    """
    if "session_id" in expected_session:
        raise ValueError(
            "assert_session_inbound_preserved: 'session_id' is NATted per "
            "connection, not preserved verbatim — use "
            "assert_session_id_natted() to check it."
        )

    peer = satellite.peer
    records = [
        r for r in master.recorder.snapshot()
        if r.direction == "bus_inject" and r.peer == peer
    ]
    if not records:
        raise AssertionError(
            f"assert_session_inbound_preserved: no bus_inject records from "
            f"peer={peer!r}.\nAll records: {master.recorder.snapshot()}"
        )

    record = records[-1]
    msg = record.payload
    actual_session = (getattr(msg, "context", {}) or {}).get("session") or {}

    errors: List[str] = []
    for key, expected_val in expected_session.items():
        actual_val = actual_session.get(key)
        if actual_val != expected_val:
            errors.append(
                f"session.{key}: expected={expected_val!r}, actual={actual_val!r}"
            )

    if errors:
        raise AssertionError(
            "assert_session_inbound_preserved: BRIDGE-1 §4.1 inbound session "
            "fidelity failures:\n  " + "\n  ".join(errors)
        )


def assert_session_id_natted(
    master: MasterNode,
    satellite: SatelliteNode,
    declared_id: str,
    *,
    admin: bool = False,
) -> None:
    """Assert the Layer-1 session id installed on *satellite*'s last inbound
    message is the NATted form of *declared_id*.

    HIVEMIND-BRIDGE-1 §4: a non-admin's declared session_id is namespaced by
    the connection's nonce (``f"{conn_nonce}:{declared_id}"``) before it
    reaches the bus, so two peers that happen to declare the same id (e.g.
    both "default") never collide onto one OVOS session. An admin connection
    is trusted to address orchestrator sessions directly and is stamped with
    the raw declared id instead.

    Reads the live ``conn_nonce`` off the master's
    ``HiveMindClientConnection`` for *satellite*'s peer and asserts the exact
    NATted string, not just its shape — a wrong or stale nonce cannot slip
    through a merely-structural check.

    Args:
        master:      The master node.
        satellite:   The satellite whose last bus_inject is inspected.
        declared_id: The session_id *satellite* declared on the wire.
        admin:       True if the satellite is connected as an admin: the id
                     is expected raw, not NATted.
    """
    peer = satellite.peer
    if peer is None:
        raise AssertionError(
            "assert_session_id_natted: satellite has no peer — it is disconnected."
        )
    records = [
        r for r in master.recorder.snapshot()
        if r.direction == "bus_inject" and r.peer == peer
    ]
    if not records:
        raise AssertionError(
            f"assert_session_id_natted: no bus_inject records from "
            f"peer={peer!r}.\nAll records: {master.recorder.snapshot()}"
        )

    msg = records[-1].payload
    actual = ((getattr(msg, "context", {}) or {}).get("session") or {}).get("session_id")

    if admin:
        expected = declared_id
    else:
        conn = master.hm_protocol.clients.get(peer)
        if conn is None:
            raise AssertionError(
                f"assert_session_id_natted: peer {peer!r} is not (or no longer) "
                "connected at master — cannot read its session_namespace."
            )
        # HIVEMIND-BRIDGE-1 §4 NAT token is the durable, identity-scoped
        # session_namespace (core #299/#306), not the per-connection
        # conn_nonce that used to back this before those changes.
        expected = f"{conn.session_namespace}:{declared_id}"

    if actual != expected:
        raise AssertionError(
            "assert_session_id_natted: BRIDGE-1 §4 per-connection NAT mismatch "
            f"— expected session_id={expected!r}, got {actual!r}."
        )


def assert_sessions_isolated(
    master: MasterNode,
    satellite: SatelliteNode,
    declared_ids: List[str],
) -> None:
    """Assert that distinct declared session ids sent over ONE connection
    each land on a distinct, isolated Layer-1 session.

    HIVEMIND-BRIDGE-1 §4 (hivemind-core#287): a single connection may
    multiplex several declared sessions — a relay forwarding several peers,
    or a per-call bridge like baresip that mints a fresh session_id per
    call. Each declared session MUST produce its own OVOS session, never
    merge onto another, while still sharing the connection's nonce (they
    are, after all, the same peer).

    For each id in *declared_ids*, finds the bus_inject record whose
    ``context.session.session_id`` ends with ``f":{declared_id}"`` and
    checks:

    - a record exists for every declared id (none went missing or collided
      away);
    - the resulting Layer-1 ids are pairwise distinct;
    - they all share exactly one nonce prefix (same connection).

    Args:
        master:       The master node.
        satellite:    The satellite that declared all of *declared_ids* over
                      its single connection.
        declared_ids: The distinct session_id values sent, in any order.
    """
    peer = satellite.peer
    records = [
        r for r in master.recorder.snapshot()
        if r.direction == "bus_inject" and r.peer == peer
    ]

    layer1_by_declared: Dict[str, str] = {}
    for declared in declared_ids:
        suffix = f":{declared}"
        match = next(
            (r for r in records
             if (((getattr(r.payload, "context", {}) or {}).get("session") or {})
                 .get("session_id") or "").endswith(suffix)),
            None,
        )
        if match is None:
            raise AssertionError(
                f"assert_sessions_isolated: no bus_inject record with a "
                f"Layer-1 session_id ending in {suffix!r} (declared={declared!r}).\n"
                f"All records from peer: {records}"
            )
        session = (getattr(match.payload, "context", {}) or {}).get("session") or {}
        layer1_by_declared[declared] = session.get("session_id")

    layer1_ids = list(layer1_by_declared.values())
    if len(set(layer1_ids)) != len(declared_ids):
        raise AssertionError(
            "assert_sessions_isolated: declared session ids did not each "
            f"produce a distinct Layer-1 id: {layer1_by_declared}"
        )

    prefixes = {sid.split(":", 1)[0] for sid in layer1_ids}
    if len(prefixes) != 1:
        raise AssertionError(
            "assert_sessions_isolated: expected all declared sessions to "
            f"share a single connection nonce prefix, got {prefixes}: "
            f"{layer1_by_declared}"
        )


def assert_session_contents_merged_over_baseline(
    master: MasterNode,
    satellite: SatelliteNode,
    expected_baseline: dict,
) -> None:
    """Assert a thin message keeps the HELLO-established session baseline.

    HIVEMIND-BRIDGE-1 §4: a per-message session that omits a field (e.g. a
    control message carrying only ``session_id``) is merged over the
    connection's HELLO baseline, not replaced by a fresh session — the
    baseline's ``location``/``lang``/etc. survive untouched. Building a
    fresh ``Session`` for a thin message instead of merging would fabricate
    the master's own defaults for the missing fields, silently overwriting
    a satellite's real values (e.g. its timezone).

    Checks that the last ``bus_inject`` record from *satellite* carries
    every field in *expected_baseline* unchanged in ``context["session"]``.

    Do not pass ``session_id`` here — it is NATted per connection, not a
    preserved content field; use :func:`assert_session_id_natted` for it.

    Args:
        master:            The master node.
        satellite:         The satellite whose last bus_inject is inspected.
        expected_baseline: HELLO-time session fields (e.g. ``{"lang": ...,
                           "location": ...}``) that a later thin message
                           must still carry.
    """
    if "session_id" in expected_baseline:
        raise ValueError(
            "assert_session_contents_merged_over_baseline: 'session_id' is "
            "NATted per connection, not a preserved content field — use "
            "assert_session_id_natted() to check it."
        )

    peer = satellite.peer
    records = [
        r for r in master.recorder.snapshot()
        if r.direction == "bus_inject" and r.peer == peer
    ]
    if not records:
        raise AssertionError(
            f"assert_session_contents_merged_over_baseline: no bus_inject "
            f"records from peer={peer!r}.\nAll records: {master.recorder.snapshot()}"
        )

    msg = records[-1].payload
    actual_session = (getattr(msg, "context", {}) or {}).get("session") or {}

    errors: List[str] = []
    for key, expected_val in expected_baseline.items():
        actual_val = actual_session.get(key)
        if actual_val != expected_val:
            errors.append(
                f"session.{key}: expected baseline value {expected_val!r}, "
                f"got {actual_val!r} — the thin message clobbered the "
                "baseline instead of merging over it"
            )

    if errors:
        raise AssertionError(
            "assert_session_contents_merged_over_baseline: BRIDGE-1 §4 "
            "contents-merge failures:\n  " + "\n  ".join(errors)
        )


def assert_session_outbound_preserved(
    satellite: SatelliteNode,
    expected_session: dict,
    timeout: float = 2.0,
) -> None:
    """Assert a bus-originated message's session reaches the satellite intact.

    BRIDGE-1 §4.1 (outbound): "The bridge MUST extract the session from the
    bus Message and include it in the external payload."

    Checks the last inbound BUS message at *satellite* and verifies that
    *expected_session* fields are present in its payload's ``context.session``.

    Args:
        satellite:        The satellite that should receive the session.
        expected_session: Dict of session fields that must be present and equal
                          in the received message's context.session.
        timeout:          Seconds to wait for an inbound BUS message.
    """
    recv = satellite.recorder.wait_for(HiveMessageType.BUS.value, direction="in",
                                       timeout=timeout)
    if recv is None:
        raise AssertionError(
            f"assert_session_outbound_preserved: '{satellite.name}' received no "
            f"inbound BUS message within {timeout}s.\n"
            f"Records: {satellite.recorder.snapshot()}"
        )

    # payload for inbound BUS records is the raw _payload dict:
    # {"type": <msg_type>, "data": {...}, "context": {...}}
    payload = recv.payload if isinstance(recv.payload, dict) else {}
    actual_session = (payload.get("context") or {}).get("session") or {}

    errors: List[str] = []
    for key, expected_val in expected_session.items():
        actual_val = actual_session.get(key)
        if actual_val != expected_val:
            errors.append(
                f"session.{key}: expected={expected_val!r}, actual={actual_val!r}"
            )

    if errors:
        raise AssertionError(
            "assert_session_outbound_preserved: BRIDGE-1 §4.1 outbound session "
            "fidelity failures:\n  " + "\n  ".join(errors)
        )


def assert_fifo_order(
    master: MasterNode,
    satellite: SatelliteNode,
    msg_type: str,
    count: int,
    timeout: float = 5.0,
) -> None:
    """Assert that *count* sequential messages from *satellite* arrive in send order.

    BRIDGE-1 §5: "Sequential utterances from the same participant MUST be
    placed on the bus in the order they were received."

    Checks that the ``bus_inject`` records for *msg_type* from *satellite*
    arrive in ascending timestamp order (no reorder).  The caller must
    send *count* messages with a monotonically increasing marker in
    ``data["_fifo_seq"]``; this helper verifies that order is preserved.

    Args:
        master:    The master node.
        satellite: The satellite that sent the messages.
        msg_type:  OVOS bus message type used for the sequenced messages.
        count:     Number of messages expected in order.
        timeout:   Seconds to wait for all *count* messages to arrive.
    """
    peer = satellite.peer
    deadline = time.monotonic() + timeout
    while True:
        records = [
            r for r in master.recorder.snapshot()
            if r.direction == "bus_inject" and r.peer == peer and r.msg_type == msg_type
        ]
        if len(records) >= count:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(0.02)

    records = [
        r for r in master.recorder.snapshot()
        if r.direction == "bus_inject" and r.peer == peer and r.msg_type == msg_type
    ][-count:]  # validate the most recent batch, not stale earlier traffic

    if len(records) < count:
        raise AssertionError(
            f"assert_fifo_order: expected {count} '{msg_type}' bus_inject records "
            f"from peer={peer!r}, got {len(records)} after {timeout}s.\n"
            f"All records: {master.recorder.snapshot()}"
        )

    errors: List[str] = []
    seqs = []
    for r in records:
        msg = r.payload
        data = getattr(msg, "data", {}) or {}
        seq = data.get("_fifo_seq")
        seqs.append(seq)

    # If _fifo_seq was set, verify monotonically increasing
    if all(s is not None for s in seqs):
        for i in range(1, len(seqs)):
            if seqs[i] <= seqs[i - 1]:
                errors.append(
                    f"FIFO reorder at position {i}: seq[{i-1}]={seqs[i-1]} "
                    f"followed by seq[{i}]={seqs[i]} (expected strictly increasing)"
                )
    else:
        # Timestamps are stamped on arrival, so they are always ascending —
        # checking them proves nothing. FIFO can only be verified with an
        # explicit sequence marker set by the sender.
        missing = [i for i, seq in enumerate(seqs) if seq is None]
        raise AssertionError(
            "assert_fifo_order: cannot verify FIFO without a '_fifo_seq' marker. "
            f"Records at position(s) {missing} carry no data['_fifo_seq']. "
            "Send each message with a strictly increasing data['_fifo_seq'] value."
        )

    if errors:
        raise AssertionError(
            "assert_fifo_order: BRIDGE-1 §5 FIFO ordering failures:\n  "
            + "\n  ".join(errors)
        )


def assert_session_propagated_unchanged(
    master: MasterNode,
    field: str,
    value: Any,
    msg_type: Optional[str] = None,
) -> None:
    """Assert a session field rides unchanged across the bridge derivation.

    SESSION-1 §4: "Every field in §3 propagates unchanged — no field is
    non-propagating."

    Checks that every ``bus_inject`` record at *master* (optionally filtered
    to *msg_type*) has ``context["session"][field] == value``.

    Args:
        master:    The master node.
        field:     Session field name (e.g. ``"lang"``).
        value:     Expected value that must be present and unchanged.
        msg_type:  Optional OVOS message type to filter records.
    """
    records = [
        r for r in master.recorder.snapshot()
        if r.direction == "bus_inject"
        and (msg_type is None or r.msg_type == msg_type)
    ]
    if not records:
        raise AssertionError(
            f"assert_session_propagated_unchanged: no bus_inject records "
            f"(msg_type={msg_type!r}).\nAll records: {master.recorder.snapshot()}"
        )

    errors: List[str] = []
    for r in records:
        msg = r.payload
        session = (getattr(msg, "context", {}) or {}).get("session") or {}
        actual = session.get(field)
        if actual != value:
            errors.append(
                f"record {r!r}: session.{field}={actual!r} (expected {value!r})"
            )

    if errors:
        raise AssertionError(
            "assert_session_propagated_unchanged: SESSION-1 §4 propagation "
            "failures:\n  " + "\n  ".join(errors)
        )


def assert_source_hidden(
    satellite: SatelliteNode,
    generic_id: str = "hive",
    msg_type: Optional[str] = None,
    timeout: float = 2.0,
) -> None:
    """Assert topology-hiding: outbound source is overwritten with *generic_id*.

    BRIDGE-1 §6 (MAY): "A bridge MAY perform topology hiding by overwriting
    the source of outbound messages with a generic assistant ID (e.g. 'hive')."

    Checks that inbound BUS messages at *satellite* carry
    ``context["source"] == generic_id`` rather than any internal peer address.

    This assertion is for the optional topology-hiding feature; mark tests
    using it with ``@pytest.mark.skipif`` if the feature is not enabled.

    Args:
        satellite:  The satellite that received the message.
        generic_id: Expected generic source id (default ``"hive"``).
        msg_type:   HiveMessage type to check (default: ``"bus"``).
        timeout:    Seconds to wait for an inbound message.
    """
    mt = msg_type or HiveMessageType.BUS.value
    recv = satellite.recorder.wait_for(mt, direction="in", timeout=timeout)
    if recv is None:
        raise AssertionError(
            f"assert_source_hidden: '{satellite.name}' received no inbound "
            f"'{mt}' message within {timeout}s.\n"
            f"Records: {satellite.recorder.snapshot()}"
        )

    payload = recv.payload if isinstance(recv.payload, dict) else {}
    context = payload.get("context") or {}
    actual_source = context.get("source")

    if actual_source != generic_id:
        raise AssertionError(
            f"assert_source_hidden: BRIDGE-1 §6 topology-hiding — "
            f"expected source={generic_id!r}, got source={actual_source!r}.\n"
            f"Payload context: {context}"
        )
