from dotenv import load_dotenv
import os
from google import genai
import pandas as pd
import json
import re
import pytesseract
from PIL import Image
from pathlib import Path
from tqdm import tqdm
from datetime import datetime

# ==== CONFIG ====
CHECKPOINT_DIR = "data"
IMAGE_DIR = Path("data") / "images"
CSV_PATH = "data/강원대 통합 공지사항 크롤링.csv"
SAVE_EVERY = 50
DAILY_LIMIT = 250
MODEL_ID = "gemini-2.5-flash"

# ==== API 초기화 ====
load_dotenv()
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")
CLIENT = genai.Client(api_key=GOOGLE_API_KEY)

# ==== Tesseract OCR 설정 ====
pytesseract.pytesseract.tesseract_cmd = r"C:/Program Files/Tesseract-OCR/tesseract.exe"
custom_config = r'--oem 3 --psm 6 -l kor+eng'
# pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"
# custom_config = r'--oem 3 --psm 6 -l kor+eng'

# ==== 기타 ====
from scripts.llm.prompt_template import TEST_PROMPT_KR


def extract_text_from_images(image_paths):
    ocr_texts = []
    for image_path in image_paths:
        image_path = image_path.replace("/", os.sep).replace("\\", os.sep)
        full_image_path = IMAGE_DIR / image_path
        
        if full_image_path.exists():
            try:
                image = Image.open(full_image_path)
                text = pytesseract.image_to_string(image, config=custom_config)
                ocr_texts.append(text.strip())
            except Exception as e:
                print(f"[OCR ERROR] {image_path} - {e}")
        else:
            print(f"[IMAGE NOT FOUND] {image_path}")
    return "\n".join(ocr_texts)


def clean_ocr_text(text: str) -> str:
    # 줄바꿈, 탭 제거 → 공백으로 치환
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    # 연속된 공백 → 하나로 축소
    text = re.sub(r'\s{2,}', ' ', text)
    # 앞뒤 공백 제거
    return text.strip()

def main():
    today = datetime.today().strftime("%Y-%m-%d")
    checkpoint_path = f"{CHECKPOINT_DIR}/checkpoint_results_{today}.csv"

    df = pd.read_csv(CSV_PATH, encoding="utf-8")

    # 작성일을 datetime으로 변환 후 최신순 정렬
    df["작성일"] = pd.to_datetime(df["작성일"], errors="coerce")
    df = df.sort_values(by="작성일", ascending=False)

    results = []
    error_rows = []


    # 체크포인트 불러오기
    if os.path.exists(checkpoint_path):
        existing_df = pd.read_csv(checkpoint_path)
        start_idx = len(existing_df)
        results = existing_df.to_dict(orient="records")
        print(f"기존 체크포인트에서 이어서 시작: {start_idx}행부터")
    else:
        start_idx = 0
        print("처음부터 시작합니다.")

    df = df.iloc[start_idx : start_idx + DAILY_LIMIT]

    # 메인 처리 루프
    for i, row in tqdm(df.iterrows(), total=len(df), desc="LLM 분류 진행"):
        try:
            title = row.get("제목", "")
            body = row.get("본문내용", "")  
            
            image_paths_str = str(row.get("사진", "")).strip()
            
            if image_paths_str.lower() != "nan" and image_paths_str != "":
                image_paths = [p.strip() for p in image_paths_str.split(";") if p.strip()]
            else:
                image_paths = []
        
            ocr_text = extract_text_from_images(image_paths)
            cleaned_ocr_text = clean_ocr_text(ocr_text)              
            print("Cleaned OCR Text:\n", cleaned_ocr_text)        

            # --- 프롬프트 생성 ---
            prompt = TEST_PROMPT_KR.format(
                title=title, 
                body=body, 
                ocr_text=cleaned_ocr_text
            )
            contents = [prompt]
            
            # --- 토큰 수 사전 계산 --- 
            try:
                token_info = CLIENT.models.count_tokens(model=MODEL_ID, contents=contents)
                pre_token_count = token_info.total_tokens
            except Exception as e:
                print(f"[TOKEN COUNT ERROR] index {i} - {e}")
                pre_token_count = None
            
            # 출력 텍스트를 파싱
            try:
                # --- LLM 호출 ---
                response = CLIENT.models.generate_content(
                    model=MODEL_ID,
                    contents=contents
                )

                usage = response.usage_metadata
                prompt_token_count = usage.prompt_token_count if usage else None
                response_token_count = usage.candidates_token_count if usage else None
                total_token_count = usage.total_token_count if usage else None
                
                answer = response.candidates[0].content.parts[0].text.strip()
                print(f"\n [LLM RAW RESPONSE - index {i}]:\n{answer}\n")
                
                # --- 백틱 제거 ---
                if answer.startswith("```"):
                    answer = re.sub(r"^```(?:json)?\n?", "", answer)
                    answer = re.sub(r"\n?```$", "", answer)

                # --- JSON 파싱 ---
                parsed = json.loads(answer)
                parsed.pop("reasoning", None)
                results.append(parsed)

                # --- 주기적 저장 ---
                if (len(results) % SAVE_EVERY == 0):
                    pd.DataFrame(results).to_csv(checkpoint_path, index=False, encoding="utf-8-sig")
                    print(f"{len(results)}개 저장됨 (index {i})")

                # Pre_token: contents에 들어간 입력(prompt+이미지등)을 기준으로 LLM이 생성 전에 사전 계산한 토큰 수
                # Prompt_token: 실체 요청 시 사용된 입력의 토큰 수; pre_token_count와 거의 일치하지만, 가끔 내부 처리 차이로 미세한 차이가 날 수도 있음
                # Response_token: 모델이 생성한 출력의 토큰 수
                # Total_token: 입력+출력을 합친 총 토큰 수 (요금 청구구 기준)
                print(f"[Token Summary] index {i}")
                print(f"  pre_token_count       : {pre_token_count}")
                print(f"  prompt_token_count    : {prompt_token_count}")
                print(f"  response_token_count  : {response_token_count}")
                print(f"  total_token_count     : {total_token_count}\n")

            except Exception as e:
                print(f"[PARSE ERROR] index {i} - {e}")
                continue

        except Exception as e:
            print(f"[ERROR] index {i}: {e}")
            error_rows.append(i)
            continue

    # 마지막 전체 저장
    output_df = pd.DataFrame(results)
    output_df.to_csv(checkpoint_path, index=False, encoding="utf-8-sig")
    
    error_path = f"{CHECKPOINT_DIR}/error_rows_{today}.txt"
    with open(error_path, "w") as f:
        f.write("\n".join(map(str, error_rows)))
        
    print("분류 결과 저장 완료!")


if __name__ == "__main__":
    main()