"""Copy this file into your repo's tests/e2e/ and rename.

Verifies that a binary payload sent from a satellite is delivered to
the master's binary protocol handler intact.
"""

from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivescope.scenarios import single_satellite


def test_binary_round_trip():
    payload = b"\x00\x01\x02hello-binary\xff\xfe"
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        s.send(HiveMessage(HiveMessageType.BINARY, payload=payload))

        # The master's binary protocol records every received payload.
        received = [c for c in m.binary_protocol.calls if c[1] == payload]
        assert received, (
            f"Binary payload not delivered. Got: {[c[1] for c in m.binary_protocol.calls]}"
        )
    finally:
        b.stop_all()
