"""
Hivescope: E2E Testing Library for HiveMind

A reusable pytest-based framework for writing end-to-end tests of HiveMind
protocol implementations. Provides stable APIs for topology simulation,
message routing verification, and protocol-level assertions.

Public API — stable across versions:

Topology:
  - TopologyBuilder: builder for test network topologies
  - MasterNode, SatelliteNode, RelayNode: network node types

Protocol plugins:
  - TestAgentProtocol: FakeBus-backed agent plugin (fast, deterministic)
  - TestBinaryProtocol: binary data handler stub
  - TestNetworkProtocol: in-process network protocol stub
  - LoopbackNetworkProtocol: real WebSocket on localhost:0 (external clients)
  - OvoscopeAgentProtocol: MiniCroft-backed agent (requires ``ovos`` extra)

Message recording:
  - MessageRecorder, RecordedMessage: per-node traffic capture + blocking wait

Database:
  - InMemoryClientDatabase: in-memory credential store (no disk I/O)

Assertion helpers (also importable from hivescope.assertions):
  - assert_handshake_complete
  - assert_encryption_match
  - assert_message_routed
  - assert_message_received_by
  - assert_message_sent_by
  - assert_client_registered
  - assert_client_not_registered
  - assert_acl_enforced

Scenario builders (also importable from hivescope.scenarios):
  - single_satellite, admin_satellite, three_satellites
  - with_relay, chain_topology, star_topology
  - with_acl_enforcement, hierarchical_hubs, with_multiple_agent_protocols

Pytest fixtures (register via conftest.py):
  pytest_plugins = ['hivescope.pytest_fixtures']

Consumer install:
  pip install "hivescope @ git+https://github.com/JarbasHiveMind/hivescope@master"

Quick example:

  from hivescope import TopologyBuilder
  from hivescope.scenarios import single_satellite
  from hivescope.assertions import assert_handshake_complete

  def test_handshake():
      b = single_satellite()
      b.start_all()
      try:
          assert_handshake_complete(b.get_master("M0"), b.get_satellite("S0"))
      finally:
          b.stop_all()
"""

from hivescope.topology import TopologyBuilder
from hivescope.node import MasterNode, SatelliteNode
from hivescope.topology import RelayNode
from hivescope.recorder import MessageRecorder, RecordedMessage
from hivescope.database import InMemoryClientDatabase
from hivescope.plugins.agent import TestAgentProtocol
from hivescope.plugins.binary import TestBinaryProtocol
from hivescope.plugins.network import TestNetworkProtocol

# Optional: requires real websockets dep (always present per pyproject.toml)
try:
    from hivescope.plugins.loopback import LoopbackNetworkProtocol
except ImportError:
    LoopbackNetworkProtocol = None  # type: ignore[assignment,misc]

# Optional: OvoscopeAgentProtocol requires ovoscope+ovos-core (``ovos`` extra)
try:
    from hivescope.plugins.ovoscope_agent import OvoscopeAgentProtocol
except ImportError:
    OvoscopeAgentProtocol = None  # type: ignore[assignment,misc]

# Assertion helpers — re-exported for convenience
from hivescope.assertions import (
    assert_handshake_complete,
    assert_encryption_match,
    assert_message_routed,
    assert_message_received_by,
    assert_message_sent_by,
    assert_client_registered,
    assert_client_not_registered,
    assert_acl_enforced,
    assert_policy_denied,
    assert_session_blacklists_injected,
    # type-specific ready helpers
    assert_hello_received,
    assert_bus_message_routed,
    assert_shared_bus_received,
    assert_broadcast_delivered,
    assert_broadcast_blocked,
    assert_propagate_delivered,
    assert_escalate_delivered,
    assert_intercom_delivered,
    assert_binary_delivered,
)

# Scenario builders — re-exported for convenience
from hivescope.scenarios import (
    single_satellite,
    admin_satellite,
    three_satellites,
    with_relay,
    chain_topology,
    star_topology,
    with_acl_enforcement,
    hierarchical_hubs,
    with_multiple_agent_protocols,
)

from hivescope.version import __version__

__all__ = [
    # --- topology ---
    "TopologyBuilder",
    "MasterNode",
    "SatelliteNode",
    "RelayNode",
    # --- plugins ---
    "TestAgentProtocol",
    "TestBinaryProtocol",
    "TestNetworkProtocol",
    "LoopbackNetworkProtocol",
    "OvoscopeAgentProtocol",
    # --- recording ---
    "MessageRecorder",
    "RecordedMessage",
    # --- database ---
    "InMemoryClientDatabase",
    # --- assertion helpers ---
    "assert_handshake_complete",
    "assert_encryption_match",
    "assert_message_routed",
    "assert_message_received_by",
    "assert_message_sent_by",
    "assert_client_registered",
    "assert_client_not_registered",
    "assert_acl_enforced",
    "assert_policy_denied",
    "assert_session_blacklists_injected",
    "assert_hello_received",
    "assert_bus_message_routed",
    "assert_shared_bus_received",
    "assert_broadcast_delivered",
    "assert_broadcast_blocked",
    "assert_propagate_delivered",
    "assert_escalate_delivered",
    "assert_intercom_delivered",
    "assert_binary_delivered",
    # --- scenario builders ---
    "single_satellite",
    "admin_satellite",
    "three_satellites",
    "with_relay",
    "chain_topology",
    "star_topology",
    "with_acl_enforcement",
    "hierarchical_hubs",
    "with_multiple_agent_protocols",
]
