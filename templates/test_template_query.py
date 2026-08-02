"""Copy this file into your repo's tests/e2e/ and rename.

QUERY behaves like ESCALATE but stops as soon as one node sends a response.

The inner payload must be a HiveMessage, not a bare OVOS Message. Core reads a
QUERY payload as a nested HiveMessage, so a bare Message raises a TypeError.
"""

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message

from hivescope.scenarios import single_satellite
from hivescope.assertions import assert_query_routed


def test_query_reaches_master():
    """A QUERY sent by a satellite should be escalated to master and stop there."""
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        s.send(HiveMessage(
            HiveMessageType.QUERY,
            payload=HiveMessage(
                HiveMessageType.BUS,
                Message("question:ask", {"utterance": "what is the weather?"})),
        ))

        assert_query_routed(m, count=1)
    finally:
        b.stop_all()
