# Changelog

## [Unreleased]

**Docs:**

- docs: correct API reference and examples to match code (Han audit round 1) — fixed
  `wait_for()` return-value documentation, lowercase `HiveMessageType` values in
  quick-start examples, `master_node` fixture wording, `SatelliteNode.connect()`
  signature, `satellite.shim.crypto_key` location, `MasterNode.db` attribute name,
  `MessageRecorder.received()` return type, recorded-message direction values,
  `InMemoryClientDatabase.add_client()` signature, the full list of 10 templates,
  moved `assert_intercom_delivered`/`assert_shared_bus_received` out of the pending
  list, corrected `assert_acl_enforced`/`assert_client_registered` descriptions, and
  expanded the assertion-helper table to cover all public helpers
- fix(scenarios): `with_multiple_agent_protocols()` now accepts an optional
  `agent_protocol` keyword, matching its documented intent

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
