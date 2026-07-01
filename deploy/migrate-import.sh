#!/usr/bin/env sh
# Restore a backup made by migrate-export.sh into a FRESH host.
#
# Run on the TARGET machine, from the repo root, AFTER bringing up infra only:
#   docker compose -f docker-compose.prod.yml up -d postgres redis minio createbuckets
#   sh deploy/migrate-import.sh            # reads ./pf-backup/
#   docker compose -f docker-compose.prod.yml up -d --build   # start api/worker/web
#
# Order matters: restore BEFORE the `api` service runs (its startup seed is
# idempotent and only refreshes the 3 curated flagships; your Create games are
# kept as-is).
set -eu

IN="${1:-pf-backup}"
PROJECT="${COMPOSE_PROJECT_NAME:-gameweave}"
COMPOSE="${COMPOSE:-docker compose -f docker-compose.prod.yml}"

if [ -f .env ]; then set -a; . ./.env; set +a; fi
PGUSER="${POSTGRES_USER:-gameweave}"; PGDB="${POSTGRES_DB:-gameweave}"
MCU="${MINIO_ROOT_USER:-minioadmin}"; MCP="${MINIO_ROOT_PASSWORD:-minioadmin}"; BUCKET="${S3_BUCKET:-gameweave}"

[ -f "$IN/db.sql" ] || { echo "ERROR: $IN/db.sql not found (run migrate-export.sh first / pass the right dir)"; exit 1; }

echo "[1/2] restore Postgres <- $IN/db.sql"
$COMPOSE exec -T postgres psql -U "$PGUSER" -d "$PGDB" < "$IN/db.sql"

echo "[2/2] restore MinIO bucket '$BUCKET' <- $IN/bucket/"
# Windows git-bash mangles `-v host:container` paths; `pwd -W` gives a Docker-
# friendly path and MSYS_NO_PATHCONV stops the colon mangling (both no-ops on Linux).
HOSTPWD="$(pwd -W 2>/dev/null || pwd)"
MSYS_NO_PATHCONV=1 docker run --rm --network "${PROJECT}_default" \
  -v "${HOSTPWD}/$IN/bucket:/backup" --entrypoint sh minio/mc -c \
  "mc alias set dst http://minio:9000 '$MCU' '$MCP' >/dev/null && mc mirror --overwrite /backup dst/'$BUCKET'"

echo
echo "Restored. Now start the app:"
echo "  $COMPOSE up -d --build"
echo "(api runs seed on boot; curated flagships refresh, your Create games are preserved.)"
