"""
In-memory ClientDatabase that avoids any plugin loading or disk I/O.
Implements the same public interface as hivemind_core.database.ClientDatabase
so it can be passed directly to HiveMindListenerProtocol.
"""
import threading
from typing import List, Optional, Iterable

from hivemind_plugin_manager.database import Client


class InMemoryClientDatabase:
    """Drop-in replacement for ClientDatabase backed by a plain dict."""

    def __init__(self):
        self._clients: dict[str, Client] = {}  # keyed by api_key
        # Monotonic client_id source. It must NOT be derived from the size of
        # the dict: delete_client() really removes rows, so `len + 1` reuses a
        # live id after a delete-then-add and makes get_client_by_id ambiguous
        # (the TTL cache refresh on the admission hot path then resolves the
        # wrong client).
        self._next_id: int = 0
        # The loopback event loop reads this store from its own thread while
        # the test thread writes it, so every access to ``_clients`` and
        # ``_next_id`` takes the lock. The lock protects the dict and the id
        # counter only: it is released before a Client object is returned, so
        # concurrent callers can get the same Client instance back and mutate
        # it without synchronization. Treat returned Client objects as
        # read-mostly, or synchronize their mutation yourself.
        self._lock = threading.RLock()

    # --- write API ---

    def add_client(self,
                   name: str,
                   key: str = "",
                   admin: bool = False,
                   intent_blacklist: Optional[List[str]] = None,
                   skill_blacklist: Optional[List[str]] = None,
                   message_blacklist: Optional[List[str]] = None,
                   allowed_types: Optional[List[str]] = None,
                   password: Optional[str] = None,
                   can_escalate: bool = True,
                   can_propagate: bool = True,
                   can_broadcast: bool = True) -> bool:
        """Add a client, or update the client that already holds ``key``.

        Field semantics on update (they match hivemind-core's ClientDatabase):

        - An empty ``password`` is IGNORED, not cleared. Use
          :meth:`update_item` with an explicit ``Client`` to clear it.
        - ``allowed_types`` is overwritten whenever it is not ``None``, so
          passing ``[]`` really does revoke a previous whitelist.
        """
        with self._lock:
            return self._add_client_locked(
                name, key, admin, intent_blacklist, skill_blacklist,
                message_blacklist, allowed_types, password,
                can_escalate, can_propagate, can_broadcast)

    def _add_client_locked(self, name, key, admin, intent_blacklist,
                           skill_blacklist, message_blacklist, allowed_types,
                           password, can_escalate, can_propagate,
                           can_broadcast) -> bool:
        existing = self.get_client_by_api_key(key)
        if existing:
            if name:
                existing.name = name
            if intent_blacklist is not None:
                if intent_blacklist:
                    existing.metadata["intent_blacklist"] = list(intent_blacklist)
                else:
                    existing.metadata.pop("intent_blacklist", None)
            if skill_blacklist is not None:
                if skill_blacklist:
                    existing.metadata["skill_blacklist"] = list(skill_blacklist)
                else:
                    existing.metadata.pop("skill_blacklist", None)
            # message_blacklist is removed from the data model (hivemind-core is
            # whitelist-only via allowed_types); accepted for API compat, ignored.
            if allowed_types is not None:
                existing.allowed_types = allowed_types
            existing.is_admin = admin
            if password:
                existing.password = password
            existing.can_escalate = can_escalate
            existing.can_propagate = can_propagate
            existing.can_broadcast = can_broadcast
            self._clients[key] = existing
            return True

        # Per-client OVOS ACL blacklists live in Client.metadata now; the old
        # top-level skill_/intent_blacklist kwargs are deprecated and
        # message_blacklist is removed (hivemind-core is whitelist-only).
        metadata = {}
        if skill_blacklist:
            metadata["skill_blacklist"] = list(skill_blacklist)
        if intent_blacklist:
            metadata["intent_blacklist"] = list(intent_blacklist)

        self._next_id += 1
        client = Client(
            api_key=key,
            name=name,
            client_id=self._next_id,
            is_admin=admin,
            allowed_types=allowed_types or [],
            password=password,
            can_escalate=can_escalate,
            can_propagate=can_propagate,
            can_broadcast=can_broadcast,
            metadata=metadata,
        )
        self._clients[key] = client
        return True

    def update_item(self, client: Client) -> bool:
        with self._lock:
            self._clients[client.api_key] = client
        return True

    def delete_client(self, key: str) -> bool:
        """Revoke a key: the entry is removed, so later lookups return None."""
        with self._lock:
            if key in self._clients:
                del self._clients[key]
                return True
        return False

    # --- read API ---

    def get_client_by_api_key(self, api_key: str) -> Optional[Client]:
        with self._lock:
            return self._clients.get(api_key)

    def get_client_by_id(self, client_id: int) -> Optional[Client]:
        """Look a client up by its numeric ``client_id``.

        Part of the ClientDatabase read API: ``resolve_user`` on the
        admission hot path caches the resolved row and, once its TTL
        lapses, re-reads it via ``client_id`` (``refresh`` → this method).
        Without it the cached re-lookup raises and the policy chain fails
        closed with POLICY_ERROR, so the *second* message a satellite
        sends on a long-lived connection (e.g. a second utterance ~16 s
        after the first) is denied "user lookup failed".
        """
        with self._lock:
            clients = list(self._clients.values())
        for c in clients:
            if getattr(c, "client_id", None) == client_id:
                return c
        return None

    def refresh(self, client_id: int) -> Optional[Client]:
        """Re-read a single client record (mirrors AbstractDB.refresh)."""
        return self.get_client_by_id(client_id)

    def get_clients_by_name(self, name: str) -> List[Client]:
        with self._lock:
            return [c for c in self._clients.values() if c.name == name]

    def total_clients(self) -> int:
        with self._lock:
            return len(self._clients)

    # --- lifecycle ---

    def sync(self):
        pass  # nothing to reload from disk

    def __enter__(self):
        return self

    def __exit__(self, _type, value, traceback):
        pass  # nothing to commit

    def __iter__(self) -> Iterable[Client]:
        with self._lock:
            return iter(list(self._clients.values()))

    def __len__(self) -> int:
        with self._lock:
            return len(self._clients)
