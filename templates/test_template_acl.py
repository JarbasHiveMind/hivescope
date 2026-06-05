"""Copy this file into your repo's tests/e2e/ and rename.

Demonstrates both policy-admission enforcement paths:

1. **allowed_types deny** — a satellite whose ``allowed_types`` excludes
   ``recognizer_loop:utterance`` has its utterance blocked by
   ``MessageTypeACLPolicy`` with code ``ACL_DISALLOWED_TYPE``.  The message
   never reaches the agent bus.

2. **Skill-blacklist injection** — a satellite whose ``allowed_types``
   includes ``recognizer_loop:utterance`` but whose ``skill_blacklist``
   contains ``"skill-weather"`` has its utterance delivered to the agent bus
   with ``session.blacklisted_skills = ["skill-weather"]`` injected by
   ``OVOSAgentPolicy`` + ``AddBlacklistedSkill``.

All admission control flows through the ``PolicyChain``.
"""

import time

from ovos_bus_client.message import Message

from hivescope import TopologyBuilder
from hivescope.assertions import (
    assert_policy_denied,
    assert_session_blacklists_injected,
)


def test_allowed_types_denial():
    """A satellite whose allowed_types excludes recognizer_loop:utterance
    has its utterance blocked by MessageTypeACLPolicy.

    The message must not reach the agent bus (no bus_inject record).
    """
    b = TopologyBuilder()
    m = b.add_master("M0")
    # speak only → recognizer_loop:utterance is NOT in allowed_types
    b.add_satellite("S0", upstream=m, allowed_types=["speak"])
    b.start_all()
    try:
        s = b.get_satellite("S0")
        s.send(Message("recognizer_loop:utterance", {"utterances": ["what is the weather"]}))

        time.sleep(0.2)  # give any errant dispatch a window to land
        assert_policy_denied(
            m, s,
            msg_type="recognizer_loop:utterance",
            deny_code="acl_disallowed_type",
        )
    finally:
        b.stop_all()


def test_skill_blacklist_injection():
    """A satellite with skill_blacklist=["skill-weather"] can inject an utterance
    (allowed_types includes it) but OVOSAgentPolicy injects
    session.blacklisted_skills=["skill-weather"] so the OVOS pipeline cannot
    route the utterance to the blacklisted skill.
    """
    b = TopologyBuilder()
    m = b.add_master("M0")
    b.add_satellite(
        "S0",
        upstream=m,
        allowed_types=["recognizer_loop:utterance"],
        skill_blacklist=["skill-weather"],
    )
    b.start_all()
    try:
        s = b.get_satellite("S0")
        seen = []
        m.agent_protocol.bus.on("recognizer_loop:utterance", seen.append)

        s.send(Message("recognizer_loop:utterance", {"utterances": ["what is the weather"]}))

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not seen:
            time.sleep(0.02)

        assert seen, "utterance did not reach the agent bus at all"

        # Verify OVOSAgentPolicy injected the skill blacklist into the session
        assert_session_blacklists_injected(
            m, s,
            msg_type="recognizer_loop:utterance",
            expected_skills=["skill-weather"],
        )
    finally:
        b.stop_all()
