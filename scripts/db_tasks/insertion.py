import pandas as pd
import pyodbc
from typing import Optional
from scripts.utils.db_utils import insert_and_return_id, insert_data
from scripts.utils.parsing_utils import parse_image_paths, parse_department
from scripts.utils.key_utils import normalize_url, sha256_hex
from scripts.utils.log_utils import init_runtime_logger, capture_unhandled_exception
from scripts.utils.db_utils import  _maybe_open
from scripts.db_tasks.notice_repo import(
    upsert_notice_keys, apply_llm_result,
    add_departments, add_attachments, upsert_ocr_text
)

logger = init_runtime_logger()

def clean_row(row):
    raw_deadline = row.get("deadline", "")
    deadline = None if pd.isna(raw_deadline) or str(raw_deadline).strip() == "" else str(raw_deadline)
    
    try:
        department = parse_department(row.get("department", ""))
    except Exception as e:
        capture_unhandled_exception(
            index=None,
            phase="INGEST",
            url=None,
            exc=e,
            extra={"row": str(row), "field": "department"}
        )
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

def insert_notice(parsed: dict, conn: Optional[pyodbc.Connection]) -> int:
    c, close_after = _maybe_open(conn)
    try:
        title = str(parsed.get("title", "") or "")
        url   = str(parsed.get("url", "") or "")
        url_hash = sha256_hex(normalize_url(url))
        notice_id, _created = upsert_notice_keys(conn, title, url, url_hash)  # 업서트
        # LLM 결과 반영(완료 마킹)
        topic   = (parsed.get("topic") or None)
        oneline = (parsed.get("oneline") or None)
        deadline= (parsed.get("deadline") or None)
        apply_llm_result(conn, notice_id, topic, oneline, deadline, new_title=title)
        return notice_id
    finally:
        if close_after:
            c.close()

def insert_notice_department(notice_id: int, departments, conn: Optional[pyodbc.Connection]):
    c, close_after = _maybe_open(conn)
    try:
        if not isinstance(departments, list):
            departments = list(departments)
        add_departments(conn, notice_id, departments)
    finally:
        if close_after:
            c.close()

def insert_notice_attachment(notice_id: int, image_paths, conn: Optional[pyodbc.Connection]):
    c, close_after = _maybe_open(conn)
    try:
        urls = parse_image_paths(image_paths)
        add_attachments(conn, notice_id, urls)
    finally:
        if close_after:
            c.close()

def insert_notice_ocr_text(notice_id: int, ocr_text: str, conn: Optional[pyodbc.Connection]):
    c, close_after = _maybe_open(conn)

    try:
        text = (ocr_text or "").strip()
        if not text:
            return
        upsert_ocr_text(conn, notice_id, text)
    finally:
        if close_after:
            c.close()

def insert_notice_all(parsed: dict,  conn: Optional[pyodbc.Connection]) -> int:
    c, close_after = _maybe_open(conn)
    try:
        parsed = clean_row(parsed)
        notice_id = insert_notice(parsed, conn=conn)

        depts = parsed.get("department", [])
        if not isinstance(depts, list):
            try:
                depts = parse_department(depts)
            except Exception as e:
                capture_unhandled_exception(index=None, phase="DB", url=parsed.get("url"),
                                            exc=e, extra={"field": "department"})
                depts = []
        if depts:
            insert_notice_department(notice_id, depts, conn=conn)

        img_paths = parsed.get("image_paths", "")
        if img_paths:
            insert_notice_attachment(notice_id, img_paths, conn=conn)

        ocr_text = (parsed.get("ocr_text") or "").strip()
        if ocr_text:
            insert_notice_ocr_text(notice_id, ocr_text, conn=conn)

        return notice_id
    finally:
        if close_after:
            try:
                c.close()
            except Exception:
                capture_unhandled_exception(
                    index=None, phase="DB", url=parsed.get("url"),
                    exc=RuntimeError("connection close failed"), extra={}
                )