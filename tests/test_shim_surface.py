"""The shim stands in for a real client, so it must expose that surface.

``InProcessHiveShim`` is a duck type: ``HiveMindSlaveProtocol`` accepts
anything implementing the ``HiveMessageBusClient`` surface, and nothing
checks that the shim keeps up. When the client moved its credentials off the
node identity onto the client, ``password`` joined that surface — every
in-repo client grew the property, the shim did not, and the whole handshake
path raised ``AttributeError: 'InProcessHiveShim' object has no attribute
'password'`` against the newer client while passing against the older one.

The required names are listed here explicitly rather than derived from the
client class. Deriving them would make this test agree with whatever the
installed client happens to expose, which is exactly the agreement that
failed to catch the last change.
"""
import pytest

from hivescope.node import InProcessHiveShim, SatelliteNode

# Read by HiveMindSlaveProtocol during connect, handshake and emit.
REQUIRED_ATTRS = {
    "identity",
    "emitter",
    "crypto_key",
    "cipher",
    "json_encoding",
    "handshake_event",
    "session_id",
    "site_id",
    "useragent",
    "password",
}


@pytest.fixture
def shim():
    return SatelliteNode.create("surface-probe").shim


def test_the_shim_exposes_everything_the_protocol_reads(shim):
    missing = sorted(a for a in REQUIRED_ATTRS if not hasattr(shim, a))
    assert not missing, (
        f"InProcessHiveShim is missing {missing}; HiveMindSlaveProtocol reads "
        "these off the client it is given, so the handshake raises rather "
        "than negotiating"
    )


def test_the_password_is_the_one_the_link_uses(shim):
    """Not merely present: the value has to be the link's own password, or
    the protocol silently decides the encrypted handshake is unavailable."""
    shim.identity.password = "link-password"

    assert shim.password == "link-password"


def test_a_satellite_without_a_password_reports_none_rather_than_raising(shim):
    """RSA-only mode is a supported configuration: no password is a value,
    not an error, and the protocol branches on it."""
    shim.identity.password = None

    assert shim.password is None
