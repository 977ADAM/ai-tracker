# Деплой

Пуш тега `v*` запускает Actions → Deploy. Сервер переключается на этот тег и выполняет `deploy/deploy.sh`.

```bash
git tag v0.1.0
git push origin v0.1.0
```

Тег должен уже быть на коммите, который запушен в `origin`. Пока идёт замер, деплой останавливается.

Ручной запуск без тега (Actions → Deploy → Run workflow) обновляет сервер до `origin/main`.
