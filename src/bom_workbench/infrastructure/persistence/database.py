"""SQLite persistence primitives for BOM Workbench."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

DEFAULT_DB_DIR_NAME = "data"
DEFAULT_DB_FILE_NAME = "bom_workbench.db"
IN_MEMORY_SQLITE_URL = "sqlite://"


@dataclass(slots=True, frozen=True)
class DatabaseSettings:
    """Settings used to resolve the SQLModel SQLite database."""

    db_path: Path | None = None
    db_dir: Path | None = None
    db_file_name: str = DEFAULT_DB_FILE_NAME
    in_memory: bool = False

    @classmethod
    def from_env(cls) -> DatabaseSettings:
        """Build database settings from environment variables."""

        in_memory = os.getenv("BOM_WORKBENCH_DB_IN_MEMORY", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        db_path_value = os.getenv("BOM_WORKBENCH_DB_PATH")
        db_dir_value = os.getenv("BOM_WORKBENCH_DB_DIR")
        db_file_name = os.getenv("BOM_WORKBENCH_DB_FILE", DEFAULT_DB_FILE_NAME)

        return cls(
            db_path=Path(db_path_value).expanduser() if db_path_value else None,
            db_dir=Path(db_dir_value).expanduser() if db_dir_value else None,
            db_file_name=db_file_name,
            in_memory=in_memory,
        )


def get_default_database_path(settings: DatabaseSettings | None = None) -> Path:
    """Resolve the on-disk SQLite file path."""

    resolved_settings = settings or DatabaseSettings()
    if resolved_settings.db_path is not None:
        return resolved_settings.db_path.expanduser().resolve()

    base_dir = resolved_settings.db_dir
    if base_dir is None:
        base_dir = Path.cwd() / DEFAULT_DB_DIR_NAME

    return (base_dir.expanduser().resolve() / resolved_settings.db_file_name)


def get_database_url(settings: DatabaseSettings | None = None) -> str:
    """Return a SQLAlchemy SQLite URL for the provided settings."""

    resolved_settings = settings or DatabaseSettings()
    if resolved_settings.in_memory:
        return IN_MEMORY_SQLITE_URL

    database_path = get_default_database_path(resolved_settings)
    return f"sqlite:///{database_path.as_posix()}"


def create_engine_from_settings(settings: DatabaseSettings | None = None) -> Engine:
    """Create a SQLAlchemy engine configured for SQLModel sessions."""

    resolved_settings = settings or DatabaseSettings()
    url = get_database_url(resolved_settings)

    if resolved_settings.in_memory:
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    database_path = get_default_database_path(resolved_settings)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        url,
        connect_args={"check_same_thread": False},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a standard sync session factory bound to the provided engine."""

    return sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


def create_session(engine: Engine) -> Session:
    """Create a sync SQLModel session for repository wrappers."""

    return Session(engine)


def create_db_and_tables(engine: Engine) -> None:
    """Create all SQLModel tables for the current metadata."""

    SQLModel.metadata.create_all(engine)
