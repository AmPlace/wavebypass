# WaveFlow Security Refactor Audit

## Current File Map

- `backend/main.py`: monolithic FastAPI app. It owns lifespan, CORS, radio proxy routes, IPTV subscriptions, Market, EPG, adapter resolve/play, M3U8 rewrite, TS/stream proxy, RTSP/FFmpeg session state, and several in-memory caches.
- `backend/database.py`: SQLite business database for settings, subscriptions, channels, EPG, Market install state, and Market sources. Security tables were added here so the first auth layer persists beside current app data.
- `backend/ssrf_guard.py`: existing SSRF checks. It is now the migration target for unified policy-driven URL validation.
- `backend/market.py`: already has its own safe fetch implementation and private-address checks; should be migrated into `infrastructure/http_client.py`.
- `backend/epg.py`: downloads XMLTV through caller-provided `httpx.AsyncClient`; should move to unified fetch policies.
- `backend/iptv_probe.py`: probe logic uses shared `httpx.AsyncClient` plus FFmpeg subprocesses; resource limits and unified request policies are needed.
- `backend/fetchers.py`: radio fetchers create their own `httpx` clients and read environment variables directly.
- `backend/adapters/*`: adapters share an `httpx.AsyncClient` contract, but final resolved media URLs still need policy validation before playback/proxying.
- `frontend/src/api/*.js`: multiple small fetch wrappers. They are being migrated to send credentials and the `X-WaveFlow-Request` CSRF header.
- `frontend/src/router/index.js`: setup/login routes, admin route metadata, and auth guard are in place. When anonymous browse is disabled, non-auth pages redirect to login.
- `electron/main/index.js` and `electron/preload/index.js`: desktop uses fixed port `18765`, loads frontend via `file://`, and does not yet perform desktop auth.
- `docker-compose.yml`: backend is currently published directly on host port `8000`; target architecture should expose backend only to the frontend container.

## Route Classification

- Public/setup/auth: `/health`, `/api/config`, new `/api/setup/*`, new `/api/auth/*`.
- Browse: `/api/stations`, `/api/myradio/all`, `/api/yunting/*`, `/api/radio-browser/*`, `/api/iptv/channels`, read-only EPG program endpoints.
- Admin: `/api/admin/subscriptions*`, `/api/admin/market*`, `/api/admin/probes/*`, `/api/admin/epg/*`, `/api/admin/media-credentials`, `/api/admin/settings/security`.
- Media: `/api/{station_id}/playlist.m3u8`, `/api/{station_id}/chunk.ts`, `/api/{station_id}/stream`, `/api/iptv/adapter/play.m3u8`, `/api/iptv/proxy/*`, `/api/iptv/subscription.m3u`, `/api/iptv/smart/{canonical_key}.m3u8`.

## High-Risk Entry Points

- Public `target_url` proxy routes remain the main SSRF/resource risk: `/api/iptv/proxy/wide.m3u8`, `/api/iptv/proxy/chunk.ts`, `/api/iptv/proxy/stream`, `/api/iptv/proxy/playlist.m3u8`, `/api/iptv/proxy/rtsp.m3u8`, and radio `/api/{station_id}/playlist.m3u8?target_url=...`.
- Admin mutations now require an admin session and the `X-WaveFlow-Request` CSRF header. Remaining risk is older non-admin media/proxy URLs that still carry raw `target_url` query strings.
- CORS is currently wide open with `allow_origins=["*"]`.
- In-memory caches such as `M3U8_CACHE`, `M3U8_CACHE_LOCKS`, `_wide_cache`, and RTSP session dictionaries are unbounded or only partly bounded.
- Docker currently allows bypassing frontend nginx and reaching the backend directly.

## Implementation Order

1. Establish config and auth foundation: centralized mode defaults, security tables, Argon2id passwords, HttpOnly sessions, setup/login/logout/me, media credentials.
2. Keep configuration layered: fixed code rules, explicit environment overrides, admin-editable SQLite runtime settings, then mode defaults. Environment variables must preserve the difference between unset and explicitly false.
3. Add frontend boot/auth store and API client with credentials plus `X-WaveFlow-Request`.
4. Move admin routes under `/api/admin/*` or protect legacy admin routes while migrating the frontend.
5. Replace public `target_url` media URLs with signed handles, then remove legacy public proxy routes.
6. Migrate all external HTTP calls to `infrastructure/http_client.py` policies.
7. Extract RTSP session manager and bounded caches.
8. Tighten Docker/nginx/Electron defaults.

## Current Progress

- Done: centralized `WAVEFLOW_*` configuration layering, SQLite runtime settings, auth/session/media credential tables, Argon2id password hashing, setup/login/logout/me APIs, and Admin security settings API.
- Done: frontend auth store, setup/login views, route guard, admin API client migration, and Admin page controls for editable runtime security settings.
- Done: management routes moved to `/api/admin/*`; old `/api/iptv/subscriptions*`, `/api/market*`, old probe, and old EPG management decorators were removed.
- Done: browse and playback routes now depend on `anonymous_browse` / `anonymous_playback`; tests cover anonymous-disabled behavior.
- Still open: replace public raw `target_url` playback/proxy URLs with signed handles or media credentials, then remove or harden the legacy raw URL paths.
- Still open: migrate outbound HTTP calls to `infrastructure/http_client.py`, add bounded cache/session managers, and finish Docker/Electron hardening.
