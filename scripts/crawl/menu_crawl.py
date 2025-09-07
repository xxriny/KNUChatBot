# knu_menu_crawler_blob_latest.py
import os
import re
import io
import csv
import argparse
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry  # ✅ 수정
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from azure.storage.blob import BlobServiceClient, ContentSettings  # ✅ 수정
from azure.core.exceptions import ResourceExistsError

# ============== 환경설정 ==============
load_dotenv(override=True)

BASE_URL = os.getenv("KNU_MENU_BASE_URL", "https://wwwk.kangwon.ac.kr/www/selecttnCafMenuListWU.do")
KEY = os.getenv("KNU_MENU_KEY", "1077")
CAFETERIAS = {"천지관": "CC10", "백록관": "CC20", "크누테리아": "CC30"}

AZURE_CONN_STR = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
# ✅ 이름 호환
AZURE_CONTAINER = (
    os.environ.get("AZURE_BLOB_CONTAINER")
    or os.environ.get("AZURE_CONTAINER")
    or "data"
)
BLOB_FILENAME = os.environ.get("BLOB_FILENAME", "KNU_식단_latest.csv")

CSV_PATH = "/home/data/extracted-app/data/KNU_식단_latest.csv"

KST = ZoneInfo("Asia/Seoul")

def make_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=5, connect=5, read=5,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"]
    )
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("http://", adapter); s.mount("https://", adapter)
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    return s

# ============== 날짜/유틸 ==============
def this_week_sunday_kst(now_utc: datetime | None = None) -> datetime:
    now = (now_utc or datetime.utcnow()).astimezone(KST)
    # 월=0 ... 일=6
    sunday = now - timedelta(days=now.weekday() + 1) if now.weekday() != 6 else now
    return sunday.replace(hour=0, minute=0, second=0, microsecond=0)

def parse_date_range(text: str):
    m = re.search(r"(\d{4})\.(\d{2})\.(\d{2})\s*~\s*(\d{4})\.(\d{2})\.(\d{2})", text)
    if not m: return (None, None)
    y1, m1, d1, y2, m2, d2 = map(int, m.groups())
    return datetime(y1, m1, d1).date(), datetime(y2, m2, d2).date()

def date_list_from_range(start, end):
    cur, out = start, []
    while cur <= end:
        out.append(cur); cur += timedelta(days=1)
    return out

def clean_text(html_fragment: str) -> str:
    frag = html_fragment.replace("<br/>", "\n").replace("<br>", "\n")
    txt = BeautifulSoup(frag, "html.parser").get_text("\n")
    lines = [re.sub(r"\s+", " ", ln.strip()) for ln in txt.splitlines()]
    lines = [ln for ln in lines if ln]
    return " / ".join(lines)

def build_url(sc1: str, week_start_yyyymmdd: str | None):
    params = {"key": KEY, "sc1": sc1, "sc2": "CC"}
    if week_start_yyyymmdd: params["sc5"] = week_start_yyyymmdd
    return f"{BASE_URL}?{urlencode(params)}#week_anchor"

# ============== 파싱 로직 ==============
def parse_cafeteria_week(html: str, cafeteria_name: str):
    soup = BeautifulSoup(html, "html.parser")
    week_h3 = soup.select_one("h3.h0, h3#week_anchor")
    start_date, end_date = (None, None)
    if week_h3:
        start_date, end_date = parse_date_range(week_h3.get_text(strip=True))
    if not (start_date and end_date):
        period_th = soup.find("th", string=re.compile(r"기간"))
        if period_th:
            period_td = period_th.find_next("td")
            if period_td:
                txt = re.sub(r"\([\u3131-\u3163\uac00-\ud7a3A-Za-z]+\)", "", period_td.get_text(strip=True))
                m = re.search(r"(\d{4}\.\d{2}\.\d{2})\s*~\s*(\d{4}\.\d{2}\.\d{2})", txt)
                if m:
                    start_date = datetime.strptime(m.group(1), "%Y.%m.%d").date()
                    end_date   = datetime.strptime(m.group(2), "%Y.%m.%d").date()

    candidate_tables = soup.select("div.over_scroll_table table.table") or soup.select("table.table")
    menu_table = None
    for t in candidate_tables:
        thead = t.find("thead")
        if thead and thead.find("th", string=re.compile(r"\d{2}\.\d{2}\(")):
            menu_table = t; break
    if not menu_table: return []

    date_headers = []
    for th in menu_table.find("thead").find_all("th"):
        txt = th.get_text(strip=True)
        if re.match(r"\d{2}\.\d{2}\(", txt):
            date_headers.append(re.match(r"(\d{2})\.(\d{2})", txt).group(0))

    date_objects = []
    if start_date and end_date:
        week_days = date_list_from_range(start_date, end_date)
        if len(date_headers) == len(week_days):
            date_objects = week_days
        else:
            mmdd_to_date = {d.strftime("%m.%d"): d for d in week_days}
            for mmdd in date_headers:
                date_objects.append(mmdd_to_date.get(mmdd))
    if not date_objects or any(d is None for d in date_objects): return []

    out_rows = []
    tbody = menu_table.find("tbody")
    current_course = None
    for tr in tbody.find_all("tr"):
        th_rowgroup = tr.find("th", attrs={"scope": "rowgroup"})
        if th_rowgroup: current_course = th_rowgroup.get_text(strip=True)
        th_meal = tr.find("th", attrs={"scope": "row"})
        if not th_meal: continue
        meal_name = th_meal.get_text(strip=True)
        tds = tr.find_all("td")
        if not tds: continue

        n = min(len(date_objects), len(tds))
        for idx in range(n):
            d = date_objects[idx]
            menu = clean_text(str(tds[idx]))
            if not menu or re.fullmatch(r"[-–—\s]+", menu): continue
            out_rows.append({
                "식당": cafeteria_name,
                "식단": current_course or "",
                "아침·점심·저녁": meal_name,
                "날짜": d.strftime("%Y-%m-%d"),
                "메뉴": menu,
            })
    return out_rows

def fetch_week(session: requests.Session, cafeteria_name: str, sc1_code: str, week_start_yyyymmdd: str | None):
    url = build_url(sc1_code, week_start_yyyymmdd)
    r = session.get(url, timeout=20)
    r.raise_for_status()
    return parse_cafeteria_week(r.text, cafeteria_name)

# ============== CSV/Blob 유틸 ==============
def ensure_container(client: BlobServiceClient, name: str):
    try:
        client.create_container(name); print(f"[Blob] created container: {name}")
    except ResourceExistsError:
        print(f"[Blob] container exists: {name}")

def rows_to_csv_bytes(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["식당", "식단", "아침·점심·저녁", "날짜", "메뉴"])
    writer.writeheader(); writer.writerows(rows)
    text = buf.getvalue()
    return ("\ufeff" + text).encode("utf-8")

def atomic_save_csv(csv_bytes: bytes, path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as f: f.write(csv_bytes)
    os.replace(tmp, path)
    return path

def save_csv_to_local(rows: list[dict], csv_path: str) -> str:
    csv_bytes = rows_to_csv_bytes(rows)
    path = atomic_save_csv(csv_bytes, csv_path)   # ✅ 원자적 저장
    size = os.path.getsize(path)
    print(f"[Local] saved CSV → {path} (rows={len(rows)}, size={size} bytes)")
    return path

def upload_csv_to_blob(rows: list[dict], blob_filename: str, start_dt: datetime) -> str:
    if not AZURE_CONN_STR:
        raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING이 설정되지 않았습니다.")
    bsc = BlobServiceClient.from_connection_string(AZURE_CONN_STR)
    ensure_container(bsc, AZURE_CONTAINER)

    csv_bytes = rows_to_csv_bytes(rows)
    blob_client = bsc.get_blob_client(container=AZURE_CONTAINER, blob=blob_filename)
    blob_client.upload_blob(
        csv_bytes,
        overwrite=True,
        content_settings=ContentSettings(content_type="text/csv; charset=utf-8"),  # ✅
    )
    print("[Blob] uploaded:", f"{AZURE_CONTAINER}/{blob_filename}",
          "(week start:", start_dt.strftime("%Y-%m-%d %Z") + ")")
    return f"{AZURE_CONTAINER}/{blob_filename}"

# ============== 엔트리 포인트 ==============
def crawl_week_to_blob(week_start_yyyymmdd: str | None = None) -> str:
    start_dt = (
        datetime.strptime(week_start_yyyymmdd, "%Y%m%d").replace(tzinfo=KST)
        if week_start_yyyymmdd else this_week_sunday_kst()
    )

    session = make_session()
    all_rows = []
    for caf_name, sc1 in CAFETERIAS.items():
        try:
            rows = fetch_week(session, caf_name, sc1, start_dt.strftime("%Y%m%d"))
            print(f"[OK] {caf_name}: {len(rows)} rows")
            all_rows.extend(rows)
        except Exception as e:
            print(f"[ERR] {caf_name}: {e}")

    if not all_rows:
        raise RuntimeError("수집된 행이 없습니다. 사이트 구조/주간 데이터 유무를 확인하세요.")

    # 1) 로컬 저장 (+ 검증 로그)
    path = save_csv_to_local(all_rows, CSV_PATH)
    print("[Local] exists:", os.path.exists(path), "| ls -l size:", os.path.getsize(path))

    # 2) Blob 업로드
    blob_uri = upload_csv_to_blob(all_rows, BLOB_FILENAME, start_dt)
    print(f"[OK] 업로드 완료 → {blob_uri} (총 행수={len(all_rows)})")
    return blob_uri

def main():
    parser = argparse.ArgumentParser(description="KNU 주간 식단 → 로컬 저장 + Azure Blob 업로드 (매주 덮어쓰기)")
    parser.add_argument("--week-start", help="주 시작(일요일) 날짜, 예: 20250831 (KST 기준)", default=None)
    args = parser.parse_args()
    crawl_week_to_blob(args.week_start)

if __name__ == "__main__":
    main()
