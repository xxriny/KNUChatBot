import pyodbc
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

conn = pyodbc.connect(
    f"DRIVER={{ODBC Driver 18 for SQL Server}};"
    f"SERVER={os.getenv('DB_SERVER')};"
    f"DATABASE={os.getenv('DB_NAME')};"
    f"UID={os.getenv('DB_USER')};"
    f"PWD={os.getenv('DB_PASSWORD')};"
    f"Encrypt=no;"
)


cursor = conn.cursor()

topic = "공모전"
department = "컴퓨터"
sort_option = "마감순"  # 또는 최신순, 오래된순

today = datetime.today().date()
topic = topic.replace(' ', '').lower()
department = department.replace(' ', '').lower()


query = """
SELECT DISTINCT
    n.id, n.title, n.deadline, n.oneline, n.topic, n.created_at, n.url,
    a.file_url,
    dep.departments
FROM dbo.notice n
JOIN (
    SELECT
        notice_id,
        STRING_AGG(department, ', ') AS departments
    FROM dbo.notice_department
    GROUP BY notice_id
) dep ON n.id = dep.notice_id
OUTER APPLY (
    SELECT TOP 1 file_url
    FROM dbo.notice_attachment
    WHERE notice_id = n.id
    ORDER BY file_order ASC
) a
WHERE n.id IN (
    SELECT notice_id
    FROM dbo.notice_department
    WHERE REPLACE(LOWER(department), ' ', '') LIKE ?
)
AND REPLACE(LOWER(n.topic), ' ', '') LIKE ?
AND (n.deadline IS NULL OR n.deadline >= ?)
"""

if sort_option == '마감순':
    query += " ORDER BY n.deadline ASC"
elif sort_option == '최신순':
    query += " ORDER BY n.created_at DESC"
elif sort_option == '오래된순':
    query += " ORDER BY n.created_at ASC"

cursor.execute(query, f"%{department[:2]}%", f"%{topic}%", today)
rows = cursor.fetchall()

for row in rows:
    print(f"[{row[0]}] {row[1]} | 마감일: {row[2]} | 요약: {row[3]} | 링크: {row[6]}")

print("💡 필터 조건 확인")
print("topic =", topic)
print("department =", department[:2])
print("날짜 =", today)
