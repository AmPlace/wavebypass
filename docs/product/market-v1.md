# Market V1 UI Product Specification

This document defines the durable product rules for the WaveFlow Market V1
package catalog. It describes the current card and filter behavior; it is not
an implementation log and it is not proof that a package is installed.

## 1. Product Goal

Market helps an administrator quickly decide what a package is, where it comes
from, how much content or capability it provides, and which action is
available. The first screen favors recognition and comparison. Complete
package metadata remains available in the package detail drawer.

## 2. Page Information Architecture

The V1 page keeps the existing Market IA:

- package type switch: Content / Plugins;
- high-frequency status shortcuts: All / Installed / Updates;
- a filter entry for lower-frequency conditions;
- search, sort, source management, refresh, and update actions;
- a responsive package grid;
- a package detail drawer.

V1 does not add a Featured, recommendation, or promotional section.

## 3. Grid and Responsive Rules

Cards use a regular CSS grid. Masonry and content-dependent row packing are not
used.

- under `640px`: one column;
- `640px` through `1023px`: two columns;
- `1024px` through `1279px`: three columns;
- `1280px` through `1599px`: four columns;
- `1600px` and wider: five columns when the available content width supports
  readable package identity and titles.

The grid is allowed to show fewer packages per viewport when that preserves
title, identity, and action readability. A smaller card count is preferable to
truncating the package identity into an ambiguous tile.

## 4. Package Card Anatomy

The normal card follows this order:

1. identity badge, package title, and source/region line;
2. scale: channel count, logo count, or Plugin scheme count;
3. up to three content or capability summary tags, followed by `+N` when
   additional core items exist;
4. quiet package/source metadata;
5. status and primary action, with overflow fixed at the trailing edge.

Card height is stable enough for row comparison. A package with fewer summary
items does not receive a large empty taxonomy area, and a package with a long
taxonomy does not grow the grid row indefinitely.

The home card does not show full channel previews, long descriptions, package
versions, full taxonomy, transport details, or complete technical capability
lists. Clicking the card opens the detail drawer.

## 5. Package Identity Resolution

The identity badge is a package identity cue, not a guessed channel logo. All
identity badges use the same container size, radius, padding, and visual
weight.

Resolution priority:

1. explicit `package.display.badge` text and tone;
2. Plugin publisher/provider identity;
3. Content operator identity;
4. region or country identity;
5. WaveFlow or official source identity;
6. stable package-name monogram fallback.

Examples:

- an operator package uses an operator cue such as Mobile, Telecom, or
  Unicom, while the province remains in the source line;
- an official Plugin uses the WaveFlow publisher cue and displays its stable
  publisher/plugin identity in text;
- a region-only package uses the region cue;
- a custom badge is honored without inferring a broadcaster logo.

The current V1 backend contract exposes a sanitized badge override, not a
generic remote package image contract. The card therefore does not invent or
fetch identity artwork.

## 6. Content Tag Taxonomy and Priority

Visible Content tags summarize content categories. They may express groups such
as CCTV, satellite, local, sports, children, film, news, education,
documentary, music, shopping, and similar curated categories.

The presenter normalizes aliases, removes identity and transport fields, and
orders tags by deterministic priority. The card shows at most three core tags;
additional core categories are represented by `+N`. Source-defined tag rules
may extend or replace the built-in taxonomy within the Market schema contract.

The following are not ordinary Content tags on the card:

- HLS, HTTP, RTSP, MPEG-TS, DASH, multicast, and other transport details;
- IPTV, playlist, dynamic package, and other package implementation fields;
- region/operator identity already shown in the source line;
- complete channel names and provider-specific technical labels.

These values remain available in the detail layer where they affect playback,
compatibility, or package inspection.

## 7. Home Metadata vs Detail Metadata

Home card metadata includes:

- package title;
- source, operator, region, or publisher identity;
- scale count;
- a short category/capability summary;
- quiet provenance/runtime/network metadata when it helps choose a package;
- current install/update/unsupported state and action.

The detail drawer includes:

- complete channel preview and taxonomy;
- playback and transport method;
- Plugin contracts, complete schemes, dependencies, runtime, permissions,
  publisher, trust, and version information;
- source provenance, compatibility, risk, and support details.

## 8. CTA and Status Semantics

The backend operation semantics remain authoritative:

- Content install uses `导入` because it creates or updates content
  subscriptions;
- Plugin install uses `安装 Plugin` because it installs a runtime package and
  establishes Plugin ownership;
- installed packages use a low-emphasis `已安装` status;
- updates use a distinct `有更新` marker and update action;
- unsupported packages use a disabled `暂不支持` status;
- in-progress operations disable the relevant action and show the operation
  label.

The overflow menu remains the home for preview/list, uninstall, and immediate
update actions when those actions are available.

## 9. Content vs Plugins

Content cards answer: what content package is this, where is it from, and how
many channels or logos does it contain? Their visible tags are content
categories.

Plugin cards answer: what provider capability is this, who publishes it, and
what runtime/capability scale does it have? Their visible tags are contract or
capability summaries. Scheme count, runtime, permission, dependency, and
complete scheme lists are metadata or detail fields, not Content tags.

## 10. Light and Dark Themes

Market uses the shared WaveFlow semantic surface, border, text, radius, and
control tokens. Light and Dark are two mappings of one visual language. Color
is an identification aid for identity or one emphasized category, not card
decoration. The primary action remains the text-primary/background contrast
pair in both themes.

## 11. Mobile Rules

Mobile uses one-column cards with the same anatomy and a minimum touch-friendly
action height. Complex filters open in the existing bottom sheet. The card
still shows no more than three summary tags, even though the wider mobile card
could fit more labels. Full taxonomy and technical information stay in the
detail drawer.

## 12. Explicit V1 Non-goals

V1 does not redesign Market IA, add recommendations, add a remote artwork
system, change install/update lifecycle semantics, change package/API schema,
rewrite the detail drawer, or turn package cards into channel preview grids.

## 13. Extension Rules

Future Market card changes should first classify a field as identity, scale,
content summary, source/provenance, runtime/technical metadata, or action
state. Only identity, scale, three core summary items, useful source metadata,
and action state belong on the normal card. New technical fields belong in the
detail layer unless they change a common package selection decision and have a
stable sanitized schema contract.
