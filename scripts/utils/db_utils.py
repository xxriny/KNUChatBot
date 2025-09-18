"""
utils/db_utils.py

이 모듈은 데이터베이스 연결 및 공통 삽입 로직을 정의한 유틸리티입니다.

기능:
- get_connection: DB 연결 객체 생성
- insert_and_return_id: 데이터 삽입 후 생성된 PK(ID) 반환
- insert_data: 일반적인 INSERT 쿼리 실행

다양한 스크립트에서 공통적으로 사용하는 DB 연동 코드를 재사용 가능하게 정리했습니다.
"""
import pyodbc, time
from typing import Optional
from configs.db_config import DB_CONFIG
from scripts.utils.log_utils import (
    init_runtime_logger,
    capture_unhandled_exception,
)

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

    server = f"tcp:{host},{port}"
    
    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={server};"
        f"DATABASE={db};"
        f"UID={user};"
        f"PWD={pwd};"
        "Encrypt=Yes;"
        "TrustServerCertificate=Yes;"   # ← 임시로 검증 생략해서 먼저 연결 확인
        "Connection Timeout=15;"
        "LoginTimeout=15;"
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
