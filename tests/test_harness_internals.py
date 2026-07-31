"""Regression tests for harness internals found by the round-1 audit.

Every test here fails against the pre-fix harness: each one pins a defect in
the topology contract, the recorder, the client database, the loopback
lifecycle, or the assertion helpers.
"""
import os
import socket
import threading
import time

import pytest
from ovos_bus_client.message import Message

from hivescope import scenarios
from hivescope.assertions import (
    assert_binary_delivered,
    assert_fifo_order,
    assert_session_blacklists_injected,
)
from hivescope.database import InMemoryClientDatabase
from hivescope.node import MasterNode, SatelliteNode
from hivescope.plugins.agent import TestAgentProtocol as _TestAgentProtocol
from hivescope.recorder import MessageRecorder
from hivescope.topology import RelayNode, TopologyBuilder


# ─────────────────────────────────────────────────────────────────────────────
# 1. Relay contract
# ─────────────────────────────────────────────────────────────────────────────

def test_add_relay_returns_relay_node():
    """add_relay returns the RelayNode, not a (satellite, master) tuple."""
    b = TopologyBuilder()
    m = b.add_master("M0")
    r = b.add_relay("R0", upstream=m)
    assert isinstance(r, RelayNode)
    assert r is b.get_relay("R0")


def test_add_satellite_accepts_relay_upstream():
    """A RelayNode is a valid upstream; the satellite connects to its listener."""
    b = TopologyBuilder()
    m = b.add_master("M0")
    r = b.add_relay("R0", upstream=m)
    s = b.add_satellite("S0", upstream=r)
    b.start_all()
    try:
        assert s.peer in r.listener.connected_peers()
    finally:
        b.stop_all()


def test_add_satellite_rejects_bad_upstream():
    """An upstream that is neither MasterNode nor RelayNode is a TypeError."""
    b = TopologyBuilder()
    with pytest.raises(TypeError):
        b.add_satellite("S0", upstream="M0")


# name → (master count, satellite count, relay count)
_PRESET_SHAPES = {
    "single_satellite":            (1, 1, 0),
    "admin_satellite":             (1, 1, 0),
    "three_satellites":            (1, 3, 0),
    "with_relay":                  (2, 3, 1),   # M0 + R0_master; R0_sat + S0 + S1
    "chain_topology":              (2, 2, 1),
    "star_topology":               (1, 5, 0),
    "with_acl_enforcement":        (1, 3, 0),
    "hierarchical_hubs":           (3, 4, 2),   # M0 + R1 + R2; 2 relay sats + 2 leaves
    "with_multiple_agent_protocols": (1, 1, 0),
}


@pytest.mark.parametrize("name", sorted(_PRESET_SHAPES))
def test_scenario_presets_construct(name):
    """Every preset builds the topology its docstring describes.

    `isinstance(b, TopologyBuilder)` alone passed for an empty builder, so it
    could not catch a preset that silently stopped wiring its nodes.
    """
    b = getattr(scenarios, name)()
    assert isinstance(b, TopologyBuilder)

    n_masters, n_sats, n_relays = _PRESET_SHAPES[name]
    assert len(b.masters) == n_masters, [m.name for m in b.masters]
    assert len(b.satellites) == n_sats, [s.name for s in b.satellites]
    assert len(b.relays) == n_relays, [r.name for r in b.relays]

    # Every satellite is wired to a master that exists in this builder.
    master_names = {m.name for m in b.masters}
    for sat_name, master_name, _ in b._connections:
        assert master_name in master_names
    assert {c[0] for c in b._connections} == {s.name for s in b.satellites}

    # Each relay owns one satellite half and one master half, sharing a bus.
    for relay in b.relays:
        assert relay.upstream.name == f"{relay.name}_sat"
        assert relay.listener.name == f"{relay.name}_master"
        assert relay.listener.agent_protocol.bus is relay.bus


def test_acl_preset_registers_the_documented_permissions():
    """with_acl_enforcement() promises three specific ACL profiles."""
    b = scenarios.with_acl_enforcement()
    b.start_all()
    try:
        m = b.get_master("M0")
        by_name = {}
        for sat_name, _, kwargs in b._connections:
            by_name[sat_name] = kwargs

        assert by_name["S_ADMIN"]["is_admin"] is True
        assert by_name["S_ADMIN"]["allowed_types"] == [
            "recognizer_loop:utterance", "speak"]
        assert by_name["S_RESTRICTED_TYPE"]["allowed_types"] == ["speak"]
        assert by_name["S_RESTRICTED_SKILL"]["skill_blacklist"] == ["skill-weather"]

        # And the profiles really landed in the master DB.
        for name in ("S_ADMIN", "S_RESTRICTED_TYPE", "S_RESTRICTED_SKILL"):
            sat = b.get_satellite(name)
            row = m.db.get_client_by_api_key(sat.identity.access_key)
            assert row is not None, f"{name} was never registered"
            assert row.allowed_types == by_name[name]["allowed_types"]
        skill_row = m.db.get_client_by_api_key(
            b.get_satellite("S_RESTRICTED_SKILL").identity.access_key)
        assert skill_row.metadata["skill_blacklist"] == ["skill-weather"]
    finally:
        b.stop_all()


def test_with_multiple_agent_protocols_accepts_override():
    """with_multiple_agent_protocols() lets the caller supply the agent
    protocol, matching what the docstring promises ("can be overridden by
    caller"). Default behavior (no arg) is unchanged."""
    custom_agent = _TestAgentProtocol()
    b = scenarios.with_multiple_agent_protocols(agent_protocol=custom_agent)
    m = b.get_master("M0")
    assert m.agent_protocol is custom_agent

    # Default (no override) still builds a topology with its own agent protocol.
    b_default = scenarios.with_multiple_agent_protocols()
    m_default = b_default.get_master("M0")
    assert isinstance(m_default.agent_protocol, _TestAgentProtocol)
    assert m_default.agent_protocol is not custom_agent


def test_with_relay_preset_starts():
    """The relay preset wires both satellites under the relay listener."""
    b = scenarios.with_relay()
    b.start_all()
    try:
        r = b.get_relay("R0")
        peers = r.listener.connected_peers()
        assert b.get_satellite("S0").peer in peers
        assert b.get_satellite("S1").peer in peers
    finally:
        b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Fixtures — real handshake API and applied credentials
# ─────────────────────────────────────────────────────────────────────────────

def test_wait_for_handshake_returns_true_after_connect():
    b = scenarios.single_satellite()
    b.start_all()
    try:
        assert b.get_satellite("S0").wait_for_handshake(timeout=5) is True
    finally:
        b.stop_all()


def test_restricted_satellite_fixture_applies_acl(restricted_satellite, master_node):
    """The fixture's allowed_types reach the DB entry of the live connection."""
    entry = master_node.db.get_client_by_api_key(
        restricted_satellite.identity.access_key)
    assert entry is not None
    assert entry.allowed_types == ["recognizer_loop:utterance"]
    assert entry.is_admin is False
    assert entry.can_propagate is False
    assert restricted_satellite._connection.allowed_types == [
        "recognizer_loop:utterance"]


def test_admin_satellite_fixture_is_admin(admin_satellite, master_node):
    entry = master_node.db.get_client_by_api_key(
        admin_satellite.identity.access_key)
    assert entry.is_admin is True


# ─────────────────────────────────────────────────────────────────────────────
# 3. Recorder
# ─────────────────────────────────────────────────────────────────────────────

def test_wait_for_survives_message_recorded_during_initial_lookup():
    """A message recorded between the first lookup and waiter registration
    must still wake the waiter instead of burning the whole timeout."""
    rec = MessageRecorder("race")
    orig_find = rec._find
    fired = []

    def _find_then_record(msg_type, direction):
        result = orig_find(msg_type, direction)
        if not fired:
            fired.append(True)
            # Simulate the racing producer thread landing right here.
            rec.record("in", "bus", {"n": 1}, "peer")
            return None
        return result

    rec._find = _find_then_record
    start = time.monotonic()
    got = rec.wait_for("bus", direction="in", timeout=5.0)
    elapsed = time.monotonic() - start
    assert got is not None
    assert elapsed < 2.0, f"wait_for burned {elapsed:.2f}s — missed wakeup"


def test_wait_for_deregisters_waiter():
    rec = MessageRecorder("dereg")
    assert rec.wait_for("nothing", timeout=0.05) is None
    assert not rec._waiters.get("nothing")


def test_snapshot_is_stable_while_recording():
    """snapshot() copies under the lock, so iteration cannot race an append."""
    rec = MessageRecorder("snap")
    stop = threading.Event()

    def producer():
        while not stop.is_set():
            rec.record("in", "bus", {}, "peer")

    t = threading.Thread(target=producer, daemon=True)
    t.start()
    try:
        for _ in range(200):
            # Iterating the live list here can raise RuntimeError; the
            # snapshot must never do so.
            assert all(r.msg_type == "bus" for r in rec.snapshot())
    finally:
        stop.set()
        t.join(timeout=5)


# ─────────────────────────────────────────────────────────────────────────────
# 4. InMemoryClientDatabase
# ─────────────────────────────────────────────────────────────────────────────

def test_delete_client_removes_the_entry():
    db = InMemoryClientDatabase()
    db.add_client(name="sat", key="k1", password="pw")
    assert db.get_client_by_api_key("k1") is not None
    assert db.delete_client("k1") is True
    assert db.get_client_by_api_key("k1") is None
    assert db.delete_client("k1") is False


def test_deleted_key_cannot_reconnect():
    """After revocation the network protocol refuses the connection."""
    m = MasterNode.create("M0")
    s = SatelliteNode.create("S0")
    m.register_satellite(key=s.identity.access_key, password=s.identity.password)
    m.db.delete_client(s.identity.access_key)
    with pytest.raises(ValueError):
        m.network_protocol.connect_satellite(satellite=s)
    m.cleanup()
    s.cleanup()


def test_database_concurrent_access():
    """Writes from one thread while another iterates must not raise."""
    db = InMemoryClientDatabase()
    stop = threading.Event()
    errors = []

    def writer():
        i = 0
        while not stop.is_set():
            db.add_client(name=f"c{i}", key=f"k{i}")
            i += 1

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    try:
        for _ in range(500):
            try:
                db.get_client_by_id(3)
                len(db)
                list(db)
            except RuntimeError as exc:  # dict changed size during iteration
                errors.append(exc)
    finally:
        stop.set()
        t.join(timeout=5)
    assert not errors, f"concurrent access raised: {errors[:3]}"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Loopback lifecycle
# ─────────────────────────────────────────────────────────────────────────────

def _port_is_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def test_loopback_stop_closes_the_listening_socket():
    b = TopologyBuilder()
    m = b.add_master("M0", use_loopback=True)
    b.start_all()
    port = int(m.network_protocol.url.rsplit(":", 1)[1].rstrip("/"))
    assert _port_is_open(port)
    b.stop_all()
    deadline = time.monotonic() + 5
    while _port_is_open(port) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _port_is_open(port), "listening socket still open after stop()"


def test_loopback_startup_failure_reports_the_real_cause():
    from hivescope.plugins.loopback import LoopbackNetworkProtocol

    proto = LoopbackNetworkProtocol(hm_protocol=None)

    async def _boom():
        raise OSError("address in use")

    proto._start_server = _boom
    start = time.monotonic()
    with pytest.raises(RuntimeError) as exc:
        proto.run()
    elapsed = time.monotonic() - start
    assert elapsed < 5, f"startup failure took {elapsed:.1f}s — polled the full wait"
    assert isinstance(exc.value.__cause__, OSError)
    proto.stop()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Temp resource cleanup
# ─────────────────────────────────────────────────────────────────────────────

def test_stop_all_removes_identity_tmpdirs():
    b = TopologyBuilder()
    m = b.add_master("M0")
    s = b.add_satellite("S0", upstream=m)
    b.start_all()
    dirs = [m.identity._hivescope_tmpdir, s.identity._hivescope_tmpdir]
    assert all(d and os.path.isdir(d) for d in dirs)
    b.stop_all()
    assert not any(os.path.exists(d) for d in dirs)


# ─────────────────────────────────────────────────────────────────────────────
# 7. stop_all shuts the agent protocol down
# ─────────────────────────────────────────────────────────────────────────────

def test_stop_all_shuts_down_agent_protocol():
    class _ShutdownAgent(_TestAgentProtocol):
        def shutdown(self):
            self.was_shut_down = True

    agent = _ShutdownAgent()
    agent.was_shut_down = False
    b = TopologyBuilder()
    b.add_master("M0", agent_protocol=agent)
    b.start_all()
    b.stop_all()
    assert agent.was_shut_down is True


# ─────────────────────────────────────────────────────────────────────────────
# 8. Assertions that used to be unable to fail
# ─────────────────────────────────────────────────────────────────────────────

def test_assert_binary_delivered_checks_the_payload():
    m = MasterNode.create("M0")
    try:
        m.recorder.record("in", "bin", b"actual-bytes", "peer")
        assert_binary_delivered(m, expected_payload=b"actual-bytes")
        with pytest.raises(AssertionError, match="payload mismatch"):
            assert_binary_delivered(m, expected_payload=b"other-bytes")
    finally:
        m.cleanup()


def test_assert_fifo_order_without_seq_marker_is_an_error():
    b = TopologyBuilder()
    m = b.add_master("M0")
    s = b.add_satellite("S0", upstream=m, allowed_types=["speak"])
    b.start_all()
    try:
        for _ in range(2):
            s.send(Message("speak", {"utterance": "hi"}))
            time.sleep(0.02)
        with pytest.raises(AssertionError, match="_fifo_seq"):
            assert_fifo_order(m, s, "speak", count=2, timeout=2.0)
    finally:
        b.stop_all()


def test_assert_session_blacklists_injected_fails_on_disconnected_satellite():
    b = TopologyBuilder()
    m = b.add_master("M0")
    s = b.add_satellite("S0", upstream=m, allowed_types=["speak"])
    b.start_all()
    s.send(Message("speak", {"utterance": "hi"}))
    time.sleep(0.1)
    s.disconnect()
    try:
        with pytest.raises(AssertionError, match="disconnected"):
            assert_session_blacklists_injected(m, s, "speak",
                                               expected_skills=["skill-x"])
    finally:
        b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# 9. Node behaviour
# ─────────────────────────────────────────────────────────────────────────────

def test_send_while_disconnected_is_not_recorded():
    b = TopologyBuilder()
    m = b.add_master("M0")
    s = b.add_satellite("S0", upstream=m, allowed_types=["speak"])
    b.start_all()
    s.disconnect()
    s._connection = None
    s._master = None
    before = len(s.recorder.received("bus", direction="out"))
    with pytest.raises(RuntimeError, match="not connected"):
        s.send(Message("speak", {"utterance": "lost"}))
    assert len(s.recorder.received("bus", direction="out")) == before
    b.stop_all()


def test_start_all_is_idempotent():
    b = TopologyBuilder()
    m = b.add_master("M0")
    s = b.add_satellite("S0", upstream=m)
    b.start_all()
    peer = s.peer
    b.start_all()
    try:
        assert s.peer == peer
        assert m.connected_peers().count(peer) == 1
    finally:
        b.stop_all()


def test_natural_language_query_raises_on_timeout():
    """Opt-in strict mode. The default now mirrors production and yields the
    None escalation sentinel — see test_audit_round2."""
    agent = _TestAgentProtocol()
    gen = agent.natural_language_query("hello", "en-US", timeout=0.2,
                                       raise_on_timeout=True)
    with pytest.raises(TimeoutError):
        next(gen)


def test_natural_language_query_ends_cleanly():
    agent = _TestAgentProtocol()

    def _reply(msg):
        if isinstance(msg, str):
            msg = Message.deserialize(msg)
        if msg.msg_type != "recognizer_loop:utterance":
            return
        qid = msg.context.get("query_id")
        agent.bus.emit(Message("speak", {"utterance": "hi"}, {"query_id": qid}))
        agent.bus.emit(Message("ovos.utterance.handled", {}, {"query_id": qid}))

    agent.bus.on("recognizer_loop:utterance", _reply)
    chunks = list(agent.natural_language_query("hello", "en-US", timeout=2.0))
    assert chunks == ["hi", None]
