from contextlib import contextmanager
import pyodbc, time
from typing import Iterator, Optional
from configs.db_config import DB_CONFIG
from scripts.utils.log_utils import init_runtime_logger

logger = init_runtime_logger()

def maybe_open(conn: Optional[pyodbc.Connection]):
    if conn is not None:
        return conn, False
    return get_connection(), True

def _mask(s: str) -> str:
    return s[:2] + "****" if s else s

def get_connection(retries: int = 3) -> pyodbc.Connection:
    """
    DB 연결 객체 반환
    
    Returns: 
        pyodbc.Connection: DB 연결 객체
    """

    host   = DB_CONFIG["host"]
    port   = DB_CONFIG["port"]
    db     = DB_CONFIG["database"]
    user   = DB_CONFIG["user"]
    pwd    = DB_CONFIG["password"]

   #server = f"tcp:{host},{port}"
    server = f"{host},{port}"
    
    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={server};"
        f"DATABASE={db};"
        f"UID={user};"
        f"PWD={pwd};"
        "Encrypt=Yes;"
        "TrustServerCertificate=Yes;"   # ← 임시로 검증 생략해서 먼저 연결 확인
        "Connection Timeout=15;"
       # "LoginTimeout=15;"
    )

    last_err = None
    for i in range(retries):
        try:
            logger.debug("[DB] connecting to %s / db=%s (user=%s)",
                         server, db, _mask(user))
            return pyodbc.connect(conn_str)
        except pyodbc.Error as e:
            last_err = e
            wait = 2 ** i
            logger.warning("[DB] connect failed (try=%d) -> %s; retry in %ss",
                           i+1, e, wait)
            time.sleep(wait)
    # 재시도 후에도 실패
    logger.error("[DB] connect permanently failed: %s", last_err)
    raise last_err

@contextmanager
def transaction(conn: Optional[pyodbc.Connection]) -> Iterator[pyodbc.Connection]:
    """
    한 단위 작업을 원자적으로 커밋/롤백.
    외부 커넥션이면 닫지 않고, 내부에서 열면 닫아줌.
    autocommit=False면: 블록 성공 시 commit, 예외 시 rollback.
    """
    c, close_after = maybe_open(conn)
    try:
        yield c
        if not getattr(c, "autocommit", False):
            c.commit()
    except Exception:
        if not getattr(c, "autocommit", False):
            c.rollback()
        raise
    finally:
        if close_after:
            c.close()