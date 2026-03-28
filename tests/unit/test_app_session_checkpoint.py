from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from bom_workbench.app import (
    _load_session_checkpoint,
    _merge_restart_warning,
    _resolve_session_checkpoint_path,
    _save_session_checkpoint,
    _select_restore_project_id,
)
from bom_workbench.infrastructure.persistence.database import DatabaseSettings


@dataclass
class _Project:
    id: int


def test_session_checkpoint_round_trip(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "session.json"

    _save_session_checkpoint(
        checkpoint_path,
        {"project_id": 12, "project_name": "demo", "selected_row_id": 5},
    )

    loaded = _load_session_checkpoint(checkpoint_path)

    assert loaded == {"project_id": 12, "project_name": "demo", "selected_row_id": 5}


def test_resolve_session_checkpoint_path_uses_database_directory(tmp_path: Path) -> None:
    settings = DatabaseSettings(db_dir=tmp_path, db_file_name="custom.db")

    checkpoint_path = _resolve_session_checkpoint_path(settings)

    assert checkpoint_path == tmp_path / "bom_workbench.session.json"


def test_select_restore_project_id_prefers_checkpoint_then_latest() -> None:
    projects = [_Project(2), _Project(5), _Project(9)]

    assert _select_restore_project_id({"project_id": 5}, projects) == 5
    assert _select_restore_project_id({"project_id": 77}, projects) == 9
    assert _select_restore_project_id({}, projects) == 9


def test_merge_restart_warning_appends_once() -> None:
    message = "Restored after app restart while enrichment had not completed."

    merged = _merge_restart_warning("", message)
    loaded = json.loads(merged)
    assert loaded == [message]

    merged_again = _merge_restart_warning(merged, message)
    loaded_again = json.loads(merged_again)
    assert loaded_again == [message]
