# Licensed under the Apache License, Version 2.0
"""Two threads sending on one session decode in nonce order, on the right cipher.

A socket delivers a connection's frames in the order they were written. The
delivery pump is per thread, so a frame whose decode waits on one thread's
pump must not be overtaken by a later frame decoded on another thread: Noise
rejects an out-of-order frame as tampered and the satellite disconnects. The
decode also swaps the satellite's cipher onto the connection the master sends
on, so a master send must not run while the swap is in place.

Each test stalls sender A at one point of its delivery while sender B sends a
frame on the same session, then checks that nothing was refused.
"""
import threading
from collections import deque

import pytest
from ovos_bus_client.message import Message
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivescope import node
from hivescope.topology import TopologyBuilder

STALL = 0.5


def _bus(i):
    return HiveMessage(HiveMessageType.BUS, payload=Message("test.order", {"i": i}))


@pytest.fixture()
def session():
    topo = TopologyBuilder()
    master = topo.add_master("hub")
    sat = topo.add_satellite("sat", master)
    topo.start_all()
    try:
        yield master, sat
    finally:
        topo.stop_all()


def _run(master, sat, stall_installer):
    """Start A, wait until it stalls, run B to completion, then release A."""
    peer = sat.peer
    stalled = threading.Event()
    b_done = threading.Event()

    def stall():
        if threading.current_thread().name == "sender-a" and not stalled.is_set():
            stalled.set()
            b_done.wait(timeout=STALL)

    restore = stall_installer(stall)
    try:
        def send(i, done=None):
            master.send_to_satellite(peer, _bus(i))
            if done:
                done.set()

        a = threading.Thread(target=send, args=(0,), name="sender-a")
        b = threading.Thread(target=send, args=(1, b_done), name="sender-b")
        a.start()
        assert stalled.wait(timeout=5.0)
        b.start()
        a.join(10)
        b.join(10)
    finally:
        restore()

    errors = [r for r in sat.recorder.snapshot() if r.msg_type == "_decode_error"]
    assert not errors, errors
    assert sat.peer is not None, "the satellite was disconnected"
    delivered = [r for r in sat.recorder.snapshot()
                 if r.direction == "in" and r.msg_type == HiveMessageType.BUS.value]
    assert len(delivered) == 2, delivered


def test_stall_before_the_frame_is_taken(session):
    master, sat = session
    real_deliver = node._deliver
    actions = {}

    def install(stall):
        def deliver(action):
            # Two pump actions per send on its own thread: the master's
            # conn.send, then the satellite's decode of the frame it produced.
            name = threading.current_thread().name
            actions[name] = actions.get(name, 0) + 1
            if actions[name] == 2:
                inner = action

                def action():
                    stall()
                    inner()
            real_deliver(action)

        node._deliver = deliver
        return lambda: setattr(node, "_deliver", real_deliver)

    _run(master, sat, install)


def test_stall_after_the_frame_is_taken(session):
    master, sat = session

    class StallingInbox(deque):
        stall = None

        def popleft(self):
            item = super().popleft()
            self.stall()
            return item

    def install(stall):
        inbox = StallingInbox(sat._inbox)
        inbox.stall = staticmethod(stall)
        sat._inbox = inbox
        return lambda: None

    _run(master, sat, install)


def test_stall_while_the_cipher_is_swapped(session):
    master, sat = session
    conn = master.hm_protocol.clients[sat.peer]
    real_decode = conn.decode

    def install(stall):
        def decode(payload):
            stall()
            return real_decode(payload)

        conn.decode = decode
        return lambda: conn.__dict__.pop("decode", None)

    _run(master, sat, install)
