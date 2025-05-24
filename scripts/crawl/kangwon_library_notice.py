from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import time
import csv
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import os
import csv
import time
import requests
from hashlib import md5
from urllib.parse import urlparse

# ChromeDriver 경로 설정
CHROMEDRIVER_PATH = "C:/Users/YOOJIIN/Downloads/chromedriver-win64/chromedriver-win64/chromedriver.exe" 

# Chrome 실행 옵션
options = Options()
# options.add_argument("--headless")  # 브라우저 안 띄우고 실행 (원하면 주석처리해도 됨)
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")

# Selenium WebDriver 실행
service = Service(CHROMEDRIVER_PATH)
driver = webdriver.Chrome(service=service, options=options)

# 크롤링할 URL
base_url = "https://library.kangwon.ac.kr"

image_dir = os.path.join("data", "images")
os.makedirs(image_dir, exist_ok=True)

# CSV 저장용
results = []

# 전체 공지 개수 기반 offset 리스트 생성
driver.get(f"{base_url}/community/bulletin/notice?max=100&offset=0&bulletinCategoryId=1")
time.sleep(3)
soup = BeautifulSoup(driver.page_source, "html.parser")
total_text = soup.select_one("span.ikc-active")
total_count = int(total_text.get_text(strip=True)) if total_text else 0
offset_list = list(range(0, total_count, 100))
print(f"총 {total_count}개의 공지사항 발견, {len(offset_list)}페이지 순회 예정")

# 🔁 페이지네이션 (0, 20, 40, ... 최대 100까지 시도)
for offset in offset_list:
    list_url = f"{base_url}/community/bulletin/notice?max=100&offset={offset}&bulletinCategoryId=1"
    print(f"\n📄 [페이지 offset={offset}] 크롤링 중...")
    driver.get(list_url)
    time.sleep(3)

    items = driver.find_elements(By.CSS_SELECTOR, "a.ikc-bulletins-title")
    total = len(items)
    print(f"{total}개 공지 발견")

    for i in range(total):
        items = driver.find_elements(By.CSS_SELECTOR, "a.ikc-bulletins-title")

        if i >= len(items):
            print(f"항목 누락 감지 (i={i}, items 수={len(items)}), 건너뜀")
            continue

        item = items[i]
        title = item.text.strip()
        print(f"\n! {i+1}. {title}")

        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", item)
            time.sleep(1)
            
            item.click()

            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "ikc-bulletin-content"))
            )

            detail_soup = BeautifulSoup(driver.page_source, "html.parser")
            content_div = detail_soup.select_one("div.ikc-bulletin-content")

            if content_div:
                paragraphs = content_div.find_all("p")
                body = "\n".join(p.get_text(strip=True) for p in paragraphs)
            else:
                body = "본문 없음"

            # 작성일 추출
            date = "작성일 정보 없음"
            for li in detail_soup.select("li"):
                label = li.select_one("label")
                if label and "작성일" in label.text:
                    span = li.select_one("span")
                    if span:
                        date = span.text.strip()
                        break

            # 이미지 URL 추출
            img_urls = []
            for img in content_div.find_all("img"):
                src = img.get("src")
                if src:
                    src = src.strip().strip('"')  # 앞뒤 공백과 따옴표 제거
                    if src.startswith("http"):   # 절대경로
                        img_url = src
                    elif src.startswith("//"):
                        img_url = "https:" + src
                    else:                        # 상대경로
                        img_url = base_url + src
                    img_urls.append(img_url)

            # 이미지 다운로드
            saved_filenames = []
            for url in img_urls:
                try:
                    ext = os.path.splitext(urlparse(url).path)[1]
                    if not ext or len(ext) > 5:
                        ext = ".jpg"  # 기본 확장자 설정
                    
                    filename = md5(url.encode()).hexdigest() + ext
                    filepath = os.path.join(image_dir, filename)

                    r = requests.get(url, timeout=10)
                    with open(filepath, "wb") as f:
                        f.write(r.content)
                    # CSV에는 상대경로로 저장
                    saved_filenames.append(os.path.join(image_dir, filename).replace("\\", "/"))
                except Exception as e:
                    print(f"이미지 저장 실패: {url} → {e}")

            
            # 링크는 현재 페이지 URL
            detail_url = driver.current_url

            # 결과 저장
            results.append([title, date, body, detail_url, ";".join(saved_filenames)])

            driver.back()
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a.ikc-bulletins-title"))
            )
            itmes = driver.find_element(By.CSS_SELECTOR, "a.ikc-bulletins-title")

        except Exception as e:
            print(f"본문 로딩 실패: {e}")
            results.append([title, "본문 로딩 실패"])

driver.quit()

# CSV로 저장
csv_path = os.path.join("data", "kangwon_library_notice.csv")
with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f)
    writer.writerow(["제목", "작성일", "본문", "상세 링크", "이미지 파일 경로로"])
    writer.writerows(results)

print(f"\n✅ 모든 크롤링 완료! 📁 '{csv_path}' 파일로 저장됨.")
