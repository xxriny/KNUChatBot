from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import os

IMAGE_DIR = Path("data") / "images"
SAVE_EVERY = 50
DAILY_LIMIT = 200
TODAY=datetime.today().strftime('%Y-%m-%d')
BACKUP_CSV_PATH = "data/llm_backup_results.csv"