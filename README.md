# Hivescope

A self-contained pytest-based E2E testing library for HiveMind protocol implementations.

## Install

```bash
pip install "hivescope @ git+https://github.com/JarbasHiveMind/hivescope@dev"
```

With OVOS skill-level testing support:

```bash
pip install "hivescope[ovos] @ git+https://github.com/JarbasHiveMind/hivescope@dev"
```

## Quick Start

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

Using pytest fixtures (add to `tests/conftest.py`):

```python
pytest_plugins = ['hivescope.pytest_fixtures']
```

```python
def test_message_forwarded(master_node, satellite_node):
    from ovos_bus_client.message import Message
    satellite_node.send(Message("test:ping", {}))
    master_node.recorder.assert_received("BUS", count=1)
```

## Templates

Copy-paste test templates from `templates/` into your repo's `tests/e2e/`:

| Template | Covers |
|---|---|
| `test_template_handshake.py` | Cipher/encoding agreement, handshake completion |
| `test_template_routing.py` | Message routing through master |
| `test_template_acl.py` | ACL enforcement for restricted satellites |
| `test_template_binary.py` | Binary protocol message handling |

## Configuration

| Key | Default | Purpose |
|---|---|---|
| `use_loopback` | `False` | Pass `True` to `add_master()` to use loopback network protocol instead of in-process |
| `[ovos]` extra | not installed | Enables `OvoscopeAgentProtocol` backed by a live MiniCroft |

## API Reference

See [docs/index.md](docs/index.md) for the full public API.

## License

AGPL-3.0
