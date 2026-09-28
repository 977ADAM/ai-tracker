"""HTTP contract for safe, partial Yandex settings."""

from __future__ import annotations

import pytest

from app.db.search_settings import SearchSettingsRepository


def test_get_returns_exact_safe_fields_for_mixed_sources(make_client, settings, secrets):
    repository = SearchSettingsRepository(
        settings.config_dir, secrets, env_api_key="env-secret",
        env_folder_id="env-folder", service_name=settings.service_name,
    )
    repository.update({"api_key": "ui-secret"})
    with make_client(search_settings_repository=repository) as client:
        response = client.get("/api/search/settings")
    assert response.status_code == 200
    assert response.json() == {"yandex": {
        "enabled": True, "folder_id": "env-folder", "has_api_key": True,
        "api_key_source": "ui", "folder_id_source": "env",
    }}
    assert "secret" not in response.text


def test_partial_put_and_empty_credentials_preserve_saved_values(make_client):
    with make_client() as client:
        assert client.put("/api/search/settings", json={"api_key": "hidden-key", "folder_id": "saved-folder"}).status_code == 200
        response = client.put("/api/search/settings", json={"enabled": False, "api_key": "", "folder_id": ""})
        assert response.status_code == 200
        assert response.json() == {"yandex": {
            "enabled": False, "folder_id": "saved-folder", "has_api_key": True,
            "api_key_source": "ui", "folder_id_source": "ui",
        }}
        assert "hidden-key" not in response.text
        assert client.get("/api/search/settings").json() == response.json()


def test_put_rejects_null_wrong_type_and_unknown_fields(make_client):
    with make_client() as client:
        for payload in ({"api_key": None}, {"folder_id": None}, {"enabled": None},
                        {"enabled": "false"}, {"other": "value"}):
            response = client.put("/api/search/settings", json=payload)
            assert response.status_code == 400, payload
            assert isinstance(response.json()["detail"], str)


def test_delete_resets_both_overrides_and_preserves_enabled(make_client, settings, secrets):
    repository = SearchSettingsRepository(
        settings.config_dir, secrets, env_api_key="env-secret",
        env_folder_id="env-folder", service_name=settings.service_name,
    )
    with make_client(search_settings_repository=repository) as client:
        client.put("/api/search/settings", json={"enabled": False, "api_key": "ui-secret", "folder_id": "ui-folder"})
        response = client.delete("/api/search/settings/credentials")
        assert response.status_code == 200
        assert response.json() == {"yandex": {
            "enabled": False, "folder_id": "env-folder", "has_api_key": True,
            "api_key_source": "env", "folder_id_source": "env",
        }}
        assert "secret" not in response.text


def test_delete_noop_reports_no_environment_sources(make_client):
    with make_client() as client:
        response = client.delete("/api/search/settings/credentials")
        assert response.status_code == 200
        assert response.json() == {"yandex": {
            "enabled": True, "folder_id": None, "has_api_key": False,
            "api_key_source": "none", "folder_id_source": "none",
        }}


def _assert_model_configuration_and_model_only_run_work(client):
    import time

    from tests.fakes import ENDPOINT

    created = client.post("/api/providers", json={
        "name": "Рабочая модель", "kind": "openai", "endpoint": ENDPOINT,
        "model": "m", "api_key": "model-key",
    })
    assert created.status_code == 200
    provider_id = created.json()["id"]
    response = client.post("/api/runs", json={
        "brand": "Ромашка", "domain": "example.ru", "prompts_text": "цветы",
        "provider_ids": [provider_id], "regions": [],
    })
    assert response.status_code == 202
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        snapshot = client.get(f"/api/runs/{response.json()['id']}").json()
        if snapshot["status"] != "pending":
            break
        time.sleep(0.01)
    else:
        raise AssertionError("model-only run did not finish")
    assert snapshot["status"] == "done"
    assert snapshot["models"][0]["status"] == "mentioned"
    assert snapshot["search"] == []


@pytest.mark.parametrize("broken_file", ["malformed", "unreadable"])
def test_bad_search_metadata_does_not_block_model_configuration_or_runs(
    make_client, config_dir, settings, secrets, broken_file,
):
    from app.api.deps import get_container
    from tests.fakes import ProviderFactorySpy

    search_repository = SearchSettingsRepository(
        config_dir, secrets, env_api_key="env-key", env_folder_id="env-folder",
        service_name=settings.service_name,
    )
    path = config_dir / "search-settings.json"
    if broken_file == "malformed":
        path.write_text("{", encoding="utf-8")
    else:
        path.mkdir()
    with make_client(
        provider_factory=ProviderFactorySpy(), search_settings_repository=search_repository,
    ) as client:
        container = client.app.dependency_overrides[get_container]()
        assert container.search.gateway is None
        failure = client.get("/api/search/settings")
        assert failure.status_code == 503
        assert failure.json() == {"detail": "Не удалось прочитать настройки поиска"}
        assert str(config_dir) not in failure.text
        assert client.post("/api/search", json={
            "domain": "example.ru", "prompts_text": "цветы", "regions": [1],
        }).status_code == 400
        _assert_model_configuration_and_model_only_run_work(client)
        if path.is_dir():
            path.rmdir()
        path.write_text('{"enabled": true}', encoding="utf-8")
        assert client.get("/api/search/settings").status_code == 200
        assert container.search.gateway is not None


def test_search_keyring_read_failure_does_not_block_models_and_recovers(
    make_client, settings, secrets,
):
    from app.api.deps import get_container
    from tests.fakes import ProviderFactorySpy

    search_repository = SearchSettingsRepository(
        settings.config_dir, secrets, env_api_key="env-key", env_folder_id="env-folder",
        service_name=settings.service_name,
    )
    original_get = secrets.get_password

    def fail_yandex(service, username):
        if username == "yandex-search":
            raise RuntimeError("private keyring path")
        return original_get(service, username)

    secrets.get_password = fail_yandex
    with make_client(
        provider_factory=ProviderFactorySpy(), search_settings_repository=search_repository,
    ) as client:
        container = client.app.dependency_overrides[get_container]()
        assert container.search.gateway is None
        failure = client.get("/api/search/settings")
        assert failure.status_code == 400
        assert failure.json() == {"detail": "Системное хранилище ключей недоступно"}
        assert "private keyring path" not in failure.text
        _assert_model_configuration_and_model_only_run_work(client)
        secrets.get_password = original_get
        restored = client.put("/api/search/settings", json={
            "api_key": "search-key", "folder_id": "search-folder",
        })
        assert restored.status_code == 200
        assert restored.json()["yandex"]["has_api_key"] is True
        assert container.search.gateway is not None


def _hold_first_metadata_write(repository):
    from threading import Event, Lock

    first_write_started = Event()
    second_read_started = Event()
    release_first_write = Event()
    counter_lock = Lock()
    reads = 0
    writes = 0
    original_read = repository._read
    original_write = repository._write

    def counted_read():
        nonlocal reads
        with counter_lock:
            reads += 1
            if reads == 2:
                second_read_started.set()
        return original_read()

    def held_write(data):
        nonlocal writes
        with counter_lock:
            writes += 1
            first = writes == 1
        if first:
            first_write_started.set()
            assert release_first_write.wait(3)
        return original_write(data)

    repository._read = counted_read
    repository._write = held_write
    return first_write_started, second_read_started, release_first_write


def test_concurrent_partial_puts_serialize_metadata_and_runtime(
    make_client, settings, secrets,
):
    from concurrent.futures import ThreadPoolExecutor

    repository = SearchSettingsRepository(
        settings.config_dir, secrets, env_api_key=None,
        env_folder_id=None, service_name=settings.service_name,
    )
    with make_client(search_settings_repository=repository) as client:
        from threading import Event

        from app.api.deps import get_container

        container = client.app.dependency_overrides[get_container]()
        second_handler = Event()
        original_update = container.search_settings.update

        def record_update(payload):
            if payload == {"enabled": False}:
                second_handler.set()
            return original_update(payload)

        container.search_settings.update = record_update
        first_write, second_read, release = _hold_first_metadata_write(repository)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(client.put, "/api/search/settings", json={"folder_id": "saved-folder"})
            assert first_write.wait(2)
            second = pool.submit(client.put, "/api/search/settings", json={"enabled": False})
            try:
                assert second_handler.wait(2)
                assert not second_read.wait(0.3), "second PUT read stale metadata before the first write finished"
            finally:
                release.set()
            assert first.result(timeout=2).status_code == 200
            assert second.result(timeout=2).status_code == 200
        assert container.search.enabled is False
        assert container.search.gateway is None
        assert client.get("/api/search/settings").json() == {"yandex": {
            "enabled": False, "folder_id": "saved-folder", "has_api_key": False,
            "api_key_source": "none", "folder_id_source": "ui",
        }}


def test_concurrent_put_then_delete_resets_both_overrides_after_put(
    make_client, settings, secrets,
):
    from concurrent.futures import ThreadPoolExecutor

    repository = SearchSettingsRepository(
        settings.config_dir, secrets, env_api_key=None,
        env_folder_id=None, service_name=settings.service_name,
    )
    with make_client(search_settings_repository=repository) as client:
        from threading import Event

        from app.api.deps import get_container

        container = client.app.dependency_overrides[get_container]()
        assert client.put("/api/search/settings", json={
            "enabled": False, "api_key": "old-key", "folder_id": "old-folder",
        }).status_code == 200
        second_handler = Event()
        original_reset = container.search_settings.reset_credentials

        def record_reset():
            second_handler.set()
            return original_reset()

        container.search_settings.reset_credentials = record_reset
        first_write, second_read, release = _hold_first_metadata_write(repository)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(client.put, "/api/search/settings", json={
                "enabled": True, "folder_id": "new-folder",
            })
            assert first_write.wait(2)
            second = pool.submit(client.delete, "/api/search/settings/credentials")
            try:
                assert second_handler.wait(2)
                assert not second_read.wait(0.3), "DELETE read stale metadata before PUT finished"
            finally:
                release.set()
            assert first.result(timeout=2).status_code == 200
            assert second.result(timeout=2).status_code == 200
        assert container.search.enabled is True
        assert container.search.gateway is None
        assert client.get("/api/search/settings").json() == {"yandex": {
            "enabled": True, "folder_id": None, "has_api_key": False,
            "api_key_source": "none", "folder_id_source": "none",
        }}
