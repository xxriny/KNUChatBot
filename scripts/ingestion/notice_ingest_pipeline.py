import pandas as pd
import os
from tqdm import tqdm
from scripts.db_tasks.ingestion_state_repo import fetch_last_published_at, update_last_published_at, to_utc_naive
from scripts.db_tasks.llm_quota_repo import reserve_llm_slot
from scripts.utils.blob_utils import load_notices_df_from_blob
from scripts.utils.ocr_utils import extract_text_from_images, clean_ocr_text
from scripts.utils.parsing_utils import parse_image_paths
from scripts.llm_tasks.llm_caller import generate_llm_response
from scripts.utils.key_utils import normalize_url, sha256_hex
from scripts.db_tasks.insertion import insert_notice_all
from scripts.db_tasks.notice_repo import get_llm_status, upsert_notice_keys, mark_failed
from scripts.utils.log_utils import init_runtime_logger, capture_unhandled_exception
from scripts.utils.db_utils import get_connection, transaction

CAP = 230
LOOKBACK_DAYS = 1
BACKUP_CSV_PATH = "data/llm_backup_results.csv"

logger = init_runtime_logger()

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
    logger.info("[NOTICE_INGEST] last=%s, cutoff=%s", last_ts, cutoff)

    df = df[df["작성일"] >= cutoff].sort_values(by="작성일", ascending=True).reset_index(drop=True)
    logger.info("[INGEST] 후보 행 수=%s", len(df))

    max_processed = last_ts  # 이번 배치에서 처리된 최신 작성일

    logger.info(
    "[DEBUG] df_max_date=%s, last_ts=%s, df_has_newer=%s",
    df["작성일"].max(),
    last_ts,
    df["작성일"].max() > last_ts
)

    # --- ingestion loop ---
    for _, row in tqdm(df.iterrows(), total=len(df), desc="Ingestion 진행"):
            try:
                title = str(row.get("제목", "") or "")
                body = str(row.get("본문내용", "") or "")
                url = str(row.get("링크", "") or "")
                image_paths_str = str(row.get("사진", "")).strip()
                url_hash = sha256_hex(normalize_url(url))

                # ── T1: 키 업서트 + 상태 조회
                try:
                    with transaction(conn) as c:
                        notice_id, _ = upsert_notice_keys(c, title, url, url_hash)
                        st = get_llm_status(c, notice_id)
                except Exception as e:
                    logger.error(
                        "[INGEST][T1] upsert/status 실패: url=%s title=%s notice_id=%s err=%s",
                        url, title, notice_id, e, exc_info=True
                    )
                    try:
                        if notice_id is not None:
                            with transaction(conn) as c2:
                                mark_failed(c2, notice_id)
                    except Exception as e2:
                        logger.warning("[INGEST][T1] 실패마킹 실패: notice_id=%s err=%s",
                                    notice_id, e2, exc_info=True)
                    continue

                if st == 1:
                    logger.info("[SKIP] 완료건 notice_id=%s url=%s", notice_id, url)
                    if pd.notna(row["작성일"]) and row["작성일"] > max_processed:
                        max_processed = row["작성일"]
                    continue

                # 하루 한도량 관리
                with transaction(conn) as c:   #
                    remain = reserve_llm_slot(c, cap=CAP, need_calls=1)
                    logger.info("[QUOTA] 예약 성공 - 남은 호출 수=%s", remain)

                # OCR 준비
                if image_paths_str.lower() == "nan" or not image_paths_str:
                    ocr_text = ""
                    image_paths = []
                else:
                    image_paths = parse_image_paths(image_paths_str)
                    ocr_text_raw = extract_text_from_images(image_paths)
                    ocr_text = clean_ocr_text(ocr_text_raw)

                # LLM 호출 및 분류
                parsed = generate_llm_response(title, body, ocr_text)
                parsed["url"] = url
                parsed["image_paths"] = image_paths_str
                parsed["ocr_text"] = ocr_text

                append_to_backup_csv(parsed)

                # ── T2: 결과 쓰기/상태 반영
                try:
                    with transaction(conn) as c:
                        insert_notice_all(parsed, conn=c)
                except Exception as e:
                    logger.error(
                        "[INGEST][T2] DB write 실패: notice_id=%s url=%s title=%s err=%s",
                        notice_id, url, title, e, exc_info=True
                    )
                    try:
                        if notice_id is not None:
                            with transaction(conn) as c2:
                                mark_failed(c2, notice_id)
                    except Exception as e2:
                        logger.warning("[INGEST][T2] 실패마킹 실패: notice_id=%s err=%s",
                                    notice_id, e2, exc_info=True)
                    continue  # 다음 행
            
                logger.info("[✔] ingestion 성공 - title=%s", parsed.get("title"))

                # 워터마크 후보 갱신
                if pd.notna(row["작성일"]) and row["작성일"] > max_processed:
                    logger.debug(
                        "[WATERMARK] 갱신됨: old=%s → new=%s (row_title=%s)",
                        max_processed, row["작성일"], row.get("제목", "N/A")
                    )
                    max_processed = row["작성일"]

                # 워터마크 갱신
                if max_processed > last_ts:
                    logger.info("[DEBUG] 워터마크 갱신")
                    with transaction(conn) as c:
                        update_last_published_at(c, max_processed)


            except Exception as e:
                try:
                    if notice_id is not None:
                        with transaction(conn) as c:
                            mark_failed(c, notice_id)
                except Exception:
                    pass

                capture_unhandled_exception(
                    index=None, phase="INGEST", url=row.get("링크", None),
                    exc=e, extra={"title": row.get("제목", "")}
                )
                logger.error("Info - title=%s - error=%s", row.get("제목", ""), str(e))
                continue

if __name__ == "__main__":
    run_ingestion()

