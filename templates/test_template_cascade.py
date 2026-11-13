"""Copy this file into your repo's tests/e2e/ and rename.

CASCADE is like PROPAGATE but expects responses from all nodes (optional).

The inner payload must be a HiveMessage, not a bare OVOS Message. Core reads a
CASCADE payload as a nested HiveMessage, so a bare Message raises a TypeError.
"""

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message

from hivescope.scenarios import three_satellites
from hivescope.assertions import assert_cascade_routed


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
            payload=HiveMessage(HiveMessageType.BUS, Message("network:ping", {})),
        ))

        assert_cascade_routed(m, s1, s2, count=1)
    finally:
        b.stop_all()
