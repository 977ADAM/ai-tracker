"""One isolated browser flow through real BFF and backend persistence."""

import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.isolated_projects
ROOT = Path(__file__).resolve().parents[2]


def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def project_instance(tmp_path):
    api_port, ui_port = port(), port()
    env = {
        **os.environ,
        "AI_TRACKER_CONFIG_DIR": str(tmp_path / "data"),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
        "AI_TRACKER_API_URL": f"http://127.0.0.1:{api_port}",
    }
    logs = []
    processes = []
    try:
        for name, args, cwd in [
            (
                "api",
                [
                    str(ROOT / "backend/.venv/bin/python"),
                    "-m",
                    "uvicorn",
                    "project_test_server:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                ],
                ROOT / "qa",
            ),
            (
                "ui",
                [
                    str(ROOT / "frontend/node_modules/.bin/vite"),
                    "dev",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(ui_port),
                    "--strictPort",
                ],
                ROOT / "frontend",
            ),
        ]:
            log = open(tmp_path / f"{name}.log", "w")
            logs.append(log)
            processes.append(
                subprocess.Popen(
                    args, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT
                )
            )
        for endpoint in [
            f"http://127.0.0.1:{api_port}/api/projects",
            f"http://127.0.0.1:{ui_port}/",
        ]:
            deadline = time.monotonic() + 30
            while True:
                try:
                    with urlopen(endpoint, timeout=1) as response:
                        assert response.status == 200
                    break
                except Exception:
                    if time.monotonic() > deadline:
                        pytest.fail(
                            "Isolated services failed: "
                            + "".join(p.read_text() for p in tmp_path.glob("*.log"))
                        )
                    time.sleep(0.1)
        yield f"http://127.0.0.1:{ui_port}"
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log in logs:
            log.close()


def test_project_creation_configuration_two_measurements_and_delete(
    page, project_instance, tmp_path
):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.set_viewport_size({"width": 375, "height": 850})
    page.goto(project_instance)
    page.get_by_role("link", name="Создать проект", exact=True).click()
    expect(page.get_by_label("Название бренда")).to_be_visible()
    expect(page.get_by_label("Название проекта", exact=True)).to_have_count(0)
    expect(page.get_by_label("Запрос 1", exact=True)).to_have_count(0)
    page.get_by_label("Название бренда").fill("Додопицца")
    page.get_by_label("Сайт", exact=True).fill("example.ru")
    page.get_by_role("button", name="✓ Далее").click()
    expect(page.get_by_role("heading", name="Описание", exact=True)).to_be_visible()
    expect(page.get_by_label("Описание бренда")).to_have_value("Сеть пиццерий", timeout=15000)
    expect(page.get_by_label("Варианты названия бренда")).to_have_value("Додошка\ndodo")
    page.set_viewport_size({"width":1280,"height":900})
    page.screenshot(path=str(tmp_path / "wizard-description.png"), full_page=True)
    page.set_viewport_size({"width":375,"height":850})
    page.get_by_label("Описание бренда").fill("Сеть пиццерий и доставки")
    page.get_by_role("button", name="Продолжить позже").click()
    page.get_by_role("link", name="Мастер настройки").click()
    expect(page.get_by_label("Промпт 1", exact=True)).to_have_value("Где заказать пиццу?", timeout=15000)
    page.get_by_role('tab',name='Из списка').click()
    def importing(route):
        expect(page.get_by_role('button',name='✓ Далее')).to_be_disabled()
        route.continue_()
    page.route('**/api/projects/import-prompts',importing)
    page.get_by_label('Загрузить промпты файлом').set_input_files(str(ROOT/'frontend/static/templates/prompts.xlsx'))
    expect(page.get_by_label('Список промптов')).to_have_value('Где заказать пиццу?\nКакая доставка работает вечером?')
    page.unroute('**/api/projects/import-prompts',importing)
    page.get_by_label('Список промптов').fill('Где заказать вкусную пиццу?\nКакая доставка работает вечером?')
    page.get_by_role('tab',name='Генерация').click()
    expect(page.get_by_label('Группа промпта 1')).to_have_value('Пицца')
    page.get_by_role("button", name="✓ Далее").click()
    expect(page.get_by_role("heading", name="Бренды конкурентов", exact=True)).to_be_visible()
    page.get_by_label('Бренд или сайт конкурента').fill('Pizza Hut')
    page.get_by_role('button',name='＋ Добавить',exact=True).click()
    page.get_by_role("button", name="✓ Далее").click()
    page.get_by_label("Выбрать все нейросети").check()
    page.get_by_role("button", name="✓ Далее").click()
    expect(page.get_by_role("heading", name="Запуск", exact=True)).to_be_visible()
    # Confirming setup never launches a paid measurement by itself.
    projects = page.request.get(project_instance+"/api/projects").json()["items"]
    assert projects[0]["active_measurement"] is None and projects[0]["latest_measurement"] is None
    page.get_by_role("button", name="↻ Создать и запустить проверку").click()
    expect(page.locator("[data-measurement-report]")).to_contain_text(
        "2 из 2", timeout=15000
    )
    expect(page.get_by_role("button", name="Читать полностью").first).to_be_visible(
        timeout=15000
    )
    page.get_by_role("button", name="Читать полностью").first.click()
    expect(page.get_by_role("dialog")).to_contain_text("Оценка служебной модели")
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Обновить",exact=True).click()
    expect(page.get_by_role("button", name="Удалить замер")).to_have_count(
        2, timeout=15000
    )
    page.get_by_role('button',name='Источники упоминаний').click()
    expect(page.get_by_role('heading',name='Цитирование сайта моделями')).to_be_visible()
    expect(page.get_by_role('heading',name='Видимость в ИИ')).to_have_count(0)
    page.get_by_role('button',name='Все упоминания').click()
    page.get_by_role('button',name='Изменить название проекта').click()
    page.get_by_label('Название проекта',exact=True).fill('Пицца — шапка')
    page.get_by_role('button',name='Сохранить',exact=True).click()
    expect(page.get_by_role('heading',name='Пицца — шапка',exact=True)).to_be_visible()
    page.set_viewport_size({'width':1650,'height':940})
    page.screenshot(path=str(tmp_path/'project-header.png'),full_page=False)
    page.set_viewport_size({'width':375,'height':850})
    page.get_by_role('link',name='Настройки',exact=True).click()
    expect(page.get_by_label('Сайт конкурента 1',exact=True)).to_have_value('')
    page.get_by_label('Название проекта',exact=True).fill('Пицца — проверено')
    page.get_by_role('button',name='Сохранить проект').click()
    page.get_by_role("link", name="Проекты",exact=True).click()
    expect(page.locator("[data-project-card]")).to_contain_text("100%")
    page.screenshot(path=str(tmp_path / "projects-mobile.png"), full_page=True)
    page.set_viewport_size({"width": 1280, "height": 900})
    page.screenshot(path=str(tmp_path / "projects.png"), full_page=True)
    page.get_by_role("button", name="Удалить проект Пицца — проверено").click()
    page.get_by_role("button", name="Удалить", exact=True).click()
    expect(page.get_by_role("heading", name="Ваш первый проект")).to_be_visible()
    assert errors == []
