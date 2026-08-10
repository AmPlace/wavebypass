from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from .errors import PluginError, invalid_response
from .protocol import PROTOCOL_VERSION, encode_frame, read_frame


logger = logging.getLogger("waveflow.plugin_runtime")


class PluginProcess:
    def __init__(self, command: Sequence[str], instance_id: str, *,
                 on_exit: Callable[[int | None], Awaitable[None]] | None = None,
                 lifecycle_timeout: float = 30.0):
        self.command = tuple(command)
        self.instance_id = instance_id
        self.on_exit = on_exit
        self.lifecycle_timeout = lifecycle_timeout
        self.process: asyncio.subprocess.Process | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._completed: set[str] = set()
        self._completed_order: deque[str] = deque()
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._wait_task: asyncio.Task | None = None
        self._write_lock = asyncio.Lock()
        self._stopping = False
        self.protocol_violations = 0
        self.stderr_lines: list[str] = []
        self.exit_code: int | None = None

    async def start(self) -> None:
        if self.process is not None:
            raise PluginError("PLUGIN_UNAVAILABLE", "Plugin process is already running", category="lifecycle")
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (OSError, ValueError) as exc:
            raise PluginError("PLUGIN_UNAVAILABLE", "Unable to start plugin process", retryable=True,
                              category="lifecycle") from exc
        self._reader_task = asyncio.create_task(self._reader_loop(), name=f"plugin-reader:{self.instance_id}")
        self._stderr_task = asyncio.create_task(self._stderr_loop(), name=f"plugin-stderr:{self.instance_id}")
        self._wait_task = asyncio.create_task(self._wait_loop(), name=f"plugin-wait:{self.instance_id}")

    async def _send(self, payload: dict[str, Any]) -> None:
        process = self.process
        if process is None or process.stdin is None or process.returncode is not None:
            raise PluginError("PLUGIN_CRASHED", "Plugin process is not running", retryable=True, category="lifecycle")
        frame = encode_frame(payload)
        try:
            async with self._write_lock:
                process.stdin.write(frame)
                await process.stdin.drain()
        except (BrokenPipeError, ConnectionError) as exc:
            raise PluginError("PLUGIN_CRASHED", "Plugin process closed its protocol stream", retryable=True,
                              category="lifecycle") from exc

    async def call(self, method: str, payload: dict[str, Any], *, timeout: float = 15.0,
                   context: dict[str, Any] | None = None, request_id: str | None = None) -> Any:
        if self._stopping and method != "runtime.shutdown":
            raise PluginError("PLUGIN_UNAVAILABLE", "Plugin is stopping", retryable=True, category="lifecycle")
        request_id = request_id or uuid.uuid4().hex
        if request_id in self._pending or request_id in self._completed:
            raise invalid_response("Plugin request_id is not unique")
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[request_id] = future
        envelope = {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "method": method,
            "plugin_instance": self.instance_id,
            "deadline_unix_ms": int((time.time() + timeout) * 1000),
            "context": dict(context or {}),
            "payload": dict(payload),
        }
        try:
            await self._send(envelope)
            try:
                response = await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
            except asyncio.CancelledError:
                self._pending.pop(request_id, None)
                self._remember_completed(request_id)
                if not future.done():
                    future.cancel()
                await self.cancel(request_id)
                raise
            except asyncio.TimeoutError as exc:
                self._pending.pop(request_id, None)
                self._remember_completed(request_id)
                if not future.done():
                    future.cancel()
                await self.cancel(request_id)
                raise PluginError("PLUGIN_TIMEOUT", "Plugin request timed out", retryable=True,
                                  category="timeout", details={"method": method}) from exc
        except BaseException:
            self._pending.pop(request_id, None)
            raise
        self._remember_completed(request_id)
        if response.get("status") == "error":
            error = response.get("error") if isinstance(response.get("error"), dict) else {}
            raise PluginError(str(error.get("code") or "INVALID_PLUGIN_RESPONSE"),
                              str(error.get("message") or "Plugin request failed"),
                              retryable=bool(error.get("retryable")), category=str(error.get("category") or "plugin"),
                              details=error.get("details") if isinstance(error.get("details"), dict) else {})
        return response.get("result")

    async def cancel(self, request_id: str) -> None:
        envelope = {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": uuid.uuid4().hex,
            "method": "runtime.cancel",
            "plugin_instance": self.instance_id,
            "deadline_unix_ms": int((time.time() + 1.0) * 1000),
            "context": {},
            "payload": {"request_id": request_id},
        }
        try:
            await self._send(envelope)
        except PluginError:
            pass

    async def _reader_loop(self) -> None:
        assert self.process and self.process.stdout
        try:
            while True:
                response = await read_frame(self.process.stdout)
                if response.get("protocol_version") != PROTOCOL_VERSION:
                    raise invalid_response("Plugin response protocol version mismatch")
                request_id = response.get("request_id")
                if not isinstance(request_id, str):
                    raise invalid_response("Plugin response request_id is invalid")
                future = self._pending.pop(request_id, None)
                if future is None or future.done():
                    self.protocol_violations += 1
                    continue
                if response.get("status") not in {"ok", "error"}:
                    future.set_exception(invalid_response())
                    continue
                future.set_result(response)
        except asyncio.CancelledError:
            raise
        except PluginError as exc:
            self.protocol_violations += 1
            process = self.process
            if process is not None and (process.returncode is not None or process.stdout.at_eof()):
                self._fail_pending(PluginError("PLUGIN_CRASHED", "Plugin process closed its protocol stream",
                                               retryable=True, category="lifecycle"))
            else:
                self._fail_pending(exc)
                # A malformed frame makes correlation impossible. Treat the protocol stream as fatal;
                # the wait monitor will remove active routing through the normal crash path.
                if process is not None and process.returncode is None:
                    process.kill()

    async def _stderr_loop(self) -> None:
        assert self.process and self.process.stderr
        while True:
            line = await self.process.stderr.readline()
            if not line:
                return
            text = line.decode("utf-8", "replace").strip()
            sanitized = text[:500].replace("Authorization", "[redacted-header]").replace("Cookie", "[redacted-header]")
            self.stderr_lines.append(sanitized)
            self.stderr_lines[:] = self.stderr_lines[-100:]

    async def _wait_loop(self) -> None:
        assert self.process
        self.exit_code = await self.process.wait()
        if not self._stopping:
            self._fail_pending(PluginError("PLUGIN_CRASHED", "Plugin process exited unexpectedly", retryable=True,
                                           category="lifecycle"))
            if self.on_exit:
                await self.on_exit(self.exit_code)

    def _fail_pending(self, exc: PluginError) -> None:
        pending, self._pending = self._pending, {}
        for future in pending.values():
            if not future.done():
                future.set_exception(exc)

    def _remember_completed(self, request_id: str) -> None:
        if request_id in self._completed:
            return
        self._completed.add(request_id)
        self._completed_order.append(request_id)
        while len(self._completed_order) > 4096:
            self._completed.discard(self._completed_order.popleft())

    async def stop(self, *, graceful: bool = True) -> None:
        process = self.process
        if process is None:
            return
        self._stopping = True
        if graceful and process.returncode is None:
            try:
                await self.call("runtime.shutdown", {}, timeout=min(self.lifecycle_timeout, 2.0))
            except PluginError:
                pass
        if process.stdin and not process.stdin.is_closing():
            process.stdin.close()
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=self.lifecycle_timeout)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        self.exit_code = process.returncode
        self._fail_pending(PluginError("PLUGIN_UNAVAILABLE", "Plugin process stopped", category="lifecycle"))
        current = asyncio.current_task()
        for task in (self._reader_task, self._stderr_task, self._wait_task):
            if task and task is not current and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (self._reader_task, self._stderr_task, self._wait_task)
                               if task and task is not current), return_exceptions=True)
