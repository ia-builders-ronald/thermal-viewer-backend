# Version History — DEV / IA Builders build

Coverage of every version of the **DEV** build (`frontend/` + `backend/`).
Per-repo detail is in each repo's `CHANGELOG.md`; this is the quick cross-tier
reference. Scheme: `VERSIONING.md`. EDC's equivalent: `VERSION_HISTORY_EDC.md`.

> **Standing doc — update on every DEV release.** When you tag a new DEV
> frontend or backend version, add its row here (see "Updating" at the bottom).

**Frontend = the user-facing "Viewer version"** (shown in the app header, quoted
in support tickets). The backend versions independently (ops-facing, on `/health`).
Tagging began at frontend `1.7.0`; `1.0.0`–`1.6.0` are *reconstructed* from git
history + the support log and are not git-tagged.

## Frontend (`frontend/`)

| Version | Date | Coverage | Tag |
|---|---|---|---|
| **1.0.0** | 2025-11-25 | Initial production: Site→Sector→Period→Pad navigation, GeoTIFF mosaic viewer (OpenLayers), camera markers, optical/thermal image panel with temperature stats, pipe-measurement panel. | reconstructed |
| **1.1.0** | 2025-12 | Line Loss Analytics Report with PDF/Word export (pre-generated from thermal-api). | reconstructed |
| **1.2.0** | 2026-01 | Colorbar display; medical palette default (thermal-mode toggle removed); auth scaffolding. | reconstructed |
| **1.3.0** | 2026-03 | Perf/UX: single-call navigation preload, sequential mosaic loading, site/sector name capitalization, max zoom 22→24, production console stripping. | reconstructed |
| **1.4.0** | 2026-07-06 | Live zoom readout + OverviewMap "you are here" inset; max zoom 24→26; lettered pad-name capitalization. | ✅ |
| **1.5.0** | 2026-07-09 | GeoTIFF mosaic download (optical+thermal, filename-stamped); max zoom →30 + per-pad native-resolution warning; map-controls polish. | ✅ |
| **1.6.0** | 2026-07-10 | Line/area measurement tool: multiple measurements, right-click control, area-on-close, numbered badges + side panel, vertex drag/click-delete; double-click-zoom disabled. | ✅ |
| **1.7.0** | 2026-07-24 | Temperature statistics panel redesign (MIN/AVG/MAX tri-panel, Location card, 2×2 calibration grid); Calibrated/Raw chip; **user-visible app version in the header**. | ✅ |
| **1.8.0** | 2026-08-12 | Camera capture date/time: hover tooltip on markers (local time from the DJI filename) + "i" info button on the optical/thermal images (filename + capture time). | ✅ |
| **1.8.1** | 2026-08-12 | Aligned the report dialog *down* to EDC's simpler format (dropped Area/Perimeter columns, "Section"→"Pad"). Divergence reconciliation. **Note:** EDC's `1.8.1` is a *different* change — see `VERSION_HISTORY_EDC.md`. | ✅ |
| **1.9.0** | 2026-08-13 | Auto-load pad imagery on selection (no "Load Data" click); old button → small refresh button; stale-load guard. | ✅ |
| **1.9.1** | 2026-08-13 | Merged the two loading indicators (fetch spinner + map raster box) into one overlay. | ✅ |
| **1.9.2** | 2026-08-13 | Fixed loading-overlay flicker across load phases (busy signal covers the tile render; hide debounced). | ✅ |
| **1.10.0** | 2026-08-13 | Frosted-glass styling for floating map surfaces (Map Controls, Pipe Measurements, measurements list, loading overlay = light glass; zoom badge + camera tooltip = dark glass). | ✅ |

## Backend (`backend/`)

Ops-facing version, surfaced on `GET /health` and `/`. The DEV backend runs
**auth-disabled + open CORS** (differs from EDC — see `DEV_EDC_DIVERGENCE.md`).

| Version | Date | Coverage | Tag |
|---|---|---|---|
| **1.0.0** | 2025-11 | Initial read-only API: hierarchical discovery, mosaic metadata + presigned orthomosaic URLs, camera positions, optical/thermal image URLs, thermal temperature stats, `/health`. | reconstructed |
| **1.1.0** | 2026-06-11 | Parallelized the per-pad completeness check (ThreadPoolExecutor). | reconstructed |
| **1.2.0** | 2026-07-24 | `download` flag on `/api/mosaic/orthomosaic` (S3 `ResponseContentDisposition` filename); single-source `APP_VERSION` on `/health` + `/`. | ✅ |

## Current DEV versions
- Frontend: **1.10.0** · Backend: **1.2.0**

## Updating (each DEV release)
1. Bump `package.json` (frontend) / `APP_VERSION` (backend) + add the `CHANGELOG.md` entry, commit, `git tag -a vX.Y.Z`, push branch + tag (per `VERSIONING.md`).
2. Add the version's row to the table above (one-line coverage summary).
3. Update "Current DEV versions".
