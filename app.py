from flask import Flask, request, jsonify
import pyodbc, os, re, calendar
from datetime import datetime, date, timedelta
from math import ceil
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# ===== 기본 상수 =====
AZURE_BASE_URL = 'https://knuchat.azurewebsites.net'
#AZURE_BASE_URL = 'https://699ef49c36cc.ngrok-free.app'
DEFAULT_IMAGE = "https://kchatsotrage.blob.core.windows.net/images/default.png"  # 실제 컨테이너/경로 확인 권장
DEBUG_MODE = os.getenv("APP_DEBUG", "0") == "1"

TOPIC_CACHE = {"loaded_at": None, "norm_map": {}}
DEPT_CACHE  = {"loaded_at": None, "norm_to_canonical": {}, "all_norms": set()}

TOPIC_ALIASES = {
    "장학금": "장학", "오래순": "오래된순",
    "학사": "학사", "공모전": "공모전",
    "행사": "행사", "취업": "취업", "경진대회": "공모전",
}

SORT_ALIASES = {"마감순":"마감순","최신순":"최신순","오래된순":"오래된순","오래순":"오래된순"}
DEPT_ALL_TOKENS = {"전체","전부","전체학과","all"}
_DEPT_SUFFIXES = ("학과","학부","전공","과","부")  # 접미사 제거용

# 식단 동의어
MENU_ALIASES = {
    "천지관": ["천지관", "학생식당"],
    "크누테리아": ["크누테리아", "교직원식당"],
    "오늘": ["오늘", "당일", "오늘의"],
    "금주": ["금주", "이번주", "주간"],
}

# 단과대학 → 하위 학과(부분문자열) 힌트
COLLEGE_HINTS = {
    "의과대학": ["의학과", "의예과", "의생명"],
    "수의과대학": ["수의학과", "수의예과"],
    "사범대학": ["교육과", "교육학과", "국어교육과", "영어교육과", "수학교육과", "역사교육과", "체육교육과", "윤리교육과", "일반사회교육과", "과학교육학부"],
    "인문대학": ["국어국문", "영어영문", "불어불문", "독어독문", "중어중문", "철학", "사학", "한문"],
    "사회과학대학": ["행정학", "정치외교", "사회학", "심리학", "정보통계", "관광경영", "부동산"],
    "공과대학": ["전자공", "전기전자", "전기공", "컴퓨터", "토목공", "건축공", "화학공", "산업공", "디자인공"],
    "의생명과학대학": ["의생명", "바이오", "생명", "식품", "분자생명"],
}

# ===== 정적 학과 목록(요청 목록 전부 반영) =====
STATIC_DEPTS = [
    "3D프린팅다빈치학과","AI융합학과","가정교육과","간호학과","강원형반도체융합학과","건축공학전공","건축학과",
    "경영학전공","경제학전공","공과대학","과학교육학부","관광경영학과","교육대학원","교육학과","국어교육과",
    "국어국문학전공","국제개발협력학과","국제무역학과","글로벌비즈니스학과","기계의용메카트로닉스공학과",
    "농업자원경제학전공","데이터사이언스학과","데이터지식재산융합학과","독어독문학전공","동물산업융합학과",
    "동물응용과학과","동물자원과학과","디자인공학과","디지털밀리터리학과","디지털헬스케어융합학과",
    "목재과학전공","무용학과","무전공학과","문화예술·공과대학","문화인류학과","미디어커뮤니케이션학과",
    "미래융합가상학과","미술학과","바이오자원환경학전공","바이오제약공학과","반도체물리학과","반도체융합학과",
    "배터리융합공학과","부동산학과","분자생명과학과","불어불문학전공","블록체인융합학과","사범대학",
    "사이버보안융합학과","사회과학대학","사회학과","산림경영학전공","산림자원학전공","산림환경보호학전공",
    "생명건강공학과","생명과학과","생물공학전공","생물의소재공학과","생태조경디자인학과","생화학전공",
    "수의과대학","수의예과","수의학과","수학과","수학교육과","스마트산업공학과","스마트원예영농창업학과",
    "스마트팜농산업학과","스마트팜융합바이오시스템공학과","스포츠과학과","시스템면역과학전공","식물의학전공",
    "식물자원응용과학전공","식품생명공학과","실감미디어학과","심리학과","심리학전공","약학과","에너지자원공학과",
    "에코환경과학전공","역사교육과","영상문화학과","영어교육과","영어영문학전공","예비교원을위한AI융합교육과",
    "원예과학전공","윤리교육과","음악학과","의과대학","의생명공학전공","의생명과학대학","의예과","의학과",
    "인문대학","일반사회교육과","일본학전공","자유전공학부","적층제조융합학과","전기전자공학과","전자공학과",
    "정밀의료융합학과","정보통계학전공","정치외교학과","종이소재과학전공","중어중문학전공","지구물리학전공",
    "지리교육과","지역건설공학과","지역산학협력학과","지질학전공","차세대반도체학과","차세대발전공학과","철학과",
    "철학전공","첨단신소재융합학과","체육교육과","커피과학과","컴퓨터공학과","컴퓨터과학전공","컴퓨터정보통신공학전공",
    "클라우드융합학과","탄소중립융합학과","토목공학전공","평화학과","한문교육과","행정학전공","헬스케어융합전공",
    "화장품과학과","화학공학전공","화학과","화학교육전공","화학전공","환경공학전공","회계학전공"
]

# ===== 유틸 =====
def _kstrip(s: str) -> str:
    return (s or "").replace(" ", "").replace("·","").lower().strip()

def _norm(s: str) -> str:
    return _kstrip(s)

def _norm_dept(s: str) -> str:
    t = _kstrip(s)
    for suf in _DEPT_SUFFIXES:
        if t.endswith(suf):
            t = t[:-len(suf)]
            break
    return t

def _resolve_sort(tok: str) -> str:
    t = _norm(tok)
    for k, v in SORT_ALIASES.items():
        if _norm(k) == t:
            return v
    return "최신순"

# 식당 명칭 정규화
RESTAURANT_ALIASES = {
    "천지관": ["천지관", "학생식당"],
    "백록관": ["백록관"],
    "크누테리아": ["크누테리아", "교직원식당"],
}

def _norm_restaurant(u: str) -> str:
    u = _norm(u)
    for canon, aliases in RESTAURANT_ALIASES.items():
        for a in aliases:
            if _norm(a) in u:
                return canon
    return "천지관"

def _norm_menu_period(u: str) -> str:
    u = _norm(u)
    for period_key in ("오늘", "금주"):
        if any(_norm(alias) in u for alias in MENU_ALIASES[period_key]):
            return period_key
    return "오늘"

def is_this_week(d: date) -> bool:
    today = datetime.today().date()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    return start_of_week <= d <= end_of_week

def _to_text(x) -> str:
    if isinstance(x, str): return x
    if isinstance(x, (int, float)): return str(x)
    if isinstance(x, dict):
        for k in ("utterance","user_input","value","text","resolved","original"):
            v = x.get(k)
            if isinstance(v, str):
                return v
        for v in x.values():
            t = _to_text(v)
            if t: return t
        return ""
    if isinstance(x, (list, tuple)):
        for v in x:
            t = _to_text(v)
            if t: return t
        return ""
    return ""

def get_utterance_from_payload(data: dict) -> str:
    u = _to_text((data or {}).get("userRequest", {}).get("utterance", ""))
    if not u:
        u = _to_text((data or {}).get("action", {}).get("params", {}))
    if not u:
        u = _to_text((data or {}).get("action", {}).get("detailParams", {}))
    return (u or "").strip()

def get_db_connection():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={os.getenv('DB_SERVER')};"
        f"DATABASE={os.getenv('DB_NAME')};"
        f"UID={os.getenv('DB_USER')};"
        f"PWD={os.getenv('DB_PASSWORD')};"
        f"Encrypt=yes;TrustServerCertificate=yes;"
        f"Connection Timeout=15;"  # 늘림
    )

# ===== 토픽 로딩 =====
def load_topics_from_db() -> dict:
    rows = []
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT topic FROM dbo.notice
            WHERE topic IS NOT NULL AND LTRIM(RTRIM(topic)) <> ''
        """)
        rows = cur.fetchall(); cur.close(); conn.close()
    except Exception as e:
        print("WARN: load_topics_from_db failed:", e)
    norm_map = {}
    for (topic,) in rows:
        t = (topic or "").strip()
        if t: norm_map[_norm(t)] = t
    for a, c in TOPIC_ALIASES.items():
        norm_map.setdefault(_norm(a), c)
        norm_map.setdefault(_norm(c), c)
    return norm_map

def get_topic_norm_map(ttl_seconds=600) -> dict:
    now = datetime.utcnow()
    if TOPIC_CACHE["loaded_at"] is None or (now - TOPIC_CACHE["loaded_at"]).total_seconds() > ttl_seconds:
        TOPIC_CACHE["norm_map"] = load_topics_from_db()
        TOPIC_CACHE["loaded_at"] = now
        print(f"INFO: topic cache loaded ({len(TOPIC_CACHE['norm_map'])} items)")
    return TOPIC_CACHE["norm_map"]

# ===== 학과 로딩(정적 + DB 병합) =====
def load_departments_from_db() -> dict:
    rows = []
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT department
            FROM dbo.notice_department
            WHERE department IS NOT NULL AND LTRIM(RTRIM(department)) <> ''
        """)
        rows = [r[0] for r in cur.fetchall()]
        cur.close(); conn.close()
    except Exception as e:
        print("WARN: load_departments_from_db failed:", e)

    candidates = list({*(rows or []), *STATIC_DEPTS})
    norm_to_canonical = {}
    for original in candidates:
        o = (original or "").strip()
        if not o: continue
        key = _norm_dept(o)
        if not key: continue
        prev = norm_to_canonical.get(key)
        if prev is None or len(o) > len(prev):
            norm_to_canonical[key] = o
    return norm_to_canonical

def get_dept_norm_map(ttl_seconds=600) -> dict:
    now = datetime.utcnow()
    if DEPT_CACHE["loaded_at"] is None or (now - DEPT_CACHE["loaded_at"]).total_seconds() > ttl_seconds:
        m = load_departments_from_db()
        DEPT_CACHE["norm_to_canonical"] = m
        DEPT_CACHE["all_norms"] = set(m.keys())
        DEPT_CACHE["loaded_at"] = now
        print(f"INFO: dept cache loaded ({len(m)} items)")
    return DEPT_CACHE["norm_to_canonical"]

def resolve_department(user_text: str) -> str:
    """자유 입력 → 대표 학과/단과대학명 보정."""
    if not user_text: return ""

    norm_map = get_dept_norm_map()
    key = _norm_dept(user_text)

    # 1) 직매칭
    if key in norm_map:
        return norm_map[key]

    # 2) 접미사 자동 보강 후 재시도
    for suf in ("과","학과","전공"):
        k2 = _norm_dept(user_text + suf)
        if k2 in norm_map:
            return norm_map[k2]

    # 3) prefix / contains 유사 매칭
    if len(key) >= 2:
        starts = [norm_map[k] for k in norm_map if k.startswith(key)]
        if len(starts) == 1: return starts[0]
        if len(starts) > 1:  return max(starts, key=len)

        contains = [norm_map[k] for k in norm_map if key in k]
        if len(contains) == 1: return contains[0]
        if len(contains) > 1:  return max(contains, key=len)

    # 4) 대학 단위 힌트 보정
    college_hint = key.replace("대학", "")
    if college_hint in norm_map:
        return norm_map[college_hint]

    return user_text  # 실패 시 원문

# ===== 파서 =====
def smart_parse_topic_dept_sort(utterance: str):
    norm_map = get_topic_norm_map()
    known_topics = set(norm_map.keys())
    tokens = [t for t in re.split(r"[,\s]+", (utterance or "").strip()) if t]
    topic, dept_canon, sort_opt, dept_raw = "", "", "최신순", ""
    for tok in tokens:
        t = _norm(tok)
        # 정렬어
        if t in { _norm(k) for k in SORT_ALIASES }:
            sort_opt = _resolve_sort(tok)
            continue
        # 전체
        if t in {_norm(x) for x in DEPT_ALL_TOKENS}:
            dept_canon, dept_raw = "", ""; continue
        # 토픽
        if t in known_topics or t == _norm("학사"):
            if not topic:
                topic = norm_map.get(t, "학사" if t == _norm("학사") else tok)
            elif not dept_canon:
                dept_raw = tok
                dept_canon = resolve_department(tok)
            continue
        # 학과/단과대학
        if not dept_canon:
            dept_raw = tok
            dept_canon = resolve_department(tok)
            if DEBUG_MODE:
                print(f"[DEBUG] resolve_department input='{tok}' -> '{dept_canon}'", flush=True)
            continue

    if not topic and not dept_canon and len(tokens) >= 2:
        topic = tokens[0]
        dept_raw = "".join(tokens[1:])
        dept_canon = resolve_department(dept_raw)

    if not topic and not dept_canon and len(tokens) == 1:
        t0 = _norm(tokens[0])
        topic = norm_map.get(t0, "")
        if not topic:
            dept_raw = tokens[0]
            dept_canon = resolve_department(dept_raw)
    return topic, dept_canon, sort_opt, dept_raw

# ===== 학사일정 =====
def parse_schedule_range(utterance: str, today: date):
    u = (utterance or "").replace(" ","").lower()
    # 동의어
    u = u.replace("당일","오늘").replace("오늘의", "오늘")
    u = u.replace("이번주","금주").replace("주간", "금주")

    if "오늘학사일정" in u or u == "오늘": 
        return today, today, "오늘 학사일정"
    if "내일학사일정" in u or u == "내일": 
        return today + timedelta(days=1), today + timedelta(days=1), "내일 학사일정"
    if "이번달" in u:
        start = date(today.year, today.month, 1)
        end = date(today.year, today.month, calendar.monthrange(today.year,today.month)[1])
        return start, end, f"{today.year}년 {today.month}월 학사일정"
    if "다음달" in u:
        y = today.year + (1 if today.month==12 else 0)
        m = 1 if today.month==12 else today.month+1
        start = date(y, m, 1)
        end = date(y, m, calendar.monthrange(y,m)[1])
        return start, end, f"{y}년 {m}월 학사일정"
    m = re.search(r'(?:(20\d{2})년)?(\d{1,2})월학사일정', u)
    if m:
        y = int(m.group(1)) if m.group(1) else today.year
        mon = int(m.group(2)); start = date(y,mon,1); end = date(y,mon,calendar.monthrange(y,mon)[1])
        return start, end, f"{y}년 {mon}월 학사일정"
    if "학사일정" in u: return None, None, "학사일정 전체"
    return None, None, ""

# 🔗 학과 공지 게시판 URL 조회
def fetch_department_homepage(dept_canon: str) -> str | None:
    """학과명(대표 이름)으로 학과 공지 게시판 URL 조회."""
    if not dept_canon:
        return None

    key = _norm_dept(dept_canon)  # '컴퓨터공학과' -> '컴퓨터공'
    if not key:
        return None

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT TOP 1 homepage_url
            FROM dbo.department_notice_board
            WHERE LOWER(
                REPLACE(REPLACE(dept_name, ' ', ''), N'학과', '')
            ) LIKE ?
        """, f"%{key}%")
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    return row[0] if row else None

def fetch_academic_events(conn, start: date|None, end: date|None):
    cur = conn.cursor()
    if start and end:
        cur.execute("""
            SELECT title,start_date,end_date
            FROM dbo.academic_event
            WHERE start_date <= ? AND end_date >= ?
            ORDER BY start_date, title
        """, end, start)
    else:
        cur.execute("""
            SELECT title,start_date,end_date
            FROM dbo.academic_event
            ORDER BY start_date, title
        """)
    rows = cur.fetchall(); cur.close(); return rows

def fetch_menu(conn, restaurant: str, start: date, end: date):
    cur = conn.cursor()
    cur.execute("""
        SELECT TOP 100 service_date, menu_group, menu
        FROM dbo.cafeteria_menu
        WHERE restaurant = ? AND service_date BETWEEN ? AND ?
        ORDER BY service_date ASC, meal_type ASC
    """, restaurant, start, end)
    rows = cur.fetchall()
    cur.close()
    return rows

def format_event_line(title: str, sd, ed) -> str:
    if isinstance(sd, datetime): sd = sd.date()
    if isinstance(ed, datetime): ed = ed.date()
    return f"{sd:%Y-%m-%d} · {title}" if sd==ed else f"{sd:%Y-%m-%d} ~ {ed:%Y-%m-%d} · {title}"

def make_text_outputs_from_lines(lines, title_label: str, page: int, page_size: int):
    total = len(lines); total_pages = max(1, ceil(total / page_size))
    page = max(1, min(page, total_pages))
    start_idx = (page - 1)*page_size; end_idx = min(total, start_idx+page_size)
    slice_lines = lines[start_idx:end_idx]
    outputs = [{"simpleText":{"text": f"📅 {title_label}\n" + "\n".join(slice_lines)}}]
    qrs = []
    if page>1: qrs.append({"action":"message","label":"◀ 이전","messageText":f"{title_label} p:{page-1}"})
    if page<total_pages: qrs.append({"action":"message","label":"다음 ▶","messageText":f"{title_label} p:{page+1}"})
    return outputs, qrs

# ===== 공통 응답 =====
def make_text_response(text):
    return jsonify({
        "version":"2.0",
        "template":{"outputs":[{"simpleText":{"text": text}}]}
    })

# ===== 부서 필터(학과/단과대학/전체) 빌더 =====
def build_dept_filters(dept_canon: str):
    norm_key = _norm_dept(dept_canon)
    if not norm_key:
        return "1=1", ()  # 전체

    base_like = f"%{norm_key}%"
    like_list = [base_like]

    is_college = dept_canon.endswith("대학") or ("대학" in dept_canon)
    if is_college:
        like_list.append(f"%{_kstrip(dept_canon)}%")
        hints = []
        for k, arr in COLLEGE_HINTS.items():
            if _norm(k) == _norm(dept_canon):
                hints = arr
                break
        for h in hints:
            like_list.append(f"%{_kstrip(h)}%")

    # ✅ 괄호를 단계적으로 정리한 정규화 표현식 (SQL Server)
    norm_sql = """
LOWER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(d.department,' ',''),N'·',''),N'학과',''),N'학부',''),N'전공',''),N'과',''),N'부',''))
"""

    or_clauses = " OR ".join([f"{norm_sql} LIKE ?" for _ in like_list])
    sql_snippet = f"EXISTS (SELECT 1 FROM dbo.notice_department AS d WHERE d.notice_id = n.id AND ({or_clauses}))"
    return sql_snippet, tuple(like_list)

# ===== 라우트 =====
@app.route('/')
def hello():
    return '안녕'

@app.route('/message', methods=['POST'])
def message():
    try:
        data = request.get_json(force=True)
    except Exception as e:
        print("❌ JSON parse error:", e); return 'Invalid JSON', 400

    utterance = get_utterance_from_payload(data)
    print("[HIT]", datetime.utcnow().isoformat(), "utterance=", repr(utterance), flush=True)

    # ----- 사용법 / 도움말 처리 -----
    norm_u = (utterance or "").strip()
    norm_no_space = norm_u.replace(" ", "")

    # if norm_u in ("사용법", "도움말") or "사용법" in norm_no_space:
    #     help_text = (
    #         "🎉 강원대 맞춤형 공지 챗봇 ‘크누리미’ 사용법 안내입니다.\n\n"
    #         "1️⃣ 공지 검색\n"
    #         " - 형식: 카테고리, 학과명\n"
    #         "   예) 공모전, 컴퓨터공학과\n"
    #         "   예) 장학, 경영학과\n"
    #         "   예) 취업, 전체\n\n"
    #         "2️⃣ 학사일정 조회\n"
    #         "   예) 오늘 학사일정\n"
    #         "   예) 내일 학사일정\n"
    #         "   예) 11월 학사일정\n\n"
    #         "3️⃣ 식단 조회\n"
    #         "   예) 천지관 오늘 식단\n"
    #         "   예) 백록관 금주의 식단\n"
    #         "   예) 크누테리아 식단\n\n"
    #         "원하는 내용을 그대로 입력해보세요! 😊"
    #     )
    #     return make_text_response(help_text)

    # ✅ 사용법 전체 안내
    if utterance and utterance.strip() in ("사용법", "도움말") :
        text_notice = (
            "📩 공지 사용법\n\n"
            "📢 공지 확인하는 방법을 안내해드릴게요!\n\n"
            "카테고리와 학과명을 공백으로 구분해 입력해주세요\n"
            "예) 공모전 경영학과 / 장학 컴퓨터공학과 / 취업 전체\n\n"
            "📌 학과명만 입력해도 최근 공지 5개를 안내해드려요!\n"
            "예) 컴퓨터공학과 / 영어영문학과 / 경영학과\n\n"
            "🔍 제공 정보\n"
            "제목 / 요약 / 마감일 / 이미지 / 상세 링크\n\n"
            "📚 지원 카테고리\n"
            "비교과 / 학생지원 / 공모전 / 대외활동 / 취업 / 장학 / 일반 / 학사 / 금주식단 / 수강신청 / 취업연계\n"
        )

        text_schedule = (
            "📅 학사일정 사용법\n\n"
            "📌 학사일정 확인하는 방법을 안내드립니다!\n\n"
            "확인하고 싶은 날짜를 입력해주세요.\n"
            "예) 오늘학사일정 / 내일학사일정 / 11월학사일정 / 학사일정\n\n"
            "📍 월 단위 조회 가능!\n"
            "📍 '학사일정'만 입력하면 전체 학사일정 확인 가능!\n"
        )

        text_menu = (
            "🍽 식단 사용법\n\n"
            "😊 오늘 뭐 먹지? 식단 조회 방법 알려드릴게요!\n\n"
            "원하는 날짜 + 식당명을 조합해서 입력해주세요.\n"
            "예) 오늘식단 크누테리아 / 내일식단 천지관 / 금주의식단 백록관\n\n"
            "📌 지원 식당\n"
            "크누테리아 / 천지관 / 백록관\n\n"
            "✅ 오늘 메뉴 / 내일 메뉴 / 이번 주 메뉴까지 확인 가능!\n"
            "맛있는 하루 되세요! 🍱✨\n"
        )

        return jsonify({
            "version": "2.0",
            "template": {
                "outputs": [
                    {"simpleText": {"text": text_notice}},
                    {"simpleText": {"text": text_schedule}},
                    {"simpleText": {"text": text_menu}},
                ]
            }
        })
    # --- 학사일정 ---
    if "학사일정" in utterance.replace(" ",""):
        today = datetime.today().date()
        mpage = re.search(r'\bp\s*:\s*(\d+)', utterance.lower())
        page = max(1, int(mpage.group(1))) if mpage else 1
        start, end, label = parse_schedule_range(utterance, today)
        conn = get_db_connection()
        try:
            rows = fetch_academic_events(conn, start, end)
        finally:
            conn.close()
        lines = [format_event_line(t, sd, ed) for (t,sd,ed) in rows]
        if not lines:
            return make_text_response(f"{label or '학사일정'} 결과가 없어요.")
        outputs, qrs = make_text_outputs_from_lines(lines, label or "학사일정", page, 20)
        return jsonify({"version":"2.0", "template":{"outputs":outputs, "quickReplies":qrs}})

    # --- 식단 조회 ---
    u_norm = _norm(utterance)
    has_menu_intent = ("식단" in u_norm) or any(a in u_norm for a in ["오늘","금주","이번주","주간","당일","오늘의","천지관","크누테리아","백록관"])
    page_match = re.search(r'(?<!\w)p\s*:\s*(\d+)', utterance.lower())
    page = max(1, int(page_match.group(1))) if page_match else 1

    if has_menu_intent:
        restaurant_name = _norm_restaurant(utterance)
        period = _norm_menu_period(utterance)

        today = datetime.today().date()
        start_date = end_date = today
        title = ""

        if period == '오늘':
            title = f"{restaurant_name} 오늘의 식단 ({today:%Y-%m-%d})"
        else:
            # 기본: 이번 주(월~일)
            start_date = today - timedelta(days=today.weekday())
            end_date = start_date + timedelta(days=6)
            title = f"{restaurant_name} 금주의 식단"

        conn = get_db_connection()
        try:
            # 1차: 이번 주 조회
            rows = fetch_menu(conn, restaurant_name, start_date, end_date)

            # 💡 이번 주에 없고, 금주 요청이면 → 다음 주 한 번 더 시도
            if not rows and period == '금주':
                next_monday = end_date + timedelta(days=1)  # 다음 주 월요일
                next_sunday = next_monday + timedelta(days=6)
                rows = fetch_menu(conn, restaurant_name, next_monday, next_sunday)
                if rows:
                    start_date, end_date = next_monday, next_sunday
                    title = f"{restaurant_name} 다음 주 식단"
        finally:
            conn.close()

        if not rows:
            return make_text_response(f"'{title}'에 대한 식단 정보가 없습니다.")

        menus_by_date = {}
        for service_date, menu_group, menu_list in rows:
            menus_by_date.setdefault(service_date, []).append((menu_group, menu_list))

        dates = sorted(menus_by_date.keys())
        total_pages = len(dates)
        page = max(1, min(page, total_pages))
        selected_date = dates[page-1]

        if period == '금주':
            title = f"{restaurant_name} 금주의 식단 ({selected_date:%Y-%m-%d})"

        menu_text = f"🍽️ {title}\n"
        for menu_group, menu_list in menus_by_date[selected_date]:
            menu_text += f" - {menu_group}:\n  {str(menu_list).replace(', ', ' | ')}\n"

        qrs = []
        if total_pages > 1:
            if page > 1:
                qrs.append({"action":"message","label":"◀ 이전","messageText":f"{restaurant_name} 금주 p:{page-1}"})
            if page < total_pages:
                qrs.append({"action":"message","label":"다음 ▶","messageText":f"{restaurant_name} 금주 p:{page+1}"})

        return jsonify({"version":"2.0", "template":{"outputs":[{"simpleText":{"text": menu_text}}], "quickReplies":qrs}})

    # --- 공지 검색 ---
    topic, dept_canon, sort_option, dept_raw = smart_parse_topic_dept_sort(utterance)
    if not topic and not dept_canon:
        return make_text_response("예: '공모전 컴퓨터공학과', '장학 전체', '취업 최신순'처럼 알려주세요.")

    topic_key = _norm(topic)
    topic_like = f"%{topic_key}%" if topic_key else "%%"

    dept_filter_sql, dept_params = build_dept_filters(dept_canon or "")

    query = f"""
SELECT DISTINCT
    n.id, n.title, n.deadline, n.oneline, n.topic, n.created_at, n.url,
    a.file_url,
    dep.departments
FROM dbo.notice AS n
JOIN (
    SELECT notice_id, STRING_AGG(department, ', ') AS departments
    FROM dbo.notice_department
    GROUP BY notice_id
) AS dep ON n.id = dep.notice_id
OUTER APPLY (
    SELECT TOP 1 file_url
    FROM dbo.notice_attachment
    WHERE notice_id = n.id
    ORDER BY file_order ASC
) AS a
WHERE {dept_filter_sql}
  AND LOWER(REPLACE(n.topic, ' ', '')) LIKE ?
"""

    if sort_option == '마감순':
        query += " ORDER BY CASE WHEN n.deadline IS NULL THEN 1 ELSE 0 END, n.deadline ASC"
    elif sort_option == '오래된순':
        query += " ORDER BY n.created_at ASC"
    else:
        query += " ORDER BY n.created_at DESC"

    conn = get_db_connection(); cur = conn.cursor()
    try:
        cur.execute(query, (*dept_params, topic_like))
        rows = cur.fetchall()
    finally:
        cur.close(); conn.close()

    display_dept = dept_raw or dept_canon
    if not rows:
        fallback_text = (
            "입력하신 내용을 이해하지 못했어요 😢\n"
            "또는 해당 조건에 맞는 공지가 없어요.\n\n"
            "사용법이 궁금하시면 ‘사용법’을 입력해보세요!"
        )
        return make_text_response(fallback_text)
        #return make_text_response(f"'{topic or '전체'}, {display_dept or '전체'}' 관련 공지가 없어요.")

    cards = []
    for (notice_id, title, deadline, one_line, topic_val, created_at, link_url, file_url, departments) in rows[:5]:
        image_url = file_url if (file_url and str(file_url).startswith("http")) else DEFAULT_IMAGE
        deadline_desc = f"마감 {deadline.strftime('%Y-%m-%d')}" if deadline else "마감일 없음"
        cards.append({
            "imageTitle": {
                "title": (title or "")[:40],
                "description": f"{topic or '전체'} · {display_dept or '전체'} · {deadline_desc}"
            },
            "thumbnail": {"imageUrl": image_url, "link": {"web": image_url}},
            "itemList": [{"title":"요약","description": (one_line or "요약 없음")[:100]}],
            "itemListAlignment": "left",
            "buttons": [{"action":"webLink","label":"자세히 보기","webLinkUrl": link_url}]
        })

    # 기본 공지 카드(캐러셀 또는 단일 카드)
    outputs = [{"itemCard": cards[0]}] if len(cards)==1 else [{"carousel":{"type":"itemCard","items":cards}}]

    # 🔗 학과 공지사항 전체 링크 simpleText 추가 (학과가 있는 경우에만)
    if dept_canon:
        dept_homepage = fetch_department_homepage(dept_canon)
        if dept_homepage:
            dept_label = display_dept or dept_canon
            hint_text = (
                f"🔗 '{dept_label}' 학과 공지사항 전체는 아래 링크에서 확인할 수 있어요.\n"
                f"{dept_homepage}"
            )
            outputs.append({"simpleText": {"text": hint_text}})

    return jsonify({"version":"2.0", "template":{"outputs": outputs}})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
