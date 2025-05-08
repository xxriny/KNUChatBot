# 통합코드.py
import os
import csv
import time
import re
import random
from datetime import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

HEADERS = {"User-Agent": "Mozilla/5.0"}
SAVE_FOLDER = "통합_images"
CSV_FILE = "메인20000여개.csv"
os.makedirs(SAVE_FOLDER, exist_ok=True)

# 요청 세션 설정 (재시도 및 백오프 적용)
session = requests.Session()
retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry)
session.mount("http://", adapter)
session.mount("https://", adapter)

all_data = []

# 맨 위에 추가
batch_size = 100  # 중간 저장 주기
record_count = 0  # 누적 카운트


def sanitize_filename(name):
    return "".join(c if c.isalnum() or c in (' ', '.', '_') else '_' for c in name)

def save_image(img_url, folder, prefix, idx, original_name="image.jpg"):
    try:
        os.makedirs(folder, exist_ok=True)
        ext = os.path.splitext(original_name)[1]
        if not ext or len(ext) > 5:
            ext = '.jpg'
        filename = sanitize_filename(f"{prefix}_{idx}{ext}")
        filepath = os.path.join(folder, filename)

        res = session.get(img_url, headers=HEADERS, timeout=10)
        time.sleep(random.uniform(0.5, 1.2))
        if res.status_code == 200 and len(res.content) > 1024:
            with open(filepath, "wb") as f:
                f.write(res.content)
            return filepath.replace("\\", "/")
        else:
            print(f"⚠️ 다운로드 실패 또는 너무 작음: {img_url}")
    except Exception as e:
        print(f"❌ 이미지 저장 실패: {img_url} ({e})")
    return None

def clean_html_keep_table(raw_html):
    soup = BeautifulSoup(raw_html, 'html.parser')
    output = ''
    for table in soup.find_all('table'):
        output += extract_table_text(table) + '\n'
        table.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for elem in soup.find_all(['p', 'div', 'span']):
        text = elem.get_text(strip=True, separator="\n")
        if text:
            output += text + '\n'
    return output.strip()

def extract_table_text(table):
    rows = table.find_all('tr')
    return '\n'.join(
        ' | '.join(col.get_text(strip=True) for col in row.find_all(['td', 'th']) if col.get_text(strip=True))
        for row in rows if row.find_all(['td', 'th'])
    )

def extract_written_date(soup):
    info_div = soup.select_one("div.bbs_right.bbs_count")
    if info_div:
        for span in info_div.find_all("span"):
            span_text = span.get_text(strip=True)
            if span_text.startswith("작성일"):
                strong = span.find("strong")
                raw_date = strong.get_text(strip=True) if strong else span_text.replace("작성일", "").strip()
                try:
                    dt = datetime.strptime(raw_date[:19], "%Y년 %m월 %d일 %H시 %M분 %S초")
                    date = dt.strftime("%Y.%m.%d")
                except ValueError:
                    date = raw_date

    text = soup.get_text(" ", strip=True)
    match = re.search(r'20\d{2}[.\-/년\s]+[01]?\d[.\-/월\s]+[0-3]?\d[일\s]*', text)
    if match:
        raw = match.group().replace(" ", "").replace("년", ".").replace("월", ".").replace("일", "")
        return raw.strip(".")
    return "(작성일 없음)"

def extract_img_links_from_filebox(soup, base_url):
    img_links = []
    for a in soup.select("div.b-file-box a.file-down-btn"):
        name = a.text.strip()
        href = a.get("href", "")
        if not href:
            continue
        full_link = base_url + "/padm/life/notice-department.do" + href if href.startswith('?') else href
        if name.lower().endswith(('.png', '.jpg', '.jpeg')):
            img_links.append(full_link)
    return img_links

# 이후 crawl_mainpage, crawl_library, crawl_administration, crawl_engineering 함수 내의
# 모든 requests.get() 호출을 session.get()으로 변경 + time.sleep(random.uniform(0.5, 1.2)) 추가
# 예시:
# r = session.get(detail_url, headers=HEADERS)
# time.sleep(random.uniform(0.5, 1.2))

# 마지막 부분의 with open(...) 구문은 그대로 두되, 서버 부하 방지를 위한 로그도 추가하면 좋음


def crawl_mainpage():
    print("\n📂 [메인페이지] 시작")

    BASE_URL = "https://www.kangwon.ac.kr"
    PATH_PREFIX = "/www"
    HEADERS_LOCAL = {"User-Agent": "Mozilla/5.0"}

    categories = [
        {"name": "공지사항", "bbsNo": "81", "key": "277", "last_page": 1459},
        {"name": "행사안내", "bbsNo": "38", "key": "279", "last_page": 242},
        {"name": "공모모집", "bbsNo": "345", "key": "1959", "last_page": 312},
        {"name": "장학게시판", "bbsNo": "34", "key": "232", "last_page": 238},
    ]

    visited_links = set()

    for cat in categories:
        for page in range(1, 101):
            list_url = f"{BASE_URL}{PATH_PREFIX}/selectBbsNttList.do?bbsNo={cat['bbsNo']}&pageUnit=10&key={cat['key']}&pageIndex={page}"
            res = session.get(list_url, headers=HEADERS_LOCAL)
            time.sleep(random.uniform(0.5, 1.2))
            soup = BeautifulSoup(res.text, 'html.parser')
            rows = soup.select("tbody tr")

            for row in rows:
                if row.select_one(".notice"):
                    continue
                a_tag = row.select_one("td.subject a")
                if not a_tag:
                    continue
                title = a_tag.text.strip()
                href = a_tag.get("href", "")

                if "fnSelectBbsNttView" in href:
                    match = re.search(r"fnSelectBbsNttView\('(\d+)',\s*'(\d+)',\s*'(\d+)'\)", href)
                    if not match:
                        continue
                    bbs_no, ntt_no, key_param = match.groups()
                    detail_url = f"{BASE_URL}{PATH_PREFIX}/selectBbsNttView.do?bbsNo={bbs_no}&nttNo={ntt_no}&key={key_param}"
                else:
                    detail_url = urljoin(f"{BASE_URL}{PATH_PREFIX}/", href)

                if detail_url in visited_links:
                    continue
                visited_links.add(detail_url)

                try:
                    r = session.get(detail_url, headers=HEADERS_LOCAL)
                    time.sleep(random.uniform(0.5, 1.2))
                    s = BeautifulSoup(r.text, 'html.parser')

                    content_div = s.select_one("div#bbs_ntt_cn_con") or s.select_one("td.bbs_content") or s.select_one("div.bbs_content")
                    content = content_div.get_text("\n", strip=True) if content_div else "(본문 없음)"
                    date = extract_written_date(s)

                    img_tags = []
                    if content_div:
                        img_tags += content_div.select("img")
                    photo_div = s.select_one("div.photo_area")
                    if photo_div:
                        img_tags += photo_div.select("img")

                    images = [urljoin(detail_url, img.get("src")) for img in img_tags if img.get("src") and img.get("src").lower().endswith((".png", ".jpg", ".jpeg", ".gif"))]
                    img_files = [save_image(link, os.path.join(SAVE_FOLDER, "main"), cat['bbsNo'], i) for i, link in enumerate(images)]
                    img_files = list(filter(None, img_files))

                    all_data.append({
                        "제목": title,
                        "작성일": date,
                        "본문내용": content,
                        "링크": detail_url,
                        "사진": ";".join(img_files)
                        
                    })
                    print(f"📄 [{cat['name']}] {page}p - {title[:25]}")

                except Exception as e:
                    print(f"❌ 상세 페이지 실패: {title[:30]} ({e})")







# ========================================
# 🟦 2. 도서관 크롤러
# ========================================
def crawl_library():
    print("\n📂 [도서관] 시작")
    base_url = "https://library.kangwon.ac.kr"
    list_api = f"{base_url}/pyxis-api/1/bulletin-boards/24/bulletins"
    detail_api = f"{base_url}/pyxis-api/1/bulletins/24/{{id}}"

    per_page = 10
    total_count = None
    seen_ids = set()
    page = 0  # offset 방식 사용 시 page 대신 offset index

    while True:
        params = {"offset": page * per_page, "max": 0}  # 🔁 핵심 변경
        res = session.get(list_api, headers=HEADERS, params=params)
        time.sleep(random.uniform(0.5, 1.2))

        data = res.json().get("data", {})
        list_data = data.get("list", [])

        if total_count is None:
            total_count = data.get("totalCount", 0)
            print(f"  📌 전체 공지 수: {total_count}개")

        if not list_data:
            print("  🔚 도서관 공지 끝")
            break

        for item in list_data:
            id_ = item['id']
            if id_ in seen_ids:
                continue
            seen_ids.add(id_)

            title = item['title']
            detail_url = f"{base_url}/community/bulletin/notice/{id_}"

            detail = session.get(detail_api.format(id=id_), headers=HEADERS).json().get("data", {})
            time.sleep(random.uniform(0.5, 1.2))
            raw_date = detail.get("dateCreated", "작성일 없음")[:10]
            date = raw_date.replace("-", ".")
            html = detail.get("content", "")
            soup = BeautifulSoup(html, "html.parser")
            content = soup.get_text("\n", strip=True)

            images = [urljoin(base_url, img['src']) for img in soup.find_all("img")
                      if img.get("src") and "/pyxis-api/attachments/" in img['src']]
            img_files = [save_image(link, os.path.join(SAVE_FOLDER, "library"), id_, i)
                         for i, link in enumerate(images)]

            all_data.append({
                "제목": title,
                "작성일": date,
                "본문내용": content,
                "링크": detail_url,
                "사진": ";".join(filter(None, img_files))
            })

            print(f"📄 [도서관] offset={page * per_page} - {title[:25]}")

        if (page + 1) * per_page >= total_count:
            break
        page += 1




# ========================================
# 🟦 3. 행정학과 크롤러
# ========================================
def crawl_administration():
    print("\n📂 [행정학과] 시작")
    base_url = "https://padm.kangwon.ac.kr"

    for offset in range(0, 8000, 10):
        url = f"{base_url}/padm/life/notice-department.do?article.offset={offset}"
        try:
            res = requests.get(url, headers=HEADERS)
            time.sleep(random.uniform(0.5, 1.2))  # ✅ 목록 페이지 요청 후 대기
            soup = BeautifulSoup(res.text, 'html.parser')
        except Exception as e:
            print(f"❌ 목록 페이지 요청 실패 (offset={offset}): {e}")
            continue

        for idx, row in enumerate(soup.select("td.b-td-left.b-td-title")):
            a_tag = row.select_one("a")
            if not a_tag:
                continue

            title = a_tag.text.strip()
            if "공지" in title:
                continue  # [공지]가 포함된 제목은 크롤링 제외
            relative = a_tag.get("href", "")
            if '?' in relative:
                detail_link = f"{base_url}/padm/life/notice-department.do{relative[relative.find('?'):]}"
            else:
                detail_link = f"{base_url}/padm/life/notice-department.do"
            print(f"📄 [행정학과] {offset}~ - {title[:25]}")  # ✅ 간소화된 로그

            try:
                r = requests.get(detail_link, headers=HEADERS)
                time.sleep(random.uniform(0.5, 1.2))  # ✅ 상세 페이지 요청 후 대기
                s = BeautifulSoup(r.text, 'html.parser')

                # 본문 내용 추출
                content_div = s.select_one("div.b-content-box div.fr-view") or s.select_one("div.b-content-box")
                content = clean_html_keep_table(str(content_div)) if content_div else "(본문 없음)"

                # 작성일 추출
                date_tag = s.select_one("li.b-date-box span:nth-of-type(2)")
                date = date_tag.text.strip() if date_tag else "(작성일 없음)"

                # 첨부 이미지 링크 추출
                img_links = []
                for a in s.select("div.b-file-box a.file-down-btn"):
                    name = a.text.strip()
                    file_href = a.get("href", "")
                    if not file_href:
                        continue
                    full_link = (
                        base_url + "/padm/life/notice-department.do" + file_href
                        if file_href.startswith('?') else file_href
                    )
                    if name.lower().endswith(('.png', '.jpg', '.jpeg')):
                        img_links.append(full_link)

                # 이미지 다운로드
                img_files = [
                    save_image(link, os.path.join(SAVE_FOLDER, "admin"), offset + idx, i)
                    for i, link in enumerate(img_links)
                ]
                img_files = list(filter(None, img_files))
                img_field = ";".join(img_files).strip()

                # 데이터 저장
                all_data.append({
                    "제목": title,
                    "작성일": date,
                    "본문내용": content,
                    "링크": detail_link,
                    "사진": img_field
                })

            except Exception as e:
                print(f"❌ 상세 페이지 실패: {title[:30]} ({e})")




# ========================================
# 🟦 4. 공학교육혁신센터 크롤러
# ========================================
def crawl_engineering():
    print("\n📂 [공학교육혁신센터] 시작")
    base_url = "https://icee.kangwon.ac.kr"

    for page in range(1, 19):
        url = f"{base_url}/index.php?mt=page&mp=5_1&mm=oxbbs&oxid=1&cpage={page}"
        try:
            res = requests.get(url, headers=HEADERS)
            time.sleep(random.uniform(0.5, 1.2))
            soup = BeautifulSoup(res.text, 'html.parser')
        except Exception as e:
            print(f"❌ 목록 페이지 요청 실패 (page={page}): {e}")
            continue

        for row in soup.select("table.bbs_list tbody tr"):
            a_tag = row.select_one("td.tit a")
            if not a_tag:
                continue

            title = a_tag.text.strip()
            href = urljoin(base_url, a_tag['href'])
            raw_date = row.select_one("td.dt").text.strip().replace("-", ".")

            try:
                r = requests.get(href, headers=HEADERS)
                time.sleep(random.uniform(0.5, 1.2))
                s = BeautifulSoup(r.text, 'html.parser')
                content_div = s.select_one("div.view_cont") or s.select_one("div.note")
                content = content_div.get_text("\n", strip=True) if content_div else "(본문 없음)"

                imgs = content_div.find_all("img") if content_div else []
                img_files = []
                for i, img in enumerate(imgs):
                    src = img.get("src")
                    if src and not src.startswith("data:image"):
                        img_files.append(save_image(
                            urljoin(href, src),
                            os.path.join(SAVE_FOLDER, "engineering"),
                            page, i
                        ))

                all_data.append({
                    "제목": title,
                    "작성일": raw_date,
                    "본문내용": content,
                    "링크": href,
                    "사진": ";".join(filter(None, img_files))
                })

                print(f"📄 [공학교육혁신센터] {page}p - {title[:25]}")

            except Exception as e:
                print(f"❌ 상세 페이지 실패: {title[:30]} ({e})")



# ========================================
# 🟦 실행
# ========================================
if __name__ == "__main__":
    crawl_mainpage()
    

    # CSV 저장
    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["제목", "작성일", "본문내용", "링크", "사진"])
        writer.writeheader()
        writer.writerows(all_data)
    print(f"\n✅ 통합 CSV 저장 완료: {CSV_FILE}")
