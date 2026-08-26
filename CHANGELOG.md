# Changelog

All notable changes to the **Thermal Viewer backend** (DEV / IA Builders build).

Format based on [Keep a Changelog](https://keepachangelog.com/); this project
follows [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`. The
version is a single source of truth in `app.py` (`APP_VERSION`, overridable via
the `APP_VERSION` env var) and is surfaced on `GET /health` and `GET /` for ops.
See `docs/VERSIONING.md` for the full scheme.

The backend versions independently from the frontend — they deploy separately
(Amplify vs ECR/EC2), so their numbers need not match. `1.1.0` is reconstructed
from history; tagging began at `1.2.0`.

## [1.3.0] — 2026-08-26
### Added
- `GET /api/navigation` now returns a per-sector `pads` map (keyed by `pad_id`,
  with `pad_name`, `geo_location_area`, and the sorted-descending list of
  `periods` that pad actually has imagery for) alongside the existing
  `periods` list, so the frontend can offer a pad-first filter order
  (Site → Sector → Pad → Period) without any additional per-selection API
  calls. Pads with no imagery in any period are omitted; the pads table
  remains the authoritative pad list. Existing `periods` output is unchanged
  (backward compatible).

## [1.2.0] — 2026-07-24
### Added
- `download` flag on `GET /api/mosaic/orthomosaic` — sets the S3
  `ResponseContentDisposition` so the presigned URL downloads as
  `{pad_id}_{period}_{mosaic_type}.tif` (sanitized, header-injection-safe).
- Single-source `APP_VERSION`, surfaced on `/health` and `/` (replaces two
  hardcoded `1.0.0` strings).
### Changed
- Test suite (`scripts/test_viewer_backend.sh`) made portable and self-diagnosing;
  domain references moved to `dev-thermal.dabuilders.net`. (Tooling/infra only.)

## [1.1.0] — 2026-06-11
### Fixed
- **Parallelized the per-pad completeness check** (ThreadPoolExecutor) in
  `/api/pads`, resolving the production slowdown after new sectors/periods were
  added (≈4×pad_count sequential S3 HEADs → concurrent).

## [1.0.0] — 2025-11
### Added
- Initial read-only API: hierarchical discovery (`/api/sites`, `/api/sectors`,
  `/api/periods`, `/api/pads`), mosaic metadata + presigned orthomosaic URLs,
  camera positions (`shots.geojson`), optical/thermal image URLs, thermal
  temperature statistics, and `/health`.
