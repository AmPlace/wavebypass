"""Radio domain API and the explicit source-selection boundary."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

import database
from plugin_runtime import PluginError
from security.dependencies import require_admin, require_browse_access


router = APIRouter(tags=["radio"])


def _radio_resolver(request: Request):
    resolver = getattr(request.app.state, "radio_resolver", None)
    if resolver is None:
        raise HTTPException(status_code=503, detail="Radio runtime is unavailable")
    return resolver


@router.get("/api/radio/stations")
async def list_radio_stations(_access=Depends(require_browse_access)):
    return {"stations": await database.list_radio_stations()}


@router.get("/api/radio/stations/{station_id}")
async def get_radio_station(station_id: str, _access=Depends(require_browse_access)):
    station = await database.get_radio_station(station_id)
    if station is None:
        raise HTTPException(status_code=404, detail="Radio station not found")
    return station


@router.get("/api/radio/stations/{station_id}/resolve")
async def resolve_radio_station(
    station_id: str,
    request: Request,
    source_id: str = Query("", description="Explicit persisted Radio source selector"),
    _access=Depends(require_browse_access),
):
    if not source_id.strip():
        raise HTTPException(status_code=400, detail="source_id is required")
    resolver = _radio_resolver(request)
    try:
        return await resolver.resolve_source(source_id.strip(), station_id=station_id)
    except PluginError as exc:
        status = 404 if exc.code in {"RESOURCE_NOT_FOUND", "SCHEME_CONFLICT"} else 503
        raise HTTPException(status_code=status, detail=exc.as_contract()) from exc


@router.get("/api/radio/stations/{station_id}/programme")
async def get_radio_programme(
    station_id: str,
    request: Request,
    source_id: str = Query("", description="Explicit persisted Radio source selector"),
    _access=Depends(require_browse_access),
):
    if not source_id.strip():
        raise HTTPException(status_code=400, detail="source_id is required")
    resolver = _radio_resolver(request)
    try:
        return await resolver.resolve_programme(source_id.strip(), station_id=station_id)
    except PluginError as exc:
        status = 404 if exc.code in {"RESOURCE_NOT_FOUND", "SCHEME_CONFLICT"} else 503
        raise HTTPException(status_code=status, detail=exc.as_contract()) from exc


@router.post("/api/radio/plugins/{plugin_identity:path}/refresh")
async def refresh_radio_catalog(
    plugin_identity: str,
    request: Request,
    _admin=Depends(require_admin),
):
    subsystem = getattr(request.app.state, "plugin_subsystem", None)
    if subsystem is None:
        raise HTTPException(status_code=503, detail="Plugin subsystem is unavailable")
    result = await subsystem.refresh_radio_catalog(plugin_identity)
    if result.get("status") != "success":
        raise HTTPException(status_code=503, detail=result)
    return result
