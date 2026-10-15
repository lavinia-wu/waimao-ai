from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
from typing import Optional

from config.settings import settings


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(settings.db_path)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def execute_scalar(query: str, params: tuple = ()) -> Optional[object]:
    with get_connection() as conn:
        row = conn.execute(query, params).fetchone()
        if row is None:
            return None
        return row[0]
