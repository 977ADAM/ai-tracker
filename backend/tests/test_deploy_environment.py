"""Runtime and migration commands must resolve the same repository .env."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.core import database

BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("exported", [False, True])
def test_runtime_reads_root_env_without_overriding_exports(tmp_path, exported):
    module = tmp_path / "backend/app/core/config.py"
    module.parent.mkdir(parents=True)
    shutil.copy(BACKEND / "app/core/config.py", module)
    (tmp_path / ".env").write_text("AI_TRACKER_DATABASE_URL=postgresql://root/app\n")
    (tmp_path / "backend/.env").write_text(
        "AI_TRACKER_DATABASE_URL=postgresql://wrong/app\n"
    )
    env = dict(os.environ)
    env.pop("AI_TRACKER_DATABASE_URL", None)
    if exported:
        env["AI_TRACKER_DATABASE_URL"] = "postgresql://exported/app"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.core.config import load_env_file, Settings; load_env_file(); print(Settings.from_env().database_url)",
        ],
        cwd=module.parents[2],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == (
        "postgresql://exported/app" if exported else "postgresql://root/app"
    )


def test_alembic_reads_the_root_env(database_dsn, tmp_path):
    backend = tmp_path / "backend"
    shutil.copytree(BACKEND / "migrations", backend / "migrations")
    shutil.copy(BACKEND / "alembic.ini", backend / "alembic.ini")
    module = backend / "app/core/config.py"
    module.parent.mkdir(parents=True)
    shutil.copy(BACKEND / "app/core/config.py", module)
    (tmp_path / ".env").write_text(f"AI_TRACKER_DATABASE_URL={database_dsn}\n")
    (backend / "migrations/versions/env_probe.py").write_text(
        "revision = 'env_probe'\ndown_revision = '0001_projects_root'\n"
        "def upgrade(): pass\ndef downgrade(): pass\n"
    )
    env = dict(os.environ)
    env.pop("AI_TRACKER_DATABASE_URL", None)
    with database.connect(database_dsn) as db:
        db.execute("UPDATE alembic_version SET version_num='env_probe'")
        db.commit()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "current"],
            cwd=backend,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    finally:
        with database.connect(database_dsn) as db:
            db.execute("UPDATE alembic_version SET version_num='0001_projects_root'")
            db.commit()
    assert result.returncode == 0, result.stderr
    assert "env_probe" in result.stdout
