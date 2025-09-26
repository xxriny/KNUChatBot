# scripts/db_tasks/llm_daily_counter_repo.py
from typing import Optional
import pyodbc
from scripts.utils.db_utils import maybe_open

TABLE = "dbo.llm_daily_counter"

class LimitReached(Exception):
    pass

def reserve_llm_slot(
    conn: Optional[pyodbc.Connection],
    cap: int,
    need_calls: int = 1,
) -> int:
    """
    오늘(KST) need_calls 만큼 예약(+증가).
    - 성공: 남은 횟수 반환
    - 초과: LimitReached
    - 커밋은 호출측에서 처리
    """
    c, close_after = maybe_open(conn)
    try:
        sql = f"""
        DECLARE @cap   int  = ?;
        DECLARE @need  int  = ?;
        DECLARE @today date = CONVERT(date, SYSDATETIMEOFFSET() AT TIME ZONE 'Korea Standard Time');

        -- id=1 행이 없으면 생성(안전장치)
        IF NOT EXISTS (SELECT 1 FROM {TABLE} WHERE id = 1)
        BEGIN
            INSERT INTO {TABLE} (id, current_date_kst, used_calls)
            VALUES (1, @today, 0);
        END;

        UPDATE t WITH (ROWLOCK, UPDLOCK, HOLDLOCK)
           SET 
             current_date_kst = CASE 
                                   WHEN t.current_date_kst <> @today THEN @today 
                                   ELSE t.current_date_kst 
                                END,
             used_calls       = CASE 
                                   WHEN t.current_date_kst <> @today THEN @need
                                   WHEN t.used_calls + @need <= @cap THEN t.used_calls + @need
                                   ELSE t.used_calls
                                END
         OUTPUT (@cap - INSERTED.used_calls) AS remain_after 
          FROM {TABLE} AS t
         WHERE t.id = 1
           AND (
                 t.current_date_kst <> @today
                 OR (t.used_calls + @need <= @cap)
               );
        """
        params = (cap, need_calls)
        with c.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            if not row:
                raise LimitReached("일일 한도 도달")
            remain_after = int(row[0])
        return remain_after
    finally:
        if close_after:
            c.close()
