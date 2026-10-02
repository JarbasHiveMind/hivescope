"""Ping-flood mesh end-to-end tests for the in-process shim.

These exercise the delivery path that deadlocked in hivemind-core PR #311 CI:
a message pushed downstream whose handler sends again on the SAME connection,
while ``NoiseTransport._send_lock`` is held across the whole wire-send.

Released ``hivemind-core`` sends a single frame with ``encrypt_frame`` and
releases ``_send_lock`` BEFORE the wire callback runs, so the re-entry never
touches a held lock. The chunking core (PR #311) sends every frame through
``NoiseTransport.send_message(payload, raw_send)`` instead, holding the lock
across ``raw_send`` so a message's frames stay contiguous and its Noise nonces
stay ordered. On that core, a handler that sends back on the connection the
frame arrived on re-enters ``send_message`` on the same transport and the
non-reentrant lock deadlocks — unless the shim defers delivery.

``lock_holding_delivery`` reproduces the chunking core's behavior on top of the
pinned released core by routing ``conn.send`` through ``send_message``. It is a
faithful model of the deadlock, not a workaround: the fix under test is the
shim's non-reentrant delivery pump, which must hold regardless of whether the
core releases the lock before delivery or holds it across.
"""
import time
import uuid

import pytest
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivescope.scenarios import single_satellite, star_topology, with_relay


def _ping(peer, site_id):
    inner = HiveMessage(HiveMessageType.PING, {
        "flood_id": uuid.uuid4().hex, "peer": peer,
        "site_id": site_id, "timestamp": 0})
    return HiveMessage(HiveMessageType.PROPAGATE, payload=inner)


@pytest.fixture
def lock_holding_delivery(monkeypatch):
    """Make ``HiveMindClientConnection.send`` hold ``_send_lock`` across the
    wire callback, as the chunking core (PR #311) does.

    Without this the released core releases the lock in ``encrypt_frame`` before
    delivery, so the re-entrancy the fix targets cannot arise. With it, every
    downstream send goes out through ``NoiseTransport.send_message``, exactly
    the path whose held lock a re-entrant send would deadlock on.
    """
    from hivemind_core.protocol import HiveMindClientConnection

    def send(self, message, plaintext=None):
        transport = self.noise_transport
        if transport is None:
            payload = plaintext if plaintext is not None else message.serialize()
            self.send_msg(payload, False)
            return
        payload = plaintext if plaintext is not None else message.serialize()
        # send_message holds _send_lock across every raw_send chunk.
        transport.send_message(payload, lambda frame: self.send_msg(frame, True))

    monkeypatch.setattr(HiveMindClientConnection, "send", send)


def test_relay_fanback_over_held_send_lock(lock_holding_delivery):
    """A handler that sends downstream on the connection a frame arrived on must
    not deadlock the shim.

    Models a relay's ``propagate_from_master`` -> ``_relay_downstream`` ->
    ``conn.send`` fan-out (or ``handle_ping``'s mesh answer), where the answer
    goes back to the peer the flood came in on. On the unfixed shim this
    re-enters the held ``_send_lock`` and hangs; the delivery pump defers it.
    """
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        hits = {"n": 0}

        def fan_back(_msg):
            # Fire a bounded number of downstream sends from inside delivery,
            # each on the SAME connection the frame arrived on.
            if hits["n"] < 3:
                hits["n"] += 1
                m.send_to_satellite(s.peer, _ping(s.peer, s.identity.site_id))

        s.shim.emitter.on(HiveMessageType.PROPAGATE.value, fan_back)

        # Master-initiated: the receive drain roots inside conn.send's
        # send_message, so on the unfixed shim the fan-back re-enters the lock.
        m.send_to_satellite(s.peer, _ping(s.peer, s.identity.site_id))

        assert hits["n"] == 3, "every downstream fan-back must have been delivered"
    finally:
        b.stop_all()


def test_star_ping_flood_all_satellites(lock_holding_delivery):
    """A mesh-wide flood answered back to every peer completes without hanging."""
    b = star_topology(4)
    b.start_all()
    try:
        m = b.get_master("M0")
        sats = [b.get_satellite(f"S{i}") for i in range(4)]

        # On every inbound PROPAGATE a satellite pushes one flood back through
        # the master to all peers, so the master answers over the same
        # connections the flood arrived on.
        seen = {"n": 0}

        def relay_all(_msg):
            if seen["n"] < 8:
                seen["n"] += 1
                m.send_to_all(_ping(m.hm_protocol.peer, "site"))

        for s in sats:
            s.shim.emitter.on(HiveMessageType.PROPAGATE.value, relay_all)

        m.send_to_all(_ping(m.hm_protocol.peer, "site"))
        assert seen["n"] >= 1
    finally:
        b.stop_all()


def test_real_relay_ping_flood(lock_holding_delivery):
    """A real relay topology floods end to end without a hang.

    Uses the actual hivemind-core relay handlers (no synthetic fan-back), so
    the message counts follow the protocol's own dedup and loop prevention;
    the assertion is only that it terminates.
    """
    b = with_relay()
    b.start_all()
    try:
        m = b.get_master("M0")
        for name in ("S0", "S1"):
            s = b.get_satellite(name)
            s.send(_ping(s.peer, s.identity.site_id))
        # A master-initiated flood down through the relay to both leaves.
        m.send_to_all(_ping(m.hm_protocol.peer, "site"))
    finally:
        b.stop_all()
