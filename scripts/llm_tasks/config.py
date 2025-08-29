from datetime import datetime
from pathlib import Path

CHECKPOINT_DIR = "data"
IMAGE_DIR = Path("data") / "images"
CSV_PATH = "data/kangwon_notices.csv"
SAVE_EVERY = 50
DAILY_LIMIT = 200
TODAY=datetime.today().strftime('%Y-%m-%d')
BACKUP_CSV_PATH = "data/llm_backup_results.csv"
MODEL_ID = "gemini-2.5-flash"