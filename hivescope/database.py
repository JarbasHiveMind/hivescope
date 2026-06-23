"""
In-memory ClientDatabase that avoids any plugin loading or disk I/O.
Implements the same public interface as hivemind_core.database.ClientDatabase
so it can be passed directly to HiveMindListenerProtocol.
"""
from typing import List, Optional, Iterable

from hivemind_plugin_manager.database import Client


class InMemoryClientDatabase:
    """Drop-in replacement for ClientDatabase backed by a plain dict."""

    def __init__(self):
        self._clients: dict[str, Client] = {}  # keyed by api_key

    # --- write API ---

    def add_client(self,
                   name: str,
                   key: str = "",
                   admin: bool = False,
                   intent_blacklist: Optional[List[str]] = None,
                   skill_blacklist: Optional[List[str]] = None,
                   message_blacklist: Optional[List[str]] = None,
                   allowed_types: Optional[List[str]] = None,
                   crypto_key: Optional[str] = None,
                   password: Optional[str] = None,
                   can_escalate: bool = True,
                   can_propagate: bool = True,
                   can_broadcast: bool = True) -> bool:
        if crypto_key is not None:
            crypto_key = crypto_key[:16]
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
            if crypto_key:
                existing.crypto_key = crypto_key
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

        client = Client(
            api_key=key,
            name=name,
            client_id=self.total_clients() + 1,
            is_admin=admin,
            allowed_types=allowed_types or [],
            crypto_key=crypto_key,
            password=password,
            can_escalate=can_escalate,
            can_propagate=can_propagate,
            can_broadcast=can_broadcast,
            metadata=metadata,
        )
        self._clients[key] = client
        return True

    def update_item(self, client: Client) -> bool:
        self._clients[client.api_key] = client
        return True

    def delete_client(self, key: str) -> bool:
        if key in self._clients:
            # mark revoked (don't reuse client_id)
            c = self._clients[key]
            self._clients[key] = Client(client_id=c.client_id, api_key="revoked")
            return True
        return False

    # --- read API ---

    def get_client_by_api_key(self, api_key: str) -> Optional[Client]:
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
        for c in self._clients.values():
            if getattr(c, "client_id", None) == client_id:
                return c
        return None

    def refresh(self, client_id: int) -> Optional[Client]:
        """Re-read a single client record (mirrors AbstractDB.refresh)."""
        return self.get_client_by_id(client_id)

    def get_clients_by_name(self, name: str) -> List[Client]:
        return [c for c in self._clients.values() if c.name == name]

    def total_clients(self) -> int:
        return len(self._clients)

    # --- lifecycle ---

    def sync(self):
        pass  # nothing to reload from disk

    def __enter__(self):
        return self

    def __exit__(self, _type, value, traceback):
        pass  # nothing to commit

    def __iter__(self) -> Iterable[Client]:
        return iter(list(self._clients.values()))

    def __len__(self) -> int:
        return len(self._clients)
