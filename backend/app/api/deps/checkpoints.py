"""Infrastructure of the SEO agent graph: the checkpoint file of one config dir.

Graph state is disposable and lives beside `runs.sqlite3`, never inside it. The
runtime passes the analysis id as the graph's `thread_id`, so one file holds the
thread of every analysis and a restart finds exactly the run it needs.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.service.seo_agents import (
    CheckpointFactory,
    checkpoint_exists,
    checkpoint_path,
    secure_checkpoint,
)


def agent_checkpointer(config_dir: Path) -> CheckpointFactory:
    """Return the factory of the owner-only graph checkpoint file."""
    path = checkpoint_path(config_dir)

    @asynccontextmanager
    async def open_checkpointer(_analysis_id: str):
        secure_checkpoint(path)
        async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
            yield saver

    return open_checkpointer


def checkpoint_probe(config_dir: Path) -> Callable[[str], bool]:
    """Return the synchronous restart probe over one config directory."""
    path = checkpoint_path(config_dir)
    return lambda analysis_id: checkpoint_exists(path, analysis_id)
