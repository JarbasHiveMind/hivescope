"""
Pytest fixtures for hivescope e2e tests.

Standard fixtures that can be imported and used in test files:

  @pytest.fixture
  def topology():
      '''TopologyBuilder auto-started and auto-stopped.'''

  @pytest.fixture
  def master_node(topology):
      '''Pre-configured master in a simple topology.'''

  @pytest.fixture
  def satellite_node(master_node, topology):
      '''Pre-configured satellite connected to master.'''

Usage in a test file:

  import pytest
  from hivescope.pytest_fixtures import *  # noqa

  def test_handshake(master_node, satellite_node):
      assert master_node is not None
      assert satellite_node is not None

Or import directly in conftest.py:

  # tests/conftest.py
  pytest_plugins = ['hivescope.pytest_fixtures']
"""

import logging

import pytest
from typing import Optional

from hivescope.topology import TopologyBuilder
from hivescope.node import MasterNode, SatelliteNode
from hivemind_bus_client.identity import NodeIdentity

log = logging.getLogger(__name__)


@pytest.fixture(scope="function")
def topology() -> TopologyBuilder:
    """
    A fresh TopologyBuilder auto-started and auto-stopped.

    Use to build test topologies:

      def test_with_topology(topology):
          m = topology.add_master("M0")
          s = topology.add_satellite("S0", upstream=m)
          topology.start_all()

          # ... assertions ...

          topology.stop_all()  # called auto-magically on fixture teardown
    """
    builder = TopologyBuilder()
    yield builder
    # The topology fixture is the single owner of teardown: every other
    # fixture here builds on it, so a stop_all() in each of them ran the
    # teardown two or three times per test.
    try:
        builder.stop_all()
    except Exception as exc:
        log.warning("topology fixture teardown failed: %s", exc)


@pytest.fixture(scope="function")
def master_node(topology: TopologyBuilder) -> MasterNode:
    """
    A pre-configured master node in a simple single-master topology.

    Started automatically. Teardown belongs to the ``topology`` fixture this
    one depends on, so it is not repeated here.

    Use to test satellite interactions:

      def test_master_receives_message(master_node, topology):
          satellite = topology.add_satellite("S1", upstream=master_node)
          topology.start_all()
          assert satellite.wait_for_handshake(timeout=5)
    """
    m = topology.add_master("M0")
    topology.start_all()
    yield m


@pytest.fixture(scope="function")
def satellite_node(
    master_node: MasterNode,
    topology: TopologyBuilder
) -> SatelliteNode:
    """
    A pre-configured satellite connected and handshook with master_node.

    Automatically started and connected.

    Use to test satellite behavior:

      def test_satellite_sends_message(satellite_node):
          from ovos_bus_client.message import Message
          satellite_node.send(Message("test:message", {"data": "value"}))
    """
    # Credentials come from the satellite's own generated identity; connect()
    # registers them in the master DB together with the permissions below.
    s = topology.add_satellite("S0", upstream=master_node)
    topology.start_all()
    assert s.wait_for_handshake(timeout=10), "satellite_node handshake timed out"

    yield s


@pytest.fixture(scope="function")
def admin_satellite(
    master_node: MasterNode,
    topology: TopologyBuilder
) -> SatelliteNode:
    """
    A pre-configured admin satellite with broadcast/propagate permissions.

    Useful for testing admin-level operations (broadcast, propagate, etc).
    """
    s = topology.add_satellite(
        "S_ADMIN",
        upstream=master_node,
        is_admin=True,
        can_propagate=True,
        can_broadcast=True,
    )
    topology.start_all()
    assert s.wait_for_handshake(timeout=10), "admin_satellite handshake timed out"

    yield s


@pytest.fixture(scope="function")
def restricted_satellite(
    master_node: MasterNode,
    topology: TopologyBuilder
) -> SatelliteNode:
    """
    A pre-configured non-admin satellite with minimal permissions.

    Useful for testing ACL enforcement.
    """
    s = topology.add_satellite(
        "S_RESTRICTED",
        upstream=master_node,
        is_admin=False,
        can_propagate=False,
        can_escalate=False,
        allowed_types=["recognizer_loop:utterance"],
    )
    topology.start_all()
    assert s.wait_for_handshake(timeout=10), "restricted_satellite handshake timed out"

    yield s

