"""
LoopbackNetworkProtocol — Real WebSocket server routing to in-process HiveMindListenerProtocol.

Unlike TestNetworkProtocol which wires satellites directly to the master's protocol
(no sockets), LoopbackNetworkProtocol starts a real WebSocket server on localhost:0
(random port). Real clients (Python async, JS, etc.) connect via WebSocket, and each
connection is routed through HiveMindClientConnection into the same HiveMindListenerProtocol.

This enables E2E testing of clients without requiring a real hub — the harness acts
as a full hub from the client's perspective.
"""

import asyncio
import base64
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import websockets
import websockets.asyncio.server
from poorman_handshake import PasswordHandShake

from hivemind_plugin_manager.protocols import NetworkProtocol
from hivemind_core.protocol import HiveMindClientConnection, HiveMindNodeType
from ovos_bus_client.session import Session

_LOG = logging.getLogger(__name__)

# run() persists min_protocol_version into the (session-isolated) XDG server
# config — a process-global resource shared by every LoopbackNetworkProtocol
# instance in this interpreter. Two live instances with different floors
# would race to overwrite each other's setting. This registry tracks the
# floor requested by each currently-running instance (keyed by id(), cleared
# in stop()) so run() can detect the conflict and refuse instead of racing.
_LIVE_FLOORS: Dict[int, int] = {}


@dataclass
class LoopbackNetworkProtocol(NetworkProtocol):
    """WebSocket server on localhost:0, routes connections in-process.

    Attributes:
        config: Protocol configuration dict.
        hm_protocol: The HiveMindListenerProtocol to route messages through.
        callbacks: Client callbacks.
        url: Connection URL set after run() starts the server.
             Format: "ws://127.0.0.1:PORT/" where PORT is assigned by OS.
    """
    config: Dict[str, Any] = field(default_factory=dict)
    _url: Optional[str] = field(default=None, init=False, repr=False)
    _server: Optional[Any] = field(default=None, init=False, repr=False)
    _loop: Optional[asyncio.AbstractEventLoop] = field(default=None, init=False, repr=False)
    _thread: Optional[threading.Thread] = field(default=None, init=False, repr=False)
    _clients: List[Any] = field(default_factory=list, init=False, repr=False)
    _ready: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _startup_error: Optional[BaseException] = field(default=None, init=False, repr=False)
    # Live connection handlers and their sockets, so stop() can let their
    # finally blocks (handle_client_disconnected) run before the loop dies.
    _sockets: Set[Any] = field(default_factory=set, init=False, repr=False)
    _handler_tasks: Set[Any] = field(default_factory=set, init=False, repr=False)
    _broken: bool = field(default=False, init=False, repr=False)
    #: Recorder that gets a ``_decode_error`` entry when an inbound frame
    #: cannot be decoded. Set by :meth:`MasterNode.create`.
    recorder: Optional[Any] = field(default=None)
    #: Seconds given to live client handlers to finish during stop().
    shutdown_grace: float = field(default=2.0)
    #: Wire-protocol floor written into the isolated server config before the
    #: server starts. hivemind-core defaults to 2 (HIVEMIND-WIRE-1 §2), which
    #: rejects the plain-JSON password-less clients this harness exists to
    #: test (they top out at v1). Set higher in a test to exercise the floor.
    #:
    #: This value is written into the process-global (session-XDG) server
    #: config, not an instance-local one — hivemind-core reads it from disk
    #: with no per-instance scoping. Because of that, two
    #: ``LoopbackNetworkProtocol`` instances running at the same time MUST
    #: agree on ``min_protocol_version``: whichever wrote last would silently
    #: overwrite the other's floor. ``run()`` raises ``RuntimeError`` instead
    #: of allowing that race — build topologies with a single loopback floor
    #: per test, or run conflicting floors sequentially.
    min_protocol_version: int = field(default=1)

    @property
    def url(self) -> str:
        """Get the WebSocket connection URL after run() starts the server.

        Returns:
            "ws://127.0.0.1:PORT/" where PORT is the OS-assigned random port.

        Raises:
            RuntimeError: If called before run() starts the server.
        """
        if self._url is None:
            raise RuntimeError(
                "LoopbackNetworkProtocol.url not available until after run() "
                "starts the server. Call it after adding the node to the topology."
            )
        return self._url

    def run(self):
        """Start WebSocket server in a daemon thread.

        Creates a real WebSocket server listening on localhost:0 (random port).
        The server runs on its own asyncio event loop in a background daemon thread.
        """
        if self._broken:
            raise RuntimeError(
                "LoopbackNetworkProtocol is broken: a previous stop() could not "
                "join the server thread, so the old event loop and its client "
                "handlers are still alive. Build a new instance."
            )
        if self._thread is not None:
            _LOG.warning("LoopbackNetworkProtocol.run() called but server already running")
            return

        # min_protocol_version is written into a process-global config file
        # (see the field docstring). If another live instance is running
        # with a different floor, writing ours would race it — refuse.
        conflicts = {
            floor for key, floor in _LIVE_FLOORS.items()
            if key != id(self) and floor != self.min_protocol_version
        }
        if conflicts:
            raise RuntimeError(
                "LoopbackNetworkProtocol.run(): another live instance is "
                f"running with min_protocol_version={sorted(conflicts)}, but "
                f"this instance requests {self.min_protocol_version}. "
                "min_protocol_version is written into the process-global "
                "(session-XDG) server config, so concurrent instances with "
                "different floors would race to overwrite each other's "
                "setting. Use the same floor for all concurrently-running "
                "instances, or run them sequentially."
            )

        # Persist the harness protocol floor into the (session-isolated) XDG
        # server config BEFORE handle_new_client() runs its version gate —
        # without this, released hivemind-core (floor 2) silently rejects the
        # raw JSON clients right after they connect and the peer never shows
        # up in hm_protocol.clients.
        try:
            from hivemind_core.config import get_server_config
            cfg = get_server_config()
            if cfg.get("min_protocol_version") != self.min_protocol_version:
                cfg["min_protocol_version"] = self.min_protocol_version
                cfg.store()
        except Exception as e:
            # This fix exists precisely because upstream's config is fragile
            # under this harness's session-isolated XDG setup — warning and
            # continuing here would silently run the test against the wrong
            # floor. Fail loudly instead.
            raise RuntimeError(
                f"LoopbackNetworkProtocol.run(): could not set "
                f"min_protocol_version={self.min_protocol_version} in server "
                f"config: {e}"
            ) from e

        _LIVE_FLOORS[id(self)] = self.min_protocol_version
        self._ready.clear()
        self._startup_error = None

        # Start background thread
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()

        # Wait for the server to bind, or for startup to fail. On failure,
        # mark the instance broken and deregister its floor — leaving
        # `_thread` set would make a retrying `run()` silently no-op on the
        # "already running" guard, hiding the original error behind a later
        # "url not available" complaint far from the cause.
        try:
            if not self._ready.wait(timeout=10):
                raise RuntimeError(
                    "LoopbackNetworkProtocol failed to start server after 10s")
            if self._startup_error is not None:
                raise RuntimeError(
                    "LoopbackNetworkProtocol failed to start server"
                ) from self._startup_error
        except Exception:
            self._broken = True
            _LIVE_FLOORS.pop(id(self), None)
            raise
        _LOG.info(f"LoopbackNetworkProtocol listening at {self._url}")

    def _run_server(self):
        """Background thread: run asyncio WebSocket server.

        Sets up new event loop, starts WebSocket server, runs event loop until stop().
        """
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            # Run the server coroutine and keep it alive
            self._server = self._loop.run_until_complete(self._start_server())
            self._ready.set()
            # Now run the event loop indefinitely (handles incoming connections)
            self._loop.run_forever()
        except Exception as e:
            _LOG.exception(f"LoopbackNetworkProtocol server error: {e}")
            # Record the real cause so run() can re-raise it instead of a
            # generic "failed to start" after the full wait.
            self._startup_error = e
            self._ready.set()
        finally:
            self._shutdown_loop()

    def _shutdown_loop(self):
        """Close the listening socket, drain tasks, then close the loop."""
        server = self._server
        self._server = None
        if server is not None:
            try:
                server.close()
                self._loop.run_until_complete(server.wait_closed())
            except Exception as exc:
                _LOG.warning(f"LoopbackNetworkProtocol: closing server failed: {exc}")
        try:
            pending = [t for t in asyncio.all_tasks(self._loop) if not t.done()]
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(
                    asyncio.wait_for(
                        asyncio.gather(*pending, return_exceptions=True),
                        timeout=5,
                    )
                )
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _LOG.warning("LoopbackNetworkProtocol: pending tasks did not finish in 5s")
        except Exception as exc:
            _LOG.warning(f"LoopbackNetworkProtocol: task cleanup failed: {exc}")
        finally:
            try:
                self._loop.close()
            except Exception as exc:
                _LOG.warning(f"LoopbackNetworkProtocol: closing loop failed: {exc}")
            self._loop = None

    async def _start_server(self):
        """Start and manage the WebSocket server.

        Returns a server object that can be managed from the thread.
        """
        async def handler(websocket):
            """Handle incoming WebSocket connection.

            Note: websockets v11+ changed signature from (websocket, path) to (websocket)
            """
            await self._handle_client(websocket)

        # Start server on localhost:0 (OS assigns port)
        server = await websockets.asyncio.server.serve(
            handler,
            "127.0.0.1",
            0,  # Random OS-assigned port
        )

        # Extract the actual port and set URL
        sockets = server.sockets
        if sockets:
            port = sockets[0].getsockname()[1]
            self._url = f"ws://127.0.0.1:{port}/"
            _LOG.info(f"LoopbackNetworkProtocol server started on {self._url}")

        return server

    async def _handle_client(self, websocket):
        """Handle a single WebSocket client connection.

        Steps:
        1. Extract authorization from query params (base64(name:key))
        2. Look up client in database
        3. Create HiveMindClientConnection with send_msg routed to WebSocket
        4. Call hm_protocol.handle_new_client() → triggers HELLO+SHAKE handshake
        5. On each message: hm_protocol.handle_message()
        6. On close: hm_protocol.handle_client_disconnected()
        """
        if self.hm_protocol is None:
            await websocket.close(code=1011, reason="No HiveMindListenerProtocol configured")
            return

        # Extract authorization from either:
        # 1. Query parameter: ?authorization=base64(name:key) (MicroPython client)
        # 2. Authorization header: Basic base64(name:key) (JS client)

        name = None
        key = None

        # Try query parameter first (MicroPython style)
        try:
            query_string = websocket.request.path.split("?", 1)[1] if "?" in websocket.request.path else ""
            if query_string:
                import urllib.parse
                params = urllib.parse.parse_qs(query_string)
                auth_b64_list = params.get("authorization", [])
                if auth_b64_list:
                    auth_b64 = auth_b64_list[0]
                    auth_decoded = base64.b64decode(auth_b64).decode("utf-8")
                    name, key = auth_decoded.split(":", 1)
                    _LOG.debug(f"Auth from query param: {name}")
        except Exception as e:
            _LOG.debug(f"Query param auth failed: {e}")

        # If query param didn't work, try Authorization header (JS style)
        if not name or not key:
            auth_header = websocket.request.headers.get("Authorization", "")
            if auth_header.startswith("Basic "):
                try:
                    auth_b64 = auth_header.split(" ", 1)[1]
                    auth_decoded = base64.b64decode(auth_b64).decode("utf-8")
                    name, key = auth_decoded.split(":", 1)
                    _LOG.debug(f"Auth from header: {name}")
                except (ValueError, IndexError, UnicodeDecodeError) as e:
                    _LOG.warning(f"Invalid Authorization header: {e}")

        # If still no auth, reject
        if not name or not key:
            await websocket.close(code=1008, reason="Missing or invalid authorization (query param or Authorization header)")
            return

        # Look up client in database
        self.hm_protocol.db.sync()
        db_client = self.hm_protocol.db.get_client_by_api_key(key)
        if db_client is None:
            _LOG.warning(f"Client key '{key}' not found in database")
            await websocket.close(code=4001, reason="Invalid API key")
            return

        # Async queue for crossing the sync/async boundary.
        # sync_send (called from protocol handlers) schedules put via
        # call_soon_threadsafe; message_sender awaits get.
        aqueue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def sync_send(payload: bytes, is_bin: bool = False):
            """Queue a message for the async sender (called from sync protocol code)."""
            loop.call_soon_threadsafe(aqueue.put_nowait, ("message", payload))

        def sync_disconnect(code: int = 1000, reason: str = ""):
            """Signal the async sender to close the WebSocket with this code/reason."""
            loop.call_soon_threadsafe(aqueue.put_nowait, ("disconnect", (code, reason)))

        async def message_sender():
            """Async task: reads from queue and sends to WebSocket."""
            close_code, close_reason = 1000, ""
            try:
                while True:
                    msg_type, payload = await aqueue.get()
                    if msg_type == "message":
                        await websocket.send(payload)
                    elif msg_type == "disconnect":
                        close_code, close_reason = payload
                        break
            except Exception as e:
                _LOG.exception(f"Message sender error for {name}: {e}")
            finally:
                try:
                    await websocket.close(close_code, close_reason)
                except Exception:
                    pass

        # Create the connection object with these callbacks
        conn = HiveMindClientConnection(
            key=key,
            name=name,
            send_msg=sync_send,
            disconnect=sync_disconnect,
            sess=Session(session_id="default"),  # Re-assigned after HELLO from satellite
            hm_protocol=self.hm_protocol,
            # Populate from DB entry
            # crypto_key is no longer a HiveMindClientConnection field under
            # v3-Noise-only — the Noise handshake is the sole transport-crypto
            # layer, so a pre-shared crypto_key is never forwarded to core.
            pswd_handshake=(PasswordHandShake(db_client.password)
                            if db_client.password else None),
            is_admin=db_client.is_admin,
            can_escalate=db_client.can_escalate,
            can_propagate=db_client.can_propagate,
            can_broadcast=db_client.can_broadcast,
            # hivemind-core is whitelist-only now: admission is via allowed_types;
            # the old msg_/skill_/intent_blacklist kwargs were removed from
            # HiveMindClientConnection (skill/intent blacklists live in
            # Client.metadata and are injected by OVOSAgentPolicy).
            allowed_types=list(db_client.allowed_types or []),
            node_type=HiveMindNodeType.NODE,
        )

        # Track this client, its socket and its handler task, so stop() can
        # close it and let this coroutine's finally block run.
        self._clients.append(conn)
        self._sockets.add(websocket)
        handler_task = asyncio.current_task()
        if handler_task is not None:
            self._handler_tasks.add(handler_task)

        try:
            # Start the message sender task (reads from queue, sends to WebSocket)
            sender_task = asyncio.create_task(message_sender())

            # Notify harness of new client — synchronous, triggers HELLO+SHAKE
            self.hm_protocol.handle_new_client(conn)

            # Process incoming messages from WebSocket
            async for message in websocket:
                try:
                    decoded = conn.decode(message)
                    self.hm_protocol.handle_message(decoded, conn)
                except Exception as e:
                    _LOG.warning(f"Failed to decode message from {name}: {e}")
                    # Mirror SatelliteNode._receive_raw: surface the cause in
                    # the recorder so a wait_for() fails with the decode error
                    # instead of burning its whole timeout.
                    if self.recorder is not None:
                        self.recorder.record("in", "_decode_error",
                                             {"error": str(e), "client": name},
                                             conn.peer)

            _LOG.info(f"Client {name} disconnected (WebSocket closed)")

        except websockets.exceptions.ConnectionClosed:
            _LOG.info(f"Client {name} disconnected")
        except Exception as e:
            _LOG.exception(f"Error handling client {name}: {e}")
        finally:
            # Signal the sender task to stop and wait
            aqueue.put_nowait(("disconnect", (1000, "")))
            try:
                if not sender_task.done():
                    await asyncio.wait_for(sender_task, timeout=2)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                if not sender_task.done():
                    sender_task.cancel()

            # Notify harness of disconnection
            self.hm_protocol.handle_client_disconnected(conn)
            try:
                self._clients.remove(conn)
            except ValueError:
                pass  # Already removed or not in list
            self._sockets.discard(websocket)
            if handler_task is not None:
                self._handler_tasks.discard(handler_task)

    async def _drain_clients(self):
        """Close every live client socket and wait for its handler to finish.

        Runs ON the server loop. Each handler's finally block calls
        ``handle_client_disconnected``, which is what removes the peer from
        ``hm_protocol.clients``. Stopping the loop first would skip all of
        that and leave ghost peers behind.
        """
        for websocket in list(self._sockets):
            try:
                await websocket.close()
            except Exception as exc:
                _LOG.warning(f"LoopbackNetworkProtocol: closing client socket failed: {exc}")
        tasks = [t for t in self._handler_tasks if not t.done()]
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=self.shutdown_grace)
            for task in pending:
                _LOG.warning(
                    "LoopbackNetworkProtocol: client handler did not finish in "
                    f"{self.shutdown_grace}s; cancelling it"
                )
                task.cancel()

    def stop(self):
        """Stop the WebSocket server and wait for the thread to finish.

        Live client handlers are given a bounded window to run their cleanup
        before the loop stops. If the thread cannot be joined, the instance is
        marked broken and :meth:`run` refuses to reuse it.
        """
        loop = self._loop
        if loop is not None and not loop.is_closed():
            try:
                future = asyncio.run_coroutine_threadsafe(self._drain_clients(), loop)
                future.result(timeout=self.shutdown_grace + 3)
            except Exception as exc:
                _LOG.warning(f"LoopbackNetworkProtocol: draining clients failed: {exc}")
            # Only now take the loop down.
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass  # loop already closed by its own thread

        if self._thread is not None:
            # Wait for thread to finish (give it time to clean up)
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                _LOG.warning(
                    "LoopbackNetworkProtocol: server thread still alive after 5s; "
                    "the event loop or a client handler did not stop. Marking "
                    "this protocol broken — it cannot be run() again."
                )
                # Keep the thread reference: dropping it would hide a live
                # thread and let run() start a second server on top of it.
                self._broken = True
            else:
                self._thread = None

        self._url = None
        self._ready.clear()
        self._clients.clear()
        self._sockets.clear()
        self._handler_tasks.clear()
        _LIVE_FLOORS.pop(id(self), None)
