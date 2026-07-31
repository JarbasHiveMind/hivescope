"""
Helpers for creating test node identities and other small utilities.
"""
import os
import shutil
import tempfile
import threading
from typing import Optional
from uuid import uuid4

from poorman_handshake import HandShake
from hivemind_bus_client.identity import NodeIdentity


class _DictConfig(dict):
    """
    Minimal dict that satisfies NodeIdentity's requirement for a file-like
    config object. Stores everything in memory; path is a throwaway string.
    """
    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def store(self):
        pass

    def reload(self):
        pass

    def merge(self, other: dict):
        self.update(other)


def make_identity(name: str,
                  password: Optional[str] = None,
                  access_key: Optional[str] = None,
                  site_id: Optional[str] = None,
                  tmpdir: Optional[str] = None) -> NodeIdentity:
    """
    Create a NodeIdentity backed by in-memory config (no XDG disk writes).
    Generates a fresh RSA key pair and saves the PEM to a temp file so
    HandShake / poorman_handshake can load it by path.
    """
    owned_tmpdir = None
    if tmpdir is None:
        tmpdir = tempfile.mkdtemp(prefix=f"hivemind_test_{name}_")
        owned_tmpdir = tmpdir

    pem_path = os.path.join(tmpdir, f"{name}.pem")

    # Generate RSA key and save PEM  (HandShake does this for us)
    hs = HandShake(path=pem_path, key_size=2048)  # 2048-bit for test speed; production default is 4096

    cfg = _DictConfig(path=os.path.join(tmpdir, f"{name}_identity.json"))
    identity = NodeIdentity(identity_file=cfg)
    identity.name = name
    identity.access_key = access_key or uuid4().hex
    identity.password = password or uuid4().hex
    identity.site_id = site_id or f"{name}-site"
    identity.private_key = pem_path
    identity.public_key = hs.pubkey

    # Nodes remove this directory when they stop. Only directories this call
    # created are tracked; a caller-supplied tmpdir stays the caller's to clean.
    identity._hivescope_tmpdir = owned_tmpdir

    return identity


def remove_identity_tmpdir(identity) -> None:
    """Remove the temp directory ``make_identity`` created for *identity*."""
    tmpdir = getattr(identity, "_hivescope_tmpdir", None)
    if tmpdir:
        shutil.rmtree(tmpdir, ignore_errors=True)
        identity._hivescope_tmpdir = None


def wait_event(event: threading.Event, timeout: float = 5.0) -> bool:
    """Wait for a threading.Event; return True if set within timeout."""
    return event.wait(timeout=timeout)
