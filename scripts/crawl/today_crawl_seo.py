import os
import csv
import time
import re
import random
import unicodedata
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

# --- 기본 설정 ---
HEADERS = {"User-Agent": "Mozilla/5.0"}
SAVE_FOLDER = "강원대 전 기관 + 전 학과_이미지"
CSV_FILE = "강원대 통합 공지사항 크롤링.csv"
os.makedirs(SAVE_FOLDER, exist_ok=True)

# ▼▼▼ 크롤링 시작 날짜 설정 ▼▼▼
CRAWL_START_DATE = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
# ▲▲▲ 설정 완료 ▲▲▲

# --- 세션 및 재시도 설정 ---
session = requests.Session()
retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry)
session.mount("http://", adapter)
session.mount("https://", adapter)

# --- 전역 변수 ---
all_data = []
pre_existing_data = [] # 기존 CSV 데이터를 담을 리스트

# --- 유틸리티 함수 ---
def sanitize_filename(name):
    return re.sub(r'[^\w\s_.-]', '_', name).strip()

def save_image(img_url, folder, prefix, idx, original_name="image.jpg"):
    try:
        os.makedirs(folder, exist_ok=True)
        ext = os.path.splitext(original_name)[1]
        if not ext or len(ext) > 5: ext = '.jpg'
        filename = sanitize_filename(f"{prefix}_{idx}{ext}")
        filepath = os.path.join(folder, filename)
        res = session.get(img_url, headers=HEADERS, timeout=10)
        time.sleep(random.uniform(0.1, 0.3))
        if res.status_code == 200 and len(res.content) > 1024:
            with open(filepath, "wb") as f:
                f.write(res.content)
            return filepath.replace("\\", "/")
    except Exception as e:
        print(f"       ⚠️ 이미지 저장 실패: {img_url} ({e})")
    return None

def clean_html_keep_table(raw_html):
    soup = BeautifulSoup(raw_html, 'html.parser')
    # ▼▼▼▼▼ 추가된 부분 ▼▼▼▼▼
    # '사진 확대보기'를 포함한 span 태그를 찾아서 제거
    for zoom_element in soup.select('span.photo_zoom'):
        zoom_element.decompose()
    # ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
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
    text = soup.get_text(" ", strip=True)
    match = re.search(r'20\d{2}[.\-/년\s]+[01]?\d[.\-/월\s]+[0-3]?\d[일\s]*', text)
    if match:
        raw = match.group().replace(" ", "").replace("년", ".").replace("월", ".").replace("일", "")
        return raw.strip(".")
    return None

def generate_notice_key(title, date):
    """
    제목과 날짜를 받아 표준화된 키를 생성합니다.
    - 제목은 소문자화 및 유니코드 정규화됩니다.
    - 특수문자는 제거하되, 단어 구분을 위한 단일 공백은 유지됩니다.
    - 날짜는 구분자가 모두 제거된 숫자 형식으로 바뀝니다.
    """
    temp_title = title if title else ""
    date_str = date if date else ""

    # 1. 유니코드 정규화 및 소문자 변환
    processed_title = unicodedata.normalize('NFKC', temp_title.lower())
    
    # 2. 특수문자 제거 (알파벳, 숫자, 한글, 공백만 남김)
    # 괄호 제거 로직을 삭제하고, 띄어쓰기를 보존하는 방식으로 변경
    processed_title = re.sub(r'[^\w\s가-힣]', '', processed_title)
    
    # 3. 여러 개의 공백을 단일 공백으로 정규화
    processed_title = ' '.join(processed_title.split())

    # 4. 날짜 형식 표준화 (기존과 동일)
    date_str = date_str.replace('.', '').replace('-', '').replace('/', '').replace(' ', '').lower()
    
    return f"{processed_title}_{date_str}"

def get_soup(url):
    try:
        response = session.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
        return BeautifulSoup(response.text, 'html.parser')
    except Exception as e:
        print(f"       ❌ 페이지 요청 실패: {url} ({e})")
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

# --- 핵심 로직: 데이터 로드 및 추가 ---
def load_existing_data():
    """시작 시 CSV 파일을 읽어 모든 데이터를 전역 리스트(pre_existing_data)에 로드합니다."""
    global pre_existing_data
    if not os.path.exists(CSV_FILE):
        print("📄 기존 CSV 파일이 없어 새로 시작합니다.")
        return
    try:
        print(f"📄 '{CSV_FILE}' 파일을 발견했습니다. 기존 데이터를 로드합니다...")
        with open(CSV_FILE, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if "제목" not in reader.fieldnames or "작성일" not in reader.fieldnames:
                print(f"⚠️ '{CSV_FILE}'에 '제목' 또는 '작성일' 컬럼이 없어 중복 검사를 위한 데이터를 로드할 수 없습니다.")
                return
            pre_existing_data = list(reader)
            print(f"✅ 기존 데이터 {len(pre_existing_data)}건을 로드했습니다. 새 게시물은 최근 3일치 데이터와 비교합니다.")
    except Exception as e:
        print(f"❌ 기존 CSV 파일 로드 중 오류 발생: {e}")

def add_notice_if_not_duplicate(title, date, content, link, images):
    """
    최종 로직에 따라 중복을 검사하고, 중복이 아닐 경우에만 데이터를 추가합니다.
    1. 현재 세션 내에서 완전 일치 및 유사도 검사
    2. 기존 CSV 데이터 중, 새 게시물 날짜 기준 -3일 범위 내에서만 완전 일치 및 유사도 검사
    3. 유사도 검사 조건: Sequence Matcher >= 0.9 AND Cosine Similarity >= 0.8
    """
    SEQ_MATCHER_THRESHOLD = 0.9
    COSINE_SIMILARITY_THRESHOLD = 0.8
    DATE_WINDOW_DAYS = 3
    new_key = generate_notice_key(title, date)
    normalized_new_title = generate_notice_key(title, "_").split('_')[0]
    
    vectorizer = TfidfVectorizer()

    # 1. 현재 세션 내에서 중복 검사 (완전 일치 + 유사도)
    try:
        new_date_obj_session = datetime.strptime(date, "%Y.%m.%d")
        for post_in_session in all_data:
            # (A) 완전 일치 검사
            if new_key == generate_notice_key(post_in_session['제목'], post_in_session['작성일']):
                print(f"       🚫 [중복-세션/완전일치] {title[:40]}")
                return False
            
            # (B) 유사도 검사 (날짜가 비슷한 경우에만 수행)
            try:
                session_date_obj = datetime.strptime(post_in_session['작성일'], "%Y.%m.%d")
                if abs((new_date_obj_session - session_date_obj).days) <= DATE_WINDOW_DAYS:
                    normalized_session_title = generate_notice_key(post_in_session['제목'], "_").split('_')[0]
                    
                    seq_ratio = SequenceMatcher(None, normalized_new_title, normalized_session_title).ratio()
                    
                    try:
                        tfidf_matrix = vectorizer.fit_transform([normalized_new_title, normalized_session_title])
                        cosine_sim = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
                    except ValueError:
                        cosine_sim = 0 # 단어가 없는 제목 처리

                    if seq_ratio >= SEQ_MATCHER_THRESHOLD and cosine_sim >= COSINE_SIMILARITY_THRESHOLD:
                        print(f"       🚫 [중복-세션/유사도] (Seq: {seq_ratio:.2f}, Cos: {cosine_sim:.2f}) {title[:40]}")
                        return False
            except (ValueError, TypeError):
                continue
    except (ValueError, TypeError):
        for post_in_session in all_data:
            if new_key == generate_notice_key(post_in_session['제목'], post_in_session['작성일']):
                print(f"       🚫 [중복-세션/완전일치] {title[:40]}")
                return False

    # 2. 기존 파일 데이터와 날짜 창(Date Window) 내에서 중복 검사 (완전 일치 + 유사도)
    try:
        new_date_obj = datetime.strptime(date, "%Y.%m.%d")
        start_date_window = new_date_obj - timedelta(days=DATE_WINDOW_DAYS)

        for existing_post in pre_existing_data:
            try:
                existing_date_str = existing_post.get('작성일')
                if not existing_date_str: continue
                
                existing_date_obj = datetime.strptime(existing_date_str, "%Y.%m.%d")

                if start_date_window <= existing_date_obj <= new_date_obj:
                    existing_title = existing_post.get('제목', '')
                    
                    if new_key == generate_notice_key(existing_title, existing_date_str):
                        print(f"       🚫 [중복-기존파일/완전일치] {title[:40]}")
                        return False
                    
                    normalized_existing_title = generate_notice_key(existing_title, "_").split('_')[0]
                    
                    seq_ratio = SequenceMatcher(None, normalized_new_title, normalized_existing_title).ratio()

                    try:
                        tfidf_matrix = vectorizer.fit_transform([normalized_new_title, normalized_existing_title])
                        cosine_sim = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
                    except ValueError:
                        cosine_sim = 0 # 단어가 없는 제목 처리

                    if seq_ratio >= SEQ_MATCHER_THRESHOLD and cosine_sim >= COSINE_SIMILARITY_THRESHOLD:
                        print(f"       🚫 [중복-기존파일/유사도] (Seq: {seq_ratio:.2f}, Cos: {cosine_sim:.2f}) {title[:40]}")
                        return False
            except (ValueError, TypeError):
                continue
    except (ValueError, TypeError):
        pass

    # 모든 중복 검사를 통과하면 데이터 추가
    all_data.append({"제목": title, "작성일": date, "본문내용": content, "링크": link, "사진": ";".join(images)})
    return True

# --- 크롤링 함수 ---
def extract_notice_board_urls(college_pages_list):
    department_boards_dict = {}
    base_wwwk_url = "https://wwwk.kangwon.ac.kr"
    print("📜 단과대학 페이지에서 학과별 공지사항 게시판 URL을 수집합니다...")
    for college in tqdm(college_pages_list, desc="단과대학별 URL 수집 중"):
        soup = get_soup(college['url'])
        if not soup: continue
        blocks = soup.select("div.box.temp_titbox")
        for block in blocks:
            dept = block.select_one("h4.h0")
            link = block.select_one("ul.shortcut li:last-child a")
            if dept and link:
                name = dept.text.strip().split('\n')[0]
                if name in manual_board_mapping: continue
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
            if not soup: break
            rows = soup.select("tbody tr")

            first_row_text = rows[0].get_text() if rows else ""
            if not rows or (len(rows) == 1 and "등록된 글이 없습니다" in first_row_text):
                if page == 0: print(f"     - 등록된 글이 없습니다.")
                break

            current_page_links = set()
            for row in rows:
                try:
                    is_notice_row = row.select_one("td") and "공지" in row.select_one("td").text
                    a_tag = row.select_one("a")
                    if not a_tag: continue
                    
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
                    if not detail_soup: continue
                    delay_request(0.1, 0.3)
                    
                    date = extract_written_date(detail_soup)

                    if is_too_old(date, start_date_obj):
                        if is_notice_row:
                            print(f"         🟠 [오래된 공지] {title[:35]} (날짜: {date}) - 건너뜁니다.")
                            continue
                        else:
                            print(f"   🔚 [{dept}] 지정된 시작 날짜 이전 게시물 발견, 중단합니다.")
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
                                saved_path = save_image(full_img_url, folder_path, prefix, i, src)
                                if saved_path: img_files.append(saved_path)
                    
                    if add_notice_if_not_duplicate(title, date, content, href, img_files):
                        print(f"         📄 [수집] {title[:40]}")

                except Exception as e:
                    print(f"         ❌ 상세 페이지 처리 중 오류 발생: {title[:30]} ({e})")
            
            if current_page_links == previous_page_links:
                print(f"     - [{dept}] 이전 페이지와 내용이 동일하여 중단합니다 (페이지네이션 없음).")
                break
            
            previous_page_links = current_page_links
            if stop_crawling_this_dept: break
            page += 1
            delay_request()
        
        if not stop_crawling_this_dept: print(f"✅ [{dept}] 확인 완료 (최대 {max_page}페이지).")

def crawl_mainpage(start_date_obj):
    print("\n📂 [메인페이지] 시작")
    BASE_URL = "https://www.kangwon.ac.kr"
    PATH_PREFIX = "/www"
    categories = [
        {"name": "공지사항", "bbsNo": "81", "key": "277"},
        {"name": "행사안내", "bbsNo": "38", "key": "279"},
        {"name": "공모모집", "bbsNo": "345", "key": "1959"},
        {"name": "장학게시판", "bbsNo": "34", "key": "232"},
    ]

    for cat in categories:
        print(f"   ➡️  [{cat['name']}] 수집 중...")
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
                            print(f"         🟠 [오래된 공지] {title[:35]} - 건너뜁니다.")
                            continue
                        else:
                            print(f"       🔚 [{cat['name']}] 지정된 시작 날짜 이전 게시물 발견, 중단합니다.")
                            stop_crawling_this_category = True
                            break
                    
                    # ▼▼▼▼▼ 주요 수정 부분 ▼▼▼▼▼
                    content_div = detail_soup.select_one("div#bbs_ntt_cn_con, td.bbs_content")
                    # .get_text() 대신 clean_html_keep_table 함수를 사용하도록 변경
                    content = clean_html_keep_table(str(content_div)) if content_div else "(본문 없음)"
                    # ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
                    
                    img_tags = (content_div.select("img") if content_div else []) + (detail_soup.select("div.photo_area img") if detail_soup.select_one("div.photo_area") else [])
                    image_urls_with_duplicates = [urljoin(detail_url, img.get("src")) for img in img_tags if img.get("src") and not img.get("src").startswith("data:")]
                    images_urls = list(dict.fromkeys(image_urls_with_duplicates))

                    prefix = f"main_{generate_notice_key(title, date)}"
                    save_folder_path = os.path.join(SAVE_FOLDER, "main")
                    img_files = [save_image(link, save_folder_path, prefix, i, link) for i, link in enumerate(images_urls)]
                    img_files = list(filter(None, img_files))

                    if add_notice_if_not_duplicate(title, date, content, detail_url, img_files):
                        print(f"         📄 [수집] {title[:45]}")

                except Exception as e:
                    print(f"       ❌ 메인페이지 상세 실패: {title[:30]} ({e})")
            
            if stop_crawling_this_category:
                break
            
    print("✅ [메인페이지] 완료")

def crawl_library(start_date_obj):
    print("\n📂 [도서관] 시작")
    base_url = "https://library.kangwon.ac.kr"
    list_api = f"{base_url}/pyxis-api/1/bulletin-boards/24/bulletins"
    detail_api_template = f"{base_url}/pyxis-api/1/bulletins/24/{{id}}"
    stop_crawling = False
    
    for page in tqdm(range(0, 999), desc="   [도서관]", leave=False): 
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
                            print(f"         🟠 [오래된 공지] {title[:35]} - 건너뜁니다.")
                            continue
                        else:
                            print(f"       🔚 [도서관] 지정된 시작 날짜 이전 게시물 발견, 중단합니다.")
                            stop_crawling = True
                            break

                    date_for_csv = date.replace("-", ".")
                    detail_url = f"{base_url}/community/bulletin/notice/{item_id}"
                    
                    html_content = detail_data.get("content", "")
                    content_soup = BeautifulSoup(html_content, "html.parser")
                    content = content_soup.get_text("\n", strip=True)
                    
                    img_files = []
                    prefix = f"library_{generate_notice_key(title, date_for_csv)}"
                    for i, img in enumerate(content_soup.select("img")):
                        src = img.get("src")
                        if src and "/pyxis-api/attachments/" in src:
                            full_img_url = urljoin(base_url, src)
                            saved_path = save_image(full_img_url, os.path.join(SAVE_FOLDER, "library"), prefix, i)
                            if saved_path:
                                img_files.append(saved_path)
                    
                    if add_notice_if_not_duplicate(title, date_for_csv, content, detail_url, img_files):
                        print(f"         📄 [수집] {title[:45]}")

                except Exception as e:
                    print(f"     - 도서관 상세 처리 실패: {e}")
            
            if stop_crawling:
                break
        except requests.exceptions.RequestException as e:
            print(f"     - 도서관 목록 요청 실패 (page={page}): {e}")
            break
            
    print("✅ [도서관] 완료")

def crawl_engineering(start_date_obj):
    print("\n📂 [공학교육혁신센터] 시작")
    base_url = "https://icee.kangwon.ac.kr"
    stop_crawling = False
    
    for page in tqdm(range(1, 999), desc="   [공학교육혁신센터]", leave=False):
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
                        print(f"         🟠 [오래된 공지] {title[:35]} - 건너뜁니다.")
                        continue
                    else:
                        print(f"       🔚 [공학교육혁신센터] 지정된 시작 날짜 이전 게시물 발견, 중단합니다.")
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
                    for i, img in enumerate(content_div.select("img")):
                        src = img.get("src")
                        if src and not src.startswith("data:"):
                            full_img_url = urljoin(detail_url, src)
                            saved_path = save_image(full_img_url, os.path.join(SAVE_FOLDER, "engineering"), prefix, i, src)
                            if saved_path:
                                img_files.append(saved_path)
                
                if add_notice_if_not_duplicate(title, date, content, detail_url, img_files):
                    print(f"         📄 [수집] {title[:45]}")

            except Exception as e:
                print(f"     - 공학교육혁신센터 상세 처리 실패: {e}")
        
        if stop_crawling:
            break
            
    print("✅ [공학교육혁신센터] 완료")

def crawl_international(start_date_obj):
    print("\n📂 [국제교류처] 시작")
    base_url = "https://oiaknu.kangwon.ac.kr"
    path = "/oiaknu/notice.do"
    stop_crawling = False
    
    for offset in tqdm(range(0, 9999, 10), desc="   [국제교류처]", leave=False):
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
                        print(f"         🟠 [오래된 공지] {title[:35]} - 건너뜁니다.")
                        continue
                    else:
                        print(f"       🔚 [국제교류처] 지정된 시작 날짜 이전 게시물 발견, 중단합니다.")
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
                    for i, img in enumerate(content_div.select("img")):
                        src = img.get("src")
                        if src and not src.startswith("data:"):
                            full_img_url = urljoin(detail_url, src)
                            saved_path = save_image(full_img_url, os.path.join(SAVE_FOLDER, "international"), prefix, i, src)
                            if saved_path:
                                img_files.append(saved_path)
                
                if add_notice_if_not_duplicate(title, date, content, detail_url, img_files):
                    print(f"         📄 [수집] {title[:45]}")

            except Exception as e:
                print(f"     - 국제교류처 처리 중 오류 발생: {e}")
        
        if stop_crawling:
            break
            
    print("✅ [국제교류처] 완료")


def crawl_sw(start_date_obj):
    print("\n📂 [SW중심대학사업단] 시작")
    base_url = "https://sw.kangwon.ac.kr"
    stop_crawling = False
    
    for page in tqdm(range(1, 100), desc="   [SW중심대학사업단]", leave=False):
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
                        print(f"           🟠 [오래된 공지] ... (날짜: {date}) - 건너뜁니다.")
                        continue
                    else:
                        print(f"         🔚 [SW중심대학사업단] 지정된 시작 날짜 이전 게시물 발견, 중단합니다.")
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
                    print(f"           📄 [수집] {title[:45]}")

            except Exception as e:
                print(f"         ❌ SW중심대학사업단 처리 중 오류 발생: {title[:30]} ({e})")
        
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
        print(f"🗓️ 수집 시작 날짜: {CRAWL_START_DATE} 이후의 모든 새 게시물을 수집합니다.")
    except ValueError:
        print(f"❌ 날짜 형식이 잘못되었습니다. 'YYYY-MM-DD' 형식으로 입력해주세요. (입력값: {CRAWL_START_DATE})")
        exit()
    
    load_existing_data()
    file_exists_before_crawl = os.path.exists(CSV_FILE)

    crawl_mainpage(START_DATE_OBJ)
    crawl_library(START_DATE_OBJ)
    crawl_engineering(START_DATE_OBJ)
    crawl_international(START_DATE_OBJ)
    crawl_sw(START_DATE_OBJ)

    boards = extract_notice_board_urls(college_intro_pages)
    if boards:
        crawl_all_departments(boards, START_DATE_OBJ, max_page=None) 

    # 수집된 새 데이터를 파일에 추가
    if not all_data:
        print("\n✅ 추가할 새로운 게시글이 없습니다.")
    else:
        try:
            with open(CSV_FILE, "a", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["제목", "작성일", "본문내용", "링크", "사진"])
                if not file_exists_before_crawl or os.path.getsize(CSV_FILE) == 0:
                    writer.writeheader()
                writer.writerows(all_data)
            print(f"\n✅ 새로운 게시글 {len(all_data)}건 추가 완료: {CSV_FILE}")
        except Exception as e:
            print(f"❌ CSV 파일 저장 중 오류 발생: {e}")