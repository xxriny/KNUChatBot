import pandas as pd
import os
from tqdm import tqdm
from scripts.db_tasks.ingestion_state_repo import fetch_last_published_at, update_last_published_at, to_utc_naive
from scripts.utils.blob_utils import load_notices_df_from_blob
from scripts.utils.ocr_utils import extract_text_from_images, clean_ocr_text
from scripts.utils.parsing_utils import parse_image_paths
from scripts.llm_tasks.llm_caller import generate_llm_response
from scripts.utils.key_utils import normalize_url, sha256_hex
from scripts.db_tasks.insertion import insert_notice_all
from scripts.db_tasks.notice_repo import get_llm_status, upsert_notice_keys, mark_failed
from scripts.utils.log_utils import init_runtime_logger, capture_unhandled_exception
from scripts.utils.db_utils import get_connection

logger = init_runtime_logger()
DAILY_LIMIT = 230
LOOKBACK_DAYS = 1
BACKUP_CSV_PATH = "data/llm_backup_results.csv"

def append_to_backup_csv(parsed_data: dict, path: str = BACKUP_CSV_PATH):
    df_row = pd.DataFrame([parsed_data])
    if not os.path.exists(path):
        df_row.to_csv(path, index=False, encoding="utf-8-sig")
    else:
        df_row.to_csv(path, mode="a", index=False, header=False, encoding="utf-8-sig")

def run_ingestion():
    conn = get_connection()

     # --- CSV 로드 및 '작성일' 표준화 ---
    df = load_notices_df_from_blob(blob_name="kangwon_notices.csv", encoding="utf-8")
    df["작성일"] = pd.to_datetime(df["작성일"], errors="coerce")

    # 작성일이 tz 없는 KST 로컬 시각이라고 가정 → KST 부여 → UTC로 변환 → tz 제거
    if getattr(df["작성일"].dt, "tz", None) is None:
        df["작성일"] = (df["작성일"]
                        .dt.tz_localize("Asia/Seoul")
                        .dt.tz_convert("UTC")
                        .dt.tz_localize(None))
    else:
        df["작성일"] = (df["작성일"]
                        .dt.tz_convert("UTC")
                        .dt.tz_localize(None))
        
    # --- 워터마크 조회 & cutoff 계산 ---
    last_ts = fetch_last_published_at(conn)          # DB에서 읽은 시각
    last_ts = to_utc_naive(pd.to_datetime(last_ts)) # DB 값도 UTC-naive로 강제 정규화
    cutoff = last_ts - pd.Timedelta(days=LOOKBACK_DAYS)
    logger.info("[NOTICE_INGEST] last=%s, cutoff=%s, daily_limit=%s", last_ts, cutoff, DAILY_LIMIT)

    df = df[df["작성일"] >= cutoff].sort_values(by="작성일", ascending=True).reset_index(drop=True)
    logger.info("[INGEST] 후보 행 수=%s", len(df))

    llm_calls = 0
    max_processed = last_ts  # 이번 배치에서 처리된 최신 작성일

    # --- ingestion loop ---
    for _, row in tqdm(df.iterrows(), total=len(df), desc="Ingestion 진행"):
            try:
                title = str(row.get("제목", "") or "")
                body = str(row.get("본문내용", "") or "")
                url = str(row.get("링크", "") or "")
                image_paths_str = str(row.get("사진", "")).strip()

                # 1) URL 해시 생성 → 먼저 DB에 업서트(LLM 호출 전)
                url_hash = sha256_hex(normalize_url(url))
                notice_id, _ = upsert_notice_keys(conn, title, url, url_hash)

                # 2) 상태 확인: 완료(1)이면 LLM 스킵
                st = get_llm_status(conn, notice_id)
                if st == 1:
                    logger.info("[SKIP] 완료건 notice_id=%s url=%s", notice_id, url)
                    continue

                # 3) 일일 LLM 한도 체크
                if llm_calls >= DAILY_LIMIT:
                    logger.info("[STOP] 일일 LLM 한도 도달: %s", llm_calls)
                    break
                llm_calls += 1

                # 4) OCR 준비
                if image_paths_str.lower() == "nan" or not image_paths_str:
                    ocr_text = ""
                    image_paths = []
                else:
                    image_paths = parse_image_paths(image_paths_str)
                    ocr_text_raw = extract_text_from_images(image_paths)
                    ocr_text = clean_ocr_text(ocr_text_raw)

                # --- LLM 호출 및 분류 ---
                parsed = generate_llm_response(title, body, ocr_text)
                parsed["url"] = url
                parsed["image_paths"] = image_paths_str
                parsed["ocr_text"] = ocr_text

                append_to_backup_csv(parsed)
                
                # --- DB 삽입 ---
                insert_notice_all(parsed, conn=conn)
                logger.info("[✔] ingestion 성공 - title=%s", parsed.get("title"))

                # --- 워터마크 후보 갱신 ---
                if pd.notna(row["작성일"]) and row["작성일"] > max_processed:
                    logger.debug(
                        "[WATERMARK] 갱신됨: old=%s → new=%s (row_title=%s)",
                        max_processed, row["작성일"], row.get("제목", "N/A")
                    )
                    max_processed = row["작성일"]

            except Exception as e:
                # 실패: 상태 마킹(2) 후 로깅
                try:
                    if 'notice_id' in locals():
                        mark_failed(None, notice_id)
                except Exception:
                    pass

                capture_unhandled_exception(
                    index=None,
                    phase="INGEST",
                    url=row.get("링크", None),
                    exc=e,
                    extra={"title": row.get("제목", "")}
                )
                logger.error("[X] ingestion 실패 - title=%s - error=%s", row.get("제목", ""), str(e))
                continue
    
    # --- 4) 워터마크 갱신 ---
    if max_processed > last_ts:
        update_last_published_at(conn, max_processed)

if __name__ == "__main__":
    run_ingestion()

