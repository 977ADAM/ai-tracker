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
