# Changelog

## [0.6.2a1](https://github.com/JarbasHiveMind/hivescope/tree/0.6.2a1) (2026-07-31)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/0.6.1a3...0.6.2a1)

**Merged pull requests:**

- fix: Han audit round 2 — regression fix, template repairs, assertion honesty, agent fidelity [\#37](https://github.com/JarbasHiveMind/hivescope/pull/37) ([JarbasAl](https://github.com/JarbasAl))

## Unreleased

**Han audit round 3:**

- fix(loopback): `LoopbackNetworkProtocol.run()` writes `min_protocol_version`
  into the process-global (session-XDG) server config. Two live instances
  with different floors used to race to overwrite each other's setting;
  `run()` now raises `RuntimeError` when it detects a live instance with a
  conflicting floor, and the field docstring documents the constraint
- fix(loopback): a failed `min_protocol_version` config write used to log a
  warning and continue, silently running the test against the wrong floor.
  `run()` now raises instead — this fix exists specifically to counter
  upstream config fragility, so swallowing the failure defeated the point
- fix(assertions): `assert_ping_responded` now takes `since=` (the
  `recorder_mark()` pattern already used by `assert_destination_routed`) and
  correlates the responsive PING by `flood_id` when the probe payload carries
  one, so a second back-to-back probe can no longer pass on the first
  probe's leftover response
- fix(assertions): `_denied_records` (and therefore `assert_acl_enforced` /
  `assert_policy_denied`) now raises `ValueError` when called with a
  `HiveMessageType` value (`"bus"`, `"escalate"`, ...) instead of the OVOS
  message type that was actually denied (`"speak"`) — the two were silently
  interchangeable before and a caller passing the wrong one always failed to
  correlate
- docs(README): the ACL enforcement example asserted
  `recorder.assert_not_received("bus")`, but the recorder logs inbound
  traffic *before* policy runs, so the record exists whether or not the
  message was denied. The example now asserts `assert_policy_denied`, the
  signal that actually reflects enforcement
- docs(LIBRARY): the three `pip install` examples pointed at
  `hivescope@master`; the active branch is `dev`, matching the README
- docs(database): the `InMemoryClientDatabase` lock docstring overstated its
  guarantee ("every access takes the lock"). Scoped it to what it actually
  protects — the dict and the id counter — returned `Client` objects are
  shared and not internally synchronized

## [0.6.1a3](https://github.com/JarbasHiveMind/hivescope/tree/0.6.1a3) (2026-07-31)

[Full Changelog](https://github.com/JarbasHiveMind/hivescope/compare/0.6.1a2...0.6.1a3)

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
