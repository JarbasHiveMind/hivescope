"""Copy this file into your repo's tests/e2e/ and rename.

PENDING: QUERY routing is not yet implemented in hivemind-core.
Track: https://github.com/JarbasHiveMind/HiveMind-core/pull/74
       https://github.com/JarbasHiveMind/hivemind-websocket-client/pull/88

QUERY behaves like ESCALATE but stops as soon as one node sends a response.
When core#74 lands, remove the xfail markers and implement the response check.
"""

import pytest
from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message

from hivescope.scenarios import single_satellite
from hivescope.assertions import assert_query_routed


@pytest.mark.xfail(
    reason="QUERY routing pending: hivemind-core#74 / hivemind-websocket-client#88",
    strict=False,
)
def test_query_reaches_master():
    """A QUERY sent by a satellite should be escalated to master and stop there."""
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        s.send(HiveMessage(
            HiveMessageType.QUERY,
            payload=Message("question:ask", {"utterance": "what is the weather?"}),
        ))

        assert_query_routed(m, count=1)
    finally:
        b.stop_all()
