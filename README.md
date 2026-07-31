[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/JarbasHiveMind/hivescope)

# Hivescope

> Pytest E2E testing library for HiveMind protocol implementations.

Hivescope provides an in-process simulator for HiveMind network topologies. It needs no
real sockets, no running servers, and no network processes. Tests wire `MasterNode`,
`SatelliteNode`, and `RelayNode` objects together directly. The library records every
`HiveMessage` for inspection.

Used by [hivemind-core](https://github.com/JarbasHiveMind/HiveMind-core) e2e tests and
by [hivemind-test-harness](https://github.com/JarbasHiveMind/hivemind-test-harness) for
multi-repo topology and stress scenarios.

---

## Install

```bash
pip install "hivescope @ git+https://github.com/JarbasHiveMind/hivescope@dev"
```

With OVOS skill-level testing (live MiniCroft backend):

```bash
pip install "hivescope[ovos] @ git+https://github.com/JarbasHiveMind/hivescope@dev"
```

---

## Quick Start

### Minimal handshake test

```python
from hivescope.scenarios import single_satellite
from hivescope.assertions import assert_handshake_complete, assert_encryption_match

def test_handshake():
    builder = single_satellite()
    builder.start_all()
    try:
        master = builder.get_master("M0")
        satellite = builder.get_satellite("S0")
        assert_handshake_complete(master, satellite)
        assert_encryption_match(master, satellite)
    finally:
        builder.stop_all()
```

### Using pytest fixtures

Add to your repo's `tests/conftest.py`:

```python
pytest_plugins = ['hivescope.pytest_fixtures']
```

Then use the provided fixtures in tests:

```python
def test_message_forwarded(master_node, satellite_node):
    from ovos_bus_client.message import Message
    satellite_node.send(Message("test:ping", {}))
    master_node.recorder.assert_received("bus", count=1)
```

### ACL enforcement test

```python
def test_acl_denied(master_node, restricted_satellite):
    from ovos_bus_client.message import Message
    restricted_satellite.send(Message("admin:command", {}))
    master_node.recorder.assert_not_received("bus")
```

---

## Key Concepts

### TopologyBuilder

Assembles and lifecycle-manages a test topology. All `add_*` methods return the created
node. `start_all()` and `stop_all()` start and stop all nodes in dependency order.

```python
builder = TopologyBuilder()
master = builder.add_master("M0")
sat0 = builder.add_satellite("S0", upstream=master)
relay = builder.add_relay("R0", upstream=master)
sat1 = builder.add_satellite("S1", upstream=relay)
builder.start_all()
# ... run tests ...
builder.stop_all()
```

### Preset Scenarios

`hivescope.scenarios` provides pre-wired topologies for common patterns:

| Function | Topology |
|---|---|
| `single_satellite()` | 1 master `M0`, 1 satellite `S0` |
| `three_satellites()` | 1 master `M0`, satellites `S0` to `S2` |
| `with_relay()` | master → relay → satellites |
| `chain_topology()` | linear relay chain |
| `star_topology(n=5)` | central master, N satellites |
| `with_acl_enforcement()` | master with ACL-restricted and admin satellites |
| `hierarchical_hubs(levels=3, sats=2)` | deeply nested relay tree |

All functions return a **not-yet-started** `TopologyBuilder`. Call `.start_all()` before
testing and `.stop_all()` in a `finally` block (or use the pytest fixtures for automatic teardown).

### MessageRecorder

Every node has a `.recorder` that captures all inbound and outbound `HiveMessage`s.

```python
# Assert a BUS message was received exactly once
master_node.recorder.assert_received("bus", count=1)

# Assert it was NOT received
master_node.recorder.assert_not_received("propagate")

# Block until a message arrives; returns the RecordedMessage, or None on timeout
master_node.wait_for("shake", timeout=5)

# For a test that should fail on timeout, use assert_received instead:
master_node.recorder.assert_received("shake", count=1)

# Inspect recorded messages
for msg in master_node.recorder.messages:
    print(msg.direction, msg.msg_type, msg.peer)
```

---

## Pytest Fixtures

Enable in `conftest.py`: `pytest_plugins = ['hivescope.pytest_fixtures']`

| Fixture | Scope | Yields |
|---|---|---|
| `topology` | function | Started `TopologyBuilder` (auto-stopped) |
| `master_node` | function | `MasterNode` in a started single-master topology (no satellite attached) |
| `satellite_node` | function | `SatelliteNode` connected to `master_node` |
| `admin_satellite` | function | Satellite with full permissions |
| `restricted_satellite` | function | Satellite with ACL restrictions |

---

## Copy-Paste Templates

`templates/` contains ready-to-copy test files. Drop them into `tests/e2e/` in your repo:

| Template | Tests |
|---|---|
| `test_template_handshake.py` | Cipher/encoding agreement, handshake completion |
| `test_template_routing.py` | Message routing through master |
| `test_template_acl.py` | ACL enforcement: `allowed_types` denial and skill-blacklist injection |
| `test_template_binary.py` | Binary protocol message handling |
| `test_template_bridge1.py` | OVOS-BRIDGE-1 / SESSION-1 conformance: source stamping, destination routing, session fidelity, FIFO order |
| `test_template_cascade.py` | CASCADE routing, pending core support, marked xfail |
| `test_template_ping.py` | PING network-map round-trip: send `PROPAGATE(PING)`, assert the responsive PING |
| `test_template_query.py` | QUERY routing, pending core support, marked xfail |
| `test_template_rendezvous.py` | RENDEZVOUS handling, pending, marked xfail |
| `test_template_thirdparty.py` | THIRDPRTY (user-land) passthrough routing |

See [docs/index.md](docs/index.md#templates) for tracking links on the pending items.

---

## Configuration

| Option | Default | Purpose |
|---|---|---|
| `use_loopback=True` | `False` | Pass to `add_master()` to use a loopback network transport instead of the default in-process transport |
| `[ovos]` extra | not installed | Enables `OvoscopeAgentProtocol` backed by a live MiniCroft instance |

---

## API Reference

Full public API documentation: [docs/index.md](docs/index.md)

---

## License

AGPL-3.0
