"""A request is never relayed to a peer, whatever its ``destination`` says.

``TestAgentProtocol.handle_internal_mycroft`` stands in for the server's
outbound delivery path. Two clauses bound what it may deliver.

**HIVEMIND-BRIDGE-1 §3.1**: "On injecting a peer's message into the Layer-1
bus, the server **MUST** ensure the resulting Layer-1 message carries a
**unique** identifier for that peer in its ``source`` [...] When the server
fronts multiple peers, their ``source`` values **MUST** be distinct".

**HIVEMIND-AGENT-1 §3.2**: "The backend **MAY** emit zero or more Layer-1
response messages. For each response the server observes: [...] The server
**MUST** deliver a response **only** to the peer or peers named in the
response's Layer-1 ``destination``. [...] A peer **MUST NOT** receive a
response generated for a different peer."

The delivery permission covers responses the backend emits. An injected
request is not one: §3.1 makes the originating peer's own identifier appear in
its ``source``, so a bus message whose ``source`` names a connected peer is
that peer's request in flight. Relaying it hands one peer's traffic to another
peer's socket, which §3.2's isolation requirement forbids.

A real response carries no connected peer in ``source``, because
``Message.reply()`` swaps ``source`` and ``destination``. That is the
discriminator, and it rests on a **MUST** rather than on a habit of the node.

The cells drive the shipped topology builder: a real ``hivemind-core`` master,
a real Noise handshake, real ``HiveMessage`` serialisation, and peer ids the
node minted itself. The transport is in-process rather than a socket, so what
a satellite's ``internal_bus`` records is the payload it decoded, not a mock's
recorded call.
"""
import time

import pytest
from ovos_bus_client.message import Message

from hivescope import TopologyBuilder

SETTLE = 0.5


class Inbox:
    """Every ``speak`` a satellite decoded onto its internal bus.

    The subscription is installed before any message is emitted.
    ``MasterNode.emit_on_bus`` delivers synchronously in this harness, so a
    listener registered after the emit never fires and every assertion built
    on one reads as "not delivered" whatever the relay did.
    """

    def __init__(self, satellite):
        self.messages = []
        satellite.internal_bus.on("speak", self.messages.append)

    def utterances(self):
        time.sleep(SETTLE)
        return [m.data.get("utterance") for m in self.messages]


@pytest.fixture
def two_peers():
    """One master, two connected satellites, and an inbox for each.

    Both satellites whitelist ``speak`` so the admission chain does not deny
    the type before the relay is reached.
    """
    b = TopologyBuilder()
    master = b.add_master("M0")
    for name in ("S0", "S1"):
        b.add_satellite(name, upstream=master,
                        allowed_types=["recognizer_loop:utterance", "speak"])
    b.start_all()
    try:
        origin = b.get_satellite("S0")
        victim = b.get_satellite("S1")
        assert origin.peer and victim.peer, "both satellites must hold a peer id"
        assert origin.peer != victim.peer, (
            "BRIDGE-1 §3.1 requires distinct source values per peer")
        yield master, origin, victim, Inbox(origin), Inbox(victim)
    finally:
        b.stop_all()


def _emit(master, destination, source=None, utterance="leak"):
    context = {"destination": destination}
    if source is not None:
        context["source"] = source
    master.emit_on_bus(Message("speak", {"utterance": utterance}, context))


class TestARequestIsNotRelayed:
    """A bus message whose source names a connected peer reaches no peer."""

    def test_a_peer_id_written_into_destination_does_not_reach_the_victim(
            self, two_peers):
        master, origin, victim, _origin_box, victim_box = two_peers

        _emit(master, victim.peer, source=origin.peer)

        assert victim_box.utterances() == []

    def test_the_victim_hidden_among_other_destinations_is_refused_too(
            self, two_peers):
        master, origin, victim, _origin_box, victim_box = two_peers

        _emit(master, [victim.peer, "audio"], source=origin.peer)

        assert victim_box.utterances() == []

    def test_a_LIST_source_is_refused_on_the_same_reading(self, two_peers):
        # A satellite's own slave protocol writes this shape: on an inbound BUS
        # message it does `context["source"] = context.pop("destination")`
        # (hivemind_bus_client.protocol.handle_bus), and a destination is
        # routinely a list. A string-only test reads a list as "no source" and
        # delivers: the same hole in a different shape.
        master, origin, victim, _origin_box, victim_box = two_peers

        _emit(master, [victim.peer], source=[origin.peer])

        assert victim_box.utterances() == []

    def test_the_peer_id_need_not_be_first_in_that_list(self, two_peers):
        master, origin, victim, _origin_box, victim_box = two_peers

        _emit(master, [victim.peer], source=["skills", origin.peer])

        assert victim_box.utterances() == []

    def test_a_TUPLE_source_is_refused_on_the_same_reading(self, two_peers):
        master, origin, victim, _origin_box, victim_box = two_peers

        _emit(master, [victim.peer], source=(origin.peer,))

        assert victim_box.utterances() == []

    def test_a_padded_peer_id_is_refused(self, two_peers):
        # A minted peer id carries no space, so stripping before the test can
        # only widen what the guard refuses. It fails closed.
        master, origin, victim, _origin_box, victim_box = two_peers

        _emit(master, [victim.peer], source=origin.peer + " ")

        assert victim_box.utterances() == []

    def test_a_peer_cannot_address_itself_either(self, two_peers):
        # A design case rather than a security one: a peer's own request must
        # not come back to it as though the backend had answered.
        master, origin, _victim, origin_box, _victim_box = two_peers

        _emit(master, origin.peer, source=origin.peer)

        assert origin_box.utterances() == []


class TestAResponseStillArrives:
    """The negative controls. The guard must not close the ordinary path."""

    def test_a_response_reaches_the_peer_its_destination_names(self, two_peers):
        master, _origin, victim, _origin_box, victim_box = two_peers

        _emit(master, victim.peer, source="skills", utterance="the answer")

        assert victim_box.utterances() == ["the answer"]

    def test_a_response_with_no_source_at_all_still_arrives(self, two_peers):
        master, _origin, victim, _origin_box, victim_box = two_peers

        _emit(master, victim.peer, utterance="no source")

        assert victim_box.utterances() == ["no source"]

    def test_a_source_naming_a_peer_that_is_not_connected_does_not_block(
            self, two_peers):
        # The guard tests the CONNECTED peers, not the shape of the string. A
        # stale id from a closed connection must not stop a live response.
        master, _origin, victim, _origin_box, victim_box = two_peers

        _emit(master, victim.peer, source="gone::session-z",
              utterance="still arrives")

        assert victim_box.utterances() == ["still arrives"]

    def test_the_origin_gets_its_own_answer_and_the_other_peer_does_not(
            self, two_peers):
        """The point of the relay: an answer to S0's request reaches S0 alone.

        This is the shape ``Message.reply()`` produces for a satellite's own
        utterance — the peer in ``destination``, a service name in ``source``.
        """
        master, origin, _victim, origin_box, victim_box = two_peers

        _emit(master, origin.peer, source="skills", utterance="your answer")

        assert origin_box.utterances() == ["your answer"]
        assert victim_box.utterances() == []

    def test_a_destination_naming_only_services_reaches_no_peer(self, two_peers):
        """The ordinary hub case: OVOS routes to "audio" and "skills" names."""
        master, _origin, _victim, origin_box, victim_box = two_peers

        _emit(master, ["audio", "skills"], source="skills")

        assert origin_box.utterances() == []
        assert victim_box.utterances() == []


class TestTheRefusalsAreNotAClosedPath:
    """Non-vacuity: a refusal cell asserts an absence, and so does a broken
    fixture. One run proves the path the refusals close is open to a response
    through the same fixture, the same peer and the same inbox.
    """

    def test_one_fixture_refuses_the_request_and_delivers_the_response(
            self, two_peers):
        master, origin, victim, _origin_box, victim_box = two_peers

        _emit(master, victim.peer, source=origin.peer, utterance="refused")
        assert victim_box.utterances() == []

        _emit(master, victim.peer, source="skills", utterance="permitted")
        assert victim_box.utterances() == ["permitted"]


class TestTheGuardReadsTheLiveClientTable:
    """A peer that has gone is no longer a reason to refuse.

    The guard reads the clients connected at delivery time, not a table
    captured earlier. A disconnected origin leaves a stale id in flight, and
    the isolation concern of §3.2 is over once that connection is gone.
    """

    def test_a_disconnected_origin_no_longer_blocks_delivery(self, two_peers):
        master, origin, victim, _origin_box, victim_box = two_peers
        stale = origin.peer

        origin.disconnect()
        deadline = time.time() + 5.0
        while stale in master.connected_peers() and time.time() < deadline:
            time.sleep(0.05)
        assert stale not in master.connected_peers(), (
            "the origin did not leave the client table")

        _emit(master, victim.peer, source=stale,
              utterance="after the origin left")

        assert victim_box.utterances() == ["after the origin left"]
