"""Scale / multi-frame variants of the ping-flood deadlock guard.

Same premise as ``test_ping_flood_mesh_e2e``: with a core that holds
``NoiseTransport._send_lock`` across the wire-send (the chunking path from
hivemind-core PR #311), a handler that sends back on the connection a frame
arrived on must not re-enter that lock. Here the fan-out is wider and one case
sends a genuinely multi-frame message to prove chunks still arrive in order
after the delivery pump defers them.
"""
import uuid

import pytest
from ovos_bus_client.message import Message
from hivemind_bus_client.message import HiveMessage, HiveMessageType
from hivemind_bus_client.noise import CHUNK_SIZE

from hivescope.scenarios import star_topology, single_satellite


def _ping(peer, site_id="site"):
    inner = HiveMessage(HiveMessageType.PING, {
        "flood_id": uuid.uuid4().hex, "peer": peer,
        "site_id": site_id, "timestamp": 0})
    return HiveMessage(HiveMessageType.PROPAGATE, payload=inner)


@pytest.fixture
def lock_holding_delivery(monkeypatch):
    """Route every downstream ``conn.send`` through ``send_message`` so the
    ``_send_lock`` is held across delivery, matching the chunking core."""
    from hivemind_core.protocol import HiveMindClientConnection

    def send(self, message, plaintext=None):
        transport = self.noise_transport
        if transport is None:
            payload = plaintext if plaintext is not None else message.serialize()
            self.send_msg(payload, False)
            return
        payload = plaintext if plaintext is not None else message.serialize()
        transport.send_message(payload, lambda frame: self.send_msg(frame, True))

    monkeypatch.setattr(HiveMindClientConnection, "send", send)


def test_wide_fanout_flood_no_deadlock(lock_holding_delivery):
    """A large star where every peer re-floods the whole mesh terminates."""
    n = 8
    b = star_topology(n)
    b.start_all()
    try:
        m = b.get_master("M0")
        budget = {"n": 0}

        def re_flood(_msg):
            if budget["n"] < 40:
                budget["n"] += 1
                m.send_to_all(_ping(m.hm_protocol.peer))

        for i in range(n):
            b.get_satellite(f"S{i}").shim.emitter.on(
                HiveMessageType.PROPAGATE.value, re_flood)

        m.send_to_all(_ping(m.hm_protocol.peer))
        assert budget["n"] >= 1
    finally:
        b.stop_all()


def test_multi_frame_chunks_arrive_in_send_order(lock_holding_delivery):
    """The frames of one multi-frame message reach the shim in send order.

    A payload larger than one Noise transport message is split by
    ``send_message`` into FIRST/MORE*/LAST frames under one held ``_send_lock``.
    The delivery pump defers each frame past the send that produced it, so the
    guarantee under test is that it neither reorders nor drops them: the
    sequence of frames arriving at the satellite must equal the sequence
    ``send_message`` put on the wire. (Reassembly back into a message is the
    receiving core's job, not the shim's, and the released core sends single
    frames only.)
    """
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        sent, received = [], []
        conn = m.hm_protocol.clients[s.peer]

        # Frames arrive through the real delivery pump (so ordering is the
        # pump's, not the caller's), recorded in the order the pump runs them.
        # Reassembly is skipped: released core's decode cannot handle partial
        # frames and this test only asserts ordering.
        from hivescope.node import _deliver
        def recording_receive(payload, is_binary):
            frame = bytes(payload)
            _deliver(lambda: received.append(frame))
        s._receive_raw = recording_receive

        # Frames as send_message puts them on the wire, then straight into the
        # (recording) receive path — exactly what conn.send_msg is wired to.
        conn.send_msg = lambda payload, is_bin: (sent.append(bytes(payload)),
                                                 s._receive_raw(payload, is_bin))[0]

        big = "payload-" + ("x" * (CHUNK_SIZE * 2 + 123))
        inner = Message("test.big", {"data": big, "marker": "END"})
        m.send_to_satellite(s.peer, HiveMessage(HiveMessageType.BUS, payload=inner))

        assert len(sent) >= 3, f"payload should span multiple frames, got {len(sent)}"
        assert received == sent, "delivery pump reordered or dropped multi-frame chunks"
    finally:
        b.stop_all()
