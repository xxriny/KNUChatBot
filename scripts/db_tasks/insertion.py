import numpy as np
from utils.db_utils import insert_and_return_id, insert_data
from utils.parsing_utils import parse_image_paths, parse_department
import pandas as pd

def clean_row(row):
    raw_deadline = row.get("deadline", "")
    deadline = None if pd.isna(raw_deadline) or str(raw_deadline).strip() == "" else str(raw_deadline)
    
    try:
        department = parse_department(row.get("department", ""))
    except Exception as e:
        print(f"[DEBUG] parse_department() input={row}, type={type(row)}")
        raise

    return {
        "title": str(row.get("title", "")),
        "deadline": deadline,
        "topic": str(row.get("topic", "")),
        "oneline": str(row.get("oneline", "")),
        "department": department,
        "url": str(row.get("url", "")),
        "image_paths": str(row.get("image_paths", "")),
        "ocr_text": str(row.get("ocr_text", ""))
    }

def insert_notice(parsed):
    columns = ['title', 'deadline', 'topic', 'oneline', 'url']
    values = [parsed[col] for col in columns]
    return insert_and_return_id("notice", columns, values)

def insert_notice_department(notice_id, departments):
    # 배열이나 시리즈가 들어오면 리스트로 강제 변환
    if not isinstance(departments, list):
        departments = list(departments)

    for dept in departments:
        if isinstance(dept, (list, dict, np.ndarray)):
            dept = str(dept)  # 이상한 구조 방지
        dept = str(dept).strip()
        if dept:  # 빈 문자열 방지
            insert_data("notice_department", ["notice_id", "department"], [notice_id, dept])
            
def insert_notice_attachment(notice_id, image_paths):
    image_list = parse_image_paths(image_paths)
    if not image_list:
        return  # 이미지가 없으면 아무 것도 하지 않음
    
    for order, url in enumerate(image_list):
        insert_data("notice_attachment", ["notice_id", "file_url", "file_order"], [notice_id, url, order])

def insert_notice_ocr_text(notice_id, ocr_text):
    if not ocr_text.strip(): 
        return  
    
    insert_data("notice_ocr_text", ["notice_id", "ocr_text"], [notice_id, ocr_text])


def insert_notice_all(parsed: dict):
    parsed = clean_row(parsed)

    try:
        notice_id = insert_notice(parsed)
        insert_notice_department(notice_id, parsed['department'])
        insert_notice_attachment(notice_id, parsed['image_paths'])

        # OCR 텍스트가 존재할 경우에만 삽입
        ocr_text = parsed.get("ocr_text", "").strip()
        if ocr_text:
            insert_notice_ocr_text(notice_id, ocr_text)

        print(f"[✔] DB 삽입 완료 - title: {parsed.get('title')}\n")
    except Exception as e:
        print(f"[X] DB 삽입 실패 - title: {parsed.get('title')} - error: {e}\n")
        raise