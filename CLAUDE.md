# CLAUDE.md — Thermal Viewer backend (DEV / IA Builders build)

Flask 3.0 + boto3. Read-only API over S3 + DynamoDB for the thermal viewer.
Dockerized; deploys **ECR → EC2** (manual, not auto). Serves `frontend/`.

This is the **DEV / IA Builders** build. Its EDC twin is a **separate repo**,
usually a sibling directory `../line-loss-analytics-backend/`.

## ⚠️ DEV ↔ EDC divergence — never blind-copy files between the two builds

The EDC backend (`line-loss-analytics-backend`) is a **separate codebase** and has
**diverged**: EDC has **Cognito auth enabled** (all data endpoints `@require_auth`)
and **restricted CORS**. Since v1.4.0 the DEV backend also enforces auth, but by a
different design: **Bearer Cognito access tokens** (ID tokens rejected), **roles
and permissions from the users table** (`thermal-viewer-dev-users`; `view` is
required on data routes), and a **CORS allowlist** (`CORS_ORIGINS`). It **fails
closed**: it will not start without `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`,
`COGNITO_DOMAIN` and `USERS_TABLE`.

When porting a shared change, **diff and hand-patch** the auth/CORS-touching bits
(`app.py`, service classes) rather than copying — copying would flip EDC's auth or
CORS posture. Full map: `../docs/DEV_EDC_DIVERGENCE.md`.

## Conventions

- **DynamoDB `FilterExpression` + `Limit` pitfall:** `Limit` is applied **after**
  the filter reads its items, so `Limit=1` with a `FilterExpression` can return 0
  matches even when matches exist later. Query without `Limit` and take
  `response['Items'][0]`, or narrow with `KeyConditionExpression` first.
- **Presigned S3 URLs:** always 3600 s (1 h), generated on demand, never cached.
- Services raise exceptions; routes catch and return JSON errors with proper codes.

## Versioning

Single source of truth: `APP_VERSION` in `app.py` (env-overridable via
`APP_VERSION`), surfaced on `GET /health` and `GET /`. Versions **independently**
from the frontend and from EDC. Release: bump `APP_VERSION` → `CHANGELOG.md` entry
→ commit → `git tag -a vX.Y.Z` → push branch **and** tag. Details:
`../docs/VERSIONING.md`.

## Deploy

`./scripts/build_and_push_backend.sh` (build + push to ECR) → SSH the EC2 → pull +
`docker-compose up -d backend`. The DEV EC2 is **shared with `thermal-api`** —
restart **only** the `backend` container. `/health` should return 200 after.
