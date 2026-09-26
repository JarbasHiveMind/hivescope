"""A refused access key closes with the code and reason the binding sends.

The loopback hub is a TEST DOUBLE for the reference WebSocket binding. A
satellite refused here must behave like a satellite refused in production,
and the behaviour that matters is keyed on the CLOSE CODE:
``hivemind_bus_client.client`` latches ``_auth_rejected`` on it, stops
reconnecting and tells the operator the identity was refused. The reason
travels with it and is the text the operator reads.

The loopback hub closed an unknown key with 4001. The binding it stands in
for closes with 1008. So a client refused by this hub kept reconnecting where
the real one would have stopped, and every test written against this hub read
a close code production never sends.

THE CLOSE FRAME IS READ OFF THE WIRE, not out of the module source. An
earlier version of this file matched the ``close(...)`` call with a regular
expression, and reviewer-b measured what that cannot see: with the 1008 call
disabled and a live ``close(4001)`` after it -- the exact defect this change
fixes, put back -- all three tests still PASSED while the wire gave 4001, and
rewording the log line failed two of them without changing any behaviour. A
source match tests the text of the file. This connects, is refused, and reads
the frame the client would read.
"""
import asyncio
import base64
from unittest.mock import MagicMock

import pytest
import websockets

from hivescope.plugins.loopback import LoopbackNetworkProtocol

# The binding words its two refusals apart on purpose, and this is the
# unknown-key one. Both close with 1008.
BINDING_UNKNOWN_KEY_REASON = "invalid api key"

# A hang guard, not an assertion. Nothing here measures how FAST the hub
# refuses, only what it sends, so this number may be generous and must be:
# a refusal took 10 ms on an idle box and 1464 ms with 16 busy loops on 16
# cores, which is 73 percent of a 2 s budget on a box less contended than a
# shared runner. Ten seconds removes that flake and changes no meaning.
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


async def _close_frame(url, auth):
    """Connect, wait to be refused, and return the close frame as sent."""
    query = ""
    if auth is not None:
        query = "?authorization=" + base64.b64encode(auth.encode()).decode()
    try:
        async with websockets.connect(url.rstrip("/") + "/" + query) as ws:
            await ws.recv()
    except websockets.exceptions.ConnectionClosed as exc:
        assert exc.rcvd is not None, "closed with no frame at all"
        return exc.rcvd.code, exc.rcvd.reason
    pytest.fail("the hub accepted a key its database does not hold")


def _refusal(auth):
    node = _hub()
    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                asyncio.wait_for(_close_frame(node.url, auth),
                                 timeout=REFUSAL_DEADLINE))
        finally:
            loop.close()
    finally:
        node.stop()


def test_an_unknown_key_closes_with_the_code_the_client_latches_on():
    """Read the expected value off the client, not restated here.

    If the fleet's client ever moves its latch, this fails instead of the
    hub quietly drifting away from it again.
    """
    from hivemind_bus_client.client import HiveMessageBusClient

    code, _ = _refusal("sat-1:a-key-nobody-has")
    assert code == HiveMessageBusClient.AUTH_REJECTED_CLOSE_CODE


def test_an_unknown_key_closes_with_the_binding_s_own_reason():
    """The reason is not decoration.

    The client copies the close reason straight into ``_auth_rejected``, and
    two suites in the fleet pin that text. The binding says "invalid api key"
    for a key the database does not hold and "invalid authorization" for a
    malformed header, so sending the header case's words here names the wrong
    fault to the operator.
    """
    _, reason = _refusal("sat-1:a-key-nobody-has")
    assert reason == BINDING_UNKNOWN_KEY_REASON


def test_no_authorization_at_all_is_still_refused_with_1008():
    """The control, on the other refusal path.

    That path already closed with 1008 and must keep doing so, so neither
    test above can pass by the hub being rewritten to one close for
    everything. Its reason is the hub's own and is deliberately not asserted
    here: the subject is the unknown-key path.
    """
    code, _ = _refusal(None)
    assert code == 1008
