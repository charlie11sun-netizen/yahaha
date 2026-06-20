#!/usr/bin/env sh
# Export live PlayForge data (Postgres + MinIO bucket) to a portable folder so you
# can carry ALL games — including Create-generated ones, which live only in the
# volumes, not in git — to another host.
#
# Run on the SOURCE machine, from the repo root, with the stack UP. Example:
#   sh deploy/migrate-export.sh            # -> ./pf-backup/
#   sh deploy/migrate-export.sh /tmp/bak   # custom output dir
# If your source stack is the prod compose, prefix:
#   COMPOSE="docker compose -f docker-compose.prod.yml" sh deploy/migrate-export.sh
set -eu

OUT="${1:-pf-backup}"
PROJECT="${COMPOSE_PROJECT_NAME:-playforge}"
COMPOSE="${COMPOSE:-docker compose}"

# Load creds from .env so we know db/minio user, password and bucket name.
if [ -f .env ]; then set -a; . ./.env; set +a; fi
PGUSER="${POSTGRES_USER:-playforge}"; PGDB="${POSTGRES_DB:-playforge}"
MCU="${MINIO_ROOT_USER:-minioadmin}"; MCP="${MINIO_ROOT_PASSWORD:-minioadmin}"; BUCKET="${S3_BUCKET:-playforge}"

mkdir -p "$OUT/bucket"

echo "[1/2] Postgres dump  -> $OUT/db.sql"
$COMPOSE exec -T postgres pg_dump -U "$PGUSER" -d "$PGDB" --no-owner --clean --if-exists > "$OUT/db.sql"

echo "[2/2] MinIO bucket '$BUCKET' -> $OUT/bucket/"
# Windows git-bash mangles `-v host:container` paths; `pwd -W` gives a Docker-
# friendly path and MSYS_NO_PATHCONV stops the colon mangling (both no-ops on Linux).
HOSTPWD="$(pwd -W 2>/dev/null || pwd)"
MSYS_NO_PATHCONV=1 docker run --rm --network "${PROJECT}_default" \
  -v "${HOSTPWD}/$OUT/bucket:/backup" --entrypoint sh minio/mc -c \
  "mc alias set src http://minio:9000 '$MCU' '$MCP' >/dev/null && mc mirror --overwrite src/'$BUCKET' /backup"

echo
echo "Done. Backup at: $OUT/  (db.sql + bucket/)"
echo "Copy this whole folder to the new host, then run deploy/migrate-import.sh there."
