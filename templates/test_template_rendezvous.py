"""Copy this file into your repo's tests/e2e/ and rename.

PENDING: RENDEZVOUS routing is not yet implemented.
Track: https://github.com/JarbasHiveMind/hivemind-websocket-client/pull/103

RENDEZVOUS is reserved for rendezvous-nodes (peer discovery / NAT traversal).
When ws#103 lands, remove the xfail marker and add the rendezvous-node fixture.
"""

import pytest
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivescope.scenarios import single_satellite
from hivescope.assertions import assert_rendezvous_handled


@pytest.mark.xfail(
    reason="RENDEZVOUS routing pending: hivemind-websocket-client#103",
    strict=False,
)
def test_rendezvous_message_handled():
    """A RENDEZVOUS message should be routed to the rendezvous handler at master."""
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        s.send(HiveMessage(HiveMessageType.RENDEZVOUS, payload={"peer": "node-xyz"}))

        assert_rendezvous_handled(m, count=1)
    finally:
        b.stop_all()
