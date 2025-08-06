import pandas as pd
import os
from tqdm import tqdm
from scripts.llm_tasks.config import CSV_PATH, DAILY_LIMIT, BACKUP_CSV_PATH
from utils.ocr_utils import extract_text_from_images, clean_ocr_text
from utils.parsing_utils import parse_image_paths
from scripts.llm_tasks.llm_utils import generate_llm_response
from scripts.db_tasks.insertion import insert_notice_all

def get_checkpoint_index(path: str = "data/checkpoint_index.txt") -> int:
    if os.path.exists(path):
        with open(path, "r") as f:
            return int(f.read().strip())
    return 0 # 처음 시작할 경우

def save_checkpoint_index(index: int, path:str = "data/checkpoint_index.txt"):
    with open(path, "w") as f:
        f.write(str(index))

def append_to_backup_csv(parsed_data: dict, path: str = BACKUP_CSV_PATH):
    df_row = pd.DataFrame([parsed_data])
    if not os.path.exists(path):
        df_row.to_csv(path, index=False, encoding="utf-8-sig")
    else:
        df_row.to_csv(path, mode="a", index=False, header=False, encoding="utf-8-sig")

def run_ingestion():
    start_idx = get_checkpoint_index()
    df = pd.read_csv(CSV_PATH, encoding="utf-8")
    df["작성일"] = pd.to_datetime(df["작성일"], errors="coerce") # 작성일을 datetime으로 변환 후 최신순 정렬
    df = df.sort_values(by="작성일", ascending=False).reset_index(drop=True)
    df = df.iloc[start_idx: start_idx + DAILY_LIMIT]

    for i, row in tqdm(df.iterrows(), total=len(df), desc="Ingestion 진행"):
        try:
            save_checkpoint_index(start_idx + i + 1) # 현재 index를 저장

            title = row.get("제목", "")
            body = row.get("본문내용", "")  
            image_paths_str = str(row.get("사진", "")).strip()
            if image_paths_str.lower() == "nan" or not image_paths_str:
                image_paths = []
                ocr_text = ""

            else:
                image_paths = parse_image_paths(image_paths_str)
                #이미지가 존재할 시 OCR 수행
                ocr_text_raw = extract_text_from_images(image_paths)
                ocr_text = clean_ocr_text(ocr_text_raw)

            # 2. LLM 분류
            parsed = generate_llm_response(title, body, ocr_text)
            
            parsed["url"] = row.get("링크", "")
            parsed["image_paths"] = row.get("사진", "")
            parsed["ocr_text"] = ocr_text

            # 중간 백업용 CSV 저장
            append_to_backup_csv(parsed)

            # 3. DB 삽입
            insert_notice_all(parsed)
            
        except Exception as e:
            print(f"[ERROR] index {start_idx + i} - {e.__class__.__name__} - {e}\n")
            continue

if __name__ == "__main__":
    run_ingestion()

