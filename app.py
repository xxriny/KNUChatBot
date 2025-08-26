from flask import Flask, request, jsonify
import pyodbc
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

AZURE_BASE_URL = 'https://knuchat.azurewebsites.net'
DEFAULT_IMAGE = f"https://kchatsotrage.blob.core.windows.net/images/default.png"

def get_db_connection():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={os.getenv('DB_SERVER')};"
        f"DATABASE={os.getenv('DB_NAME')};"
        f"UID={os.getenv('DB_USER')};"
        f"PWD={os.getenv('DB_PASSWORD')};"
        f"Encrypt=no;"
    )

@app.route('/')
def hello():
    return '안녕'

@app.route('/message', methods=['POST'])
def message():
    try:
        data = request.get_json(force=True)
        print("✅ DEBUG - JSON data:", data)
    except Exception as e:
        print("❌ ERROR - JSON 파싱 실패:", str(e))
        return 'Invalid JSON', 400

    skill_data = data.get('skillData', {})
    topic = skill_data.get('topic')
    department = skill_data.get('department')
    sort_option = skill_data.get('sort')

    if not topic or not department:
        utterance = (
            data.get('userRequest', {}).get('utterance')
            or data.get('action', {}).get('params', {}).get('utterance', '')
        ).strip()

        parts = [s.strip() for s in utterance.split(',')]
        if len(parts) < 2:
            return make_text_response("방금 하신 말씀을 잘 이해하지 못했어요.\n'주제, 학과' 형식으로 알려주셔야 가장 정확하게 찾아드릴 수 있어요!")

        topic = parts[0]
        department = parts[1]
        sort_option = parts[2] if len(parts) >= 3 else '마감순'

    # 전처리
    topic = topic.replace(' ', '').lower()
    department = department.replace(' ', '').lower()
    today = datetime.today().date()

    # 쿼리
    # query = """
    #     SELECT DISTINCT
    #         n.id, n.title, n.deadline, n.oneline, n.topic, n.created_at, n.url,
    #         a.file_url
    #     FROM dbo.notice n
    #     JOIN dbo.notice_department d ON n.id = d.notice_id
    #     OUTER APPLY (
    #         SELECT TOP 1 file_url
    #         FROM dbo.notice_attachment
    #         WHERE notice_id = n.id
    #         ORDER BY file_order ASC
    #     ) a
    #     WHERE REPLACE(LOWER(d.department), ' ', '') LIKE ?
    #     AND REPLACE(LOWER(n.topic), ' ', '') LIKE ?
    #     AND (n.deadline IS NULL OR n.deadline >= ?)
    # """
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

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, f"%{department}%", f"%{topic}%", today)
        rows = cursor.fetchall()

        if not rows:
            return make_text_response(f"'{topic}, {department}' 관련 마감 기한이 지난 정보이거나 공지사항이 존재하지 않아요.")
        cards = []
        full_lines = []  # 안 쓰면 삭제해도 됨

        for idx, row in enumerate(rows[:5], start=1):
            notice_id, title, deadline, one_line, topic_val, created_at, link_url, file_url, departments = row
            image_url = file_url if (file_url and str(file_url).startswith("http")) else DEFAULT_IMAGE
            deadline_text = deadline.strftime('%Y-%m-%d') if deadline else '정보 없음'
            cards.append({
                "imageTitle": {
                    "title": title[:40],
                    "description": f"마감 {deadline_text}"
                },
                "thumbnail": {
                    "imageUrl": image_url,       # 썸네일 표시용
                    "link": { "web": image_url } # 이미지 클릭 시 원본 열기
                },
                "itemList": [
                    { "title": "요약", "description": (one_line or "요약 없음")[:100] },
                ],
                "itemListAlignment": "left",
                "buttons": [
                    { "action": "webLink", "label": "자세히 보기", "webLinkUrl": link_url }  # 사이트 URL
                ]
            })


            # cards.append({
            #     "itemCard": {
            #         "imageTitle": {         # 상단 큰 타이틀 영역
            #             "title": title,
            #             "description": f"마감 {deadline_text}"
            #         },
            #         "thumbnail": {          # 우상단 썸네일 (선택)
            #             "imageUrl": image_url
            #         },
            #         "itemList": [           # 여기 항목으로 길게 넣으면 안 잘림
            #             { "title": "요약",  "description": one_line or "요약 없음" },
            #             { "title": "학과",  "description": departments or "-" },
            #             { "title": "링크",  "description": link_url }
            #         ],
            #         "itemListAlignment": "left",
            #         "buttons": [
            #             { "action": "webLink", "label": "자세히 보기", "webLinkUrl": link_url }
            #         ]
            #     }
            # })

        return jsonify({
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "carousel": {
                            "type": "itemCard",
                            "items": cards
                        }
                    }
                ]
            }
        })
    finally:
        cursor.close()
        conn.close()

def make_text_response(text):
    return jsonify({
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": text
                    }
                }
            ]
        }
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)