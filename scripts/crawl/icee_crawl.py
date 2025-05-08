import requests
from bs4 import BeautifulSoup
import os
import csv
import time
import base64
from urllib.parse import urljoin
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import mysql.connector
import re
from datetime import datetime

BASE_URL = 'https://icee.kangwon.ac.kr'
LIST_URL_TEMPLATE = BASE_URL + '/index.php?mt=page&mp=5_1&mm=oxbbs&oxid=1&cpage={}'
SAVE_FOLDER = '../../data/images'
CSV_FOLDER = '../../data'
CSV_FILE = os.path.join(CSV_FOLDER, 'icee_crawl.csv')
HEADERS = {"User-Agent": "Mozilla/5.0"}

session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retries)
session.mount('http://', adapter)
session.mount('https://', adapter)

os.makedirs(SAVE_FOLDER, exist_ok=True)
os.makedirs(CSV_FOLDER, exist_ok=True)

# db
db = mysql.connector.connect(
    host='localhost',
    user='root',        # 🔁 사용자 설정
    password='1234',    # 🔁 비밀번호 설정
    database='icee_crawl'
)
cursor = db.cursor()

def parse_date(date_str):
    if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
        return date_str
    return None

with open(CSV_FILE, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.writer(f)
    writer.writerow(['게시판종류', '제목', '작성일', '본문내용', '링크', '사진'])

    page = 1
    while True:
        print(f'\n📄 페이지 {page} 처리 중...')
        res = requests.get(LIST_URL_TEMPLATE.format(page), headers=HEADERS)
        if res.status_code != 200:
            print(f'❌ 페이지 {page} 요청 실패: {res.status_code}')
            break

        soup = BeautifulSoup(res.text, 'html.parser')
        rows = soup.select('table.bbs_list tbody tr')
        if not rows:
            print("❌ 더 이상 게시글 없음. 종료.")
            break

        for row in rows:
            try:
                a_tag = row.select_one('td.tit a')
                if not a_tag:
                    continue

                post_url = urljoin(BASE_URL, a_tag['href'])
                title = a_tag.text.strip()
                date_raw = row.select_one('td.dt').text.strip()
                post_date = parse_date(date_raw)

                post_res = requests.get(post_url, headers=HEADERS)
                if post_res.status_code != 200:
                    continue

                post_soup = BeautifulSoup(post_res.text, 'html.parser')
                content_tag = post_soup.select_one('div.view_cont') or post_soup.select_one('div.note')
                content = content_tag.get_text(separator='\n', strip=True) if content_tag else '본문 없음'

                # 이미지 저장
                img_filenames = []
                if content_tag:
                    for idx, img in enumerate(content_tag.find_all('img')):
                        img_src = img.get('src')
                        if not img_src:
                            continue

                        if img_src.startswith('data:image'):
                            try:
                                header, b64data = img_src.split(',', 1)
                                ext = header.split('/')[1].split(';')[0]
                                img_name = f"base64_{page}_{idx}.{ext}"
                                save_path = os.path.join(SAVE_FOLDER, img_name)
                                with open(save_path, 'wb') as f_img:
                                    f_img.write(base64.b64decode(b64data))
                                img_filenames.append(os.path.join(SAVE_FOLDER, img_name).replace('\\', '/'))
                                time.sleep(0.2)
                            except Exception as e:
                                print(f'⚠️ Base64 이미지 저장 실패: {e}')
                                continue
                        else:
                            try:
                                img_url = urljoin(post_url, img_src)
                                img_name = os.path.basename(img_url)
                                save_path = os.path.join(SAVE_FOLDER, img_name)
                                img_res = session.get(img_url, headers=HEADERS, stream=True, timeout=10)
                                img_res.raise_for_status()
                                with open(save_path, 'wb') as f_img:
                                    for chunk in img_res.iter_content(1024):
                                        f_img.write(chunk)
                                img_filenames.append(os.path.join(SAVE_FOLDER, img_name).replace('\\', '/'))
                                time.sleep(0.2)
                            except Exception as e:
                                print(f'⚠️ 이미지 저장 실패: {img_src} ({e})')
                                continue

                # CSV 저장
                writer.writerow(['공지사항', title, f"'{date_raw}", content, post_url, ';'.join(img_filenames)])

                # DB 저장
                try:
                    sql = "INSERT INTO posts (board_type, title, post_date, content, link, image_files) VALUES (%s, %s, %s, %s, %s, %s)"
                    cursor.execute(sql, (
                        '공지사항',
                        title,
                        post_date,  
                        content,
                        post_url,
                        ';'.join(img_filenames)
                    ))
                    db.commit()
                except Exception as db_error:
                    print(f"❌ DB 저장 실패: {db_error}")

                print(f'✅ 저장됨: {title[:50]}...')
                time.sleep(1)

            except Exception as e:
                print(f'❌ 게시글 처리 실패: {e}')
                continue

        # 다음 페이지가 없으면 종료
        if not soup.select_one(f'a[href*="cpage={page+1}"]'):
            print("✅ 마지막 페이지 도달")
            break

        page += 1

cursor.close()
db.close()
print('\n🎉 전체 크롤링 및 저장 완료!')


# import requests
# from bs4 import BeautifulSoup
# import os
# import csv
# import time
# import base64
# from urllib.parse import urljoin
# from requests.adapters import HTTPAdapter
# from urllib3.util.retry import Retry

# # 설정
# BASE_URL = 'https://icee.kangwon.ac.kr'
# LIST_URL_TEMPLATE = BASE_URL + '/index.php?mt=page&mp=5_1&mm=oxbbs&oxid=1&cpage={}'
# SAVE_FOLDER = 'images'
# CSV_FOLDER = '../scripts/crawl'
# CSV_FILE = os.path.join(CSV_FOLDER,'icee_crawl.csv')
# HEADERS = {"User-Agent": "Mozilla/5.0"}

# # 이미지 재시도 설정
# session = requests.Session()
# retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
# adapter = HTTPAdapter(max_retries=retries)
# session.mount('http://', adapter)
# session.mount('https://', adapter)

# # 폴더 생성
# if not os.path.exists(SAVE_FOLDER):
#     os.makedirs(SAVE_FOLDER)

# # CSV 저장
# with open(CSV_FILE, 'w', newline='', encoding='utf-8-sig') as f:
#     writer = csv.writer(f)
#     writer.writerow(['게시판종류', '제목', '작성일', '본문내용', '링크', '사진'])

#     page = 1
#     while True:
#         print(f'\n📄 페이지 {page} 처리 중...')
#         res = requests.get(LIST_URL_TEMPLATE.format(page), headers=HEADERS)
#         if res.status_code != 200:
#             print(f'❌ 페이지 {page} 요청 실패: {res.status_code}')
#             break

#         soup = BeautifulSoup(res.text, 'html.parser')
#         rows = soup.select('table.bbs_list tbody tr')
#         if not rows:
#             print("❌ 더 이상 게시글 없음. 종료.")
#             break

#         for row in rows:
#             try:
#                 a_tag = row.select_one('td.tit a')
#                 if not a_tag:
#                     continue

#                 post_url = urljoin(BASE_URL, a_tag['href'])
#                 title = a_tag.text.strip()
#                 date = row.select_one('td.dt').text.strip()

#                 post_res = requests.get(post_url, headers=HEADERS)
#                 if post_res.status_code != 200:
#                     continue

#                 post_soup = BeautifulSoup(post_res.text, 'html.parser')
#                 content_tag = post_soup.select_one('div.view_cont') or post_soup.select_one('div.note')
#                 content = content_tag.get_text(separator='\n', strip=True) if content_tag else '본문 없음'

#                 # 이미지 다운로드 (URL 또는 base64 둘 다 처리)
#                 img_filenames = []
#                 if content_tag:
#                     for idx, img in enumerate(content_tag.find_all('img')):
#                         img_src = img.get('src')
#                         if not img_src:
#                             continue

#                         if img_src.startswith('data:image'):
#                             try:
#                                 header, b64data = img_src.split(',', 1)
#                                 ext = header.split('/')[1].split(';')[0]
#                                 img_name = f"base64_{page}_{idx}.{ext}"
#                                 save_path = os.path.join(SAVE_FOLDER, img_name)

#                                 with open(save_path, 'wb') as f_img:
#                                     f_img.write(base64.b64decode(b64data))
#                                 img_filenames.append(img_name)
#                                 time.sleep(0.2)
#                             except Exception as e:
#                                 print(f'⚠️ Base64 이미지 저장 실패: {e}')
#                                 continue
#                         else:
#                             try:
#                                 img_url = urljoin(post_url, img_src)
#                                 img_name = os.path.basename(img_url)
#                                 save_path = os.path.join(SAVE_FOLDER, img_name)

#                                 img_res = session.get(img_url, headers=HEADERS, stream=True, timeout=10)
#                                 img_res.raise_for_status()

#                                 with open(save_path, 'wb') as f_img:
#                                     for chunk in img_res.iter_content(1024):
#                                         f_img.write(chunk)
#                                 img_filenames.append(img_name)
#                                 time.sleep(0.2)
#                             except Exception as e:
#                                 print(f'⚠️ 이미지 저장 실패: {img_src} ({e})')
#                                 continue

#                 writer.writerow([
#                     '공지사항',
#                     title,
#                     f"'{date}",
#                     content,
#                     post_url,
#                     ';'.join(img_filenames)
#                 ])
#                 print(f'✅ 저장됨: {title[:50]}...')
#                 time.sleep(1)

#             except Exception as e:
#                 print(f'❌ 게시글 처리 실패: {e}')
#                 continue

#         if not soup.select_one(f'a[href*="cpage={page+1}"]'):
#             print("✅ 마지막 페이지 도달")
#             break

#         page += 1

# print('\n 전체 크롤링 완료!')
