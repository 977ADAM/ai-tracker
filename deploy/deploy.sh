#!/usr/bin/env bash
set -euo pipefail
commit=$1
deploy_dir=$2
export AI_TRACKER_ORIGIN=$3
cd "$deploy_dir"
exec 9>.deploy.lock
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }
test -z "$(git status --porcelain --untracked-files=no)" || {
  echo 'Server checkout has local changes. Deployment stopped.' >&2
  exit 1
}
previous_commit=$(git rev-parse HEAD)
frontend_stopped=false
backend_stopped=false
migration_started=false
finished=false
restore_before_migration() {
  rc=$?
  if [ "$finished" = false ] && [ "$migration_started" = false ]; then
    if [ "$backend_stopped" = true ]; then docker start ai-tracker-backend-1 || true; fi
    if [ "$frontend_stopped" = true ]; then docker start ai-tracker-frontend-1 || true; fi
    git checkout --detach "$previous_commit" || true
  fi
  if [ "$rc" -ne 0 ] && [ "$migration_started" = true ]; then
    echo 'Deployment failed after migrations started. Check the server; no automatic database rollback.' >&2
  fi
  exit "$rc"
}
trap restore_before_migration EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP
git fetch origin +refs/heads/main:refs/remotes/origin/main --tags
git cat-file -e "$commit^{commit}"
git merge-base --is-ancestor "$commit" origin/main
git checkout --detach "$commit"
docker compose config --quiet
docker compose build backend frontend
active_measurements() {
  docker exec ai-tracker-postgres-1 psql -U ai_tracker -d ai-tracker \
    -Atc "SELECT count(*) FROM project_measurements WHERE status='running'"
}
test "$(active_measurements)" = 0 || {
  echo 'Active measurements exist. Try deployment after they finish.' >&2
  exit 1
}
frontend_stopped=true
docker stop ai-tracker-frontend-1
test "$(active_measurements)" = 0 || {
  echo 'A measurement started during deployment. Try again later.' >&2
  exit 1
}
backend_stopped=true
docker stop ai-tracker-backend-1
migration_started=true
docker compose run --rm --no-deps -T migrate < /dev/null
docker compose up -d --no-deps backend frontend
healthy=false
for attempt in $(seq 1 24); do
  if curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8000/api/projects >/dev/null \
    && curl --fail --silent --show-error --max-time 10 http://127.0.0.1:3001/clustering/tracker/ >/dev/null; then
    healthy=true
    break
  fi
  sleep 5
done
test "$healthy" = true || { echo 'Deployment health check failed.' >&2; exit 1; }
finished=true
echo "Deployed $commit"
