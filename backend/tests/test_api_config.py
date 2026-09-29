"""The configuration document: every stored setting, and never a key.

The document is what the interface shows in its configuration window, so the
tests prove the three sections appear together, that an absent file is `null`
instead of a missing section, that a broken file stays readable, and that no API
key can reach the document.
"""

from __future__ import annotations

import json

SETTINGS_BODY = {
    "name": "DeepSeek", "endpoint": "https://api.deepseek.com/chat/completions",
    "api_key": "shared-secret",
    "models": [{"model": "deepseek-chat", "name": "DeepSeek Chat"}],
}

SEO_BODY = {
    "endpoint": "https://llm.example.com/v1/chat/completions",
    "model": "seo-model",
    "api_key": "seo-secret",
}


def read_config(client) -> dict:
    response = client.get("/api/config")
    assert response.status_code == 200
    return response.json()


def sections(client) -> dict:
    body = read_config(client)
    assert body["exists"] is True
    return json.loads(body["content"])


def test_an_empty_directory_reports_nothing_stored(client, config_dir):
    body = read_config(client)

    assert body == {"directory": str(config_dir), "exists": False, "content": None}


def test_the_document_carries_every_section(client, config_dir):
    assert client.post("/api/providers/settings", json=SETTINGS_BODY).status_code == 200
    assert client.put("/api/seo/settings", json=SEO_BODY).status_code == 200
    assert client.put("/api/search/settings", json={"enabled": True, "folder_id": "folder-1"}).status_code == 200

    body = read_config(client)
    assert body["directory"] == str(config_dir)
    document = sections(client)

    # All three settings resources are in one document, in reading order.
    assert list(document) == ["providers", "search", "seo"]
    assert document["providers"]["groups"][0]["name"] == "DeepSeek"
    assert document["search"]["folder_id"] == "folder-1"
    assert document["seo"]["model"] == "seo-model"
    # The document is a stored-settings view: no key is in any of the files.
    assert "shared-secret" not in body["content"]
    assert "seo-secret" not in body["content"]


def test_a_section_that_was_never_saved_is_null(client, config_dir):
    assert client.post("/api/providers/settings", json=SETTINGS_BODY).status_code == 200

    document = sections(client)

    assert document["providers"] is not None
    assert document["search"] is None
    assert document["seo"] is None


def test_a_broken_file_stays_readable_and_hides_no_other_section(client, config_dir):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "providers.json").write_text("{", encoding="utf-8")
    assert client.put("/api/seo/settings", json=SEO_BODY).status_code == 200

    document = sections(client)

    # The broken file is shown as its own text, and the others still parse.
    assert document["providers"] == "{"
    assert document["seo"]["model"] == "seo-model"


def test_an_oversized_file_is_refused_with_a_safe_error(client, config_dir):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "providers.json").write_text("x" * (300 * 1024), encoding="utf-8")

    response = client.get("/api/config")

    assert response.status_code == 400
    assert response.json()["detail"] == "Файл конфигурации слишком большой"
