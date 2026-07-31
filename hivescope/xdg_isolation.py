"""Auto-isolate XDG dirs for every pytest session that has hivescope installed.

HiveMind identity state — access key, password, TOFU-pinned Noise static
keys — lives in the caller's XDG config dir. A test that builds a bare
``NodeIdentity()`` (or boots a real client/server) therefore reads AND
rewrites the developer's real ``~/.config/hivemind``: pins from throwaway
loopback servers accumulate there and later make a real deployment pick a
``KKpsk0`` resumption against the wrong key.

This plugin redirects ``XDG_CONFIG_HOME`` / ``XDG_DATA_HOME`` /
``XDG_CACHE_HOME`` / ``XDG_STATE_HOME`` to a per-session temp directory
before any test imports resolve paths. It registers via the ``pytest11``
entry point, so simply installing hivescope protects the whole session.

Opt out (e.g. a test that must read the real user config) with::

    HIVESCOPE_NO_XDG_ISOLATION=1 pytest ...
"""
import os
import shutil
import tempfile

_XDG_VARS = ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME")


def pytest_configure(config):
    if os.environ.get("HIVESCOPE_NO_XDG_ISOLATION", "").strip().lower() in ("1", "true", "yes"):
        return
    root = tempfile.mkdtemp(prefix="hivescope-xdg-")
    for var in _XDG_VARS:
        path = os.path.join(root, var.split("_")[1].lower())
        os.makedirs(path, exist_ok=True)
        os.environ[var] = path
    config._hivescope_xdg_root = root


def pytest_unconfigure(config):
    """Remove the per-session XDG directory at the end of the run."""
    root = getattr(config, "_hivescope_xdg_root", None)
    if root:
        shutil.rmtree(root, ignore_errors=True)
        config._hivescope_xdg_root = None
