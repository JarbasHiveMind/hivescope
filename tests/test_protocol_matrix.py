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
    """MessageRecorder.messages is an alias for .records."""
    from hivescope.recorder import MessageRecorder
    r = MessageRecorder("test")
    r.record("in", "bus", {}, "peer1")
    assert r.messages is r.records
    assert len(r.messages) == 1


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
# PENDING — PING
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.xfail(
    reason="PING full round-trip pending: hivemind-core#74",
    strict=False,
)
def test_ping_responded():
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")
        s.send(HiveMessage(HiveMessageType.PING, payload={}))
        assert_ping_responded(m, s)
    finally:
        b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# PENDING — RENDEZVOUS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.xfail(
    reason="RENDEZVOUS routing pending: hivemind-websocket-client#103",
    strict=False,
)
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

@pytest.mark.xfail(
    reason="THIRDPRTY passthrough not yet verified in core routing",
    strict=False,
)
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
