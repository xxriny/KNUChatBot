from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import time
import re
import csv

# ===== 크롬 드라이버 설정 =====
options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')

driver = webdriver.Chrome(options=options)

# ===== URL 설정 =====
base_url = "https://padm.kangwon.ac.kr"
list_url = f"{base_url}/padm/life/notice-department.do"

# ===== HTML 태그 제거 및 표 처리 =====
def clean_html_keep_table(raw_html):
    soup = BeautifulSoup(raw_html, 'html.parser')
    output_text = ''
    tables = soup.find_all('table')
    for table in tables:
        table_text = extract_table_text(table)
        if table_text.strip():
            output_text += table_text + '\n'
        table.decompose()
    for elem in soup.find_all(['p', 'div']):
        text = elem.get_text(strip=True)
        if text:
            output_text += text + '\n'
    return output_text.strip()

def extract_table_text(table):
    rows = table.find_all('tr')
    table_text = ''
    for row in rows:
        cols = row.find_all(['td', 'th'])
        valid_cols = [col.get_text(strip=True) for col in cols if col.get_text(strip=True)]
        if valid_cols:
            row_text = ' | '.join(valid_cols)
            table_text += row_text + '\n'
    return table_text

# ===== 공지 리스트 크롤링 =====
def crawl_notice_list(offset=0):
    driver.get(f"{list_url}?article.offset={offset}")
    time.sleep(2)

    notices = []
    rows = driver.find_elements(By.CSS_SELECTOR, 'td.b-td-left.b-td-title')

    for row in rows:
        try:
            title_box = row.find_element(By.CSS_SELECTOR, 'div.b-title-box')

            if 'b-notice' in title_box.get_attribute('class'):
                continue

            link_tag = title_box.find_element(By.CSS_SELECTOR, 'a')
            title = link_tag.text.strip()
            href = link_tag.get_attribute('href')
            detail_url = base_url + "/padm/life/notice-department.do" + href[href.find('?'):]

            notices.append({'title': title, 'url': detail_url})
        except Exception as e:
            print("[!] 리스트 항목 파싱 실패:", e)
            continue

    return notices

# ===== 공지 본문 크롤링 =====
def crawl_notice_detail(url):
    driver.get(url)

    try:
        date_element = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'div.b-etc-box li.b-date-box span:nth-child(2)'))
        )
        date_text = date_element.text.strip()
    except:
        date_text = "(작성일 없음)"

    selector_candidates = [
        'div.b-content-box div.fr-view',
        'div.b-content-box'
    ]

    content_text = ""
    for selector in selector_candidates:
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            element = driver.find_element(By.CSS_SELECTOR, selector)
            content_html = element.get_attribute('innerHTML')
            content_text = clean_html_keep_table(content_html)
            if content_text.strip():
                break
        except:
            continue

    if not content_text.strip():
        content_text = "(본문 없음)"

    img_links = []
    try:
        file_elements = driver.find_elements(By.CSS_SELECTOR, 'div.b-file-box a.file-down-btn')
        for file in file_elements:
            file_href = file.get_attribute('href')
            file_name = file.text.strip()
            if file_href and file_name:
                full_link = base_url + file_href if file_href.startswith('?') else file_href
                if any(file_name.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg']):
                    img_links.append(full_link)
    except:
        pass

    return date_text, content_text, img_links

# ===== 메인 실행 =====
if __name__ == "__main__":
    all_notices = []
    total_articles = 7218 
    articles_per_page = 10

    for offset in range(0, total_articles, articles_per_page):
        print(f"\n📄 현재 페이지 offset: {offset} (공지 {offset+1} ~ {offset+10})")
        notices = crawl_notice_list(offset=offset)

        for idx, notice in enumerate(notices, start=1):
            title = notice['title']
            url = notice['url']
            date, content, img_links = crawl_notice_detail(url)

            all_notices.append({
                '제목': title,
                '작성일': date,
                '본문': content,
                'url': url  ,
                '이미지파일 링크': ', '.join(img_links)
            })

            print(f"✅ 크롤링 완료: {title} ({offset+idx}/{total_articles})")
            time.sleep(2)  # ✅ 서버 부하 방지

    driver.quit()

    # ✅ CSV 파일로 저장
    keys = ['제목', '작성일', '본문', 'url', '이미지파일 링크']
    with open('kangwon_notices_total.csv', 'w', newline='', encoding='utf-8-sig') as f:
        dict_writer = csv.DictWriter(f, fieldnames=keys)
        dict_writer.writeheader()
        dict_writer.writerows(all_notices)

    print(f"\n✅ 전체 크롤링 완료! 총 {len(all_notices)}개 저장 완료.")