"""Runtime configuration, resolved from environment variables with safe defaults."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent


@dataclass(frozen=True)
class Settings:
    """Immutable application settings.

    Every value can be overridden with a ``CERTPREP_*`` environment variable so
    the server can be configured without touching the source.
    """

    host: str = "0.0.0.0"
    port: int = 8000
    data_dir: Path = PROJECT_ROOT / "data"
    db_path: Path = PROJECT_ROOT / "results.db"
    static_dir: Path = PACKAGE_DIR / "static"
    templates_dir: Path = PACKAGE_DIR / "templates"
    max_json_bytes: int = 1 * 1024 * 1024
    max_upload_bytes: int = 10 * 1024 * 1024

    @property
    def catalog_path(self) -> Path:
        return self.data_dir / "catalog.json"

    @property
    def questions_dir(self) -> Path:
        return self.data_dir / "questions"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        defaults = cls()
        return cls(
            host=env.get("CERTPREP_HOST", defaults.host),
            port=int(env.get("CERTPREP_PORT", defaults.port)),
            data_dir=Path(env.get("CERTPREP_DATA_DIR", defaults.data_dir)),
            db_path=Path(env.get("CERTPREP_DB", defaults.db_path)),
        )
