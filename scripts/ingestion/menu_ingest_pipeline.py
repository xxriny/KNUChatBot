from tqdm import tqdm
from scripts.db_tasks.menu_repo import insert_menu_rows
from scripts.utils.blob_utils import load_notices_df_from_blob
from scripts.utils.log_utils import init_runtime_logger

logger = init_runtime_logger()

KOR_TO_ENG = {
    "식당": "restaurant",
    "식단": "menu_group",
    "아침·점심·저녁": "meal_type",
    "날짜": "service_date",
    "메뉴": "menu",
}
COLS = ["restaurant", "menu_group", "meal_type", "service_date", "menu"]

def run_ingestion():
    logger.info("[MENU_INGEST] 시작")
    
    df = load_notices_df_from_blob(blob_name="KNU_식단_latest.csv",encoding="utf-8")

    df = df.rename(columns=KOR_TO_ENG)[COLS].copy()
    rows = list(df.itertuples(index=False, name=None))
    inserted = insert_menu_rows(None, rows)
    print(f"Inserted rows: {inserted}")
        


if __name__ == "__main__":
    run_ingestion()