"""Copy this file into your repo's tests/e2e/ and rename.

Verifies that a satellite completes its handshake with a master and that
both sides agree on cipher + encoding.
"""

from hivescope.scenarios import single_satellite
from hivescope.assertions import (
    assert_handshake_complete,
    assert_encryption_match,
)


def test_satellite_completes_handshake():
    builder = single_satellite()
    builder.start_all()
    try:
        master = builder.get_master("M0")
        satellite = builder.get_satellite("S0")
        assert_handshake_complete(master, satellite)
        assert_encryption_match(master, satellite)
    finally:
        builder.stop_all()
