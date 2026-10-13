# Деплой

`deploy.sh` выполняется на сервере. GitHub Actions передаёт его через SSH
из проверенного коммита; отдельный скрипт в YAML не дублируется.

Параметры:

```bash
bash deploy.sh COMMIT_SHA DEPLOY_DIR APP_ORIGIN
```

Для запуска с локальной машины:

```bash
commit=$(git rev-parse HEAD)
ssh myserver bash -s -- "$commit" /opt/ai-tracker https://dev.coresmart.tech < deploy/deploy.sh
```

Коммит должен быть опубликован и принадлежать истории `main`. Скрипт использует
существующий серверный checkout и `docker-compose.yml`, собирает образы на
сервере, проверяет активные замеры, останавливает сервисы, применяет миграции,
запускает приложение и проверяет API и интерфейс. Тома сохраняются.

При ошибке до начала миграций прежние контейнеры запускаются автоматически,
checkout возвращается на прежний коммит. После начала миграций автоматического
отката нет: workflow завершается ошибкой, состояние проверяют вручную.

В GitHub environment `production` нужны секреты `DEPLOY_SSH_KEY` и
`DEPLOY_KNOWN_HOSTS`. Переменные `DEPLOY_HOST`, `DEPLOY_PORT`, `DEPLOY_USER`,
`DEPLOY_DIR`, `APP_ORIGIN` необязательны: workflow содержит значения текущего
сервера. SSH-пользователю нужны доступ к checkout и Docker. На сервере нужны
Git, Bash, flock и curl.

Запуск: Actions → Deploy → Run workflow (ветка `main` либо тег `v*`) или push
тега `v*`. Перед обновлением выполняется CI того же коммита.
