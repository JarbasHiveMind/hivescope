"""
Hivescope self-tests — protocol-matrix coverage.

These tests verify hivescope's own assertion helpers and templates against
the 14 HiveMessageType values.  They stand in for the CI build-tests path
(`test_path: 'tests'`) and catch regressions in the library itself.

Ready types (core routing implemented):
  HANDSHAKE, HELLO, BUS, SHARED_BUS, BROADCAST, PROPAGATE,
  ESCALATE, INTERCOM, BINARY

Pending types (xfail scaffolds, strict=False):
  QUERY      — core#74 / ws#88
  CASCADE    — core#74 / ws#88
  PING       — core#74  (partial)
  RENDEZVOUS — ws#103
  THIRDPRTY  — verify status

ACL enforcement:
  assert_acl_enforced / assert_broadcast_blocked
"""

import pytest
import importlib.util

# ACL tests exercise the policy admission chain (HiveMind-core#89 MessageTypeACLPolicy,
# hivemind-ovos-agent-plugin#3 OVOSAgentPolicy). Skip them when those are not in the
# installed packages so the suite is green against released deps; they run
# automatically once the policy packages are installed.
_HAS_POLICY_CHAIN = importlib.util.find_spec("hivemind_core.policy") is not None
_HAS_OVOS_POLICY = importlib.util.find_spec("hivemind_ovos_agent_plugin") is not None
_requires_policy_chain = pytest.mark.skipif(
    not _HAS_POLICY_CHAIN,
    reason="policy admission chain (HiveMind-core#89) not in installed hivemind-core",
)
_requires_ovos_policy = pytest.mark.skipif(
    not (_HAS_POLICY_CHAIN and _HAS_OVOS_POLICY),
    reason="OVOSAgentPolicy (hivemind-ovos-agent-plugin#3) + core#89 not installed",
)

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message

from hivescope import (
    TopologyBuilder,
    assert_handshake_complete,
    assert_encryption_match,
    assert_message_routed,
    assert_client_registered,
    assert_bus_message_routed,
    assert_hello_received,
    assert_broadcast_delivered,
    assert_broadcast_blocked,
    assert_propagate_delivered,
    assert_escalate_delivered,
    assert_binary_delivered,
    assert_acl_enforced,
)
from hivescope.assertions import (
    assert_intercom_delivered,
    assert_shared_bus_received,
    assert_query_routed,
    assert_cascade_routed,
    assert_ping_responded,
    assert_rendezvous_handled,
    assert_thirdparty_passed,
)
from hivescope.assertions import assert_policy_denied, assert_session_blacklists_injected
from hivescope.scenarios import single_satellite, three_satellites, with_relay


# ─────────────────────────────────────────────────────────────────────────────
# Public API smoke test
# ─────────────────────────────────────────────────────────────────────────────

def test_public_api_importable():
    """All __all__ symbols are importable from the top-level package."""
    import hivescope
    for name in hivescope.__all__:
        assert hasattr(hivescope, name), f"hivescope.{name} missing from package"


def test_recorder_messages_alias():
    """MessageRecorder.messages returns a snapshot of .records."""
    from hivescope.recorder import MessageRecorder
    r = MessageRecorder("test")
    r.record("in", "bus", {}, "peer1")
    assert r.messages == r.records
    # A snapshot, not the live list: appending later must not mutate it.
    assert r.messages is not r.records
    snap = r.messages
    r.record("in", "bus", {}, "peer2")
    assert len(snap) == 1
    assert len(r.messages) == 2


# ─────────────────────────────────────────────────────────────────────────────
# HANDSHAKE + HELLO
# ─────────────────────────────────────────────────────────────────────────────

def test_handshake_complete():
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")
        assert_handshake_complete(m, s)
        assert_encryption_match(m, s)
        assert_client_registered(m, s.peer)
    finally:
        b.stop_all()


def test_hello_received():
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        assert_hello_received(m, count=1)
    finally:
        b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# BUS
# ─────────────────────────────────────────────────────────────────────────────

def test_bus_message_routed():
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")
        s.send(HiveMessage(HiveMessageType.BUS, payload=Message("speak", {"utterance": "hello"})))
        assert_bus_message_routed(m, count=1)
    finally:
        b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# BROADCAST
# ─────────────────────────────────────────────────────────────────────────────

def test_broadcast_delivered():
    # BROADCAST requires is_admin=True — non-admin senders are rejected by core
    b = TopologyBuilder()
    m = b.add_master("M0")
    b.add_satellite("S0", upstream=m, is_admin=True)  # sender — must be admin
    b.add_satellite("S1", upstream=m)
    b.add_satellite("S2", upstream=m)
    b.start_all()
    try:
        s0 = b.get_satellite("S0")
        s1 = b.get_satellite("S1")
        s2 = b.get_satellite("S2")
        # BROADCAST payload must be a nested HiveMessage, not a plain Message
        inner = HiveMessage(HiveMessageType.BUS, payload=Message("speak", {"utterance": "hi"}))
        msg = HiveMessage(HiveMessageType.BROADCAST, payload=inner)
        s0.send(msg)
        # Core unwraps BROADCAST and forwards the inner BUS to siblings
        assert_broadcast_delivered(s1, s2, count=1,
                                   inner_msg_type=HiveMessageType.BUS.value)
    finally:
        b.stop_all()


@_requires_policy_chain
def test_broadcast_blocked_by_acl():
    b = TopologyBuilder()
    m = b.add_master("M0")
    b.add_satellite("S0", upstream=m, can_broadcast=False)
    b.add_satellite("S1", upstream=m)
    b.start_all()
    try:
        s0 = b.get_satellite("S0")
        s1 = b.get_satellite("S1")
        inner = HiveMessage(HiveMessageType.BUS, payload=Message("speak", {"utterance": "blocked"}))
        s0.send(HiveMessage(HiveMessageType.BROADCAST, payload=inner))
        assert_broadcast_blocked(s1)
    finally:
        b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# BUS ACL — per-client message-type allowlist (MessageTypeACLPolicy)
# ─────────────────────────────────────────────────────────────────────────────

@_requires_policy_chain
def test_bus_acl_allowed_type_reaches_master():
    """A satellite with ``allowed_types=["recognizer_loop:utterance"]`` can inject
    that message type onto the master bus.  Proves that the ACL whitelist is live
    (not vacuously deny-all), i.e. the DB entry carrying ``allowed_types`` is
    reachable via ``resolve_user`` on the active connection.
    """
    import time

    b = TopologyBuilder()
    m = b.add_master("M0")
    b.add_satellite("S0", upstream=m, allowed_types=["recognizer_loop:utterance"])
    b.start_all()
    try:
        s = b.get_satellite("S0")
        seen = []
        m.agent_protocol.bus.on("recognizer_loop:utterance", seen.append)

        s.send(HiveMessage(
            HiveMessageType.BUS,
            payload=Message("recognizer_loop:utterance", {"utterances": ["hello"]}),
        ))

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not seen:
            time.sleep(0.02)

        assert seen, (
            "recognizer_loop:utterance did NOT reach the master bus — "
            "allowed_types ACL is blocking an explicitly-allowed type"
        )
    finally:
        b.stop_all()


@_requires_policy_chain
def test_bus_acl_denied_type_does_not_reach_master():
    """A satellite WITHOUT any ``allowed_types`` (deny-all by default) cannot
    inject a BUS message onto the master bus.  The message must be silently
    dropped by ``MessageTypeACLPolicy`` — not raise, not disconnect.
    """
    import time

    b = TopologyBuilder()
    m = b.add_master("M0")
    # No allowed_types → deny-by-default whitelist model → all types blocked.
    b.add_satellite("S0", upstream=m)
    b.start_all()
    try:
        s = b.get_satellite("S0")
        seen = []
        m.agent_protocol.bus.on("recognizer_loop:utterance", seen.append)

        s.send(HiveMessage(
            HiveMessageType.BUS,
            payload=Message("recognizer_loop:utterance", {"utterances": ["hello"]}),
        ))

        time.sleep(0.2)  # give any errant dispatch a window to land
        assert not seen, (
            "recognizer_loop:utterance reached the master bus — "
            "MessageTypeACLPolicy did not enforce the deny-all default"
        )
    finally:
        b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# ACL — policy-model paths (MessageTypeACLPolicy + OVOSAgentPolicy)
# ─────────────────────────────────────────────────────────────────────────────

@_requires_policy_chain
def test_acl_allowed_types_restricted_satellite_utterance_denied():
    """Path (a): allowed_types-restricted satellite's utterance is denied.

    A satellite whose ``allowed_types`` excludes ``recognizer_loop:utterance``
    must have its utterance blocked by ``MessageTypeACLPolicy`` with code
    ``acl_disallowed_type``.  The message must never reach the agent bus.
    """
    import time

    b = TopologyBuilder()
    m = b.add_master("M0")
    # speak only → recognizer_loop:utterance excluded from allowed_types
    b.add_satellite("S0", upstream=m, allowed_types=["speak"])
    b.start_all()
    try:
        s = b.get_satellite("S0")
        s.send(Message("recognizer_loop:utterance", {"utterances": ["what is the weather"]}))
        time.sleep(0.2)
        assert_policy_denied(m, s, msg_type="recognizer_loop:utterance",
                             deny_code="acl_disallowed_type")
    finally:
        b.stop_all()


@_requires_ovos_policy
def test_acl_skill_blacklisted_satellite_utterance_delivered_with_injection():
    """Path (b): skill-blacklisted satellite's utterance is delivered WITH
    session.blacklisted_skills injected by OVOSAgentPolicy.

    Wire ``OVOSAgentPolicy`` explicitly into the master's policy chain
    (normally it is loaded via the ``hivemind.policy`` entry-point group;
    here we inject it directly so the test is hermetic).  The satellite's
    utterance must reach the agent bus AND the bus-inject record's session
    must contain ``blacklisted_skills=["skill-weather"]``.
    """
    import time
    from hivemind_core.policy import MessageTypeACLPolicy, PolicyChain
    from hivemind_ovos_agent_plugin.policy import OVOSAgentPolicy

    b = TopologyBuilder()
    m = b.add_master("M0")
    b.add_satellite(
        "S0",
        upstream=m,
        allowed_types=["recognizer_loop:utterance"],
        skill_blacklist=["skill-weather"],
    )

    # Inject OVOSAgentPolicy after add_master (policy_chain already built in
    # __post_init__); replace it with a chain that includes both policies.
    m.hm_protocol.policy_chain = PolicyChain(
        policies=[
            MessageTypeACLPolicy(hm_protocol=m.hm_protocol),
            OVOSAgentPolicy(hm_protocol=m.hm_protocol),
        ],
        _optional=[False, False],
    )

    b.start_all()
    try:
        s = b.get_satellite("S0")
        seen = []
        m.agent_protocol.bus.on("recognizer_loop:utterance", seen.append)

        s.send(Message("recognizer_loop:utterance", {"utterances": ["what is the weather"]}))

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not seen:
            time.sleep(0.02)

        assert seen, "utterance did not reach the agent bus at all"

        assert_session_blacklists_injected(
            m, s,
            msg_type="recognizer_loop:utterance",
            expected_skills=["skill-weather"],
        )
    finally:
        b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# BINARY
# ─────────────────────────────────────────────────────────────────────────────

def test_binary_delivered():
    payload = b"\x00\x01\x02binary-test\xff"
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")
        s.send(HiveMessage(HiveMessageType.BINARY, payload=payload))
        assert_binary_delivered(m, expected_payload=payload, count=1)
    finally:
        b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# PENDING — QUERY
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.xfail(
    reason="QUERY routing pending: hivemind-core#74 / hivemind-websocket-client#88",
    strict=False,
)
def test_query_routed():
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")
        s.send(HiveMessage(HiveMessageType.QUERY,
                           payload=Message("question:ask", {"utterance": "weather?"})))
        assert_query_routed(m, count=1)
    finally:
        b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# PENDING — CASCADE
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.xfail(
    reason="CASCADE routing pending: hivemind-core#74 / hivemind-websocket-client#88",
    strict=False,
)
def test_cascade_routed():
    b = three_satellites()
    b.start_all()
    try:
        m = b.get_master("M0")
        s0 = b.get_satellite("S0")
        s1 = b.get_satellite("S1")
        s2 = b.get_satellite("S2")
        s0.send(HiveMessage(HiveMessageType.CASCADE, payload=Message("network:ping", {})))
        assert_cascade_routed(m, s1, s2, count=1)
    finally:
        b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# PING — flood discovery, answered with a responsive PING
# ─────────────────────────────────────────────────────────────────────────────

def test_ping_responded():
    """A PING flood is answered with the node's own PING, same flood_id.

    The PING must travel inside a PROPAGATE: hivemind-core reaches
    handle_ping_message only from handle_propagate_message.
    """
    import uuid

    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")
        inner = HiveMessage(HiveMessageType.PING, {
            "flood_id": uuid.uuid4().hex,
            "peer": s.peer,
            "site_id": s.identity.site_id,
            "timestamp": 0,
        })
        s.send(HiveMessage(HiveMessageType.PROPAGATE, payload=inner))
        assert_ping_responded(m, s)
    finally:
        b.stop_all()


def test_bare_ping_is_not_routed():
    """A PING sent without a PROPAGATE wrapper gets no response."""
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")
        s.send(HiveMessage(HiveMessageType.PING, payload={}))
        with pytest.raises(AssertionError, match="round-trip incomplete"):
            assert_ping_responded(m, s, timeout=0.5)
    finally:
        b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# PENDING — RENDEZVOUS
# ─────────────────────────────────────────────────────────────────────────────

def test_rendezvous_handled():
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")
        s.send(HiveMessage(HiveMessageType.RENDEZVOUS, payload={"peer": "node-xyz"}))
        assert_rendezvous_handled(m, count=1)
    finally:
        b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# THIRDPRTY (verify passthrough)
# ─────────────────────────────────────────────────────────────────────────────

def test_thirdparty_passed():
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")
        s.send(HiveMessage(HiveMessageType.THIRDPRTY, payload={"custom": "payload"}))
        assert_thirdparty_passed(m, count=1, direction="in")
    finally:
        b.stop_all()
