import os
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import time
import requests
from urllib.parse import urljoin
import re
from tqdm import tqdm # 진행률 표시 라이브러리 다시 활성화
import datetime # 날짜 사용 (현재는 최적화에 직접 사용 안함)

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException, WebDriverException

# --- 설정 ---
CHROMEDRIVER_PATH = r"D:\chromedriver-win64\chromedriver.exe"
CSV_FILENAME = "kangwon_wwwk_notices_cumulative_final.csv" # 최종 누적 데이터 CSV 파일명
IMAGE_FOLDER = "images_content" # 이미지 저장 폴더
PROCESSED_URLS_FILE = "processed_urls.txt" # 처리된 URL 기록 파일

TARGETS = [
    {'site': 'wwwk', 'name': '공지사항', 'bbsNo': '81', 'key': '277', 'searchCtgry': '%EC%A0%84%EC%B2%B4%40%40%EC%B6%98%EC%B2%9C'},
    {'site': 'wwwk', 'name': '행사안내', 'bbsNo': '38', 'key': '279', 'searchCtgry': '%EC%A0%84%EC%B2%B4%40%40%EC%B6%98%EC%B2%9C'},
    {'site': 'wwwk', 'name': '공모모집', 'bbsNo': '345', 'key': '1959', 'searchCtgry': ''},
    {'site': 'wwwk', 'name': '장학게시판', 'bbsNo': '34', 'key': '232', 'searchCtgry': ''},
]

# --- 이미지 저장 폴더 확인 및 절대 경로 ---
IMAGE_FOLDER_ABSPATH = ""
# ... (폴더 생성 및 권한 확인 로직은 이전과 동일) ...
if not os.path.exists(IMAGE_FOLDER):
    try: os.makedirs(IMAGE_FOLDER)
    except OSError as e: print(f"❌ Error creating directory '{IMAGE_FOLDER}': {e}"); exit()
try:
    IMAGE_FOLDER_ABSPATH = os.path.abspath(IMAGE_FOLDER)
    print(f"ℹ️ Images will be saved to: {IMAGE_FOLDER_ABSPATH}")
    test_file_path = os.path.join(IMAGE_FOLDER_ABSPATH, "write_test.tmp")
    with open(test_file_path, "w") as f_test: f_test.write("test"); os.remove(test_file_path)
    # print(f"  ✅ Write permission seems OK.")
except Exception as e_perm: print(f"  ❌ WARNING: Write permission check failed: {e_perm}")


# --- 웹드라이버 설정 ---
options = Options()
# ... (옵션 설정은 이전과 동일) ...
options.add_argument("--disable-gpu"); options.add_argument("--no-sandbox"); options.add_argument("--start-maximized")
# options.add_argument("--headless") # 전체 크롤링 시 비추천
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
service = Service(CHROMEDRIVER_PATH)

# === 처리된 URL 불러오기 ===
processed_urls = set()
# ... (URL 불러오기 로직은 이전과 동일) ...
try:
    if os.path.exists(PROCESSED_URLS_FILE):
        with open(PROCESSED_URLS_FILE, 'r', encoding='utf-8') as f_urls:
            processed_urls = set(line.strip() for line in f_urls if line.strip())
        print(f"✅ Loaded {len(processed_urls)} previously processed URLs from '{PROCESSED_URLS_FILE}'.")
    else: print(f"ℹ️ '{PROCESSED_URLS_FILE}' not found. Starting fresh.")
except Exception as e_load: print(f"❌ Error loading processed URLs: {e_load}")

# --- 전체 진행 상황 카운터 ---
total_processed_overall = 0 # 이번 실행 새로 처리된 수
total_attempted = 0       # 이번 실행 처리 시도 수
total_skipped_duplicates = 0 # 이번 실행 중복 건너뛴 수

# --- 게시판 크롤링 함수 ---
def scrape_wwwk_category(driver, category_info):
    # global total_processed_overall, total_attempted, total_skipped_duplicates
    category_results = []
    category_name = category_info['name']; bbsNo = category_info['bbsNo']; key = category_info['key']
    category_searchCtgry = category_info.get('searchCtgry', ''); wwwk_base_url = "https://wwwk.kangwon.ac.kr"
    page_index = 1; processed_count_in_category_this_run = 0; skipped_duplicates_this_run = 0; skipped_notices_after_p1 = 0
    newly_added_in_category = 0

    while True: # 페이지 순회
        # === 페이지 제한 로직 제거 ===
        # if page_index > 3: break

        print(f"\n{'='*15} {category_name} - 페이지 {page_index} 크롤링 시도 {'='*15}")
        search_param = f"&searchCtgry={category_searchCtgry}" if category_searchCtgry else ""
        list_url = f"{wwwk_base_url}/www/selectBbsNttList.do?bbsNo={bbsNo}&pageUnit=10{search_param}&key={key}&pageIndex={page_index}"

        try: # 목록 페이지 로딩
            driver.get(list_url)
            WebDriverWait(driver, 30).until( EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr")))
        except TimeoutException: print(f"❌ 페이지 {page_index} 로딩 시간 초과: {list_url}"); break

        notices_on_page = [] # 현재 페이지에서 상세 처리할 후보
        rows = []
        new_url_found_on_this_page = False # 최적화용 플래그

        try: # 목록 처리
            rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr") # 모든 행 가져오기
            if not rows: print(f"  ✅ 페이지 {page_index}에 게시글 행이 없습니다. '{category_name}' 크롤링 종료."); break

            # print(f"  - 페이지 {page_index} 에서 {len(rows)}개 행 발견...")

            for row_idx, row in enumerate(rows):
                try:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) < 3: continue

                    first_cell_content = "N/A"; is_notice = False
                    try:
                        first_cell_content = cells[0].text.strip()
                        is_notice = not first_cell_content.isdigit()
                    except IndexError: continue

                    # 공지 건너뛰기 (첫 페이지 제외)
                    if is_notice and page_index != 1:
                        skipped_notices_after_p1 += 1; continue

                    # 정보 추출 (일반글 또는 첫 페이지 공지)
                    title = "제목 없음"; detail_url = None; href = None; date_from_list = "날짜 찾기 실패"
                    try:
                        title_element = cells[2].find_element(By.CSS_SELECTOR, "a")
                        title = title_element.text.strip(); href = title_element.get_attribute('href')
                    except Exception: continue
                    for cell in cells: # 날짜 찾기
                        cell_text = cell.text.strip()
                        if re.match(r'^\d{4}[.-]\d{2}[.-]\d{2}$', cell_text): date_from_list = cell_text.replace('-', '.'); break
                    # URL 처리
                    if href and title:
                        if href.startswith('javascript:fnSelectBbsNttView'):
                            try: ntt_no = href.split("'")[1]
                            except IndexError: detail_url = None
                            else: detail_url = f"{wwwk_base_url}/www/selectBbsNttView.do?bbsNo={bbsNo}&nttNo={ntt_no}&key={key}"
                        elif href.startswith('/'): detail_url = urljoin(wwwk_base_url, href)
                        elif href.startswith('http'): detail_url = href
                        else: detail_url = None
                    if detail_url:
                        notices_on_page.append({'title': title, 'url': detail_url, 'date': date_from_list})
                except Exception as e_row: print(f"    ❌ 행 처리 중 예외 발생 (Row {row_idx+1}): {e_row}")

        except Exception as e: print(f"  ❌ 목록 처리 중 오류 (페이지 {page_index}): {e}"); break

        if not notices_on_page: # 처리할 후보가 없으면
             if rows: print(f"  ⚠️ 페이지 {page_index}에서 처리할 게시글 후보를 찾지 못했습니다.")
             else: print(f"  ✅ 페이지 {page_index} 에서 처리할 유효한 게시글이 없습니다. '{category_name}' 크롤링 종료."); break
             # === 최적화: 현재 페이지에 후보가 없었고, 1페이지가 아니면 종료 ===
             if page_index > 1:
                  print(f"  ---> No processable items found on page {page_index}. Stopping crawl for '{category_name}'.")
                  break
             page_index += 1; time.sleep(1); continue # 첫 페이지는 비어도 다음 페이지 시도

        # === 상세 페이지 처리 (URL 중복 제거 포함) ===
        print(f"  - 페이지 {page_index}: {len(notices_on_page)}개 게시글 후보 상세 처리 시작...")
        processed_on_this_page = 0
        for notice_info in tqdm(notices_on_page, desc=f"  Processing Page {page_index} Items", leave=False, ncols=100): # tqdm 다시 사용
            global total_processed_overall, total_attempted, total_skipped_duplicates
            total_attempted += 1
            detail_url = notice_info['url']; title = notice_info['title']

            if detail_url in processed_urls:
                skipped_duplicates_this_run += 1; total_skipped_duplicates += 1; continue

            processed_urls.add(detail_url)
            processed_count_in_category_this_run += 1
            total_processed_overall += 1
            new_url_found_on_this_page = True # ★★★ 새 URL 찾음 플래그 설정 ★★★
            date = notice_info['date']

            body = "본문 내용 없음"; local_image_filenames = []
            try:
                driver.get(detail_url)
                WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                # 본문/이미지 처리 (이전과 동일)
                try: # Body
                    soup = BeautifulSoup(driver.page_source, 'html.parser'); content_div_bs = soup.select_one("div#bbs_ntt_cn_con"); body_parts = [];
                    if content_div_bs: body = content_div_bs.get_text(separator='\n', strip=True);
                    if not body: body = "본문 내용 없음"
                except Exception: body = "본문 추출 오류"
                try: # Image
                    images_selenium = driver.find_elements(By.TAG_NAME, "img")
                    for idx, img_selenium in enumerate(images_selenium):
                        img_url_raw = None; img_url = None; final_filename = None
                        try:
                            img_url_raw = img_selenium.get_attribute('src')
                            if not img_url_raw or img_url_raw.startswith('data:image') or '/DATA/bbs/' not in img_url_raw: continue
                            img_url = urljoin(detail_url, img_url_raw);
                            if not img_url.startswith('http'): continue
                            img_data = None
                            try: # Download
                                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                                img_response = requests.get(img_url, timeout=20, headers=headers); img_response.raise_for_status(); img_data = img_response.content
                            except Exception: continue
                            try: # Save
                                img_filename_base = os.path.basename(img_url.split('?')[0]); valid_chars = "-_.() abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"; img_filename_base = ''.join(c for c in img_filename_base if c in valid_chars).strip()
                                if not img_filename_base or len(img_filename_base) > 100: img_filename_base = f"image_{total_processed_overall}_{idx}"
                                _, ext = os.path.splitext(img_url.split('?')[0]);
                                if not ext: ext = '.jpg'
                                final_filename = f"{os.path.splitext(img_filename_base)[0]}_{int(time.time() * 1000)}{ext}"; img_save_path = os.path.join(IMAGE_FOLDER_ABSPATH, final_filename)
                                with open(img_save_path, 'wb') as f: f.write(img_data)
                                if final_filename not in local_image_filenames: local_image_filenames.append(final_filename)
                            except Exception as e_save: print(f"       ❌ File save FAILED for '{final_filename}' (from {img_url}): {e_save}")
                        except Exception: pass
                except Exception: pass

                category_results.append([title, body, date, detail_url, ", ".join(local_image_filenames)])
                processed_on_this_page += 1

            except Exception as e_detail:
                 print(f"     ❌ Error processing detail page for {title[:20]}...: {e_detail}")
            finally: time.sleep(0.3)

            if total_processed_overall % 50 == 0 and total_processed_overall > 0: current_time = time.strftime("%H:%M:%S"); print(f"\n✨ [{current_time}] --- 총 {total_processed_overall}개 신규 게시글 처리 완료 (누적) --- ✨\n")

        print(f"  📊 페이지 {page_index} 완료. 신규 처리: {processed_on_this_page}개. (P2+ 공지 {skipped_notices_after_p1}개, URL중복 {skipped_duplicates_this_run}개 건너<0xEB><0x8B>)")

        # === 최적화: 현재 페이지에서 새 URL이 없었고, 1페이지가 아니면 종료 ===
        if not new_url_found_on_this_page and page_index > 1:
             print(f"  ---> No new posts found on page {page_index}. Stopping crawl for '{category_name}'.")
             break

        page_index += 1; time.sleep(1) # 다음 페이지로

    print(f"\n### {category_name} 크롤링 완료 (페이지 {page_index-1}까지 확인) ###")
    return category_results, skipped_duplicates_this_run


# --- 메인 실행 로직 ---
newly_added_results = [] # 이번 실행에서 새로 추가된 결과만 저장
total_skipped_this_run = 0
driver = None; start_time = time.time()
try:
    try: from tqdm import tqdm
    except ImportError: print("Tip: 'pip install tqdm' to see progress bars."); tqdm = lambda x, **kwargs: x
    driver = webdriver.Chrome(service=service, options=options)
    print("✅ WebDriver 시작됨.")
    for target_info in TARGETS:
        category_name = target_info['name']; print(f"\n{'='*20} 카테고리 시작: {category_name} {'='*20}")
        site_type = target_info.get('site'); category_results = []; skipped_count = 0
        if site_type == 'wwwk':
            category_results, skipped_count = scrape_wwwk_category(driver, target_info) # 반환값 2개 받음
        else: print(f"❗ 알 수 없는 사이트 타입: {site_type}")
        if category_results:
            newly_added_results.extend(category_results) # 새로 찾은 결과만 누적
            print(f"\n✅ '{category_name}' 카테고리에서 {len(category_results)}개의 **새로운** 게시글 발견. (중복 URL 건너<0xEB><0x8B> {skipped_count}개)")
        else: print(f"⚠️ '{category_name}' 카테고리에서 새로운 게시글을 찾지 못했습니다. (중복 URL 건너<0xEB><0x8B> {skipped_count}개)")
        total_skipped_this_run += skipped_count
        print(f"\n... 다음 카테고리 전 잠시 대기 ({category_name} 완료, 1초) ...\n"); time.sleep(1) # 대기 시간 줄임
except Exception as e_main:
    print(f"\n🚨 메인 크롤링 프로세스 중 예상치 못한 오류 발생: {e_main}")
    import traceback; traceback.print_exc()
finally:
    # === 업데이트된 URL 목록 파일에 저장 ===
    try:
        print(f"\n💾 Saving {len(processed_urls)} processed URLs to '{PROCESSED_URLS_FILE}'...")
        with open(PROCESSED_URLS_FILE, 'w', encoding='utf-8') as f_urls_out:
            for url in sorted(list(processed_urls)): f_urls_out.write(url + '\n')
        print(f"✅ Successfully saved processed URLs.")
    except Exception as e_save_urls: print(f"❌ Error saving processed URLs: {e_save_urls}")
    if driver:
        try: driver.quit()
        except Exception as e_quit: print(f"❌ WebDriver 종료 중 오류 발생: {e_quit}")
        else: print("\n✅ WebDriver 종료됨.")

# --- 결과를 CSV로 저장 ---
end_time = time.time(); elapsed_time = end_time - start_time
print(f"\n{'='*20} 크롤링 결과 요약 (전체 페이지) {'='*20}") # 로그 수정
print(f"⏱️ 총 실행 시간: {elapsed_time:.2f} 초 ({elapsed_time/60:.2f} 분)"); print(f"🔄 처리 시도한 총 게시글 수: {total_attempted}");
print(f"⏭️ 건너<0xEB><0x9D<0x80 중복 URL 수: {total_skipped_this_run}"); print(f"✨ 이번 실행 새로 추가된 게시글 수: {len(newly_added_results)}")
print(f"💾 최종 누적된 고유 URL 수: {len(processed_urls)}")

if newly_added_results:
    try:
        df = pd.DataFrame(newly_added_results, columns=["제목", "본문", "작성일", "링크", "사진_파일명"])
        df_ordered = df[["제목", "작성일", "본문", "링크", "사진_파일명"]]; df_ordered.columns = ["제목", "작성일", "본문내용", "링크", "사진"]
        # === CSV 저장 방식: 추가 (Append) ===
        is_new_file = not os.path.exists(CSV_FILENAME) # 파일 존재 여부 확인
        df_ordered.to_csv(CSV_FILENAME, mode='a', index=False, header=is_new_file, encoding='utf-8-sig')
        print(f"\n✅ 이번 실행에서 찾은 {len(newly_added_results)}개의 새로운 게시글을 '{CSV_FILENAME}'에 **추가했습니다**.")
        if is_new_file: print(f"   (새로운 CSV 파일을 생성했습니다.)")
        else: print(f"   (기존 CSV 파일에 이어서 추가했습니다.)")

        try:
            image_files_count = len([name for name in os.listdir(IMAGE_FOLDER) if os.path.isfile(os.path.join(IMAGE_FOLDER, name))])
            print(f"🖼️ '{IMAGE_FOLDER}' 폴더에 약 {image_files_count}개의 이미지가 저장되었습니다.")
        except FileNotFoundError: print(f"🖼️ 이미지 폴더 '{IMAGE_FOLDER}'를 찾을 수 없습니다.")
    except ImportError: print(f"\n❌ CSV 저장을 위해 'pandas' 라이브러리가 필요합니다.")
    except Exception as e_csv: print(f"\n❌ CSV 파일 저장 중 오류 발생: {e_csv}")
else: print(f"\n✅ 이번 실행에서 새로 추가된 게시글이 없습니다.")