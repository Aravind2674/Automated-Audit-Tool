"""
Database engine and session handling.

The connection URL comes from the DATABASE_URL environment variable (loaded from
.env), never from a hardcoded string -- see CLAUDE.md Section 6 and the Phase 7
requirement that grepping the codebase for secrets returns nothing.
"""

from __future__ import annotations

import os
import pathlib

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.schema import Base

REPO_ROOT = pathlib.Path(__file__).parent.parent

DEFAULT_URL = "postgresql+psycopg://audit:@localhost:5432/audit_tool"


class DatabaseNotConfigured(Exception):
    """Raised when DATABASE_URL is absent or the server is unreachable."""


def database_url() -> str:
    load_dotenv(REPO_ROOT / ".env")
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise DatabaseNotConfigured(
            "DATABASE_URL is not set. Copy .env.example to .env and fill it in."
        )
    return url


def get_engine(url: str | None = None, echo: bool = False):
    return create_engine(url or database_url(), echo=echo, future=True)


def get_sessionmaker(engine=None):
    return sessionmaker(bind=engine or get_engine(), future=True, expire_on_commit=False)


def create_schema(engine=None) -> None:
    """Create all tables defined in models.schema if they do not already exist."""
    Base.metadata.create_all(engine or get_engine())
