#!/usr/bin/env bash
# Деплой ai-tracker. Запускается в /opt/ai-tracker после git reset;
# вручную: bash deploy/deploy.sh
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"

export AI_TRACKER_ORIGIN="${AI_TRACKER_ORIGIN:-https://dev.coresmart.tech}"

exec 9>.deploy.lock
flock -n 9 || { echo 'Уже идёт другой деплой.' >&2; exit 1; }
test -z "$(git status --porcelain --untracked-files=no)" || {
  echo 'В каталоге есть локальные изменения. Деплой остановлен.' >&2
  exit 1
}

frontend_stopped=false
backend_stopped=false
migration_started=false
finished=false
restore_before_migration() {
  rc=$?
  if [ "$finished" = false ] && [ "$migration_started" = false ]; then
    if [ "$backend_stopped" = true ]; then docker compose start backend || true; fi
    if [ "$frontend_stopped" = true ]; then docker compose start frontend || true; fi
  fi
  if [ "$rc" -ne 0 ] && [ "$migration_started" = true ]; then
    echo 'Деплой упал после начала миграций. База не откатывается автоматически.' >&2
  fi
  exit "$rc"
}
trap restore_before_migration EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

docker compose config --quiet
docker compose build backend frontend

active_measurements() {
  docker compose exec -T postgres psql -U ai_tracker -d ai-tracker \
    -Atc "SELECT count(*) FROM project_measurements WHERE status='running'"
}
test "$(active_measurements)" = 0 || {
  echo 'Есть активные замеры. Повторите деплой, когда они закончатся.' >&2
  exit 1
}

frontend_stopped=true
docker compose stop frontend
test "$(active_measurements)" = 0 || {
  echo 'Пока останавливался интерфейс, начался замер. Повторите деплой позже.' >&2
  exit 1
}

backend_stopped=true
docker compose stop backend
migration_started=true
docker compose run --rm --no-deps -T migrate < /dev/null
docker compose up -d --no-deps backend frontend

healthy=false
for _ in $(seq 1 24); do
  if curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8000/api/projects >/dev/null \
    && curl --fail --silent --show-error --max-time 10 http://127.0.0.1:3001/clustering/tracker/ >/dev/null; then
    healthy=true
    break
  fi
  sleep 5
done
test "$healthy" = true || { echo 'Проверка после деплоя не прошла.' >&2; exit 1; }

finished=true
echo "deploy OK: $(git rev-parse --short HEAD)"
