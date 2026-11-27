"""A relay forwards a downstream BUS message to its master and routes the
answer back to the satellite that asked (hivemind-test-harness#85)."""
import time

from ovos_bus_client.message import Message

from hivescope.topology import TopologyBuilder


def _wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_relay_forwards_utterance_up_and_speak_down():
    b = TopologyBuilder()
    m = b.add_master("M0")
    acl = {"allowed_types": ["recognizer_loop:utterance", "speak"]}
    relay = b.add_relay("R0", upstream=m, **acl)
    s = b.add_satellite("S0", upstream=relay, **acl)
    b.start_all()
    try:
        heard = []
        s.internal_bus.on("speak", lambda msg: heard.append(msg))
        s.send(Message("recognizer_loop:utterance",
                       {"utterances": ["what time is it"], "lang": "en-US"}))

        master_agent = m.agent_protocol
        assert _wait(lambda: master_agent.last_injected("recognizer_loop:utterance")), \
            [x.msg_type for x in master_agent.injected]
        request = master_agent.last_injected("recognizer_loop:utterance")
        assert request.data["utterances"] == ["what time is it"]

        m.emit_on_bus(request.reply("speak", {"utterance": "it is noon"}))
        assert _wait(lambda: heard), "speak never reached the satellite"
        assert heard[0].data["utterance"] == "it is noon"
    finally:
        b.stop_all()
