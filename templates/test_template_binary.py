"""Copy this file into your repo's tests/e2e/ and rename.

Verifies that a binary payload sent from a satellite reaches the master.

Two paths, and they are not the same:

* An **UNDEFINED** binary payload (the default) carries no handler hint, so
  hivemind-core has nothing to dispatch it to. It arrives, and the recorder
  sees it, but no ``BinaryDataHandlerProtocol`` method runs.
* A **typed** payload (``RAW_AUDIO``, ``STT_AUDIO_TRANSCRIBE``, …) is
  dispatched to the matching handler, so ``binary_protocol.calls`` fills in.

Both need a satellite with a **non-empty** ``allowed_types`` whitelist.
hivemind-core's MessageTypeACLPolicy denies every binary payload from a
client that is granted no message type at all — otherwise a client that may
not emit a single bus message could still push RAW_AUDIO into the STT
pipeline and FILE payloads to disk. The specific types do not matter to the
binary path; having some does.
"""

from hivemind_bus_client.message import (HiveMessage, HiveMessageType,
                                         HiveMindBinaryPayloadType)

from hivescope.assertions import assert_binary_delivered
from hivescope.scenarios import single_satellite


def test_untyped_binary_reaches_the_master():
    payload = b"\x00\x01\x02hello-binary\xff\xfe"
    b = single_satellite(allowed_types=["recognizer_loop:utterance", "speak"])
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        s.send(HiveMessage(HiveMessageType.BINARY, payload=payload))

        assert_binary_delivered(m, expected_payload=payload, count=1)
    finally:
        b.stop_all()


def test_typed_binary_reaches_the_handler():
    payload = b"\x00\x01\x02fake-audio\xff\xfe"
    b = single_satellite(allowed_types=["recognizer_loop:utterance", "speak"])
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        s.send(HiveMessage(
            HiveMessageType.BINARY,
            payload=payload,
            bin_type=HiveMindBinaryPayloadType.RAW_AUDIO,
            metadata={"sample_rate": 16000, "sample_width": 2},
        ))

        # BinaryCall is a dataclass: read c.data, never c[1].
        received = [c for c in m.binary_protocol.calls if c.data == payload]
        assert received, (
            f"Binary payload not delivered to the handler. "
            f"Calls: {m.binary_protocol.calls}"
        )
        m.binary_protocol.assert_called("microphone_input")
    finally:
        b.stop_all()
