from __future__ import annotations

import base64
import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import database as db
import market
from plugin_tasks import reconcile_plugin_update_task
from plugin_runtime import PluginError
from security.dependencies import require_admin


router = APIRouter(prefix="/api/admin/plugins", tags=["plugins"], dependencies=[Depends(require_admin)])
IDENTIFIER_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$")


class PluginActionRequest(BaseModel):
    package_id: str = ""


class PublisherTrustRequest(BaseModel):
    publisher_id: str
    key_id: str
    public_key: str
    trust_level: str = "third_party"
    enabled: bool = True
    description: str = Field(default="", max_length=500)


class OwnershipRequest(BaseModel):
    mode: str
    plugin: str = ""


def _subsystem(request: Request):
    subsystem = getattr(request.app.state, "plugin_subsystem", None)
    if subsystem is None:
        raise HTTPException(status_code=503, detail={"code": "PLUGIN_UNAVAILABLE", "message": "Plugin subsystem is unavailable"})
    return subsystem


def _error(exc: PluginError) -> HTTPException:
    statuses = {
        "RESOURCE_NOT_FOUND": 404, "ARTIFACT_NOT_FOUND": 404,
        "PLUGIN_UNTRUSTED": 403, "CAPABILITY_DENIED": 403,
        "SCHEME_CONFLICT": 409, "PLUGIN_CANDIDATE_CONFLICT": 409,
        "PLUGIN_INCOMPATIBLE": 422, "PLATFORM_UNSUPPORTED": 422,
    }
    return HTTPException(status_code=statuses.get(exc.code, 400), detail=exc.as_contract())


def _manifest_projection(row: dict[str, Any]) -> dict[str, Any]:
    try:
        manifest = json.loads(row.get("manifest_json") or "{}")
    except json.JSONDecodeError:
        manifest = {}
    return {
        "plugin": f"{row['publisher_id']}/{row['plugin_id']}",
        "display_name": manifest.get("display_name") or row["plugin_id"],
        "version": row.get("active_version") or row.get("installed_version") or "",
        "enabled": bool(row.get("enabled")),
        "lifecycle_state": row.get("lifecycle_state") or "",
        "runtime_available": row.get("lifecycle_state") == "active",
        "quarantined": bool(row.get("quarantined")),
        "owned_schemes": [item.get("scheme") for item in manifest.get("owned_schemes", []) if isinstance(item, dict)],
        "provider_contracts": manifest.get("provider_contracts") or [],
        "source_provenance": {"source_key": row.get("source_key") or "", "package_id": row.get("source_package_id") or ""},
        "trust_state": row.get("trust_state") or "",
        "last_error": str(row.get("last_error") or "")[:1024],
    }


async def _packages(package_id: str = "") -> list[dict[str, Any]]:
    await market.ensure_market_loaded()
    packages = market.market_packages_snapshot()
    if package_id:
        packages = [item for item in packages if item.get("id") == package_id]
    return packages


@router.get("")
async def list_plugins() -> dict[str, Any]:
    rows = await db.list_plugin_installations()
    return {"plugins": [_manifest_projection(row) for row in rows]}


@router.get("/trust")
async def list_trust() -> dict[str, Any]:
    rows = await db.list_plugin_publisher_trust()
    return {"publishers": [{k: row[k] for k in ("publisher_id", "key_id", "trust_level", "enabled", "description")} for row in rows]}


@router.put("/trust")
async def put_trust(body: PublisherTrustRequest, request: Request) -> dict[str, Any]:
    if not IDENTIFIER_RE.fullmatch(body.publisher_id) or not IDENTIFIER_RE.fullmatch(body.key_id):
        raise HTTPException(status_code=422, detail={"code": "INVALID_PLUGIN_RESPONSE", "message": "Invalid publisher identity"})
    if body.trust_level not in {"official", "third_party"}:
        raise HTTPException(status_code=422, detail={"code": "INVALID_PLUGIN_RESPONSE", "message": "Invalid trust level"})
    try:
        decoded = base64.b64decode(body.public_key, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_PLUGIN_RESPONSE", "message": "Invalid Ed25519 public key"}) from exc
    if len(decoded) != 32:
        raise HTTPException(status_code=422, detail={"code": "INVALID_PLUGIN_RESPONSE", "message": "Invalid Ed25519 public key"})
    row = await db.upsert_plugin_publisher_trust(**body.model_dump())
    await _subsystem(request).reload_trust()
    return {k: row[k] for k in ("publisher_id", "key_id", "trust_level", "enabled", "description")}


@router.get("/dependencies/{package_id:path}")
async def content_dependencies(package_id: str, request: Request) -> dict[str, Any]:
    try:
        return await _subsystem(request).service.installed_content_dependency_projection(package_id)
    except PluginError as exc:
        raise _error(exc) from exc


@router.get("/{publisher_id}/{plugin_id}")
async def plugin_detail(publisher_id: str, plugin_id: str) -> dict[str, Any]:
    row = await db.get_plugin_installation(publisher_id, plugin_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "Plugin is not installed"})
    return _manifest_projection(row)


@router.post("/{publisher_id}/{plugin_id}/install")
async def install_plugin(publisher_id: str, plugin_id: str, body: PluginActionRequest, request: Request) -> dict[str, Any]:
    identity = f"{publisher_id}/{plugin_id}"
    packages = await _packages(body.package_id)
    try:
        result = await _subsystem(request).install(identity, packages)
        automation = getattr(request.app.state, "automation_service", None)
        if automation is not None:
            await reconcile_plugin_update_task(automation, _subsystem(request))
        return result
    except PluginError as exc:
        raise _error(exc) from exc


@router.post("/{publisher_id}/{plugin_id}/update")
async def update_plugin(publisher_id: str, plugin_id: str, body: PluginActionRequest, request: Request) -> dict[str, Any]:
    return await install_plugin(publisher_id, plugin_id, body, request)


@router.post("/{publisher_id}/{plugin_id}/enable")
async def enable_plugin(publisher_id: str, plugin_id: str, request: Request) -> dict[str, Any]:
    try:
        return await _subsystem(request).service.enable(f"{publisher_id}/{plugin_id}")
    except PluginError as exc:
        raise _error(exc) from exc


@router.post("/{publisher_id}/{plugin_id}/disable")
async def disable_plugin(publisher_id: str, plugin_id: str, request: Request) -> dict[str, Any]:
    try:
        return await _subsystem(request).service.disable(f"{publisher_id}/{plugin_id}")
    except PluginError as exc:
        raise _error(exc) from exc


@router.post("/{publisher_id}/{plugin_id}/recover")
async def recover_plugin(publisher_id: str, plugin_id: str, request: Request) -> dict[str, Any]:
    try:
        return await _subsystem(request).service.recover_quarantine(f"{publisher_id}/{plugin_id}")
    except PluginError as exc:
        raise _error(exc) from exc


@router.delete("/{publisher_id}/{plugin_id}")
async def uninstall_plugin(publisher_id: str, plugin_id: str, request: Request) -> dict[str, Any]:
    try:
        removed = await _subsystem(request).service.uninstall(f"{publisher_id}/{plugin_id}")
        automation = getattr(request.app.state, "automation_service", None)
        if automation is not None:
            await reconcile_plugin_update_task(automation, _subsystem(request))
        return {"removed": removed}
    except PluginError as exc:
        raise _error(exc) from exc


@router.put("/ownership/{scheme}")
async def set_ownership(scheme: str, body: OwnershipRequest, request: Request) -> dict[str, Any]:
    try:
        return await _subsystem(request).set_ownership(scheme, body.mode, body.plugin)
    except PluginError as exc:
        raise _error(exc) from exc
