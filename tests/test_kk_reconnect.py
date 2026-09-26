# Licensed under the Apache License, Version 2.0
"""A satellite that reconnects negotiates KKpsk0 and its traffic still flows.

The second handshake of a satellite's life is not the first. The server's Noise
static key is pinned after the first session, so the client selects ``KKpsk0``,
which has two Noise messages instead of ``XXpsk2``'s three -- and the
RESPONDER's session opens on message 1 rather than message 3. Four things in
the in-process shim assumed the ``XXpsk2`` shape and broke on that
asymmetry. Each cell below fails on one of them:

1. a disconnect left ``shim.noise_transport``, ``shim.handshake_event`` and the
   slave protocol's handshake state behind, so the reconnect decoded a new
   session with the previous session's transport;
2. the server's ``HELLO`` and ``HANDSHAKE`` payloads were kept too, and
   HIVEMIND-CRYPTO-1 §3.4.3 binds both into the Noise prologue, so the second
   handshake built a prologue the master did not;
3. the master's ``send`` was queued by the delivery pump, so Noise message 2 --
   which must go out in cleartext -- was encoded after
   ``_finish_noise_handshake`` had installed the master's transport, and went
   out encrypted;
4. the decode borrowed the satellite's transport only when it had one, leaving
   the master's "already encrypted" view in place while the satellite was still
   mid-handshake, so a cleartext message 2 was refused as a "non-Noise message
   received on a protocol v3 session".

A real hub reconnects with ``KKpsk0`` correctly (T-1177), so none of this was
the client's KK path.
"""
import pytest
from ovos_bus_client.message import Message

from hivescope.topology import TopologyBuilder


@pytest.fixture()
def hub_and_satellite():
    topo = TopologyBuilder()
    master = topo.add_master("hub")
    sat = topo.add_satellite("sat", master)
    topo.start_all()
    try:
        yield master, sat
    finally:
        topo.stop_all()


def _decode_errors(sat):
    return [r for r in sat.recorder.records if r.msg_type == "_decode_error"]


def test_first_session_is_xxpsk2(hub_and_satellite):
    """The control. If the first session is not XXpsk2 the reconnect below is
    not testing a pattern change at all."""
    _, sat = hub_and_satellite
    assert sat.slave_protocol._noise_pattern == "XXpsk2", (
        f"first session negotiated {sat.slave_protocol._noise_pattern!r}")
    assert sat.shim.noise_transport is not None


def test_disconnect_forgets_the_session_but_keeps_the_pin(hub_and_satellite):
    """Everything that belongs to one connection goes; the pinned server key
    stays.

    The pin is what makes the reconnect select KKpsk0, and
    HIVEMIND-CRYPTO-1 §3.5 requires it to hold across handshakes. A harness
    that cleared the pin to make a reconnect work would negotiate XXpsk2 twice
    and never exercise KK at all.
    """
    master, sat = hub_and_satellite
    with master.db:
        user = master.db.get_client_by_api_key(sat.identity.access_key)
        pinned_before = (user.metadata or {}).get("noise_pubkey")
    assert pinned_before, "the master did not pin the client key in session 1"

    sat.disconnect()

    assert sat.shim.noise_transport is None
    assert sat.shim.crypto_key is None
    assert not sat.shim.handshake_event.is_set()
    assert sat.slave_protocol._noise_established is False
    assert sat.slave_protocol._server_hello_payload is None, (
        "the server HELLO survived the disconnect; §3.4.3 binds it into the "
        "prologue, so the next handshake would build one the master did not")
    assert sat.slave_protocol._server_handshake_payload is None

    with master.db:
        user = master.db.get_client_by_api_key(sat.identity.access_key)
        assert (user.metadata or {}).get("noise_pubkey") == pinned_before, (
            "the disconnect dropped the master's pin of the client key")


def test_disconnect_is_idempotent(hub_and_satellite):
    """A second disconnect, and a disconnect after one, must not raise: a
    teardown that raises hides the failure the test was about."""
    _, sat = hub_and_satellite
    sat.disconnect()
    sat.disconnect()


def test_reconnect_negotiates_kkpsk0_and_delivers(hub_and_satellite):
    """The cell this module exists for.

    Reconnect, and assert three things: the pattern really was KKpsk0, no
    decode failed, and a message sent on the second session arrived. The
    pattern assertion matters most -- without it a harness whose reconnect
    quietly fell back to XXpsk2 would look identical.
    """
    master, sat = hub_and_satellite
    sat.disconnect()
    sat.connect(master)

    assert sat.slave_protocol._noise_pattern == "KKpsk0", (
        f"the reconnect negotiated "
        f"{sat.slave_protocol._noise_pattern!r}, not KKpsk0: with the server "
        f"key pinned the client must prefer KK, so this is not the reconnect "
        f"the defect was about")
    assert sat.shim.handshake_event.is_set()
    assert sat.shim.noise_transport is not None

    before = len(_decode_errors(sat))
    sat.send(Message("speak", {"utterance": "after the reconnect"}))
    errors = _decode_errors(sat)[before:]
    assert not errors, (
        f"the first transport message of the KKpsk0 session failed to decode: "
        f"{errors}")


def test_two_reconnects_in_a_row(hub_and_satellite):
    """State that survives one connection tends to survive two. Each session
    must stand on its own."""
    master, sat = hub_and_satellite
    for round_number in (1, 2):
        sat.disconnect()
        sat.connect(master)
        assert sat.slave_protocol._noise_pattern == "KKpsk0", (
            f"reconnect {round_number} negotiated "
            f"{sat.slave_protocol._noise_pattern!r}")
        before = len(_decode_errors(sat))
        sat.send(Message("speak", {"utterance": f"round {round_number}"}))
        assert not _decode_errors(sat)[before:], (
            f"reconnect {round_number} could not carry a message")
