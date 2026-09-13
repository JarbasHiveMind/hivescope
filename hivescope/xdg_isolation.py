"""Auto-isolate XDG dirs for every pytest session that has hivescope installed.

HiveMind identity state — access key, password, TOFU-pinned Noise static
keys — lives in the caller's XDG config dir. A test that builds a bare
``NodeIdentity()`` (or boots a real client/server) therefore reads AND
rewrites the developer's real ``~/.config/hivemind``: pins from throwaway
loopback servers accumulate there and later make a real deployment pick a
``KKpsk0`` resumption against the wrong key.

This plugin redirects ``XDG_CONFIG_HOME`` / ``XDG_DATA_HOME`` /
``XDG_CACHE_HOME`` / ``XDG_STATE_HOME`` to a per-session temp directory, and
puts the previous values back at the end of the session.

It registers via the ``pytest11`` entry point, so simply installing hivescope
protects the session. Note the limit of that hook: entry-point plugins get
``pytest_configure`` *after* the root ``conftest.py`` is imported, so a module
that resolves an XDG path at conftest import time still reads the real one.
Resolve paths inside fixtures or tests, not at import time.

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
    # Remember what was there. Overwriting the process environment without a
    # way back leaks the temp paths into anything that runs after pytest in
    # the same process (a REPL session, a plugin, a second pytest.main call).
    config._hivescope_xdg_saved = {var: os.environ.get(var) for var in _XDG_VARS}
    for var in _XDG_VARS:
        path = os.path.join(root, var.split("_")[1].lower())
        os.makedirs(path, exist_ok=True)
        os.environ[var] = path
    config._hivescope_xdg_root = root


def pytest_unconfigure(config):
    """Restore the original XDG env and remove the per-session directory."""
    saved = getattr(config, "_hivescope_xdg_saved", None)
    if saved is not None:
        for var, value in saved.items():
            if value is None:
                os.environ.pop(var, None)   # it was unset before we ran
            else:
                os.environ[var] = value
        config._hivescope_xdg_saved = None

    root = getattr(config, "_hivescope_xdg_root", None)
    if root:
        shutil.rmtree(root, ignore_errors=True)
        config._hivescope_xdg_root = None
