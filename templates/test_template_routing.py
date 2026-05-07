"""Copy this file into your repo's tests/e2e/ and rename.

Verifies that a BUS message sent from a satellite reaches the master
agent bus and is recorded by the master.
"""

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message

from hivescope.scenarios import single_satellite
from hivescope.assertions import assert_message_routed


def test_bus_message_reaches_master():
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        s.send(HiveMessage(
            HiveMessageType.BUS,
            payload=Message("speak", {"utterance": "hello"}),
        ))

        assert_message_routed(m, "BUS", count=1, direction="inbound")
    finally:
        b.stop_all()
