# WaveFlow Market Schema

WaveFlow Market uses two layers:

- `market.json`: index data for listing, search, filters, badges, update checks, and dependency hints.
- `manifest.json`: executable import/preview configuration loaded lazily when the user opens details, previews, or imports a package.

Market data is configuration only. WaveFlow does not download or execute third-party code from Market packages.

## market.json

`market.json` should be fast to fetch and safe to render. Do not put concrete channel lists or playback URLs in it.

```json
{
  "schema_version": 1,
  "market_version": "2026.05.28",
  "updated_at": "2026-05-28T00:00:00+08:00",
  "packages": [
    {
      "id": "japantv-public",
      "name": "Japan Public TV",
      "description": "A dynamic M3U package for public Japanese TV streams.",
      "kind": "dynamic_playlist",
      "version": "2026.05.28",
      "updated_at": "2026-05-28T00:00:00+08:00",
      "manifest_url": "packages/japantv-public/manifest.json",
      "region": {
        "country": "JP",
        "province": null,
        "city": null
      },
      "operators": ["global"],
      "language": ["ja-JP"],
      "categories": ["tv"],
      "tags": ["Japan", "public", "dynamic_playlist", "HLS"],
      "status": "stable",
      "source_origin": "community",
      "source_policy": "community_index",
      "risk_level": "low",
      "importable": true,
      "previewable": true,
      "supported_in_v1": true,
      "unsupported_reason": null,
      "requires_proxy": false,
      "requires_resolver": false,
      "requires_cookie": false,
      "requires_referer": false,
      "requires_custom_ua": false,
      "channel_count": 35,
      "source_count": 35,
      "health": {
        "rate": 0.9,
        "last_checked_at": "2026-05-28T00:00:00+08:00"
      },
      "compatibility": {
        "waveflow": "recommended",
        "vlc": "supported",
        "aptv": "supported",
        "tivimate": "supported"
      },
      "contributors": [
        {
          "name": "AmPlace",
          "url": "https://github.com/AmPlace"
        }
      ]
    }
  ]
}
```

Recommended package fields:

| Field | Purpose |
| --- | --- |
| `id`, `name`, `description`, `kind` | Basic display and package identity. |
| `version`, `updated_at` | Lightweight update checks. |
| `manifest_url` | Lazy-loaded package manifest. Prefer relative paths. |
| `region`, `operators`, `language` | Region/operator/language filters. |
| `categories`, `tags` | Category filters and fuzzy discovery. |
| `status`, `source_origin`, `source_policy`, `risk_level` | Source quality and risk hints. |
| `importable`, `previewable`, `supported_in_v1`, `unsupported_reason` | V1 support status. |
| `requires_proxy`, `requires_resolver`, `requires_cookie`, `requires_referer`, `requires_custom_ua` | Dependency badges. |
| `channel_count`, `source_count` | Package scale hints. |
| `health`, `compatibility`, `contributors` | Optional richer details. |

Do not put these execution fields in `market.json`:

```text
defaults
channel_sources
inline_channels
channels
channels_url
source_defaults
headers
```

## manifest.json

`manifest.json` is loaded only when WaveFlow needs to preview or import a package.

```json
{
  "schema_version": 1,
  "id": "japantv-public",
  "name": "Japan Public TV",
  "kind": "dynamic_playlist",
  "version": "2026.05.28",
  "updated_at": "2026-05-28T00:00:00+08:00",
  "defaults": {
    "source": {
      "type": "hls",
      "requires_proxy": false,
      "headers": {}
    }
  },
  "channel_sources": [
    {
      "type": "playlist",
      "id": "japantv-public-m3u",
      "name": "Japan public M3U",
      "url": "https://example.com/japan.m3u",
      "format": "auto",
      "headers": {
        "User-Agent": "Mozilla/5.0"
      }
    }
  ]
}
```

`manifest.json` may keep display fields such as `description`, `region`, and `tags`, but `market.json` must still contain index metadata because refresh does not read manifests.

## channel_sources

V1 supports:

### playlist

Remote M3U/M3U8/TXT subscription file. This is a channel list, not a single HLS playlist.

```json
{
  "type": "playlist",
  "id": "public-list",
  "name": "Public IPTV list",
  "url": "https://example.com/list.m3u",
  "format": "auto",
  "headers": {
    "User-Agent": "Mozilla/5.0"
  }
}
```

Supported content:

- M3U / M3U8 with `#EXTINF`.
- TXT in the common form:

```text
News,#genre#
Channel 1,http://example.com/1.m3u8
Channel 2,http://example.com/2.m3u8
```

### inline_channels

Inline channels or a remote `channels.json`.

```json
{
  "type": "inline_channels",
  "channels_url": "channels.json"
}
```

`channels.json` may be:

```json
{
  "channels": [
    {
      "id": "cctv-1",
      "name": "CCTV-1",
      "group_name": "CCTV",
      "sources": [
        {
          "type": "hls",
          "url": "https://example.com/cctv1.m3u8"
        }
      ]
    }
  ]
}
```

or a raw array of channel objects.

## Headers

There are two different header meanings.

### channel_sources[].headers

Used only when WaveFlow fetches the remote playlist or `channels_url`.

```json
{
  "type": "playlist",
  "url": "https://example.com/list.m3u",
  "headers": {
    "User-Agent": "Mozilla/5.0"
  }
}
```

This does not mean each playback source requires a custom UA.

### defaults.source.headers / source.headers

Used for playback sources. If a playback source needs `User-Agent` or `Referer`, put it here.

```json
{
  "defaults": {
    "source": {
      "headers": {
        "User-Agent": "okHttp/Mod-1.5.0.0",
        "Referer": "https://example.com/"
      }
    }
  }
}
```

Playback headers usually imply proxying because browsers cannot safely set all media request headers.

Cookie sources are not imported as playable V1 sources. Mark them with `requires_cookie=true`; users will need a future local credential configuration.

## requires_* rules

In `market.json`, dependency flags should summarize package-level needs:

- `requires_proxy=true` if package/default source requires backend proxy.
- `requires_resolver=true` if playback needs provider or remote resolver resolution.
- `requires_cookie=true` if any source needs Cookie or login.
- `requires_referer=true` if playback sources need `Referer`.
- `requires_custom_ua=true` if playback sources need custom `User-Agent`.

Do not set `requires_custom_ua` just because `channel_sources[].headers.User-Agent` exists. That header is only for fetching the remote playlist file.

## YouTube

V1 supports YouTube URLs only when an embeddable video id can be extracted, for example:

```text
https://www.youtube.com/watch?v=xxxxxxxxxxx
https://youtu.be/xxxxxxxxxxx
https://www.youtube.com/live/xxxxxxxxxxx
```

V1 does not resolve channel live URLs:

```text
https://www.youtube.com/@SomeChannel/live
https://www.youtube.com/channel/UCxxxx/live
```

Packages containing channel live URLs should usually be marked:

```json
{
  "requires_resolver": true,
  "supported_in_v1": false,
  "importable": false,
  "previewable": false,
  "unsupported_reason": "YouTube channel live URLs require a resolver; V1 does not support them yet."
}
```

## Validation Checklist

- `market.json` and every manifest are valid JSON.
- Each market package has `id`, `name`, `kind`, and `manifest_url`.
- `manifest_url` is relative whenever the manifest is in the same Market repository.
- `market.json` does not include execution fields such as `defaults` or `channel_sources`.
- `null` is real JSON `null`, not the string `"null"`.
- Use consistent casing such as `JP`, `CN`, `global`, `ja-JP`, `zh-CN`.
- `market.json` contains enough metadata for cards, filters, dependency badges, and update checks.
- `manifest.json` contains enough configuration for preview/import.

## Local Import Provenance

When WaveFlow imports a Market package, it stores package/source identity on each local channel source:

| Local field | Source |
| --- | --- |
| `market_package_id` | Imported package id. |
| `market_source_id` | `channel_sources[].id` when present, otherwise `channel_sources[].name`. |
| `market_channel_id` | Channel `id`, `canonical_key`, `tvg_id`, EPG `tvg_id`, or channel name. |
| `market_source_item_id` | Source `id` / `source_id`; if missing, WaveFlow generates an `auto-...` id from package, channel source, channel, source index, and URL. |

These fields are for future package diff updates, uninstall checks, and local health display. Ordinary user subscriptions keep them empty.
