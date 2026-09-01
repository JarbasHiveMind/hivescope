"""Regression test for the widened HiveMind disconnect-callback contract.

hivemind-core now rejects bad-credential/handshake clients by calling
``client.disconnect(code, reason)`` instead of the old zero-arg
``client.disconnect()``. hivescope wires two in-process providers
(TestNetworkProtocol and LoopbackNetworkProtocol) whose disconnect callbacks
used to be defined with no parameters, so a call with a close code raised
TypeError.
"""
from hivescope.topology import TopologyBuilder


def test_network_disconnect_callback_accepts_close_code():
    """TestNetworkProtocol wires satellite._on_disconnect as the disconnect
    callback; it must tolerate being called with (code, reason)."""
    b = TopologyBuilder()
    m = b.add_master("M0")
    s = b.add_satellite("S0", upstream=m, allowed_types=["speak"])
    b.start_all()
    try:
        conn = s._connection
        assert conn is not None
        # Must not raise TypeError when called with a close code + reason,
        # matching hivemind-core's client.disconnect(1008, reason) call on
        # auth/handshake rejection.
        conn.disconnect(1008, "policy violation")
        assert conn.peer not in m.hm_protocol.clients
    finally:
        b.stop_all()


def test_network_disconnect_callback_still_works_with_no_args():
    """Existing zero-arg callers keep working (default close code)."""
    b = TopologyBuilder()
    m = b.add_master("M0")
    s = b.add_satellite("S0", upstream=m, allowed_types=["speak"])
    b.start_all()
    try:
        conn = s._connection
        assert conn is not None
        conn.disconnect()
        assert conn.peer not in m.hm_protocol.clients
    finally:
        b.stop_all()


def test_loopback_disconnect_callback_accepts_close_code():
    """LoopbackNetworkProtocol wires a sync_disconnect() closure as the
    disconnect callback; it must tolerate being called with (code, reason)."""
    import base64
    import json
    import threading
    import time

    import asyncio

    def _ws_client(url, name, key, session_id, connected, close):
        import websockets

        async def _run():
            auth = base64.b64encode(f"{name}:{key}".encode()).decode()
            async with websockets.connect(
                    url, additional_headers={"Authorization": f"Basic {auth}"}) as ws:
                await ws.send(json.dumps({
                    "msg_type": "hello",
                    "payload": {"session": {"session_id": session_id},
                                "site_id": "test-site"},
                }))
                connected.set()
                while not close.is_set():
                    try:
                        await asyncio.wait_for(ws.recv(), timeout=0.1)
                    except Exception:
                        pass

        try:
            asyncio.run(_run())
        except Exception:
            pass

    b = TopologyBuilder()
    m = b.add_master("M0", use_loopback=True, require_crypto=False,
                     handshake_enabled=False)
    m.register_satellite(key="close-code-key")
    b.start_all()
    url = m.network_protocol.url

    connected, close = threading.Event(), threading.Event()
    t = threading.Thread(
        target=_ws_client,
        args=(url, "close-code-node", "close-code-key", "cc-session",
              connected, close),
        daemon=True)
    t.start()
    try:
        assert connected.wait(timeout=20), "websocket client never connected"

        deadline = time.monotonic() + 20
        while not m.hm_protocol.clients and time.monotonic() < deadline:
            time.sleep(0.05)
        assert m.hm_protocol.clients, "master never registered the client"

        conn = next(iter(m.hm_protocol.clients.values()))
        # Must not raise TypeError, matching hivemind-core's
        # client.disconnect(1008, reason) call on rejection.
        conn.disconnect(1008, "policy violation")
    finally:
        close.set()
        t.join(timeout=5)
        b.stop_all()
