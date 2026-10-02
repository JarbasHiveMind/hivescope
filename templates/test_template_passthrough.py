"""Copy this file into your repo's tests/e2e/ and rename.

Generic passthrough — asserts an unhandled, user-land message type traverses
the mesh untouched. Use this for any ``HiveMessageType`` with no core-side
handler (e.g. RENDEZVOUS, which has a wire code but is not routed by
hivemind-core). Core is expected to forward such messages without inspection.
Swap ``HiveMessageType.RENDEZVOUS`` below for whichever type you're testing.
"""

from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivescope.scenarios import single_satellite
from hivescope.assertions import assert_passthrough_message_delivered


def test_passthrough_message_delivered_to_master():
    """An unhandled message from satellite should be forwarded to master."""
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        s.send(HiveMessage(
            HiveMessageType.RENDEZVOUS,
            payload={"custom": "user-land payload"},
        ))

        assert_passthrough_message_delivered(
            m, HiveMessageType.RENDEZVOUS, count=1, direction="in"
        )
    finally:
        b.stop_all()
