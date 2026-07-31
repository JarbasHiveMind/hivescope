"""Copy this file into your repo's tests/e2e/ and rename.

PING maps the network. There is no PONG message type: a node answers a PING
by sending its own PING, with the same ``flood_id``, wrapped in a PROPAGATE.

The wrapper matters. hivemind-core reaches ``handle_ping_message`` only from
``handle_propagate_message``, so a bare PING is dropped. Send
``PROPAGATE(PING)`` and the master answers with ``PROPAGATE(PING)``.
"""

import uuid

from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivescope.scenarios import single_satellite
from hivescope.assertions import assert_ping_responded


def test_ping_round_trip():
    """A PING flood from a satellite comes back as a responsive PING."""
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        inner = HiveMessage(HiveMessageType.PING, {
            "flood_id": uuid.uuid4().hex,
            "peer": s.peer,
            "site_id": s.identity.site_id,
            "timestamp": 0,
        })
        s.send(HiveMessage(HiveMessageType.PROPAGATE, payload=inner))

        assert_ping_responded(m, s)
    finally:
        b.stop_all()
