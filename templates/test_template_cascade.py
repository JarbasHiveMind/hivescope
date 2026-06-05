"""Copy this file into your repo's tests/e2e/ and rename.

PENDING: CASCADE routing is not yet implemented in hivemind-core.
Track: https://github.com/JarbasHiveMind/HiveMind-core/pull/74
       https://github.com/JarbasHiveMind/hivemind-websocket-client/pull/88

CASCADE is like PROPAGATE but expects responses from all nodes (optional).
When core#74 lands, remove the xfail markers and implement the response check.
"""

import pytest
from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message

from hivescope.scenarios import three_satellites
from hivescope.assertions import assert_cascade_routed


@pytest.mark.xfail(
    reason="CASCADE routing pending: hivemind-core#74 / hivemind-websocket-client#88",
    strict=False,
)
def test_cascade_reaches_all_nodes():
    """A CASCADE sent from one satellite should reach master and all siblings."""
    b = three_satellites()
    b.start_all()
    try:
        m = b.get_master("M0")
        s0 = b.get_satellite("S0")
        s1 = b.get_satellite("S1")
        s2 = b.get_satellite("S2")

        s0.send(HiveMessage(
            HiveMessageType.CASCADE,
            payload=Message("network:ping", {}),
        ))

        assert_cascade_routed(m, s1, s2, count=1)
    finally:
        b.stop_all()
