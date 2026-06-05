"""Copy this file into your repo's tests/e2e/ and rename.

PENDING (partial): PING network-map routing is partially implemented in core.
Track: https://github.com/JarbasHiveMind/HiveMind-core/pull/74

PING is used to map the network topology; it cascades like CASCADE but is
reserved for the mesh's own use. Basic ping handling exists; full round-trip
responses are pending. When core#74 lands, remove the xfail marker.
"""

import pytest
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivescope.scenarios import single_satellite
from hivescope.assertions import assert_ping_responded


@pytest.mark.xfail(
    reason="PING full round-trip pending: hivemind-core#74",
    strict=False,
)
def test_ping_round_trip():
    """A PING from satellite should be received by master and a pong returned."""
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        s.send(HiveMessage(HiveMessageType.PING, payload={}))

        assert_ping_responded(m, s)
    finally:
        b.stop_all()
