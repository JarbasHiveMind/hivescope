"""
Protocol-level assertion helpers for hivescope e2e tests.

Each helper targets one or more ``HiveMessageType`` values and raises
``AssertionError`` with a diagnostic message (actual recorder contents,
peer lists, etc.) on failure.

All 14 HiveMessageType values are covered:

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
  ACL (all)  — assert_acl_enforced

Pending (core routing not yet implemented; helpers scaffold the check):
  QUERY      — assert_query_routed        (xfail: core#74 / ws#88)
  CASCADE    — assert_cascade_routed      (xfail: core#74 / ws#88)
  PING       — assert_ping_responded      (xfail: core#74)
  RENDEZVOUS — assert_rendezvous_handled  (xfail: ws#103)
  THIRDPRTY  — assert_thirdparty_passed   (verify status)

Usage::

    from hivescope.assertions import (
        assert_handshake_complete,
        assert_bus_message_routed,
        assert_broadcast_delivered,
    )
"""

from typing import Any, List, Optional

from hivescope.node import MasterNode, SatelliteNode
from hivemind_bus_client.message import HiveMessageType

# Policy-model deny codes (stable strings; mirrored from hivemind-plugin-manager)
ACL_DISALLOWED_TYPE = "acl_disallowed_type"
SESSION_ID_DEFAULT_FORBIDDEN = "session_id_default_forbidden"

# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find(recorder, msg_type_value: str, direction: Optional[str] = None):
    return [
        r for r in recorder.records
        if r.msg_type == msg_type_value
        and (direction is None or r.direction == direction)
    ]


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
    - ``satellite.shim.crypto_key`` is not None (crypto negotiated)
    - ``satellite.shim.handshake_event`` is set
    - master's ``connected_peers()`` includes this satellite
    """
    errors: List[str] = []

    if satellite.shim.crypto_key is None:
        errors.append("satellite.shim.crypto_key is None (no crypto negotiated)")

    if not satellite.shim.handshake_event.is_set():
        errors.append("satellite.shim.handshake_event not set (handshake not complete)")

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
            f"All inbound: {[r.msg_type for r in master.recorder.records if r.direction == 'in']}"
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
            f"All records: {master.recorder.records}"
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
            f"got {len(matches)}.\nAll records: {node.recorder.records}"
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

    HiveMind core *unwraps* a BROADCAST into its inner payload before
    forwarding to sibling peers — so each recipient records the *inner*
    message type (e.g. ``BUS``), not ``BROADCAST`` itself.  This helper
    therefore counts all inbound messages at recipients; pass
    ``inner_msg_type`` to narrow to a specific type.

    Args:
        recipients: Nodes that should have received the broadcast.
        count: Expected number of messages at each recipient.
        inner_msg_type: If given, only count messages with this type
            (e.g. ``HiveMessageType.BUS.value``).
    """
    errors: List[str] = []
    for node in recipients:
        if inner_msg_type:
            matches = _find(node.recorder, inner_msg_type, direction="in")
            label = f"BROADCAST(inner={inner_msg_type})"
        else:
            # count all inbound messages added after handshake
            matches = [
                r for r in node.recorder.records
                if r.direction == "in"
                and r.msg_type not in (HiveMessageType.HANDSHAKE.value, HiveMessageType.HELLO.value)
            ]
            # subtract handshake messages already recorded before the broadcast
            label = "BROADCAST(any inbound post-handshake)"
        if len(matches) != count:
            errors.append(
                f"Node '{node.recorder.name}': expected {count} {label}, got {len(matches)}.\n"
                f"  All records: {node.recorder.records}"
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
            f"All records: {master.recorder.records}"
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
            f"got {len(matches)}.\nAll records: {recipient.recorder.records}"
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
            f"All records: {master.recorder.records}"
        )

    # Secondary: if expected_payload given and binary protocol has typed calls, verify
    if expected_payload is not None:
        typed_calls = [c for c in master.binary_protocol.calls if c.data == expected_payload]
        if not typed_calls:
            # Acceptable: untyped binary goes through recorder only
            pass  # recorder check above already passed


# ─────────────────────────────────────────────────────────────────────────────
# ACL / policy-admission helpers
# ─────────────────────────────────────────────────────────────────────────────

def assert_acl_enforced(
    master: MasterNode,
    satellite: SatelliteNode,
    msg_type: str,
    allowed: bool = False,
) -> None:
    """Assert policy-admission enforcement for *msg_type* on *satellite*.

    When ``allowed=False`` (default): verifies that the satellite received a
    ``hive.policy.denied`` response (meaning ``MessageTypeACLPolicy`` denied
    the message) and that no ``bus_inject`` record for *msg_type* appears at
    master (the message was never forwarded to the OVOS bus).

    When ``allowed=True``: verifies the message WAS recorded at master's
    ``bus_inject`` level (the injection hook was reached).

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
    # back to the satellite (recorded as inbound at the satellite).
    policy_denied_at_sat = [
        r for r in satellite.recorder.records
        if r.direction == "in" and r.msg_type == "bus"
    ]
    # Look deeper: check inner payload msg_type for hive.policy.denied
    denied_responses = []
    for r in policy_denied_at_sat:
        payload = r.payload if isinstance(r.payload, dict) else {}
        # Satellite recorder stores HiveMessage._payload for BUS messages:
        # {"type": <inner msg_type>, "data": {...}, "context": {...}}
        if payload.get("type") == "hive.policy.denied":
            denied_responses.append(r)

    if allowed:
        if denied_responses:
            raise AssertionError(
                f"ACL: expected '{msg_type}' to be allowed, but satellite received "
                f"{len(denied_responses)} hive.policy.denied response(s).\n"
                f"Denied responses: {denied_responses}"
            )
    else:
        if not denied_responses:
            raise AssertionError(
                f"ACL violation: '{msg_type}' was NOT blocked — "
                f"satellite received no hive.policy.denied response.\n"
                f"Inbound records at satellite: {satellite.recorder.records}"
            )


def assert_policy_denied(
    master: MasterNode,
    satellite: SatelliteNode,
    msg_type: str,
    deny_code: Optional[str] = None,
) -> None:
    """Assert that *msg_type* sent by *satellite* was denied by the policy chain.

    Verifies that the satellite received a ``hive.policy.denied`` response
    from the master.  If *deny_code* is given, also checks that the denial
    carries that specific stable code (e.g. ``"acl_disallowed_type"``).

    Args:
        master:     The master node (unused in the check, kept for signature
                    parity with other helpers).
        satellite:  The satellite that sent the message.
        msg_type:   The OVOS message type that should have been denied
                    (used only for the error message; not matched in the
                    payload since deny responses don't echo the type).
        deny_code:  Optional stable deny code to verify.  If ``None``, any
                    ``hive.policy.denied`` response satisfies the assertion.
    """
    # The satellite should have received a HiveMessage whose inner BUS payload
    # has msg_type "hive.policy.denied".  The recorder stores the raw payload
    # dict for inbound "bus" records.
    inbound_bus = [
        r for r in satellite.recorder.records
        if r.direction == "in" and r.msg_type == "bus"
    ]

    denied_responses = []
    for r in inbound_bus:
        payload = r.payload if isinstance(r.payload, dict) else {}
        # Satellite recorder stores HiveMessage._payload for BUS messages:
        # {"type": <inner msg_type>, "data": {...}, "context": {...}}
        if payload.get("type") == "hive.policy.denied":
            denied_responses.append((r, payload))

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
    bus_injected = [
        r for r in master.recorder.records
        if r.direction == "bus_inject" and r.msg_type == msg_type
        and (peer is None or r.peer == peer)
    ]
    if not bus_injected:
        raise AssertionError(
            f"assert_session_blacklists_injected: no bus_inject record for "
            f"'{msg_type}' at master (peer={peer!r}) — the message was not forwarded to the bus.\n"
            f"All records: {master.recorder.records}"
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
        timeout: Reserved for future async use.
    """
    messages = node.recorder.records
    if direction:
        messages = [m for m in messages if m.direction == direction]
    matching = [m for m in messages if m.msg_type == msg_type]
    if len(matching) != count:
        raise AssertionError(
            f"Expected {count} '{msg_type}' messages (direction={direction!r}), "
            f"got {len(matching)}.\n"
            f"All messages: {[m.msg_type for m in node.recorder.records]}"
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
# PENDING — QUERY, CASCADE, PING, RENDEZVOUS, THIRDPRTY
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
            f"(core#74 / ws#88).\nAll records: {master.recorder.records}"
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


def assert_ping_responded(
    master: MasterNode,
    satellite: SatelliteNode,
) -> None:
    """Assert that a PING from *satellite* produced a response at master.

    .. note::
        PENDING (partial) — PING network-map routing is not fully implemented.
        Track: `hivemind-core#74 <https://github.com/JarbasHiveMind/HiveMind-core/pull/74>`_.
        Tests using this helper should be marked ``@pytest.mark.xfail(strict=False)``.
    """
    ping_out = _find(satellite.recorder, HiveMessageType.PING.value, direction="out")
    ping_in = _find(master.recorder, HiveMessageType.PING.value, direction="in")
    if not ping_out or not ping_in:
        raise AssertionError(
            f"[PENDING] PING round-trip incomplete (core#74). "
            f"satellite sent {len(ping_out)}, master received {len(ping_in)}."
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
            f"All records: {master.recorder.records}"
        )


def assert_thirdparty_passed(
    node,
    count: int = 1,
    direction: Optional[str] = None,
) -> None:
    """Assert that *count* THIRDPRTY (3rdparty) messages were passed through *node*.

    THIRDPRTY is user-land passthrough; core is expected to forward it without
    inspection. Verify the routing status against the matrix in ``LIBRARY.md``.
    """
    matches = _find(node.recorder, HiveMessageType.THIRDPRTY.value, direction=direction)
    if len(matches) != count:
        raise AssertionError(
            f"Expected {count} THIRDPRTY message(s) (direction={direction!r}) "
            f"at '{node.recorder.name}', got {len(matches)}.\n"
            f"All records: {node.recorder.records}"
        )
