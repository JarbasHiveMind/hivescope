"""A refused key runs the invalid-key path, as the real binding does.

The loopback hub is a TEST DOUBLE for the reference WebSocket binding. On a
key the database does not hold, the binding builds the connection and calls
``hm_protocol.handle_invalid_key_connected(client)`` BEFORE it closes. That
one call records the rejection in the bounded ``recent_rejections`` ring,
fires ``on_invalid_key`` on the protocol, the binary protocol and the agent
protocol, and emits ``hive.client.connection.error``.

The hub used to close the socket and return. So a harness driving this
double saw no ``on_invalid_key`` callback and no rejection-ring entry where
production has both, and a suite could not test either.

THE CALLBACK IS DRIVEN, NOT READ OUT OF THE SOURCE. The test connects with
an unknown key and asserts on what the protocol object received.
"""
import asyncio
import base64
from unittest.mock import MagicMock

import pytest
import websockets

from hivescope.plugins.loopback import LoopbackNetworkProtocol

# A hang guard, not an assertion: nothing here measures how fast the hub
# refuses. Generous on purpose, for a loaded shared runner.
REFUSAL_DEADLINE = 10


def _hub():
    """A loopback hub whose database holds no key at all."""
    hm = MagicMock()
    hm.db.sync = MagicMock()
    hm.db.get_client_by_api_key = MagicMock(return_value=None)
    node = LoopbackNetworkProtocol(config={}, hm_protocol=hm,
                                   callbacks=MagicMock())
    node.run()
    return node


async def _connect_and_be_refused(url, auth="sat-1:a-key-nobody-has"):
    query = "?authorization=" + base64.b64encode(auth.encode()).decode()
    try:
        async with websockets.connect(url.rstrip("/") + "/" + query) as ws:
            await ws.recv()
    except websockets.exceptions.ConnectionClosed:
        return
    pytest.fail("the hub accepted a key its database does not hold")


def _refuse_one():
    """Drive one refusal and hand back the hub's protocol object."""
    node = _hub()
    try:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(asyncio.wait_for(
                _connect_and_be_refused(node.url), timeout=REFUSAL_DEADLINE))
        finally:
            loop.close()
        return node.hm_protocol
    finally:
        node.stop()


def test_a_refused_key_runs_the_invalid_key_path():
    hm = _refuse_one()
    hm.handle_invalid_key_connected.assert_called_once()


def test_the_call_carries_the_refused_connection():
    """Not a bare call: the ring entry and every callback read the client.

    ``record_rejection`` stores ``client.peer`` and ``on_invalid_key``
    handlers are handed the connection, so a call with nothing useful in it
    would satisfy the test above and tell a harness nothing.
    """
    hm = _refuse_one()
    client = hm.handle_invalid_key_connected.call_args[0][0]
    assert client is not None
    assert client.key == "a-key-nobody-has"
    assert client.name == "sat-1"


def test_the_refused_connection_is_not_registered():
    """It is refused, so it must not appear among the hub's clients.

    The binding does not register it either. A double that kept it would
    show a harness a connected satellite that production never had.
    """
    node = _hub()
    try:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(asyncio.wait_for(
                _connect_and_be_refused(node.url), timeout=REFUSAL_DEADLINE))
        finally:
            loop.close()
        assert node._clients == []
    finally:
        node.stop()


def test_a_failing_callback_does_not_stop_the_refusal():
    """The close is what the satellite sees, so it must survive a harness bug."""
    node = _hub()
    node.hm_protocol.handle_invalid_key_connected.side_effect = RuntimeError("boom")
    try:
        loop = asyncio.new_event_loop()
        try:
            # no exception, and the connection is still closed
            loop.run_until_complete(asyncio.wait_for(
                _connect_and_be_refused(node.url), timeout=REFUSAL_DEADLINE))
        finally:
            loop.close()
    finally:
        node.stop()


def test_a_known_key_does_not_run_the_invalid_key_path():
    """The control. A hub that called it for everyone would pass the rest."""
    hm = MagicMock()
    hm.db.sync = MagicMock()
    db_client = MagicMock()
    db_client.password = None
    db_client.is_admin = False
    db_client.can_escalate = False
    db_client.can_propagate = False
    db_client.can_broadcast = False
    db_client.allowed_types = []
    hm.db.get_client_by_api_key = MagicMock(return_value=db_client)
    node = LoopbackNetworkProtocol(config={}, hm_protocol=hm,
                                   callbacks=MagicMock())
    node.run()
    try:
        async def _connect_and_hold():
            query = "?authorization=" + base64.b64encode(
                b"sat-1:a-key-that-exists").decode()
            async with websockets.connect(node.url.rstrip("/") + "/" + query):
                await asyncio.sleep(0.2)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(asyncio.wait_for(_connect_and_hold(),
                                                     timeout=REFUSAL_DEADLINE))
        except Exception:
            pass  # the handshake is not the subject; the callback is
        finally:
            loop.close()
        hm.handle_invalid_key_connected.assert_not_called()
    finally:
        node.stop()
