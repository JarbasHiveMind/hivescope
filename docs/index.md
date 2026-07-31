# Hivescope

A self-contained pytest-based E2E testing library for HiveMind protocol implementations.

## Overview

Hivescope provides an in-process simulator for HiveMind network topologies. No real sockets or network processes are required. Tests wire nodes together directly, recording all HiveMessages for inspection.

The entire simulation runtime lives in `hivescope/`: topology builder, node types, protocol plugins, message recorder, in-memory database, assertion helpers, preset scenarios, and pytest fixtures.

## Key Classes

| Class | Purpose | Source |
|---|---|---|
| `TopologyBuilder` | Assembles and lifecycle-manages a test topology | `hivescope/topology.py:92` |
| `MasterNode` | Hub node. Holds database, recorder, HiveMind listener protocol | `hivescope/node.py:98` |
| `SatelliteNode` | Client node. Connects upstream, sends/receives HiveMessages | `hivescope/node.py:223` |
| `RelayNode` | Dual-role node (master downstream, satellite upstream) | `hivescope/topology.py:45` |
| `MessageRecorder` | Records all inbound/outbound HiveMessages for a node | `hivescope/recorder.py:24` |
| `RecordedMessage` | Single recorded message with direction, type, payload, peer, timestamp | `hivescope/recorder.py:13` |
| `InMemoryClientDatabase` | In-memory credential store used instead of a real database | `hivescope/database.py:11` |
| `TestAgentProtocol` | Agent protocol backed by FakeBus (fast, deterministic) | `hivescope/plugins/agent.py` |
| `TestBinaryProtocol` | Binary protocol stub. Records binary messages, no-op processing | `hivescope/plugins/binary.py` |
| `TestNetworkProtocol` | In-process network protocol, no sockets | `hivescope/plugins/network.py` |
| `OvoscopeAgentProtocol` | Agent protocol backed by a live MiniCroft (requires `[ovos]` extra) | `hivescope/plugins/ovoscope_agent.py` |

## TopologyBuilder

`hivescope/topology.py:92`

| Method | Returns | Notes |
|---|---|---|
| `add_master(name, use_loopback=False, **kwargs)` | `MasterNode` | Creates and registers a master |
| `add_satellite(name, upstream, **kwargs)` | `SatelliteNode` | Creates satellite under an upstream master or relay |
| `add_relay(name, upstream, **kwargs)` | `RelayNode` | Dual-role relay. Upstream is a master or another relay |
| `get_master(name)` | `MasterNode` | |
| `get_satellite(name)` | `SatelliteNode` | |
| `get_relay(name)` | `RelayNode` | |
| `start_all()` | `None` | Starts all nodes in dependency order |
| `stop_all()` | `None` | Stops all nodes and releases resources |
| `masters` | `List[MasterNode]` | Property |
| `satellites` | `List[SatelliteNode]` | Property |
| `relays` | `List[RelayNode]` | Property |

## MasterNode

`hivescope/node.py:98`

| Method / Attribute | Notes |
|---|---|
| `register_satellite(key, password, **kwargs)` | Pre-registers a satellite credential before it connects |
| `send_to_satellite(peer, message)` | Send a HiveMessage to a specific connected peer |
| `send_to_all(message)` | Broadcast to all connected peers |
| `emit_on_bus(message)` | Inject an OVOS Message onto the master's FakeBus |
| `wait_for(msg_type, timeout=5)` | Block until a HiveMessage of that type is recorded |
| `connected_peers()` | `List[str]` of currently connected peer identifiers |
| `recorder` | `MessageRecorder` for all inbound/outbound HiveMessages |
| `db` | `InMemoryClientDatabase` |

## SatelliteNode

`hivescope/node.py:223`

| Method / Attribute | Notes |
|---|---|
| `connect(master, is_admin=False, can_escalate=True, can_propagate=True, can_broadcast=True, allowed_types=None, msg_blacklist=None, skill_blacklist=None, intent_blacklist=None)` | Connects to a MasterNode and runs the handshake synchronously. Raises `RuntimeError` if the handshake does not complete. There is no `timeout` kwarg. To wait for a handshake that completes asynchronously (loopback mode), use `wait_for_handshake(timeout)` below |
| `wait_for_handshake(timeout=5.0)` | Blocks until the handshake completes. Returns `True` if it did, `False` on timeout |
| `disconnect()` | Disconnect cleanly |
| `send(message)` | Send a `HiveMessage` or `Message` upstream |
| `wait_for(msg_type, timeout=5)` | Block until a HiveMessage of that type is recorded |
| `wait_for_bus(ovos_type, timeout=5)` | Block until an OVOS bus Message is received |
| `peer` | This satellite's peer identifier (set after handshake) |
| `recorder` | `MessageRecorder` for all inbound/outbound HiveMessages |
| `shim.crypto_key` | Negotiated session key (set after handshake). Lives on the `InProcessHiveShim`, not directly on `SatelliteNode` |

## RelayNode

`hivescope/topology.py:45`

A thin wrapper that holds both a `MasterNode` (`.hm_protocol`) and a `SatelliteNode` (`.slave_protocol`). Constructed by `TopologyBuilder.add_relay()`. Access via `builder.get_relay(name)`.

## MessageRecorder

`hivescope/recorder.py:24`

| Method | Notes |
|---|---|
| `record(direction, msg_type, payload, peer)` | Called internally by node instrumentation |
| `wait_for(msg_type, direction=None, timeout=5)` | Blocks until message found. Returns the `RecordedMessage`, or `None` on timeout |
| `assert_received(msg_type, count=1, direction=None)` | Raises `AssertionError` if count does not match |
| `assert_not_received(msg_type, direction=None)` | Raises `AssertionError` if message was seen |
| `received(msg_type, direction=None)` | `List[RecordedMessage]`, all matching records (empty list if none) |
| `clear()` | Reset all recorded messages |

`RecordedMessage` attributes: `direction` (`"in"`, `"out"`, or `"bus_inject"`), `msg_type`, `payload`, `peer`, `timestamp`.

## InMemoryClientDatabase

`hivescope/database.py:11`

Implements the HiveMind client database interface backed by a plain dict. `MasterNode` uses it automatically. You can also use it standalone.

| Method | Notes |
|---|---|
| `add_client(name, key="", admin=False, ..., password=None, ...)` | Register a new client credential. The 3rd positional argument is `admin`, not `password`. `password` is much further down the signature. Pass it as a keyword (`password="..."`) or it silently lands in `admin` and registers the client as an admin |
| `get_client_by_api_key(api_key)` | Look up a `Client` by key |
| `delete_client(key)` | Remove a credential |
| `total_clients()` | Count of registered clients |

## Assertion Helpers

`hivescope/assertions.py`. All functions below are exported from `hivescope.assertions`. Most are also re-exported from `hivescope` directly (see `__all__`).

### Core / generic

| Function | Notes |
|---|---|
| `assert_message_routed(node, msg_type, count=1, direction=None, timeout=2.0)` | Waits (up to `timeout`) then asserts the recorded count matches |
| `assert_message_received_by(node, msg_type, count=1)` | Shorthand for `assert_message_routed(..., direction="in")` |
| `assert_message_sent_by(node, msg_type, count=1)` | Shorthand for `assert_message_routed(..., direction="out")` |
| `assert_client_registered(master, peer)` | Asserts `peer` is in master's live `connected_peers()`, not a database lookup |
| `assert_client_not_registered(master, peer)` | Asserts `peer` is absent from `connected_peers()` |

### Type-specific (implemented message types)

| Function | Notes |
|---|---|
| `assert_handshake_complete(master, satellite, timeout=5)` | Verifies `satellite.shim.crypto_key` is set, the handshake event fired, and the satellite is in `connected_peers()` |
| `assert_encryption_match(master, satellite)` | Verifies cipher and encoding agree between master and satellite |
| `assert_hello_received(master, count=1)` | Asserts master recorded `count` inbound HELLO announcements |
| `assert_bus_message_routed(master, count=1)` | Asserts `count` BUS messages reached the master's agent bus |
| `assert_shared_bus_received(node, count=1, direction=None)` | Asserts `node` recorded `count` SHARED_BUS messages |
| `assert_broadcast_delivered(*recipients, count=1, inner_msg_type=None)` | Asserts every node in `recipients` received the broadcast. Core unwraps BROADCAST into its inner type, so this counts inbound payload messages unless `inner_msg_type` narrows it |
| `assert_broadcast_blocked(node)` | Asserts `node` received no BROADCAST (ACL-blocked case) |
| `assert_propagate_delivered(*recipients, count=1)` | Asserts every node in `recipients` recorded `count` inbound PROPAGATE messages |
| `assert_escalate_delivered(master, count=1)` | Asserts master received `count` inbound ESCALATE messages |
| `assert_intercom_delivered(recipient, count=1)` | Asserts `recipient` satellite received `count` inbound INTERCOM messages |
| `assert_binary_delivered(master, expected_payload=None, count=1)` | Asserts master received `count` BINARY messages. If `expected_payload` is given, also checks it was delivered |
| `assert_query_routed(master, count=1)` | PENDING: QUERY routing not yet in hivemind-core ([core#74](https://github.com/JarbasHiveMind/HiveMind-core/pull/74) / [ws#88](https://github.com/JarbasHiveMind/hivemind-websocket-client/pull/88)). Use with `@pytest.mark.xfail(strict=False)` |
| `assert_cascade_routed(*nodes, count=1)` | PENDING: CASCADE routing not yet in hivemind-core (core#74 / ws#88), xfail |
| `assert_ping_responded(master, satellite)` | PING round-trip. There is no PONG: the answer is the node's own PING inside a PROPAGATE. Send `PROPAGATE(PING)`; a bare PING is dropped by core |
| `assert_rendezvous_handled(master, count=1)` | PENDING: RENDEZVOUS not yet implemented ([ws#103](https://github.com/JarbasHiveMind/hivemind-websocket-client/pull/103)), xfail |
| `assert_thirdparty_passed(node, count=1, direction=None)` | Asserts `count` THIRDPRTY (user-land passthrough) messages at `node`. Verify routing status against `LIBRARY.md` before relying on this |

### OVOS-BRIDGE-1 / SESSION-1 conformance

| Function | Notes |
|---|---|
| `assert_msg1_envelope(master, msg_type, count=1)` | BRIDGE-1 §2: every bus-injected message of `msg_type` has a non-empty `msg_type` and a `context` dict |
| `assert_source_stamped(master, satellite, other_satellites=None)` | BRIDGE-1 §3.1: inbound bus messages from `satellite` carry a stable, non-empty `context.source`. If `other_satellites` is given, their sources must differ |
| `assert_destination_routed(master, target_satellite, other_satellites, msg_type, timeout=2.0)` | BRIDGE-1 §3.2: an outbound message reaches only `target_satellite`, never `other_satellites` |
| `assert_session_inbound_preserved(master, satellite, expected_session)` | BRIDGE-1 §4.1 (inbound): the satellite's session lands unchanged in the bus-injected message's `context.session` |
| `assert_session_outbound_preserved(satellite, expected_session, timeout=2.0)` | BRIDGE-1 §4.1 (outbound): a bus-originated session reaches the satellite unchanged |
| `assert_fifo_order(master, satellite, msg_type, count, timeout=5.0)` | BRIDGE-1 §5: `count` sequential messages from `satellite` arrive in send order. Requires the sender to stamp a monotonically increasing `data["_fifo_seq"]` on each message |
| `assert_session_propagated_unchanged(master, field, value, msg_type=None)` | SESSION-1 §4: every bus-injected message (optionally filtered by `msg_type`) has `context.session[field] == value` |
| `assert_source_hidden(satellite, generic_id="hive", msg_type=None, timeout=2.0)` | BRIDGE-1 §6 (optional): outbound `context.source` is overwritten with `generic_id` instead of an internal peer address |

### Policy / session (ACL enforcement)

| Function | Notes |
|---|---|
| `assert_acl_enforced(master, satellite, msg_type, allowed=False)` | Fully implemented ACL enforcement check. `allowed=False` (default) verifies the satellite received a `hive.policy.denied` response. `allowed=True` verifies the message was recorded at master's `bus_inject` level |
| `assert_policy_denied(master, satellite, msg_type, deny_code=None)` | Asserts `satellite` received a `hive.policy.denied` response for `msg_type`. If `deny_code` is given, checks the denial carries that stable code (e.g. `"acl_disallowed_type"`) |
| `assert_session_blacklists_injected(master, satellite, msg_type, expected_skills=None, expected_intents=None)` | Asserts the policy chain injected the expected `blacklisted_skills` / `blacklisted_intents` into the session of a bus-injected message |

## Preset Scenarios

`hivescope/scenarios.py`

All functions return a fully wired (not yet started) `TopologyBuilder`.

| Function | Topology |
|---|---|
| `single_satellite()` | 1 master `M0`, 1 satellite `S0` |
| `three_satellites()` | 1 master `M0`, satellites `S0`–`S2` |
| `with_relay()` | 1 master `M0`, 1 relay `R0`, satellites under relay |
| `chain_topology()` | Master → relay → satellites |
| `star_topology(num_satellites=5)` | Central master, N satellites |
| `with_acl_enforcement()` | Master with ACL-restricted and admin satellites |
| `hierarchical_hubs(num_levels=3, sats_per_relay=2)` | Deeply nested relay tree |
| `with_multiple_agent_protocols()` | Master configured with custom protocol set |

## Pytest Fixtures

`hivescope/pytest_fixtures.py`: enable with `pytest_plugins = ['hivescope.pytest_fixtures']` in `conftest.py`.

| Fixture | Yields | Scope |
|---|---|---|
| `topology` | `TopologyBuilder` (started, auto-stopped) | function |
| `master_node` | `MasterNode` in a started single-master topology (no satellite attached) | function |
| `satellite_node` | `SatelliteNode` connected to `master_node` | function |
| `admin_satellite` | Satellite with full permissions | function |
| `restricted_satellite` | Satellite with ACL restrictions | function |

## Templates

`templates/` contains ten ready-to-copy test files. Drop them into `tests/e2e/` and rename:

| File | Tests |
|---|---|
| `test_template_handshake.py` | Handshake completion, cipher/encoding agreement |
| `test_template_routing.py` | Message routing through master |
| `test_template_acl.py` | ACL enforcement: `allowed_types` denial and skill-blacklist injection |
| `test_template_binary.py` | Binary protocol message handling |
| `test_template_bridge1.py` | OVOS-BRIDGE-1 / SESSION-1 / SESSION-2 conformance: source stamping, destination routing, session fidelity, FIFO order |
| `test_template_cascade.py` | CASCADE routing, pending core support ([core#74](https://github.com/JarbasHiveMind/HiveMind-core/pull/74) / [ws#88](https://github.com/JarbasHiveMind/hivemind-websocket-client/pull/88)), marked xfail |
| `test_template_ping.py` | PING network-map round-trip: send `PROPAGATE(PING)` and assert the responsive PING |
| `test_template_query.py` | QUERY routing, pending core support (core#74 / ws#88), marked xfail |
| `test_template_rendezvous.py` | RENDEZVOUS handling, pending ([ws#103](https://github.com/JarbasHiveMind/hivemind-websocket-client/pull/103)), marked xfail |
| `test_template_thirdparty.py` | THIRDPRTY (user-land) passthrough routing |

## Contents

- [Installation & Quick Start](../README.md)
- [Assertion Helpers](#assertion-helpers)
- [Preset Scenarios](#preset-scenarios)
- [Pytest Fixtures](#pytest-fixtures)
- [Templates](#templates)
