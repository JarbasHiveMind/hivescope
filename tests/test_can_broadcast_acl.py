"""BROADCAST admission honours the per-client ``can_broadcast`` ACL.

Listeners watch for ``BROADCAST``, not ``BUS``: since HiveMind-core#216 a
forwarded broadcast keeps its envelope (``_rewrap``, NODE-1 §3.3), so a
sibling receives the wrapper with the BUS still inside it.

Broadcast requires ``is_admin``. ``can_broadcast`` narrows an admin that should
not be able to broadcast; it never grants rights to a non-admin. Enforcement
landed in HiveMind-core; these tests drive a real satellite through the real
protocol.
"""
from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message

from hivescope import TopologyBuilder


def _broadcast():
    return HiveMessage(
        HiveMessageType.BROADCAST,
        payload=HiveMessage(HiveMessageType.BUS,
                            payload=Message("test.event", {"ping": "pong"})),
    )


def test_admin_with_can_broadcast_reaches_other_peers():
    b = TopologyBuilder()
    m = b.add_master("M0")
    b.add_satellite("Caster", upstream=m, is_admin=True, can_broadcast=True)
    listener = b.add_satellite("Listener", upstream=m)
    try:
        b.start_all()
        seen = []
        listener.shim.emitter.on(HiveMessageType.BROADCAST, seen.append)

        b.get_satellite("Caster").send(_broadcast())
        listener.wait_for(HiveMessageType.BROADCAST, timeout=5)

        assert len(seen) == 1, f"listener missed the broadcast: {seen}"
        assert seen[0].payload.msg_type == HiveMessageType.BUS, \
            f"inner payload must stay a BUS, got {seen[0].payload.msg_type}"
    finally:
        b.stop_all()


def test_admin_without_can_broadcast_is_refused():
    b = TopologyBuilder()
    m = b.add_master("M0")
    b.add_satellite("Caster", upstream=m, is_admin=True, can_broadcast=False)
    listener = b.add_satellite("Listener", upstream=m)
    try:
        b.start_all()
        m0 = b.get_master("M0")
        caster = b.get_satellite("Caster")
        seen = []
        listener.shim.emitter.on(HiveMessageType.BROADCAST, seen.append)

        caster.send(_broadcast())

        # illegal action: the caster is kicked and nothing is relayed
        assert caster.peer not in m0.connected_peers()
        assert seen == [], f"broadcast leaked to listener: {seen}"
    finally:
        b.stop_all()


def test_non_admin_is_refused_regardless_of_can_broadcast():
    """can_broadcast narrows admin rights; it never grants them."""
    b = TopologyBuilder()
    m = b.add_master("M0")
    b.add_satellite("S0", upstream=m, is_admin=False, can_broadcast=True)
    try:
        b.start_all()
        m0 = b.get_master("M0")
        s0 = b.get_satellite("S0")

        s0.send(_broadcast())

        assert s0.peer not in m0.connected_peers()
    finally:
        b.stop_all()


def test_can_broadcast_defaults_to_true():
    """An admin registered without the flag keeps the prior behaviour."""
    b = TopologyBuilder()
    m = b.add_master("M0")
    b.add_satellite("Caster", upstream=m, is_admin=True)
    listener = b.add_satellite("Listener", upstream=m)
    try:
        b.start_all()
        seen = []
        listener.shim.emitter.on(HiveMessageType.BROADCAST, seen.append)

        b.get_satellite("Caster").send(_broadcast())
        listener.wait_for(HiveMessageType.BROADCAST, timeout=5)

        assert len(seen) == 1
    finally:
        b.stop_all()
