from fastapi.testclient import TestClient

from ai_tracker.web import create_app


def test_home_page_has_check_form_and_limits_note():
    response = TestClient(create_app(allowed_hosts=["testserver"])).get("/")
    assert response.status_code == 200
    assert 'name="brand"' in response.text
    assert 'name="domain"' in response.text
    assert 'name="prompts"' in response.text
    assert 'type="submit"' in response.text
    assert "срез на момент проверки" in response.text.lower()
    assert "не проверяем ссылки" in response.text.lower()


def test_browser_assets_are_served():
    client = TestClient(create_app(allowed_hosts=["testserver"]))
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_settings_page_and_provider_controls():
    client = TestClient(create_app(allowed_hosts=["testserver"]))
    home = client.get("/").text
    settings = client.get("/settings")
    assert settings.status_code == 200
    assert 'id="provider-list"' in home
    assert 'href="/settings"' in home
    assert 'id="connections"' in settings.text
    assert 'id="connection-form"' in settings.text
    assert "OpenAI" in settings.text
    assert client.get("/static/settings.js").status_code == 200
    assert "Сбросить ключ" in client.get("/static/settings.js").text
    assert "срез на момент проверки" in home.lower()
