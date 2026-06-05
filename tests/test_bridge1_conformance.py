"""
OVOS-BRIDGE-1 conformance suite for hivescope.

Tests every normative clause of OVOS-BRIDGE-1 + SESSION-1/2 using the
hivescope harness.  Each test group is labelled with the spec clause it
covers.

Skipif gates
------------
- Tests that require the policy admission chain
  (``hivemind_core.policy`` / BRIDGE-1 §4.2) are decorated with
  ``@_requires_policy_chain``.  They are skipped against released core
  and run automatically once the policy packages are installed.
- All other tests (source stamping, destination routing, session fidelity,
  FIFO ordering) exercise the bridge with the whitelist open (no policy
  chain needed) and run on released core without any skipif.

Topology coverage
-----------------
- §3.1 source uniqueness    → three_satellites() multi-sat topology
- §3.2 destination routing  → three_satellites()
- §4.1 session fidelity     → single_satellite()
- §5   FIFO ordering        → chain_topology() relay chain
- §6   topology hiding      → xfail (optional bridge feature; not yet wired)
"""

import importlib.util
import time

import pytest
from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from hivescope import TopologyBuilder
from hivescope.assertions import (
    assert_msg1_envelope,
    assert_source_stamped,
    assert_destination_routed,
    assert_session_inbound_preserved,
    assert_session_outbound_preserved,
    assert_fifo_order,
    assert_session_propagated_unchanged,
    assert_source_hidden,
)
from hivescope.scenarios import (
    single_satellite,
    three_satellites,
    chain_topology,
)

# ---------------------------------------------------------------------------
# Skipif markers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utterance_msg(seq: int = 0, session_id: str = None, lang: str = "en-US") -> Message:
    """Build a recognizer_loop:utterance message with an optional FIFO sequence tag."""
    ctx: dict = {}
    if session_id:
        sess = Session(session_id=session_id)
        ctx["session"] = sess.serialize()
    msg = Message(
        "recognizer_loop:utterance",
        data={"utterances": [f"utterance {seq}"], "_fifo_seq": seq},
        context=ctx,
    )
    return msg


def _single_sat_with_utterance_allowed() -> TopologyBuilder:
    """Single-satellite topology with recognizer_loop:utterance whitelisted."""
    b = TopologyBuilder()
    m = b.add_master("M0")
    b.add_satellite("S0", upstream=m,
                    allowed_types=["recognizer_loop:utterance", "speak"])
    return b


# ─────────────────────────────────────────────────────────────────────────────
# §2 — OVOS-MSG-1 envelope conformance
# ─────────────────────────────────────────────────────────────────────────────

class TestMsg1Envelope:
    """BRIDGE-1 §2: bus emissions conform to OVOS-MSG-1 envelope."""

    def test_bus_injection_has_msg_type_and_context(self):
        """Every bus-injected message carries msg_type and a context dict."""
        b = _single_sat_with_utterance_allowed()
        b.start_all()
        try:
            m = b.get_master("M0")
            s = b.get_satellite("S0")
            s.send(_utterance_msg(seq=0))
            time.sleep(0.2)
            assert_msg1_envelope(m, "recognizer_loop:utterance", count=1)
        finally:
            b.stop_all()

    def test_speak_injection_has_envelope(self):
        """A 'speak' message injected from a satellite also conforms to MSG-1."""
        b = _single_sat_with_utterance_allowed()
        b.start_all()
        try:
            m = b.get_master("M0")
            s = b.get_satellite("S0")
            s.send(Message("speak", {"utterance": "hello from satellite"}))
            time.sleep(0.2)
            assert_msg1_envelope(m, "speak", count=1)
        finally:
            b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# §3.1 — Source stamping: unique, stable source per satellite
# ─────────────────────────────────────────────────────────────────────────────

class TestSourceStamping:
    """BRIDGE-1 §3.1: unique, stable context.source per inbound participant."""

    def test_source_present_and_stable(self):
        """A satellite's injections carry a consistent non-empty context.source."""
        b = _single_sat_with_utterance_allowed()
        b.start_all()
        try:
            m = b.get_master("M0")
            s = b.get_satellite("S0")
            for i in range(3):
                s.send(_utterance_msg(seq=i))
                time.sleep(0.05)
            assert_source_stamped(m, s)
        finally:
            b.stop_all()

    def test_source_unique_across_three_satellites(self):
        """Three simultaneous satellites each get a distinct context.source."""
        b = TopologyBuilder()
        m = b.add_master("M0")
        for i in range(3):
            b.add_satellite(f"S{i}", upstream=m,
                            allowed_types=["recognizer_loop:utterance"])
        b.start_all()
        try:
            sats = [b.get_satellite(f"S{i}") for i in range(3)]
            for s in sats:
                s.send(_utterance_msg(seq=0))
                time.sleep(0.1)

            # Each satellite's source must differ from every other's
            for idx, sat in enumerate(sats):
                others = [s for s in sats if s is not sat]
                assert_source_stamped(m, sat, other_satellites=others)
        finally:
            b.stop_all()

    @pytest.mark.xfail(
        strict=False,
        reason="relay bind_upstream not in released hivemind-core; "
               "passes once core relay wiring lands",
    )
    def test_source_stamped_through_relay(self):
        """Source stamping survives a relay hop (chain_topology: M0→R0→S0)."""
        b = TopologyBuilder()
        m = b.add_master("M0")
        m.register_satellite("relay-key", password="relay-password")
        r = b.add_relay("R0", upstream=m)
        r.register_satellite("sat-key", password="sat-password",
                              allowed_types=["recognizer_loop:utterance"])
        b.add_satellite("S0", upstream=r,
                        allowed_types=["recognizer_loop:utterance"])
        b.start_all()
        try:
            s = b.get_satellite("S0")
            s.send(_utterance_msg(seq=0))
            time.sleep(0.3)
            # Check at the relay's listener side (the intermediate master)
            assert_source_stamped(r.listener, s)
        finally:
            b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# §3.2 — Destination routing: outbound reaches only the target satellite
# ─────────────────────────────────────────────────────────────────────────────

class TestDestinationRouting:
    """BRIDGE-1 §3.2: outbound message with context.destination reaches only
    the addressed satellite."""

    def test_targeted_bus_message_reaches_only_target(self):
        """A BUS message emitted with context.destination set to S0's peer
        must reach S0 and not S1 or S2."""
        b = TopologyBuilder()
        m_node = b.add_master("M0")
        for i in range(3):
            b.add_satellite(f"S{i}", upstream=m_node,
                            allowed_types=["recognizer_loop:utterance", "speak"])
        b.start_all()
        try:
            m = b.get_master("M0")
            s0 = b.get_satellite("S0")
            s1 = b.get_satellite("S1")
            s2 = b.get_satellite("S2")

            # Emit a targeted BUS message directly on the master's agent bus
            target_peer = s0.peer
            response = Message(
                "speak",
                data={"utterance": "only for S0"},
                context={"destination": target_peer},
            )
            m.emit_on_bus(response)

            assert_destination_routed(
                m, s0,
                other_satellites=[s1, s2],
                msg_type=HiveMessageType.BUS.value,
                timeout=2.0,
            )
        finally:
            b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# §4.1 — Session fidelity: inbound and outbound
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionFidelity:
    """BRIDGE-1 §4.1: the bridge preserves context.session in both directions."""

    def test_session_inbound_preserved(self):
        """Satellite's session_id and lang reach the bus context unchanged."""
        b = _single_sat_with_utterance_allowed()
        b.start_all()
        try:
            m = b.get_master("M0")
            s = b.get_satellite("S0")

            custom_session_id = s.shim.session_id  # the satellite's own session
            sess = Session(session_id=custom_session_id, lang="pt-PT")
            msg = Message(
                "recognizer_loop:utterance",
                data={"utterances": ["olá"]},
                context={"session": sess.serialize()},
            )
            s.send(msg)
            time.sleep(0.2)

            assert_session_inbound_preserved(
                m, s,
                expected_session={"session_id": custom_session_id, "lang": sess.serialize().get("lang")},
            )
        finally:
            b.stop_all()

    def test_session_outbound_preserved(self):
        """A bus-originated message's session is forwarded to the satellite."""
        b = _single_sat_with_utterance_allowed()
        b.start_all()
        try:
            m = b.get_master("M0")
            s = b.get_satellite("S0")

            target_peer = s.peer
            session_id = s.shim.session_id
            sess = Session(session_id=session_id, lang="de-DE")
            response = Message(
                "speak",
                data={"utterance": "Hallo"},
                context={
                    "destination": target_peer,
                    "session": sess.serialize(),
                },
            )
            m.emit_on_bus(response)

            assert_session_outbound_preserved(
                s,
                expected_session={"session_id": session_id},
                timeout=2.0,
            )
        finally:
            b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# §4.2 — Policy injection (Layer-2 blacklists) — requires policy chain
# ─────────────────────────────────────────────────────────────────────────────

class TestPolicyInjection:
    """BRIDGE-1 §4.2: Layer-2 policy injects blacklisted_skills at boundary.

    These tests are skipped when the policy admission chain is not installed.
    Covered by the existing assert_session_blacklists_injected helper; the
    tests here exercise it in the conformance framing.
    """

    @_requires_ovos_policy
    def test_blacklisted_skills_injected_in_session(self):
        """OVOSAgentPolicy injects session.blacklisted_skills before bus injection."""
        from hivemind_core.policy import MessageTypeACLPolicy, PolicyChain
        from hivemind_ovos_agent_plugin.policy import OVOSAgentPolicy
        from hivescope.assertions import assert_session_blacklists_injected

        b = TopologyBuilder()
        m_node = b.add_master("M0")
        b.add_satellite(
            "S0",
            upstream=m_node,
            allowed_types=["recognizer_loop:utterance"],
            skill_blacklist=["skill-weather"],
        )
        # Wire the policy chain before start_all — same pattern as
        # test_acl_skill_blacklisted_satellite_utterance_delivered_with_injection
        m_node.hm_protocol.policy_chain = PolicyChain(
            policies=[
                MessageTypeACLPolicy(hm_protocol=m_node.hm_protocol),
                OVOSAgentPolicy(hm_protocol=m_node.hm_protocol),
            ],
            _optional=[False, False],
        )
        b.start_all()
        try:
            m = b.get_master("M0")
            s = b.get_satellite("S0")

            s.send(Message("recognizer_loop:utterance", {"utterances": ["weather"]}))
            time.sleep(0.3)

            assert_session_blacklists_injected(
                m, s,
                msg_type="recognizer_loop:utterance",
                expected_skills=["skill-weather"],
            )
        finally:
            b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# §5 — FIFO ordering
# ─────────────────────────────────────────────────────────────────────────────

class TestFifoOrdering:
    """BRIDGE-1 §5: sequential utterances from one participant arrive in order."""

    def test_fifo_direct_connection(self):
        """5 sequential utterances from a direct satellite arrive in send order."""
        b = _single_sat_with_utterance_allowed()
        b.start_all()
        try:
            m = b.get_master("M0")
            s = b.get_satellite("S0")

            n = 5
            for i in range(n):
                s.send(_utterance_msg(seq=i))
                time.sleep(0.02)

            assert_fifo_order(m, s, "recognizer_loop:utterance", count=n, timeout=3.0)
        finally:
            b.stop_all()

    @pytest.mark.xfail(
        strict=False,
        reason="relay bind_upstream not in released hivemind-core; "
               "passes once core relay wiring lands",
    )
    def test_fifo_through_relay(self):
        """Sequential utterances through a relay chain arrive in order at the root."""
        b = TopologyBuilder()
        m = b.add_master("M0")
        m.register_satellite("relay-key", password="relay-password")
        r = b.add_relay("R0", upstream=m)
        r.register_satellite("sat-key", password="sat-password",
                              allowed_types=["recognizer_loop:utterance"])
        b.add_satellite("S0", upstream=r,
                        allowed_types=["recognizer_loop:utterance"])
        b.start_all()
        try:
            s = b.get_satellite("S0")
            n = 4
            for i in range(n):
                s.send(_utterance_msg(seq=i))
                time.sleep(0.02)
            # Check ordering at the relay's listener (intermediate bridge)
            assert_fifo_order(r.listener, s, "recognizer_loop:utterance",
                              count=n, timeout=3.0)
        finally:
            b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# SESSION-1 §4 — Session field propagation unchanged
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionPropagation:
    """SESSION-1 §4: session fields propagate unchanged across derivations."""

    def test_lang_propagated_unchanged(self):
        """A session lang field set by the satellite is unchanged at bus injection."""
        b = _single_sat_with_utterance_allowed()
        b.start_all()
        try:
            m = b.get_master("M0")
            s = b.get_satellite("S0")

            sess = Session(session_id=s.shim.session_id, lang="fr-FR")
            msg = Message(
                "recognizer_loop:utterance",
                data={"utterances": ["bonjour"]},
                context={"session": sess.serialize()},
            )
            s.send(msg)
            time.sleep(0.2)

            assert_session_propagated_unchanged(
                m,
                field="lang",
                value=sess.serialize().get("lang"),
                msg_type="recognizer_loop:utterance",
            )
        finally:
            b.stop_all()

    def test_session_id_propagated_unchanged(self):
        """session_id set by the satellite is unchanged at bus injection."""
        b = _single_sat_with_utterance_allowed()
        b.start_all()
        try:
            m = b.get_master("M0")
            s = b.get_satellite("S0")

            sid = s.shim.session_id
            sess = Session(session_id=sid)
            msg = Message(
                "recognizer_loop:utterance",
                data={"utterances": ["hello"]},
                context={"session": sess.serialize()},
            )
            s.send(msg)
            time.sleep(0.2)

            assert_session_propagated_unchanged(
                m,
                field="session_id",
                value=sid,
                msg_type="recognizer_loop:utterance",
            )
        finally:
            b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# §6 MAY — Topology hiding (optional; xfail until bridge wires the feature)
# ─────────────────────────────────────────────────────────────────────────────

class TestTopologyHiding:
    """BRIDGE-1 §6 (MAY): topology hiding overwrites outbound source."""

    @pytest.mark.skip(
        reason="BRIDGE-1 §6 topology-hiding is an optional MAY the bridge does not implement",
    )
    def test_source_hidden_on_outbound(self):
        """Outbound messages from master carry a generic 'hive' source id."""
        b = _single_sat_with_utterance_allowed()
        b.start_all()
        try:
            m = b.get_master("M0")
            s = b.get_satellite("S0")

            target_peer = s.peer
            response = Message(
                "speak",
                data={"utterance": "hi"},
                context={"destination": target_peer},
            )
            m.emit_on_bus(response)

            assert_source_hidden(s, generic_id="hive", timeout=2.0)
        finally:
            b.stop_all()


# ─────────────────────────────────────────────────────────────────────────────
# Public API smoke — all new helpers importable from top-level package
# ─────────────────────────────────────────────────────────────────────────────

def test_bridge1_assertions_importable():
    """All BRIDGE-1 conformance helpers are exported from hivescope.__all__."""
    import hivescope
    for name in [
        "assert_msg1_envelope",
        "assert_source_stamped",
        "assert_destination_routed",
        "assert_session_inbound_preserved",
        "assert_session_outbound_preserved",
        "assert_fifo_order",
        "assert_session_propagated_unchanged",
        "assert_source_hidden",
    ]:
        assert hasattr(hivescope, name), f"hivescope.{name} missing from __all__"
