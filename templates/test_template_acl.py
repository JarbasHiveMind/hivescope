"""Copy this file into your repo's tests/e2e/ and rename.

Verifies that a satellite without the broadcast permission cannot fan
out a message to siblings.
"""

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message

from hivescope import TopologyBuilder


def test_restricted_satellite_cannot_broadcast():
    b = TopologyBuilder()
    m = b.add_master("M0")
    b.add_satellite("S0", upstream=m, can_broadcast=False)
    b.add_satellite("S1", upstream=m)
    b.start_all()
    try:
        s0 = b.get_satellite("S0")
        s1 = b.get_satellite("S1")

        # BROADCAST payload must be a HiveMessage wrapping the inner message
        inner = HiveMessage(HiveMessageType.BUS, payload=Message("speak", {"utterance": "hello world"}))
        msg = HiveMessage(HiveMessageType.BROADCAST, payload=inner)
        s0.send(msg)

        # S1 must not receive the broadcast because S0 lacks the permission.
        received = [r for r in s1.recorder.messages
                    if r.msg_type == HiveMessageType.BROADCAST.value]
        assert received == [], f"ACL violation: S1 received {received}"
    finally:
        b.stop_all()
