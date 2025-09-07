import os
import csv
import time
import re
import random
import unicodedata
import io
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm
from difflib import SequenceMatcher
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.feature_extraction.text import TfidfVectorizer
from datetime import datetime, timedelta
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import AzureError, ResourceNotFoundError  
from dotenv import load_dotenv

# --- .env 파일 로드 ---
load_dotenv(override=True)   # ← 이걸로 기존 환경변수 위에 덮어쓰기

# --- 기본 설정 ---
HEADERS = {"User-Agent": "Mozilla/5.0"}
# SAVE_FOLDER는 이제 로컬 경로가 아닌, Blob 경로의 기반으로만 사용됩니다.
SAVE_FOLDER = "images"
CSV_FILE = "kangwon_notices.csv"   # Blob에 저장할 블롭 이름
# ✅ 로컬 CSV 저장 경로(고정)
CSV_PATH = "/home/data/extracted-app/data/kangwon_notices.csv"

# ▼▼▼ 크롤링 시작 날짜 설정 ▼▼▼
CRAWL_START_DATE = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
# ▲▲▲ 설정 완료 ▲▲▲

# ▼▼▼ Azure Blob Storage 설정 (필수) ▼▼▼
AZURE_CONNECTION_STRING = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = "images"            # 이미지 저장 컨테이너
AZURE_CSV_CONTAINER_NAME = "data"          # CSV 저장 컨테이너

# Azure 서비스 클라이언트 초기화
blob_service_client = None
try:
    if AZURE_CONNECTION_STRING:
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
        print("☁️  Azure Blob Storage 클라이언트가 성공적으로 초기화되었습니다.")
    else:
        print("‼️  중요: AZURE_STORAGE_CONNECTION_STRING 환경 변수가 설정되지 않았습니다. 이미지/CSV의 Blob 업로드를 건너뜁니다.")
except Exception as e:
    print(f"❌ Azure 클라이언트 초기화 실패: {e}. 이미지/CSV의 Blob 업로드를 건너뜁니다.")

# --- 세션 및 재시도 설정 ---
session = requests.Session()
retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry)
session.mount("http://", adapter)
session.mount("https://", adapter)

# --- 전역 변수 ---
all_data = []
pre_existing_data = []  # 기존 CSV 데이터를 담을 리스트
existing_keys_set = set()

# --- 유틸리티 함수 ---
def sanitize_filename(name):
    return re.sub(r'[^\w\s_.-]', '_', name).strip()

def save_image(img_url, folder, prefix, idx, original_name="image.jpg", referer_url=None):
    """
    이미지를 다운로드하여 Azure Blob Storage에 저장합니다.
    Azure 클라이언트가 설정되지 않았다면 이미지 저장을 건너뜁니다.
    """
    if not blob_service_client:
        return None

    try:
        img_headers = HEADERS.copy()
        if referer_url:
            img_headers['Referer'] = referer_url

        res = session.get(img_url, headers=img_headers, timeout=10)
        time.sleep(random.uniform(0.1, 0.3))

        if not (res.status_code == 200 and len(res.content) > 1024):
            return None

        ext = os.path.splitext(original_name)[1] or '.jpg'
        if len(ext) > 5:
            ext = '.jpg'
        filename = sanitize_filename(f"{prefix}_{idx}{ext}")

        blob_path_prefix = os.path.relpath(folder, SAVE_FOLDER).replace("\\", "/")
        blob_name = f"{blob_path_prefix}/{filename}" if blob_path_prefix != '.' else filename

        blob_client = blob_service_client.get_blob_client(container=AZURE_CONTAINER_NAME, blob=blob_name)
        blob_client.upload_blob(res.content, overwrite=True)

        return blob_client.url

    except AzureError as e:
        print(f"      ❌ Azure 업로드 실패: {img_url} ({e})")
    except Exception as e:
        print(f"      ⚠️ 이미지 처리/업로드 중 오류 발생: {img_url} ({e})")

    return None

def clean_html_keep_table(raw_html):
    soup = BeautifulSoup(raw_html, 'html.parser')
    for zoom_element in soup.select('span.photo_zoom'):
        zoom_element.decompose()
    output = []
    for table in soup.find_all('table'):
        output.append(extract_table_text(table))
        table.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for elem in soup.find_all(['p', 'div', 'span']):
        text = elem.get_text(strip=True, separator="\n")
        if text and text not in output:
            output.append(text)
    return "\n".join(output).strip()

def extract_table_text(table):
    rows = table.find_all('tr')
    return '\n'.join(
        ' | '.join(col.get_text(strip=True) for col in row.find_all(['td', 'th']) if col.get_text(strip=True))
        for row in rows if row.find_all(['td', 'th'])
    )

def extract_written_date(soup):
    selectors = [
        "table.bbs_view tr:nth-of-type(2) td:nth-of-type(2)",  # SW중심대학사업단 형식
        "dd.info div.date",                                    # 공학교육혁신센터 형식
        "div.bbs_right span:last-child",                       # 메인페이지 공지사항 형식
        "li.b-date-box span:last-child",                       # 학과 페이지 형식
        "div.b-etc-box li.b-date-box span",
        "dl.date dd",
        "span.date"
    ]

    for selector in selectors:
        date_tag = soup.select_one(selector)
        if date_tag:
            date_text = date_tag.get_text(strip=True)
            match = re.search(r'(20\d{2}[.\s년-]+[01]?\d[.\s월-]+[0-3]?\d+)', date_text)
            if match:
                cleaned_date = match.group(1)
                cleaned_date = cleaned_date.replace('년', '.').replace('월', '.').replace('일', '').replace('-', '.').replace(' ', '')
                return cleaned_date.strip('.')

    full_text = soup.get_text(" ", strip=True)
    match = re.search(r'(20\d{2}[.\-/년\s]+[01]?\d[.\-/월\s]+[0-3]?\d+)', full_text)
    if match:
        cleaned_date = match.group(1)
        cleaned_date = cleaned_date.replace('년', '.').replace('월', '.').replace('일', '').replace(' ', '').replace('-', '.')
        return cleaned_date.strip('.')

    return "(작성일 없음)"

def generate_notice_key(title, date):
    temp_title = title if title else ""
    date_str = date if date else ""
    processed_title = re.sub(r'\[[^\]]+\]|\([^\)]+\)|<[^>]+>|【[^】]+】', '', temp_title)
    processed_title = unicodedata.normalize('NFKC', processed_title)
    processed_title = re.sub(r'[^a-zA-Z0-9가-힣]', '', processed_title).lower()
    date_str = re.sub(r'[^0-9]', '', date_str)
    return f"{processed_title}_{date_str}"

def get_soup(url):
    try:
        response = session.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
        return BeautifulSoup(response.text, 'html.parser')
    except Exception as e:
        print(f"      ❌ 페이지 요청 실패: {url} ({e})")
        return None

def delay_request(min_sec=0.5, max_sec=1.5):
    time.sleep(random.uniform(min_sec, max_sec))

def is_too_old(post_date_str, start_date_obj, date_format="%Y.%m.%d"):
    """게시물 날짜가 지정된 시작 날짜보다 오래되었는지 확인"""
    if not post_date_str:
        return False
    try:
        post_date_obj = datetime.strptime(post_date_str, date_format)
        return post_date_obj < start_date_obj
    except (ValueError, TypeError):
        return False

# --- 기존 데이터 로드 ---
def load_existing_data():
    """
    1순위: Azure Blob Storage에서 CSV 다운로드 → pre_existing_data 로드
    2순위: Blob이 없거나 실패 시 로컬 CSV_PATH에서 로드 (fallback)
    """
    global pre_existing_data, existing_keys_set

    # 1) Azure Blob 시도
    if blob_service_client:
        try:
            blob_client = blob_service_client.get_blob_client(container=AZURE_CSV_CONTAINER_NAME, blob=CSV_FILE)
            print(f"📄 Azure Storage에서 '{CSV_FILE}' 파일을 다운로드합니다...")
            downloader = blob_client.download_blob()  # exists() 호출 없이 바로 시도
            blob_bytes = downloader.readall()
            blob_string = blob_bytes.decode("utf-8-sig")

            csv_file_in_memory = io.StringIO(blob_string)
            reader = csv.DictReader(csv_file_in_memory)

            if "제목" not in reader.fieldnames or "작성일" not in reader.fieldnames:
                print(f"⚠️ '{CSV_FILE}'에 '제목' 또는 '작성일' 컬럼이 없어 중복 검사 데이터를 로드할 수 없습니다.")
            else:
                pre_existing_data = list(reader)
                existing_keys_set = {
                    generate_notice_key(row.get('제목', ''), row.get('작성일', ''))
                    for row in pre_existing_data
                }
                print(f"✅ 기존 데이터 {len(pre_existing_data)}건 로드 및 중복 검사용 key {len(existing_keys_set)}개 생성 완료.")
                return  # 성공했으므로 함수 종료

        except ResourceNotFoundError:
            print(f"📄 Azure Storage에 '{CSV_FILE}' 파일이 없어 새로 시작합니다.")
        except Exception as e:
            print(f"❌ Azure Storage에서 CSV 파일 로드 중 오류 발생: {e}")

    # 2) 로컬 CSV fallback
    try:
        if os.path.exists(CSV_PATH):
            print(f"📄 로컬에서 기존 CSV 로드: {CSV_PATH}")
            with open(CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                if "제목" in reader.fieldnames and "작성일" in reader.fieldnames:
                    pre_existing_data = list(reader)
                    existing_keys_set = {
                        generate_notice_key(row.get('제목', ''), row.get('작성일', ''))
                        for row in pre_existing_data
                    }
                    print(f"✅ (로컬) 기존 데이터 {len(pre_existing_data)}건 로드 완료.")
                else:
                    print("⚠️ (로컬) CSV 컬럼에 '제목' 또는 '작성일'이 없어 중복검사를 건너뜁니다.")
        else:
            print(f"ℹ️ 로컬 CSV가 존재하지 않습니다: {CSV_PATH}")
    except Exception as e:
        print(f"❌ 로컬 CSV 로드 중 오류: {e}")

def add_notice_if_not_duplicate(title, date, content, link, images):
    """중복을 검사하고, 중복이 아닐 경우에만 데이터를 추가합니다."""
    def _is_similar(title1, title2):
        SEQ_MATCHER_THRESHOLD = 0.9
        COSINE_SIMILARITY_THRESHOLD = 0.8

        def normalize_for_similarity(text):
            processed = unicodedata.normalize('NFKC', text.lower())
            processed = re.sub(r'[^\w\s가-힣]', '', processed)
            return ' '.join(processed.split())

        norm_title1 = normalize_for_similarity(title1)
        norm_title2 = normalize_for_similarity(title2)

        if not norm_title1 or not norm_title2:
            return False

        seq_ratio = SequenceMatcher(None, norm_title1, norm_title2).ratio()

        try:
            vectorizer = TfidfVectorizer()
            tfidf_matrix = vectorizer.fit_transform([norm_title1, norm_title2])
            cosine_sim = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
        except ValueError:
            cosine_sim = 0

        if seq_ratio >= SEQ_MATCHER_THRESHOLD and cosine_sim >= COSINE_SIMILARITY_THRESHOLD:
            print(f"      🚫 [중복-유사도] (Seq: {seq_ratio:.2f}, Cos: {cosine_sim:.2f}) {title[:40]}")
            return True
        return False

    DATE_WINDOW_DAYS = 3
    new_key = generate_notice_key(title, date)

    try:
        new_date_obj = datetime.strptime(date, "%Y.%m.%d")
    except (ValueError, TypeError):
        new_date_obj = None

    # 1. 현재 세션 내 중복 검사
    for post_in_session in all_data:
        if new_key == generate_notice_key(post_in_session['제목'], post_in_session['작성일']):
            print(f"      🚫 [중복-세션/완전일치] {title[:40]}")
            return False

        if new_date_obj:
            try:
                session_date_obj = datetime.strptime(post_in_session['작성일'], "%Y.%m.%d")
                if abs((new_date_obj - session_date_obj).days) <= DATE_WINDOW_DAYS:
                    if _is_similar(title, post_in_session['제목']):
                        return False
            except (ValueError, TypeError):
                continue

    # 2. 기존 파일 데이터와 중복 검사
    if new_date_obj and pre_existing_data:
        start_date_window = new_date_obj - timedelta(days=DATE_WINDOW_DAYS)
        for existing_post in pre_existing_data:
            try:
                existing_date_obj = datetime.strptime(existing_post.get('작성일', ''), "%Y.%m.%d")

                if start_date_window <= existing_date_obj <= new_date_obj:
                    existing_title = existing_post.get('제목', '')
                    if new_key == generate_notice_key(existing_title, existing_post.get('작성일', '')):
                        print(f"      🚫 [중복-기존파일/완전일치] {title[:40]}")
                        return False
                    if _is_similar(title, existing_title):
                        return False
            except (ValueError, TypeError):
                continue

    all_data.append({"제목": title, "작성일": date, "본문내용": content, "링크": link, "사진": ";".join(images)})
    return True

# --- 크롤링 함수 ---
def extract_notice_board_urls(college_pages_list):
    department_boards_dict = {}
    base_wwwk_url = "https://wwwk.kangwon.ac.kr"
    print("📜 단과대학 페이지에서 학과별 공지사항 게시판 URL을 수집합니다...")
    for college in tqdm(college_pages_list, desc="단과대학별 URL 수집 중"):
        soup = get_soup(college['url'])
        if not soup:
            continue
        blocks = soup.select("div.box.temp_titbox")
        for block in blocks:
            dept = block.select_one("h4.h0")
            link = block.select_one("ul.shortcut li:last-child a")
            if dept and link:
                name = dept.text.strip().split('\n')[0]
                if name in manual_board_mapping:
                    continue
                href = link.get("href")
                if href:
                    url = urljoin(base_wwwk_url, href)
                    url = url.replace("wwwk.kangwon.ac.kr/wwwk.kangwon.ac.kr", "wwwk.kangwon.ac.kr")
                    department_boards_dict[name] = url
        time.sleep(0.1)

    for dept_name, manual_url in manual_board_mapping.items():
        department_boards_dict[dept_name] = manual_url
    print(f"✅ 총 {len(department_boards_dict)}개의 학과 공지사항 URL 수집 완료.")
    return department_boards_dict

def crawl_all_departments(board_dict, start_date_obj, max_page=None):
    def append_offset(url, offset):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        query['article.offset'] = [str(offset)]
        new_query = urlencode(query, doseq=True)
        return urlunparse(parsed._replace(query=new_query))

    for dept, url in tqdm(board_dict.items(), desc="학과별 진행"):
        print(f"\n📘 [{dept}] 시작: {url}")
        page = 0
        stop_crawling_this_dept = False
        previous_page_links = set()

        while not stop_crawling_this_dept and (max_page is None or page < max_page):
            page_url = append_offset(url, page * 10)
            soup = get_soup(page_url)
            if not soup:
                break
            rows = soup.select("tbody tr")

            first_row_text = rows[0].get_text() if rows else ""
            if not rows or (len(rows) == 1 and "등록된 글이 없습니다" in first_row_text):
                if page == 0:
                    print(f"      - 등록된 글이 없습니다.")
                break

            current_page_links = set()
            for row in rows:
                try:
                    is_notice_row = row.select_one("td") and "공지" in row.select_one("td").text
                    a_tag = row.select_one("a")
                    if not a_tag:
                        continue

                    raw_href = a_tag.get("href")
                    parsed_href = urlparse(raw_href)
                    query_params = parse_qs(parsed_href.query)
                    query_params.pop('article.offset', None); query_params.pop('pageIndex', None); query_params.pop('page', None)
                    normalized_query = urlencode(query_params, doseq=True)
                    normalized_href = urlunparse(parsed_href._replace(query=normalized_query))
                    current_page_links.add(normalized_href)

                    title = a_tag.get_text(strip=True)
                    href = urljoin(url, raw_href)

                    detail_soup = get_soup(href)
                    if not detail_soup:
                        continue
                    delay_request(0.1, 0.3)

                    date = extract_written_date(detail_soup)

                    if is_too_old(date, start_date_obj):
                        if is_notice_row:
                            continue
                        else:
                            print(f"  🔚 [{dept}] 지정된 시작 날짜 이전 게시물 발견, 중단합니다.")
                            stop_crawling_this_dept = True
                            break

                    content_div = detail_soup.select_one("div.b-content-box div.fr-view") or detail_soup.select_one("div.b-content-box")
                    content = clean_html_keep_table(str(content_div)) if content_div else "(본문 없음)"

                    img_files = []
                    if content_div:
                        prefix = f"{sanitize_filename(dept)}_{generate_notice_key(title, date)}"
                        folder_path = os.path.join(SAVE_FOLDER, "college_depts", sanitize_filename(dept))

                        for i, img in enumerate(content_div.select("img")):
                            src = img.get("src")
                            if src and not src.startswith("data:"):
                                full_img_url = urljoin(href, src)
                                saved_path = save_image(full_img_url, folder_path, prefix, i, original_name=src, referer_url=href)
                                if saved_path:
                                    img_files.append(saved_path)

                    if add_notice_if_not_duplicate(title, date, content, href, img_files):
                        print(f"      📄 [수집] {title[:40]}")

                except Exception as e:
                    print(f"      ❌ 상세 페이지 처리 중 오류 발생: {title[:30]} ({e})")

            if current_page_links == previous_page_links:
                print(f"      - [{dept}] 이전 페이지와 내용이 동일하여 중단합니다 (페이지네이션 없음).")
                break

            previous_page_links = current_page_links
            if stop_crawling_this_dept:
                break
            page += 1
            delay_request()

        if not stop_crawling_this_dept:
            print(f"✅ [{dept}] 확인 완료.")

def crawl_mainpage(start_date_obj):
    print("\n📂 [메인페이지] 시작")
    BASE_URL = "https://www.kangwon.ac.kr"
    PATH_PREFIX = "/www"
    categories = [
        {"name": "공지사항", "bbsNo": "81", "key": "277"},
        {"name": "행사안내", "bbsNo": "38", "key": "279"},
        {"name": "공모모집", "bbsNo": "345", "key": "1959"},
        {"name": "장학게시판", "bbsNo": "34", "key": "232"},
        {"name": "취업정보", "bbsNo": "117", "key": "768"},
    ]

    for cat in categories:
        print(f"  ➡️  [{cat['name']}] 수집 중...")
        stop_crawling_this_category = False
        for page in range(1, 999):
            if stop_crawling_this_category:
                break

            list_url = f"{BASE_URL}{PATH_PREFIX}/selectBbsNttList.do?bbsNo={cat['bbsNo']}&pageUnit=10&key={cat['key']}&pageIndex={page}"
            soup = get_soup(list_url)
            if not soup:
                break

            rows = soup.select("tbody tr")
            if not rows:
                break

            for row in rows:
                try:
                    is_notice_row = row.select_one("td") and '공지' in row.select_one("td").get_text(strip=True)
                    a_tag = row.select_one("td.subject a")
                    if not a_tag:
                        continue

                    title = a_tag.get_text(strip=True)
                    href = a_tag.get("href", "")

                    detail_url = ""
                    if "fnSelectBbsNttView" in href:
                        match = re.search(r"fnSelectBbsNttView\('(\d+)',\s*'(\d+)',\s*'(\d+)'\)", href)
                        if not match:
                            continue
                        bbs_no, ntt_no, key_param = match.groups()
                        detail_url = f"{BASE_URL}{PATH_PREFIX}/selectBbsNttView.do?bbsNo={bbs_no}&nttNo={ntt_no}&key={key_param}"
                    else:
                        detail_url = urljoin(f"{BASE_URL}{PATH_PREFIX}/", href)

                    detail_soup = get_soup(detail_url)
                    if not detail_soup:
                        continue
                    delay_request()

                    date = extract_written_date(detail_soup)

                    if is_too_old(date, start_date_obj):
                        if is_notice_row:
                            continue
                        else:
                            print(f"      🔚 [{cat['name']}] 지정된 시작 날짜 이전 게시물 발견, 중단합니다.")
                            stop_crawling_this_category = True
                            break

                    content_div = detail_soup.select_one("div#bbs_ntt_cn_con, td.bbs_content")
                    content = clean_html_keep_table(str(content_div)) if content_div else "(본문 없음)"

                    img_tags = (content_div.select("img") if content_div else []) + (detail_soup.select("div.photo_area img") if detail_soup.select_one("div.photo_area") else [])
                    image_urls_with_duplicates = [urljoin(detail_url, img.get("src")) for img in img_tags if img.get("src") and not img.get("src").startswith("data:")]
                    images_urls = list(dict.fromkeys(image_urls_with_duplicates))

                    prefix = f"main_{generate_notice_key(title, date)}"
                    save_folder_path = os.path.join(SAVE_FOLDER, "main")
                    img_files = [save_image(link, save_folder_path, prefix, i, link) for i, link in enumerate(images_urls)]
                    img_files = list(filter(None, img_files))

                    if add_notice_if_not_duplicate(title, date, content, detail_url, img_files):
                        print(f"      📄 [수집] {title[:45]}")

                except Exception as e:
                    print(f"      ❌ 메인페이지 상세 실패: {title[:30]} ({e})")

            if stop_crawling_this_category:
                break

    print("✅ [메인페이지] 완료")

def crawl_library(start_date_obj):
    print("\n📂 [도서관] 시작")
    base_url = "https://library.kangwon.ac.kr"
    list_api = f"{base_url}/pyxis-api/1/bulletin-boards/24/bulletins"
    detail_api_template = f"{base_url}/pyxis-api/1/bulletins/24/{{id}}"
    stop_crawling = False

    for page in tqdm(range(0, 999), desc="  [도서관]", leave=False):
        if stop_crawling:
            break

        params = {"offset": page * 10, "max": 10, "bulletinCategoryId": 1}
        try:
            res = session.get(list_api, headers=HEADERS, params=params, timeout=10)
            res.raise_for_status()
            list_data = res.json().get("data", {}).get("list", [])
            if not list_data:
                break

            for item in list_data:
                try:
                    is_notice_item = item.get('isNotice', False)
                    title = item.get('title', '(제목 없음)')
                    item_id = item.get('id')
                    if not item_id:
                        continue

                    detail_res = session.get(detail_api_template.format(id=item_id), headers=HEADERS, timeout=10)
                    detail_res.raise_for_status()
                    detail_data = detail_res.json().get("data", {})

                    date = detail_data.get("dateCreated", "")[:10]

                    if is_too_old(date, start_date_obj, date_format="%Y-%m-%d"):
                        if is_notice_item:
                            continue
                        else:
                            print(f"      🔚 [도서관] 지정된 시작 날짜 이전 게시물 발견, 중단합니다.")
                            stop_crawling = True
                            break

                    date_for_csv = date.replace("-", ".")
                    detail_url = f"{base_url}/community/bulletin/notice/{item_id}"

                    html_content = detail_data.get("content", "")
                    content_soup = BeautifulSoup(html_content, "html.parser")
                    content = content_soup.get_text("\n", strip=True)

                    img_files = []
                    prefix = f"library_{generate_notice_key(title, date_for_csv)}"
                    folder_path = os.path.join(SAVE_FOLDER, "library")
                    for i, img in enumerate(content_soup.select("img")):
                        src = img.get("src")
                        if src and "/pyxis-api/attachments/" in src:
                            full_img_url = urljoin(base_url, src)
                            saved_path = save_image(full_img_url, folder_path, prefix, i)
                            if saved_path:
                                img_files.append(saved_path)

                    if add_notice_if_not_duplicate(title, date_for_csv, content, detail_url, img_files):
                        print(f"      📄 [수집] {title[:45]}")

                except Exception as e:
                    print(f"      - 도서관 상세 처리 실패: {e}")

            if stop_crawling:
                break
        except requests.exceptions.RequestException as e:
            print(f"      - 도서관 목록 요청 실패 (page={page}): {e}")
            break

    print("✅ [도서관] 완료")

def crawl_engineering(start_date_obj):
    print("\n📂 [공학교육혁신센터] 시작")
    base_url = "https://icee.kangwon.ac.kr"
    stop_crawling = False

    for page in tqdm(range(1, 999), desc="  [공학교육혁신센터]", leave=False):
        if stop_crawling:
            break

        list_url = f"{base_url}/index.php?mt=page&mp=5_1&mm=oxbbs&oxid=1&cpage={page}"
        soup = get_soup(list_url)
        if not soup:
            break

        rows = soup.select("table.bbs_list tbody tr")
        if not rows:
            break

        for row in rows:
            try:
                a_tag = row.select_one("td.tit a")
                date_td = row.select_one("td.dt")
                if not a_tag or not date_td:
                    continue

                title = a_tag.get_text(strip=True)
                date = date_td.text.strip().replace("-", ".")
                is_notice_row = title.startswith('[공지]')

                if is_too_old(date, start_date_obj):
                    if is_notice_row:
                        continue
                    else:
                        print(f"      🔚 [공학교육혁신센터] 지정된 시작 날짜 이전 게시물 발견, 중단합니다.")
                        stop_crawling = True
                        break

                detail_url = urljoin(base_url, a_tag['href'])
                detail_soup = get_soup(detail_url)
                if not detail_soup:
                    continue
                delay_request()

                content_div = detail_soup.select_one("div.view_cont, div.note")
                content = clean_html_keep_table(str(content_div))

                img_files = []
                if content_div:
                    prefix = f"engineering_{generate_notice_key(title, date)}"
                    folder_path = os.path.join(SAVE_FOLDER, "engineering")
                    for i, img in enumerate(content_div.select("img")):
                        src = img.get("src")
                        if src and not src.startswith("data:"):
                            full_img_url = urljoin(detail_url, src)
                            saved_path = save_image(full_img_url, folder_path, prefix, i, src)
                            if saved_path:
                                img_files.append(saved_path)

                if add_notice_if_not_duplicate(title, date, content, detail_url, img_files):
                    print(f"      📄 [수집] {title[:45]}")

            except Exception as e:
                print(f"      - 공학교육혁신센터 상세 처리 실패: {e}")

        if stop_crawling:
            break

    print("✅ [공학교육혁신센터] 완료")

def crawl_international(start_date_obj):
    print("\n📂 [국제교류처] 시작")
    base_url = "https://oiaknu.kangwon.ac.kr"
    path = "/oiaknu/notice.do"
    stop_crawling = False

    for offset in tqdm(range(0, 9999, 10), desc="  [국제교류처]", leave=False):
        if stop_crawling:
            break

        list_url = f"{base_url}{path}?article.offset={offset}"
        soup = get_soup(list_url)
        if not soup:
            break

        rows = soup.select("tbody > tr")
        if not rows:
            break

        for row in rows:
            try:
                title_tag = row.select_one("td.b-td-left a")
                date_tag = row.select_one("td:nth-last-child(3)")
                if not title_tag or not date_tag:
                    continue

                title = title_tag.get_text(strip=True)
                date_str = date_tag.get_text(strip=True)
                date = "20" + date_str if date_str and not date_str.startswith("20") else date_str
                is_notice_row = (row.select_one("td").get_text(strip=True) == "공지")

                if is_too_old(date, start_date_obj):
                    if is_notice_row:
                        continue
                    else:
                        print(f"      🔚 [국제교류처] 지정된 시작 날짜 이전 게시물 발견, 중단합니다.")
                        stop_crawling = True
                        break

                href = title_tag.get('href', '')
                parsed_href = urlparse(href)
                query_params = parse_qs(parsed_href.query)
                article_no = query_params.get('articleNo', [None])[0]
                if not article_no:
                    continue

                detail_url = f"{base_url}{path}?mode=view&articleNo={article_no}"
                detail_soup = get_soup(detail_url)
                if not detail_soup:
                    continue
                delay_request()

                content_div = detail_soup.select_one("div.b-content-box")
                content = clean_html_keep_table(str(content_div))

                img_files = []
                if content_div:
                    prefix = f"international_{generate_notice_key(title, date)}"
                    folder_path = os.path.join(SAVE_FOLDER, "international")
                    for i, img in enumerate(content_div.select("img")):
                        src = img.get("src")
                        if src and not src.startswith("data:"):
                            full_img_url = urljoin(detail_url, src)
                            saved_path = save_image(full_img_url, folder_path, prefix, i, src)
                            if saved_path:
                                img_files.append(saved_path)

                if add_notice_if_not_duplicate(title, date, content, detail_url, img_files):
                    print(f"      📄 [수집] {title[:45]}")

            except Exception as e:
                print(f"      - 국제교류처 처리 중 오류 발생: {e}")

        if stop_crawling:
            break

    print("✅ [국제교류처] 완료")

def crawl_sw(start_date_obj):
    print("\n📂 [SW중심대학사업단] 시작")
    base_url = "https://sw.kangwon.ac.kr"
    stop_crawling = False

    for page in tqdm(range(1, 100), desc="  [SW중심대학사업단]", leave=False):
        if stop_crawling:
            break

        list_url = f"{base_url}/index.php?mt=page&mp=5_1&mm=oxbbs&oxid=1&cpage={page}"
        soup = get_soup(list_url)
        if not soup:
            break

        rows = soup.select("table.bbs_list > tbody > tr")
        if not rows:
            break

        for row in rows:
            try:
                date_td = row.select_one("td:nth-last-child(2)")
                title_tag = row.select_one("td.tit a")

                if not date_td or not title_tag:
                    continue

                date = date_td.get_text(strip=True).replace("-", ".")
                is_notice_row = bool(row.select_one("img[alt='공지글']"))

                if is_too_old(date, start_date_obj):
                    if is_notice_row:
                        continue
                    else:
                        print(f"      🔚 [SW중심대학사업단] 지정된 시작 날짜 이전 게시물 발견, 중단합니다.")
                        stop_crawling = True
                        break

                title = title_tag.get_text(strip=True)
                detail_url = urljoin(base_url, title_tag.get("href"))

                detail_soup = get_soup(detail_url)
                if not detail_soup:
                    continue
                delay_request()

                content_div = detail_soup.select_one("table.bbs_view td.bbs_td[colspan='6']")
                content = clean_html_keep_table(str(content_div)) if content_div else "(본문 없음)"

                img_files = []
                if content_div:
                    prefix = f"sw_{generate_notice_key(title, date)}"
                    folder_path = os.path.join(SAVE_FOLDER, "sw")

                    for i, img in enumerate(content_div.select("img")):
                        src = img.get("src")
                        if src and not src.startswith("data:"):
                            full_img_url = urljoin(detail_url, src)
                            saved_path = save_image(full_img_url, folder_path, prefix, i, src)
                            if saved_path:
                                img_files.append(saved_path)

                if add_notice_if_not_duplicate(title, date, content, detail_url, img_files):
                    print(f"      📄 [수집] {title[:45]}")

            except Exception as e:
                print(f"      ❌ SW중심대학사업단 처리 중 오류 발생: {title[:30]} ({e})")

        if stop_crawling:
            break

    print("✅ [SW중심대학사업단] 완료")

# --- 데이터 소스 ---
college_intro_pages = [
    {'college_name': '간호대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1782&'},
    {'college_name': '경영대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1752&'},
    {'college_name': '농업생명과학대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1758&'},
    {'college_name': '동물생명과학대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1761&'},
    {'college_name': '문화예술 공과대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1912&'},
    {'college_name': '사범대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1767&'},
    {'college_name': '사회과학대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1770&'},
    {'college_name': '산림환경과학대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1773&'},
    {'college_name': '수의과대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1776&'},
    {'college_name': '약학대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1779&'},
    {'college_name': '의과대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1975&'},
    {'college_name': '의생명과학대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1785&'},
    {'college_name': '인문대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1788&'},
    {'college_name': '자연과학대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1791&'},
    {'college_name': 'IT대학', 'url': 'https://wwwk.kangwon.ac.kr/www/contents.do?key=1794&'},
]
manual_board_mapping = {
    "AI융합학과": "https://ai.kangwon.ac.kr/ai/community/notice.do",
    "디지털밀리터리학과": "https://military.kangwon.ac.kr/military/professor/notice.do",
    "자유전공학부": "https://liberal.kangwon.ac.kr/liberal/community/notice.do",
    "글로벌융합학부": "https://globalconvergence.kangwon.ac.kr/globalconvergence/info/undergraduate-community.do",
    "미래융합가상학과": "https://multimajor.kangwon.ac.kr/multimajor/community/notice.do",
    "동물산업융합학과": "https://animal.kangwon.ac.kr/animal/community/notice.do"
}

# --- 메인 실행 로직 ---
if __name__ == "__main__":
    print("\n🚀 강원대 전체 공지 크롤링 시작")

    try:
        START_DATE_OBJ = datetime.strptime(CRAWL_START_DATE, "%Y-%m-%d")
        print(f"🗓️  수집 시작 날짜: {CRAWL_START_DATE} 이후의 모든 새 게시물을 수집합니다.")
    except ValueError:
        print(f"❌ 날짜 형식이 잘못되었습니다. 'YYYY-MM-DD' 형식으로 입력해주세요. (입력값: {CRAWL_START_DATE})")
        exit()

    load_existing_data()

    crawl_mainpage(START_DATE_OBJ)
    crawl_library(START_DATE_OBJ)
    crawl_engineering(START_DATE_OBJ)
    crawl_international(START_DATE_OBJ)
    crawl_sw(START_DATE_OBJ)

    boards = extract_notice_board_urls(college_intro_pages)
    if boards:
        crawl_all_departments(boards, START_DATE_OBJ, max_page=None)

    # --- 수집된 데이터를 CSV로 저장 (로컬 + Azure 업로드) ---
    if not all_data:
        print("\n✅ 추가할 새로운 게시글이 없습니다.")
    else:
        print(f"\n🔄 총 {len(all_data)}건의 새로운 게시글을 기존 데이터와 병합하여 저장합니다...")

        try:
            # 1) 기존 데이터 + 신규 데이터 병합
            final_data_to_save = pre_existing_data + all_data

            # 2) CSV 문자열로 변환 (UTF-8-SIG)
            output_stream = io.StringIO()
            writer = csv.DictWriter(output_stream, fieldnames=["제목", "작성일", "본문내용", "링크", "사진"])
            writer.writeheader()
            writer.writerows(final_data_to_save)
            csv_output_string = output_stream.getvalue()

            # 3) ✅ 먼저 "로컬"에 저장
            os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
            with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
                f.write(csv_output_string)
            print(f"💾 로컬 저장 완료: {CSV_PATH} (총 {len(final_data_to_save)}건)")

            # 4) 그 다음 Azure Blob에도 업로드(가능할 때)
            if not blob_service_client:
                print("⚠️ Azure 클라이언트가 없어 Blob 업로드는 건너뜁니다.")
            else:
                try:
                    blob_client = blob_service_client.get_blob_client(container=AZURE_CSV_CONTAINER_NAME, blob=CSV_FILE)
                    blob_client.upload_blob(csv_output_string.encode("utf-8-sig"), overwrite=True)
                    print(f"☁️ Azure Storage 업로드 완료: container='{AZURE_CSV_CONTAINER_NAME}', blob='{CSV_FILE}'")
                except Exception as e:
                    print(f"⚠️ Blob 업로드 실패(로컬 저장은 완료): {e}")

            print("✅ 저장 절차 완료 (로컬 → Blob 순서)")

        except Exception as e:
            print(f"❌ CSV 저장/업로드 중 오류 발생: {e}")
