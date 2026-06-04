"""Copy this file into your repo's tests/e2e/ and rename.

THIRDPRTY (3rdparty) — user-land passthrough message type.

Core is expected to forward THIRDPRTY messages without inspection.
Verify the routing status in LIBRARY.md; this template tests the basic
passthrough path. If core does not yet handle THIRDPRTY, add an xfail marker.
"""

from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivescope.scenarios import single_satellite
from hivescope.assertions import assert_thirdparty_passed


def test_thirdparty_message_passed_to_master():
    """A THIRDPRTY message from satellite should be forwarded to master."""
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        s.send(HiveMessage(
            HiveMessageType.THIRDPRTY,
            payload={"custom": "user-land payload"},
        ))

        assert_thirdparty_passed(m, count=1, direction="in")
    finally:
        b.stop_all()
