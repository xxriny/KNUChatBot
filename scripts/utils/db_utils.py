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

def _maybe_open(conn: Optional[pyodbc.Connection]):
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

def insert_and_return_id(table_name, columns, values):
    """
    데이터 삽입 후, 생성된 PK(ID) 반환 함수
 
    Args:
        table_name (str): 테이블 이름
        columns (list): 삽입할 컬럼 이름 리스트
        valus (list): 컬럼에 대응하는 값 리스트

    설명:
        - conn: DB에 접속한 연결 객체
        - cursor: DB에 SQL 명령을 전달하고 실행 결과를 다루는 객체
    """

    placeholders = ", ".join(["?"] * len(values))
    columns_str = ", ".join(columns)
    sql = f"""
    INSERT INTO {table_name} ({columns_str})
    OUTPUT INSERTED.id
    VALUES ({placeholders})
    """

    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        logger.debug("[DB] SQL: %s | values(len=%d)", sql, len(values))
        cursor.execute(sql, values)
        inserted_id = cursor.fetchone()[0]
        conn.commit()

        return inserted_id

    except Exception as e:
        capture_unhandled_exception(
            index=None,
            phase="DB",
            url=None,
            exc=e,
            extra={"table": table_name, "columns": columns},
        )
        if conn:
            try:
                conn.rollback()
            except Exception:
                logger.exception("[DB] rollback failed")
        raise
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                logger.exception("[DB] cursor close failed")
        if conn:
            try:
                conn.close()
            except Exception:
                logger.exception("[DB] connection close failed")

def insert_data(table_name, columns, values):
    """
    데이터 삽입 함수
    
    Args:
        table_name (str): 테이블 이름
        columns (list): 삽입할 컬럼 이름 리스트
        valus (list): 컬럼에 대응하는 값 리스트
    
    
    설명:
        - conn: DB에 접속한 연결 객체
        - cursor: DB에 SQL 명령을 전달하고 실행 결과를 다루는 객체
    """

    # 값 자리 표시자 (SQL Injection 방지)
    placeholders = ", ".join(["?"]* len(values))
    # SQL에 들어갈 컬럼 문자열
    columns_str = ", ".join(columns)
    # 최종 insert 쿼리 문자열 생성
    sql = f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders})"

    conn = None
    cursor = None

    try:
        conn = get_connection() #DB 연결 객체 생성
        cursor = conn.cursor() # 커서(cursor) 객체 생성 (SQL 실행 담당)

        logger.debug("[DB] SQL: %s | values(len=%d)", sql, len(values))
        
        # SQL 실행 (values는 ? 자리표시자에 자동 바인딩)
        cursor.execute(sql, values)
        # DB에 변경 사항 저장 (commit)
        conn.commit()


    except Exception as e:
        # 구조화(JSONL) + 런타임 로그 동시 기록
        capture_unhandled_exception(
            index=None,
            phase="DB",
            url=None,
            exc=e,
            extra={"table": table_name, "columns": columns},
        )
        if conn:
            try:
                conn.rollback()
            except Exception:
                logger.exception("[DB] rollback failed")
        raise
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                logger.exception("[DB] cursor close failed")
        if conn:
            try:
                conn.close()
            except Exception:
                logger.exception("[DB] connection close failed")
