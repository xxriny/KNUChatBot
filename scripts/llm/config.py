from datetime import datetime
from pathlib import Path

CHECKPOINT_DIR = "data"
IMAGE_DIR = Path("data") / "images"
CSV_PATH = "data/강원대 통합 공지사항 크롤링.csv"
SAVE_EVERY = 50
DAILY_LIMIT = 250
TODAY=datetime.today().strftime('%Y-%m-%d')
CHECKPOINT_PATH = f"{CHECKPOINT_DIR}/checkpoint_results_{TODAY}.csv"
MODEL_ID = "gemini-2.5-flash"