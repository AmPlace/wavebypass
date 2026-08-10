from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from .errors import PluginError, invalid_response
from .manifest import PluginManifest
from .permissions import PermissionGate, PermissionPolicy
from .process import PluginProcess
from .registry import LifecycleState, PluginInstance, PluginRegistry
from .validation import validate_station_ref, validate_stream_descriptor


class PluginRuntime:
    def __init__(self, *, registry: PluginRegistry | None = None, permission_policy: PermissionPolicy | None = None,
                 clock: Callable[[], float] | None = None,
                 sleep: Callable[[float], Awaitable[None]] | None = None,
                 restart_window: float = 600.0, max_starts: int = 3,
                 capability_dispatcher: Any | None = None):
        self.registry = registry or PluginRegistry()
        self.permission_policy = permission_policy or PermissionPolicy()
        self.clock = clock or time.monotonic
        self.sleep = sleep or asyncio.sleep
        self.restart_window = restart_window
        self.max_starts = max_starts
        self.capability_dispatcher = capability_dispatcher
        self._commands: dict[str, tuple[str, ...]] = {}
        self._gates: dict[str, PermissionGate] = {}
        self._closed = False

    def install(self, manifest: PluginManifest, command: Sequence[str], *, instance_id: str | None = None) -> PluginInstance:
        instance = PluginInstance(instance_id or str(uuid.uuid4()), manifest)
        self.registry.install(instance)
        self._commands[instance.instance_id] = tuple(command)
        self._gates[instance.instance_id] = PermissionGate(manifest, self.permission_policy)
        return instance

    async def enable(self, instance: PluginInstance, *, activate: bool = True) -> None:
        if self._closed:
            raise PluginError("PLUGIN_UNAVAILABLE", "Plugin runtime is shutting down", category="lifecycle")
        if instance.state == LifecycleState.QUARANTINED:
            raise PluginError("PLUGIN_QUARANTINED", "Plugin is quarantined", category="lifecycle")
        instance.transition(LifecycleState.STARTING)
        self._record_start(instance)
        async def dispatch(method: str, payload: dict[str, Any], timeout: float, context: dict[str, Any]) -> Any:
            if self.capability_dispatcher is None:
                raise PluginError("CAPABILITY_DENIED", "Core capabilities are unavailable", category="permission")
            return await self.capability_dispatcher.dispatch(
                instance.manifest.identity, self._gates[instance.instance_id], method, payload,
                timeout=timeout, context=context,
            )
        process = PluginProcess(self._commands[instance.instance_id], instance.instance_id,
                                on_exit=lambda code: self._on_exit(instance, code), capability_handler=dispatch)
        instance.process = process
        try:
            await process.start()
            instance.transition(LifecycleState.HANDSHAKING)
            hello = await process.call("runtime.hello", {
                "core_protocol_versions": ["1.1", "1.0"],
                "manifest_identity": instance.manifest.identity,
            }, timeout=5.0)
            self._validate_hello(instance, hello)
            process.negotiate_protocol(str(hello["protocol_version"]))
            health = await process.call("runtime.health", {}, timeout=5.0)
            if not isinstance(health, dict) or health.get("healthy") is not True:
                raise invalid_response("Plugin health check failed")
            if activate:
                self.registry.activate(instance)
        except BaseException:
            await process.stop(graceful=False)
            self.registry.mark_unhealthy(instance)
            raise

    def _validate_hello(self, instance: PluginInstance, hello: Any) -> None:
        if not isinstance(hello, dict) or hello.get("plugin") != instance.manifest.identity or hello.get("version") != instance.manifest.version:
            raise invalid_response("Plugin hello identity/version mismatch")
        if hello.get("protocol_version") not in {"1.0", "1.1"}:
            raise PluginError("PLUGIN_INCOMPATIBLE", "Plugin protocol version is incompatible", category="compatibility")
        declared_contracts = {(c.contract, c.contract_version): c.features for c in instance.manifest.provider_contracts}
        claimed_contracts: dict[tuple[str, str], set[str]] = {}
        for item in hello.get("provider_contracts", []):
            if not isinstance(item, dict):
                raise invalid_response("Plugin hello contains invalid contracts")
            key = (item.get("contract"), item.get("contract_version"))
            features = item.get("features")
            if key not in declared_contracts or not isinstance(features, list) or not set(features).issubset(declared_contracts[key]):
                raise invalid_response("Plugin hello exceeds declared contracts")
            claimed_contracts[key] = set(features)
        if set(claimed_contracts) != set(declared_contracts):
            raise invalid_response("Plugin hello omits a declared contract")
        claimed_schemes = {(v.get("scheme"), v.get("contract")) for v in hello.get("owned_schemes", []) if isinstance(v, dict)}
        if claimed_schemes != set(instance.manifest.owned_schemes):
            raise invalid_response("Plugin hello scheme declaration mismatch")
        capabilities = hello.get("capabilities")
        if not isinstance(capabilities, list) or not set(capabilities).issubset(instance.manifest.capabilities):
            raise invalid_response("Plugin hello exceeds declared capabilities")
        self._gates[instance.instance_id].validate_hello(hello.get("permissions", []))

    async def request(self, instance: PluginInstance, method: str, payload: dict[str, Any], *, timeout: float = 15.0) -> Any:
        if instance.state == LifecycleState.QUARANTINED:
            raise PluginError("PLUGIN_QUARANTINED", "Plugin is quarantined", category="lifecycle")
        if instance.state != LifecycleState.HEALTHY_ACTIVE or not instance.process:
            raise PluginError("PLUGIN_UNAVAILABLE", "Plugin is unavailable", retryable=True, category="lifecycle")
        result = await instance.process.call(method, payload, timeout=timeout)
        if method in {"tv.resolve_stream", "radio.resolve_stream"}:
            return validate_stream_descriptor(result)
        if method == "radio.catalog":
            if not isinstance(result, dict) or not isinstance(result.get("stations"), list):
                raise invalid_response("Invalid Radio catalog")
            stations = []
            seen: set[tuple[str, str]] = set()
            for station in result["stations"]:
                if not isinstance(station, dict):
                    raise invalid_response("Invalid Radio catalog station")
                ref = validate_station_ref(station.get("station_ref"))
                identity = (ref["provider_key"], ref["provider_station_id"])
                if identity in seen:
                    raise invalid_response("Duplicate StationRef identity")
                seen.add(identity)
                stations.append(dict(station))
            return {**result, "stations": stations}
        return result

    async def disable(self, instance: PluginInstance) -> None:
        if instance.state == LifecycleState.HEALTHY_ACTIVE:
            instance.transition(LifecycleState.DRAINING)
            self.registry.unregister(instance)
            instance.transition(LifecycleState.STOPPING)
        elif instance.state == LifecycleState.UNHEALTHY:
            instance.transition(LifecycleState.STOPPING)
        else:
            raise PluginError("PLUGIN_UNAVAILABLE", "Plugin cannot be disabled from its current state", category="lifecycle")
        if instance.process:
            await instance.process.stop()
        instance.transition(LifecycleState.INSTALLED_DISABLED)
        instance.health = "unknown"

    async def _on_exit(self, instance: PluginInstance, _code: int | None) -> None:
        if instance.state == LifecycleState.HEALTHY_ACTIVE:
            self.registry.mark_unhealthy(instance)

    def _record_start(self, instance: PluginInstance) -> None:
        now = self.clock()
        instance.start_attempts[:] = [value for value in instance.start_attempts if now - value <= self.restart_window]
        instance.start_attempts.append(now)

    async def restart(self, instance: PluginInstance) -> None:
        if instance.state != LifecycleState.UNHEALTHY:
            raise PluginError("PLUGIN_UNAVAILABLE", "Only unhealthy plugins can restart", category="lifecycle")
        now = self.clock()
        instance.start_attempts[:] = [value for value in instance.start_attempts if now - value <= self.restart_window]
        if len(instance.start_attempts) >= self.max_starts:
            instance.transition(LifecycleState.QUARANTINED)
            self.registry.unregister(instance)
            raise PluginError("PLUGIN_QUARANTINED", "Plugin restart limit exceeded", category="lifecycle")
        await self.sleep(2 ** max(0, len(instance.start_attempts) - 1))
        await self.enable(instance)

    async def activate_candidate(
        self,
        old: PluginInstance,
        candidate: PluginInstance,
        *,
        commit: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        if old.state != LifecycleState.HEALTHY_ACTIVE:
            raise PluginError("PLUGIN_UNAVAILABLE", "Old plugin is not active", category="lifecycle")
        try:
            await self.enable(candidate, activate=False)
            self.registry.replace(old, candidate)
            if commit:
                try:
                    await commit()
                except BaseException:
                    self.registry.rollback_replace(old, candidate)
                    candidate.transition(LifecycleState.STOPPING)
                    if candidate.process:
                        await candidate.process.stop(graceful=False)
                    candidate.transition(LifecycleState.INSTALLED_DISABLED)
                    raise
        except BaseException:
            if candidate.process:
                await candidate.process.stop(graceful=False)
            if candidate.state in {LifecycleState.STARTING, LifecycleState.HANDSHAKING}:
                self.registry.mark_unhealthy(candidate)
            raise
        old.transition(LifecycleState.STOPPING)
        if old.process:
            try:
                await old.process.stop()
            except BaseException:
                # The registry switch and durable commit already succeeded.
                # Old-process cleanup is best effort and must not roll the
                # active candidate back into an inconsistent DB/runtime pair.
                process = old.process.process
                if process is not None and process.returncode is None:
                    process.kill()
        old.transition(LifecycleState.INSTALLED_DISABLED)

    async def shutdown(self) -> None:
        self._closed = True
        for instance in list(self.registry.instances.values()):
            if instance.state in {LifecycleState.HEALTHY_ACTIVE, LifecycleState.UNHEALTHY}:
                try:
                    await self.disable(instance)
                except PluginError:
                    if instance.process:
                        await instance.process.stop(graceful=False)
        if self.capability_dispatcher is not None:
            self.capability_dispatcher.close()

    async def uninstall(self, instance: PluginInstance) -> None:
        if instance.state in {LifecycleState.HEALTHY_ACTIVE, LifecycleState.UNHEALTHY}:
            await self.disable(instance)
        self.registry.remove(instance)
        self._commands.pop(instance.instance_id, None)
        self._gates.pop(instance.instance_id, None)
