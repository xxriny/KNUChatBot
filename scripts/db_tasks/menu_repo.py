import pyodbc
from typing import Optional, Iterable
from scripts.utils.db_utils import maybe_open
from scripts.utils.log_utils import init_runtime_logger

logger = init_runtime_logger()

def insert_menu_rows(
    conn: Optional[pyodbc.Connection],
    rows: Iterable[tuple[str, str, str, str, str]],
) -> int:
    c, close_after = maybe_open(conn)
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
        logger.info("[MENU_REPO] insert done - inserted=%d", len(rows))
        return len(rows)
    finally:
        if close_after: c.close()
