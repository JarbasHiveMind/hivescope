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
    import threading
    import time

    import asyncio

    def _ws_client(url, name, key, password, connected, close):
        """Real v3 client: a bare HELLO is not reachable any more
        (hivemind-core is v3-Noise-only, HiveMind-core#309), so this client
        completes a genuine Noise handshake to get registered at master
        before the test grabs its connection and disconnects it with a
        close code -- the actual subject under test."""
        from hivemind_bus_client.async_client import AsyncHiveMessageBusClient
        from hivemind_bus_client.identity import NodeIdentity

        host_port = url.split("://", 1)[1]
        host, port = host_port.split(":")
        port = int(port.split("/")[0])

        identity = NodeIdentity()
        identity.access_key = key
        identity.password = password
        identity.default_master = f"ws://{host}"
        identity.default_port = port

        async def _run():
            client = AsyncHiveMessageBusClient(
                key=key, password=password, host=f"ws://{host}", port=port,
                identity=identity, max_protocol_version=3, useragent=name)
            try:
                await asyncio.wait_for(client.connect(handshake_max_retries=3), timeout=15)
                connected.set()
                while not close.is_set():
                    await asyncio.sleep(0.1)
            finally:
                try:
                    await client.close()
                except Exception:
                    pass

        try:
            asyncio.run(_run())
        except Exception:
            pass

    b = TopologyBuilder()
    m = b.add_master("M0", use_loopback=True, require_crypto=False,
                     handshake_enabled=False)
    m.register_satellite(key="close-code-key",
                         password="x9K#mQ7z!vL2pR8w$nT4jY6c-close")
    b.start_all()
    url = m.network_protocol.url

    connected, close = threading.Event(), threading.Event()
    t = threading.Thread(
        target=_ws_client,
        args=(url, "close-code-node", "close-code-key",
              "x9K#mQ7z!vL2pR8w$nT4jY6c-close", connected, close),
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
