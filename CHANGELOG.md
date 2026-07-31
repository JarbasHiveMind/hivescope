# Changelog

## [0.6.1a3](https://github.com/JarbasHiveMind/hivescope/tree/0.6.1a3) (2026-07-31)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/0.6.1a2...0.6.1a3)

**Han audit round 2:**

- fix(database): `client_id` now comes from a monotonic counter. Since round 1
  made `delete_client()` really delete, `total_clients() + 1` handed the id of a
  live client to the next one, and `get_client_by_id` (the TTL cache refresh on
  the admission path) resolved the wrong row
- fix(templates): repaired the two templates that could never pass —
  `test_template_binary.py` indexed the `BinaryCall` dataclass with `c[1]`, and
  `test_template_routing.py` asserted `"BUS"` / `direction="inbound"` against
  recorded `"bus"` / `"in"`. The binary template now covers both the untyped and
  the typed dispatch path, and the bridge-1 template builds its `PolicyChain`
  the way the policies require
- test(templates): the shipped templates are now executed by the suite
  (`tests/test_templates_contract.py`), so a broken template fails CI
- fix(assertions): `assert_acl_enforced(allowed=True)` now also requires a
  `bus_inject` record — "no denial" was also what a never-delivered message
  looked like
- fix(assertions): `assert_ping_responded` now requires the responsive PING.
  There is no PONG in HiveMind: a node answers with its own PING inside a
  PROPAGATE, and a bare PING is not routed at all. PING moved from pending to
  ready
- fix(assertions): `assert_destination_routed` counted the whole inbound
  history of the other satellites as cross-talk. It now looks only at traffic
  from the probe, via a new `since=` mark (`recorder_mark()`); the settle window
  is the `settle=` argument
- fix(assertions): denial correlation reads the `denied_type` key hivemind-core
  actually sends, and a new `strict=True` default rejects untyped denials, so
  `assert_policy_denied(deny_code=...)` can no longer pass on unrelated traffic
- fix(agent): `handle_send` matches `OVOSAgentProtocol` exactly — CASCADE is no
  longer fanned out and QUERY is no longer dropped; both are sent to their
  target peer
- fix(agent): `natural_language_query` defaults to a 10 s timeout and yields the
  `None` escalation sentinel on timeout, matching the `AgentProtocol` contract.
  Pass `raise_on_timeout=True` for the old strict behaviour
- fix(agent): a bus emission that cannot be deserialized is logged at warning
  instead of silently swallowed, and is still forwarded
- feat(agent): `TestAgentProtocol.shutdown()` restores `bus.emit` and removes
  its bus handlers, so `TopologyBuilder.stop_all()`'s shutdown hook does
  something
- fix(node): `MasterNode.create()` no longer takes `**kwargs`, so a misspelled
  option raises `TypeError` instead of silently misconfiguring the node
- fix(node): `wait_for_bus` removes its `once` listener on timeout
- fix(loopback): `stop()` closes client sockets and lets the handlers run their
  cleanup before the loop stops, so no ghost peers stay in
  `hm_protocol.clients`; a thread that will not join marks the protocol broken
  instead of being dropped
- fix(loopback): an undecodable frame is recorded as `_decode_error`, so
  `wait_for()` fails with the cause instead of on timeout
- fix(ovoscope): `shutdown()` unwinds the bus wiring before stopping MiniCroft;
  the capture session exposes `timed_out`; `wait_for_skill_emission` uses
  "at least" semantics at both the poll and the deadline
- fix(pytest_fixtures): only the `topology` fixture tears the topology down —
  the other fixtures used to repeat it two or three times per test
- fix(xdg_isolation): the original XDG variables are restored at the end of the
  session, and variables that were unset are unset again
- fix(topology_plot): relay halves are merged using the builder's `_relays`
  registry instead of `_sat`/`_master` name guessing
- test: added adversarial regression coverage for every fix above plus the gaps
  the test-quality review found — database update semantics, public-API
  disconnect, `stop_all` partial failure, unknown-peer `KeyError`, pre-start
  state, partial FIFO markers, key revocation on a live connection, per-preset
  topology shapes, and `MessageRecorder.clear()` semantics

**Docs:**

**Merged pull requests:**

- docs: rewrite README in Simplified Technical English [\#38](https://github.com/JarbasHiveMind/hivescope/pull/38) ([JarbasAl](https://github.com/JarbasAl))

## [0.6.1a2](https://github.com/JarbasHiveMind/hivescope/tree/0.6.1a2) (2026-07-31)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/0.6.1a1...0.6.1a2)

**Merged pull requests:**

- docs: correct API reference and examples to match code \(Han audit round 1\) [\#35](https://github.com/JarbasHiveMind/hivescope/pull/35) ([JarbasAl](https://github.com/JarbasAl))

## [0.6.1a1](https://github.com/JarbasHiveMind/hivescope/tree/0.6.1a1) (2026-07-31)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/0.6.0a1...0.6.1a1)

**Merged pull requests:**

- fix: Han audit round 1 — concurrency, lifecycle, and assertion correctness [\#33](https://github.com/JarbasHiveMind/hivescope/pull/33) ([JarbasAl](https://github.com/JarbasAl))

## [0.6.0a1](https://github.com/JarbasHiveMind/hivescope/tree/0.6.0a1) (2026-07-16)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/0.5.2a1...0.6.0a1)

**Merged pull requests:**

- feat: auto-isolate XDG dirs for every pytest session [\#31](https://github.com/JarbasHiveMind/hivescope/pull/31) ([JarbasAl](https://github.com/JarbasAl))

## [0.5.2a1](https://github.com/JarbasHiveMind/hivescope/tree/0.5.2a1) (2026-06-23)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/0.5.1a1...0.5.2a1)

**Merged pull requests:**

- fix: floor hivemind-core to the 2.x line \(collapse the consumer prerelease cascade\) [\#28](https://github.com/JarbasHiveMind/hivescope/pull/28) ([JarbasAl](https://github.com/JarbasAl))

## [0.5.1a1](https://github.com/JarbasHiveMind/hivescope/tree/0.5.1a1) (2026-06-23)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/0.5.0a2...0.5.1a1)

**Merged pull requests:**

- fix\(loopback\): drop removed blacklist kwargs \(real-socket handshake hang\) [\#26](https://github.com/JarbasHiveMind/hivescope/pull/26) ([JarbasAl](https://github.com/JarbasAl))

## [0.5.0a2](https://github.com/JarbasHiveMind/hivescope/tree/0.5.0a2) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/0.5.0a1...0.5.0a2)

**Merged pull requests:**

- docs: zero-to-hero README rewrite [\#23](https://github.com/JarbasHiveMind/hivescope/pull/23) ([JarbasAl](https://github.com/JarbasAl))

## [0.5.0a1](https://github.com/JarbasHiveMind/hivescope/tree/0.5.0a1) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/0.4.0a2...0.5.0a1)

**Merged pull requests:**

- feat: TestAgentProtocol.natural\_language\_query [\#21](https://github.com/JarbasHiveMind/hivescope/pull/21) ([JarbasAl](https://github.com/JarbasAl))

## [0.4.0a2](https://github.com/JarbasHiveMind/hivescope/tree/0.4.0a2) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/0.4.0a1...0.4.0a2)

**Merged pull requests:**

- Release 0.4.0a2 [\#20](https://github.com/JarbasHiveMind/hivescope/pull/20) ([github-actions[bot]](https://github.com/apps/github-actions))

## [0.4.0a1](https://github.com/JarbasHiveMind/hivescope/tree/0.4.0a1) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/0.3.0a3...0.4.0a1)

**Merged pull requests:**

- Release 0.4.0a1 [\#19](https://github.com/JarbasHiveMind/hivescope/pull/19) ([github-actions[bot]](https://github.com/apps/github-actions))
- feat: inject a real DB backend into MasterNode \(db=\) [\#18](https://github.com/JarbasHiveMind/hivescope/pull/18) ([JarbasAl](https://github.com/JarbasAl))

## [0.3.0a3](https://github.com/JarbasHiveMind/hivescope/tree/0.3.0a3) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/0.3.0a2...0.3.0a3)

**Merged pull requests:**

- Release 0.3.0a3 [\#17](https://github.com/JarbasHiveMind/hivescope/pull/17) ([github-actions[bot]](https://github.com/apps/github-actions))
- test: XPASS warning + §6 MAY → skip [\#16](https://github.com/JarbasHiveMind/hivescope/pull/16) ([JarbasAl](https://github.com/JarbasAl))

## [0.3.0a2](https://github.com/JarbasHiveMind/hivescope/tree/0.3.0a2) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/0.3.0a1...0.3.0a2)

**Merged pull requests:**

- Release 0.3.0a2 [\#15](https://github.com/JarbasHiveMind/hivescope/pull/15) ([github-actions[bot]](https://github.com/apps/github-actions))

## [0.3.0a1](https://github.com/JarbasHiveMind/hivescope/tree/0.3.0a1) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/0.2.2a2...0.3.0a1)

**Merged pull requests:**

- Release 0.3.0a1 [\#14](https://github.com/JarbasHiveMind/hivescope/pull/14) ([github-actions[bot]](https://github.com/apps/github-actions))
- feat: OVOS-BRIDGE-1 conformance assertions + test suite [\#13](https://github.com/JarbasHiveMind/hivescope/pull/13) ([JarbasAl](https://github.com/JarbasAl))

## [0.2.2a2](https://github.com/JarbasHiveMind/hivescope/tree/0.2.2a2) (2026-06-04)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/0.2.2a1...0.2.2a2)

**Merged pull requests:**

- Release 0.2.2a2 [\#12](https://github.com/JarbasHiveMind/hivescope/pull/12) ([github-actions[bot]](https://github.com/apps/github-actions))

## [0.2.2a1](https://github.com/JarbasHiveMind/hivescope/tree/0.2.2a1) (2026-06-04)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/0.2.1a1...0.2.2a1)

**Merged pull requests:**

- Release 0.2.2a1 [\#11](https://github.com/JarbasHiveMind/hivescope/pull/11) ([github-actions[bot]](https://github.com/apps/github-actions))
- fix: dynamic version from version.py + CodeRabbit follow-ups \(PR\#7\) [\#10](https://github.com/JarbasHiveMind/hivescope/pull/10) ([JarbasAl](https://github.com/JarbasAl))

## [0.2.1a1](https://github.com/JarbasHiveMind/hivescope/tree/0.2.1a1) (2026-06-04)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/0.2.0a2...0.2.1a1)

**Merged pull requests:**

- Release 0.2.1a1 [\#9](https://github.com/JarbasHiveMind/hivescope/pull/9) ([github-actions[bot]](https://github.com/apps/github-actions))
- fix: per-client ACL \(allowed\_types\) now resolves in the harness [\#7](https://github.com/JarbasHiveMind/hivescope/pull/7) ([JarbasAl](https://github.com/JarbasAl))

## [0.2.0a2](https://github.com/JarbasHiveMind/hivescope/tree/0.2.0a2) (2026-06-04)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/0.2.0a1...0.2.0a2)

**Merged pull requests:**

- Release 0.2.0a2 [\#8](https://github.com/JarbasHiveMind/hivescope/pull/8) ([github-actions[bot]](https://github.com/apps/github-actions))

## [0.2.0a1](https://github.com/JarbasHiveMind/hivescope/tree/0.2.0a1) (2026-06-04)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/0.1.0a2...0.2.0a1)

**Merged pull requests:**

- Release 0.2.0a1 [\#6](https://github.com/JarbasHiveMind/hivescope/pull/6) ([github-actions[bot]](https://github.com/apps/github-actions))
- feat: full protocol-matrix coverage — 14 HiveMessageType helpers + tests [\#5](https://github.com/JarbasHiveMind/hivescope/pull/5) ([JarbasAl](https://github.com/JarbasAl))

## [0.1.0a2](https://github.com/JarbasHiveMind/hivescope/tree/0.1.0a2) (2026-05-13)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/e212e8727f6cadccfc1711d294cacc70975f6efe...0.1.0a2)

**Merged pull requests:**

- Release 0.1.0a2 [\#3](https://github.com/JarbasHiveMind/hivescope/pull/3) ([github-actions[bot]](https://github.com/apps/github-actions))
- Configure Renovate [\#1](https://github.com/JarbasHiveMind/hivescope/pull/1) ([renovate[bot]](https://github.com/apps/renovate))



\* *This Changelog was automatically generated by [github_changelog_generator](https://github.com/github-changelog-generator/github-changelog-generator)*
