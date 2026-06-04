# hivescope — Protocol Matrix & API Reference

Consumer install:

```bash
pip install "hivescope @ git+https://github.com/JarbasHiveMind/hivescope@master"
```

---

## Protocol-matrix coverage

14 `HiveMessageType` values, each with an assertion helper and a copy-paste template.

| Message type | Value | Assertion helper | Template | Status |
|---|---|---|---|---|
| HANDSHAKE | `shake` | `assert_handshake_complete`, `assert_encryption_match` | `test_template_handshake.py` | **ready** |
| HELLO | `hello` | `assert_hello_received` | `test_template_handshake.py` | **ready** |
| BUS | `bus` | `assert_bus_message_routed` | `test_template_routing.py` | **ready** |
| SHARED_BUS | `shared_bus` | `assert_shared_bus_received` | `test_template_routing.py` | **ready** |
| BROADCAST | `broadcast` | `assert_broadcast_delivered`, `assert_broadcast_blocked` | `test_template_acl.py` | **ready** |
| PROPAGATE | `propagate` | `assert_propagate_delivered` | `test_template_routing.py` | **ready** |
| ESCALATE | `escalate` | `assert_escalate_delivered` | `test_template_routing.py` | **ready** |
| INTERCOM | `intercom` | `assert_intercom_delivered` | `test_template_routing.py` | **ready** |
| BINARY | `bin` | `assert_binary_delivered` | `test_template_binary.py` | **ready** |
| QUERY | `query` | `assert_query_routed` | `test_template_query.py` | **pending** — [core#74](https://github.com/JarbasHiveMind/HiveMind-core/pull/74) / [ws#88](https://github.com/JarbasHiveMind/hivemind-websocket-client/pull/88) |
| CASCADE | `cascade` | `assert_cascade_routed` | `test_template_cascade.py` | **pending** — [core#74](https://github.com/JarbasHiveMind/HiveMind-core/pull/74) / [ws#88](https://github.com/JarbasHiveMind/hivemind-websocket-client/pull/88) |
| PING | `ping` | `assert_ping_responded` | `test_template_ping.py` | **pending (partial)** — [core#74](https://github.com/JarbasHiveMind/HiveMind-core/pull/74) |
| RENDEZVOUS | `rendezvous` | `assert_rendezvous_handled` | `test_template_rendezvous.py` | **pending** — [ws#103](https://github.com/JarbasHiveMind/hivemind-websocket-client/pull/103) |
| THIRDPRTY | `3rdparty` | `assert_thirdparty_passed` | `test_template_thirdparty.py` | **verify** — passthrough; routing status TBD |

Pending tests are decorated `@pytest.mark.xfail(strict=False)` — they will show
as `xfail` (expected failures) rather than errors. When the referenced PR lands,
remove the `xfail` marker and implement the response-assertion.

---

## Quick-start: adding `tests/e2e/` to your repo

**5 minutes to your first protocol test.**

### 1. Install hivescope

```bash
pip install "hivescope @ git+https://github.com/JarbasHiveMind/hivescope@master"
```

Or add to your `pyproject.toml` test deps:

```toml
[project.optional-dependencies]
test = [
    "hivescope @ git+https://github.com/JarbasHiveMind/hivescope@master",
    "pytest>=7.4",
]
```

### 2. Create `tests/e2e/conftest.py`

```python
# tests/e2e/conftest.py
pytest_plugins = ['hivescope.pytest_fixtures']
```

This registers the `topology`, `master_node`, `satellite_node`, `admin_satellite`,
and `restricted_satellite` fixtures automatically.

### 3. Copy a template

```bash
cp $(python -c "import hivescope, os; print(os.path.dirname(hivescope.__file__) + '/../templates/test_template_handshake.py')") \
   tests/e2e/test_handshake.py
```

Or copy any template from the
[`templates/`](https://github.com/JarbasHiveMind/hivescope/tree/master/templates)
directory.

### 4. Run

```bash
pytest tests/e2e/ -q
```

### 5. Write your own test

```python
from hivescope.scenarios import single_satellite
from hivescope.assertions import assert_handshake_complete, assert_bus_message_routed

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message


def test_my_feature():
    b = single_satellite()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        assert_handshake_complete(m, s)

        s.send(HiveMessage(
            HiveMessageType.BUS,
            payload=Message("my.feature:request", {"key": "value"}),
        ))

        assert_bus_message_routed(m, count=1)
    finally:
        b.stop_all()
```

---

## Full public API

All symbols are importable from `hivescope` directly:

```python
from hivescope import (
    # Topology
    TopologyBuilder, MasterNode, SatelliteNode, RelayNode,
    # Plugins
    TestAgentProtocol, TestBinaryProtocol, TestNetworkProtocol,
    LoopbackNetworkProtocol,  # real WebSocket on localhost:0
    OvoscopeAgentProtocol,   # requires ``ovos`` extra
    # Recording
    MessageRecorder, RecordedMessage,
    # Database
    InMemoryClientDatabase,
    # Assertion helpers
    assert_handshake_complete, assert_encryption_match,
    assert_message_routed, assert_message_received_by, assert_message_sent_by,
    assert_client_registered, assert_client_not_registered,
    assert_acl_enforced,
    assert_bus_message_routed, assert_hello_received,
    assert_broadcast_delivered, assert_broadcast_blocked,
    assert_propagate_delivered, assert_escalate_delivered,
    assert_binary_delivered,
    # Scenario builders
    single_satellite, admin_satellite, three_satellites,
    with_relay, chain_topology, star_topology,
    with_acl_enforcement, hierarchical_hubs, with_multiple_agent_protocols,
)
```

Type-specific pending helpers live in `hivescope.assertions`:

```python
from hivescope.assertions import (
    assert_intercom_delivered, assert_shared_bus_received,
    assert_query_routed, assert_cascade_routed,
    assert_ping_responded, assert_rendezvous_handled, assert_thirdparty_passed,
)
```

Pytest fixtures — register in `conftest.py`:

```python
pytest_plugins = ['hivescope.pytest_fixtures']
# Fixtures: topology, master_node, satellite_node, admin_satellite, restricted_satellite
```

---

## Pending cells — what to do when PRs land

| PR | Type | Action |
|---|---|---|
| [hivemind-core#74](https://github.com/JarbasHiveMind/HiveMind-core/pull/74) | QUERY, CASCADE, PING | Remove `xfail` in templates + tests; implement response assertions |
| [hivemind-websocket-client#88](https://github.com/JarbasHiveMind/hivemind-websocket-client/pull/88) | QUERY, CASCADE | Remove `xfail` in templates + tests |
| [hivemind-websocket-client#103](https://github.com/JarbasHiveMind/hivemind-websocket-client/pull/103) | RENDEZVOUS | Remove `xfail`; add rendezvous-node fixture to topology |
| THIRDPRTY verify | THIRDPRTY | Run test; if passes, remove xfail; if not routed, add xfail with issue ref |
