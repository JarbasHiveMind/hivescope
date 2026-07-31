"""Regression tests for the round-3 audit findings.

Every test here fails against the pre-fix harness: the loopback protocol
floor race and its warn-and-continue config write, PING correlation by
flood_id, and an ACL helper that silently accepted the wrong kind of
msg_type.
"""
import time

import pytest

from hivemind_bus_client.message import HiveMessageType

from hivescope.assertions import _denied_records, assert_ping_responded
from hivescope.node import MasterNode, SatelliteNode
from hivescope.plugins.loopback import LoopbackNetworkProtocol
from hivescope.recorder import MessageRecorder


# ─────────────────────────────────────────────────────────────────────────────
# A. loopback.py — min_protocol_version isolation
# ─────────────────────────────────────────────────────────────────────────────

def test_loopback_run_persists_the_requested_floor():
    import hivemind_core.config as hm_config

    proto = LoopbackNetworkProtocol(hm_protocol=None, min_protocol_version=3)
    proto.run()
    try:
        assert hm_config.get_server_config()["min_protocol_version"] == 3
    finally:
        proto.stop()


def test_loopback_run_rejects_a_conflicting_concurrent_floor():
    p1 = LoopbackNetworkProtocol(hm_protocol=None, min_protocol_version=1)
    p1.run()
    try:
        p2 = LoopbackNetworkProtocol(hm_protocol=None, min_protocol_version=2)
        with pytest.raises(RuntimeError, match="min_protocol_version"):
            p2.run()
    finally:
        p1.stop()


def test_loopback_run_allows_a_second_instance_with_the_same_floor():
    p1 = LoopbackNetworkProtocol(hm_protocol=None, min_protocol_version=1)
    p1.run()
    try:
        p2 = LoopbackNetworkProtocol(hm_protocol=None, min_protocol_version=1)
        p2.run()
        p2.stop()
    finally:
        p1.stop()


def test_loopback_run_raises_when_config_write_fails(monkeypatch):
    import hivemind_core.config as hm_config

    def _boom():
        raise OSError("config store failed")

    monkeypatch.setattr(hm_config, "get_server_config", _boom)
    proto = LoopbackNetworkProtocol(hm_protocol=None)
    with pytest.raises(RuntimeError, match="min_protocol_version"):
        proto.run()


# ─────────────────────────────────────────────────────────────────────────────
# B. assertions.py — assert_ping_responded flood_id correlation
# ─────────────────────────────────────────────────────────────────────────────

def test_assert_ping_responded_does_not_pass_on_a_leftover_record():
    """A second probe must not be satisfied by the first probe's response."""
    m = MasterNode.create("M0")
    s = SatelliteNode.create("S0")
    try:
        # First probe: sent, received at master, and answered — flood_id "a".
        s.recorder.record("out", HiveMessageType.PING.value,
                           {"flood_id": "a"}, m.recorder.name)
        m.recorder.record("in", HiveMessageType.PING.value,
                           {"flood_id": "a"}, s.recorder.name)
        s.recorder.record("in", HiveMessageType.PING.value,
                           {"flood_id": "a"}, m.recorder.name)

        # First probe passes on its own leftover records.
        assert_ping_responded(m, s, timeout=0.5)

        # Second probe: sent and received at master, but never answered.
        since = time.monotonic()
        s.recorder.record("out", HiveMessageType.PING.value,
                           {"flood_id": "b"}, m.recorder.name)
        m.recorder.record("in", HiveMessageType.PING.value,
                           {"flood_id": "b"}, s.recorder.name)

        with pytest.raises(AssertionError, match="PING round-trip incomplete"):
            assert_ping_responded(m, s, timeout=0.2, since=since)
    finally:
        m.cleanup()
        s.cleanup()


def test_assert_ping_responded_accepts_when_a_flood_id_actually_correlates():
    m = MasterNode.create("M0")
    s = SatelliteNode.create("S0")
    try:
        since = time.monotonic()
        s.recorder.record("out", HiveMessageType.PING.value,
                           {"flood_id": "x"}, m.recorder.name)
        m.recorder.record("in", HiveMessageType.PING.value,
                           {"flood_id": "x"}, s.recorder.name)
        s.recorder.record("in", HiveMessageType.PING.value,
                           {"flood_id": "x"}, m.recorder.name)

        assert_ping_responded(m, s, timeout=0.5, since=since)
    finally:
        m.cleanup()
        s.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# C. assertions.py — _denied_records rejects HiveMessageType values
# ─────────────────────────────────────────────────────────────────────────────

class _FakeSatellite:
    def __init__(self, recorder):
        self.recorder = recorder


def test_denied_records_rejects_a_hivemessagetype_value():
    fake = _FakeSatellite(MessageRecorder(name="S0"))

    for bad in (HiveMessageType.BUS.value, HiveMessageType.ESCALATE.value):
        with pytest.raises(ValueError, match="OVOS message type"):
            _denied_records(fake, bad)


def test_denied_records_accepts_a_real_ovos_msg_type():
    fake = _FakeSatellite(MessageRecorder(name="S0"))

    # No matching records; the point is that a real OVOS type does not raise.
    assert _denied_records(fake, "speak") == []
