from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / '.env', override=False)


@dataclass
class Settings:
    base_dir: Path = BASE_DIR
    db_path: Path = BASE_DIR / 'database' / 'foreign_trade.db'
    uploads_dir: Path = BASE_DIR / 'uploads'
    outputs_dir: Path = BASE_DIR / 'outputs'
    templates_dir: Path = BASE_DIR / 'templates'
    system_templates_dir: Path = BASE_DIR / 'system_templates'
    env_file: Path = BASE_DIR / '.env'

    @staticmethod
    def from_env() -> 'Settings':
        obj = Settings()
        obj.db_path = Path(os.getenv('DB_PATH', str(obj.db_path)))
        obj.uploads_dir = Path(os.getenv('UPLOADS_DIR', str(obj.uploads_dir)))
        obj.outputs_dir = Path(os.getenv('OUTPUTS_DIR', str(obj.outputs_dir)))
        obj.templates_dir = Path(os.getenv('TEMPLATES_DIR', str(obj.templates_dir)))
        obj.env_file = Path(os.getenv('ENV_FILE', str(obj.env_file)))
        return obj


settings = Settings.from_env()


def ensure_directories() -> None:
    for directory in [
        settings.db_path.parent,
        settings.uploads_dir,
        settings.outputs_dir,
        settings.templates_dir,
        settings.system_templates_dir,
    ]:
        directory.mkdir(parents=True, exist_ok=True)
