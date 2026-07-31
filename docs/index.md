# Hivescope

A self-contained pytest-based E2E testing library for HiveMind protocol implementations.

## Overview

Hivescope provides an in-process simulator for HiveMind network topologies. No real sockets or network processes are required. Tests wire nodes together directly, recording all HiveMessages for inspection.

The entire simulation runtime lives in `hivescope/`: topology builder, node types, protocol plugins, message recorder, in-memory database, assertion helpers, preset scenarios, and pytest fixtures.

## Key Classes

| Class | Purpose | Source |
|---|---|---|
| `TopologyBuilder` | Assembles and lifecycle-manages a test topology | `hivescope/topology.py:92` |
| `MasterNode` | Hub node; holds database, recorder, HiveMind listener protocol | `hivescope/node.py:98` |
| `SatelliteNode` | Client node; connects upstream, sends/receives HiveMessages | `hivescope/node.py:223` |
| `RelayNode` | Dual-role node (master downstream, satellite upstream) | `hivescope/topology.py:45` |
| `MessageRecorder` | Records all inbound/outbound HiveMessages for a node | `hivescope/recorder.py:24` |
| `RecordedMessage` | Single recorded message with direction, type, payload, peer, timestamp | `hivescope/recorder.py:13` |
| `InMemoryClientDatabase` | In-memory credential store used instead of a real database | `hivescope/database.py:11` |
| `TestAgentProtocol` | Agent protocol backed by FakeBus (fast, deterministic) | `hivescope/plugins/agent.py` |
| `TestBinaryProtocol` | Binary protocol stub; records binary messages, no-op processing | `hivescope/plugins/binary.py` |
| `TestNetworkProtocol` | In-process network protocol; no sockets | `hivescope/plugins/network.py` |
| `OvoscopeAgentProtocol` | Agent protocol backed by a live MiniCroft (requires `[ovos]` extra) | `hivescope/plugins/ovoscope_agent.py` |

## TopologyBuilder

`hivescope/topology.py:92`

| Method | Returns | Notes |
|---|---|---|
| `add_master(name, use_loopback=False, **kwargs)` | `MasterNode` | Creates and registers a master |
| `add_satellite(name, upstream, **kwargs)` | `SatelliteNode` | Creates satellite under an upstream master or relay |
| `add_relay(name, upstream, **kwargs)` | `RelayNode` | Dual-role relay; upstream is a master or another relay |
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
| `database` | `InMemoryClientDatabase` |

## SatelliteNode

`hivescope/node.py:223`

| Method / Attribute | Notes |
|---|---|
| `connect(master, timeout=10)` | Connect to a MasterNode and perform handshake |
| `disconnect()` | Disconnect cleanly |
| `send(message)` | Send a `HiveMessage` or `Message` upstream |
| `wait_for(msg_type, timeout=5)` | Block until a HiveMessage of that type is recorded |
| `wait_for_bus(ovos_type, timeout=5)` | Block until an OVOS bus Message is received |
| `peer` | This satellite's peer identifier (set after handshake) |
| `recorder` | `MessageRecorder` for all inbound/outbound HiveMessages |
| `crypto_key` | Negotiated session key (set after handshake) |

## RelayNode

`hivescope/topology.py:45`

A thin wrapper that holds both a `MasterNode` (`.hm_protocol`) and a `SatelliteNode` (`.slave_protocol`). Constructed by `TopologyBuilder.add_relay()`. Access via `builder.get_relay(name)`.

## MessageRecorder

`hivescope/recorder.py:24`

| Method | Notes |
|---|---|
| `record(direction, msg_type, payload, peer)` | Called internally by node instrumentation |
| `wait_for(msg_type, direction=None, timeout=5)` | Block until message found; raises `TimeoutError` |
| `assert_received(msg_type, count=1, direction=None)` | Raises `AssertionError` if count does not match |
| `assert_not_received(msg_type, direction=None)` | Raises `AssertionError` if message was seen |
| `received(msg_type, direction=None)` | `bool` — whether at least one matching message exists |
| `clear()` | Reset all recorded messages |

`RecordedMessage` attributes: `direction` (`"inbound"` or `"outbound"`), `msg_type`, `payload`, `peer`, `timestamp`.

## InMemoryClientDatabase

`hivescope/database.py:11`

Implements the HiveMind client database interface backed by a plain dict. Used automatically by `MasterNode`; also usable standalone.

| Method | Notes |
|---|---|
| `add_client(name, key, password, **kwargs)` | Register a new client credential |
| `get_client_by_api_key(api_key)` | Look up a `Client` by key |
| `delete_client(key)` | Remove a credential |
| `total_clients()` | Count of registered clients |

## Assertion Helpers

`hivescope/assertions.py`

| Function | Notes |
|---|---|
| `assert_handshake_complete(master, satellite, timeout=5)` | Verifies crypto_key set on both sides and satellite is in connected_peers |
| `assert_encryption_match(master, satellite)` | Verifies cipher and encoding agree between master and satellite |
| `assert_message_routed(node, msg_type, count, direction=None, timeout=5)` | Waits then checks recorder count |
| `assert_acl_enforced(master, satellite, msg_type, allowed=False)` | ACL enforcement check (placeholder for full policy testing) |
| `assert_client_registered(master, peer)` | Asserts peer is in master's database |
| `assert_client_not_registered(master, peer)` | Asserts peer is absent from master's database |
| `assert_message_received_by(node, msg_type, count=1)` | Shorthand for inbound direction check |
| `assert_message_sent_by(node, msg_type, count=1)` | Shorthand for outbound direction check |

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

`hivescope/pytest_fixtures.py` — enable with `pytest_plugins = ['hivescope.pytest_fixtures']` in `conftest.py`.

| Fixture | Yields | Scope |
|---|---|---|
| `topology` | `TopologyBuilder` (started, auto-stopped) | function |
| `master_node` | `MasterNode` in a started topology | function |
| `satellite_node` | `SatelliteNode` connected to `master_node` | function |
| `admin_satellite` | Satellite with full permissions | function |
| `restricted_satellite` | Satellite with ACL restrictions | function |

## Templates

`templates/` contains four ready-to-copy test files. Drop them into `tests/e2e/` and rename:

| File | Tests |
|---|---|
| `test_template_handshake.py` | Handshake completion, cipher/encoding agreement |
| `test_template_routing.py` | Message routing through master |
| `test_template_acl.py` | ACL enforcement for restricted vs admin satellites |
| `test_template_binary.py` | Binary protocol message handling |

## Contents

- [Installation & Quick Start](../README.md)
- [Assertion Helpers](#assertion-helpers)
- [Preset Scenarios](#preset-scenarios)
- [Pytest Fixtures](#pytest-fixtures)
- [Templates](#templates)
