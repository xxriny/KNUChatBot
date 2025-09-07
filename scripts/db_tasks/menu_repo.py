from __future__ import annotations
from typing import Optional, Iterable, Tuple
import pyodbc

from scripts.utils.db_utils import get_connection
from scripts.utils.log_utils import init_runtime_logger

logger = init_runtime_logger()

def _maybe_open(conn: Optional[pyodbc.Connection]):
    if conn is not None:
        return conn, False
    return get_connection(), True

def insert_menu_rows(
    conn: Optional[pyodbc.Connection],
    rows: Iterable[tuple[str, str, str, str, str]],
) -> int:
    """
    중복 허용일 때 빠르게 꽂기.
    """
    c, close_after = _maybe_open(conn)
    try:
        cur = c.cursor()
        cur.fast_executemany = True
        sql = """
        INSERT INTO dbo.cafeteria_menu
            (restaurant, menu_group, meal_type, service_date, menu)
        VALUES (?, ?, ?, ?, ?)
        """
        rows = list(rows)
        cur.executemany(sql, rows)
        c.commit()
        logger.info("[MENU_REPO] insert done - inserted=%d", len(rows))
        return len(rows)
    finally:
        if close_after: c.close()
