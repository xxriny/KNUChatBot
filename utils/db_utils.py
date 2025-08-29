"""
utils/db_utils.py

이 모듈은 데이터베이스 연결 및 공통 삽입 로직을 정의한 유틸리티입니다.

기능:
- get_connection: DB 연결 객체 생성
- insert_and_return_id: 데이터 삽입 후 생성된 PK(ID) 반환
- insert_data: 일반적인 INSERT 쿼리 실행

다양한 스크립트에서 공통적으로 사용하는 DB 연동 코드를 재사용 가능하게 정리했습니다.
"""

from configs.db_config import DB_CONFIG
import pyodbc

def get_connection():
    """
    DB 연결 객체 반환
    
    Returns: 
        pyodbc.Connection: DB 연결 객체
    """
    conn_str = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={DB_CONFIG['host']}, {DB_CONFIG['port']};"
        f"DATABASE={DB_CONFIG['database']};"
        f"UID={DB_CONFIG['user']};"
        f"PWD={DB_CONFIG['password']}"
    )

    return pyodbc.connect(conn_str)

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
    
    conn = None
    cursor = None

    placeholders = ", ".join(["?"] * len(values))
    columns_str = ", ".join(columns)
    # OUTPUT 절 추가!
    sql = f"""
    INSERT INTO {table_name} ({columns_str})
    OUTPUT INSERTED.id
    VALUES ({placeholders})
    """

    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute(sql, values)
        inserted_id = cursor.fetchone()[0]

        conn.commit()
        return inserted_id

    except Exception as e:
        print(f"[INSERT+ID ERROR] - {e.__class__.__name__} - {e}\n")
        if conn:
            conn.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

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
        
        # SQL 실행 (values는 ? 자리표시자에 자동 바인딩)
        cursor.execute(sql, values)
        
        # DB에 변경 사항 저장 (commit)
        conn.commit()
    except Exception as e:
        print(f"[INSERT ERROR] - {e.__class__.__name__} - {e}\n")
        if conn:
            conn.rollback() # 오류 발생 시 롤백
        raise
    finally:
        if cursor:
            cursor.close() # 커서 닫기
        if conn:
            conn.close() # DB 연결 종료
