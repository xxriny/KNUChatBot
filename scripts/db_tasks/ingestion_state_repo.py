import pandas as pd
from scripts.utils.db_utils import maybe_open
from scripts.utils.log_utils import init_runtime_logger
import pyodbc
from typing import Optional

logger = init_runtime_logger()

def fetch_last_published_at(conn: Optional[pyodbc.Connection]) -> pd.Timestamp:
    c, close_after = maybe_open(conn)
    try:
        cur = c.cursor()
        cur.execute(
            "SELECT last_published_at FROM dbo.ingestion_state WHERE source_name=?",
            ("knu_notice",),
        )
        row = cur.fetchone()
        if row and row[0]:
            ts = pd.Timestamp(row[0], tz="UTC")
            logger.debug("[INGESTION_STATE] fetched watermark=%s", ts)
            return ts
        
        # 값이 없을 때 현재 시각(UTC) 반환
        now = pd.Timestamp.now(tz="UTC")
        logger.info("[INGESTION_STATE] no row found, using current UTC=%s", now)
        return now
    
    except Exception as e:
        # 오류 발생 시에도 현재 시각(UTC) 반환
        now = pd.Timestamp.now(tz="UTC")
        logger.error("[INGESTION_STATE] fetch failed: %s → fallback to current UTC=%s", e, now, exc_info=True)
        return now
    
    finally:
        if close_after: c.close()

def to_utc_naive(ts: pd.Timestamp) -> pd.Timestamp:
    # UTC로 맞추고 tz 제거(naive) – pyodbc/SQL Server DATETIME2 안전
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.tz_localize(None)

def update_last_published_at(conn: Optional[pyodbc.Connection], ts: pd.Timestamp):
    c, close_after = maybe_open(conn)
    try:
        ts_naive = to_utc_naive(ts).to_pydatetime()
        cur = c.cursor()
        
        cur.execute("""
            MERGE dbo.ingestion_state AS t
            USING (SELECT ? AS source_name, ? AS last_published_at) AS s
            ON (t.source_name = s.source_name)
            WHEN MATCHED THEN
                UPDATE SET last_published_at = s.last_published_at
            WHEN NOT MATCHED THEN
                INSERT (source_name, last_published_at) VALUES (s.source_name, s.last_published_at);
        """, ("knu_notice", ts_naive))

        if close_after:
            c.commit()
        logger.info("[INGESTION_STATE] watermark upserted -> %s (source=%s)", ts, "knu_notice")


    except Exception as e:
        logger.error("[INGESTION_STATE] update failed: %s", e, exc_info=True)
        if close_after:
            c.rollback()
        raise
    
    finally:
        if close_after: 
            c.close()
