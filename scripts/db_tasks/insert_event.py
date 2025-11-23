import csv, pyodbc
from dateutil import parser
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

CSV_PATH = "../../data/rad_academic_calendar_2025.csv"  # 지금 올리신 파일 경로
CONN_STR = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={os.getenv('DB_SERVER')};"
        f"DATABASE={os.getenv('DB_NAME')};"
        f"UID={os.getenv('DB_USER')};"
        f"PWD={os.getenv('DB_PASSWORD')};"
        f"Encrypt=no;"
    )


def to_date(s):
    s = (s or "").strip()
    if not s: return None
    return parser.parse(s, yearfirst=True, dayfirst=False).date()

rows = []
with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
    r = csv.DictReader(f)
    for row in r:
        title = (row.get("title") or "").strip()
        sd = to_date(row.get("start_date"))
        ed = to_date(row.get("end_date")) or sd
        if title and sd:
            rows.append((title, sd, ed))

with pyodbc.connect(CONN_STR) as conn:
    cur = conn.cursor()
    # MERGE로 “있으면 그대로, 없으면 INSERT” — 실행을 여러 번 돌려도 중복 안 생깁니다.
    for chunk_start in range(0, len(rows), 500):
        chunk = rows[chunk_start : chunk_start+500]
        params = []
        for title, sd, ed in chunk:
            params.extend([title, sd, ed])
        values_clause = " UNION ALL ".join(["SELECT ?, ?, ?"] * len(chunk))
        sql = f"""
        MERGE dbo.academic_event AS T
        USING ({values_clause}) AS S(title, start_date, end_date)
        ON  T.title = S.title AND T.start_date = S.start_date AND T.end_date = S.end_date
        WHEN NOT MATCHED THEN
          INSERT (title, start_date, end_date) VALUES (S.title, S.start_date, S.end_date);
        """
        cur.execute(sql, params)
    conn.commit()

print(f"완료: {len(rows)}행 처리")
