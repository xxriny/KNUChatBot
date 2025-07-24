import pandas as pd
import json
import re
import os
from tqdm import tqdm
from scripts.llm.config import CSV_PATH, CHECKPOINT_PATH, CHECKPOINT_DIR, TODAY, SAVE_EVERY, DAILY_LIMIT, MODEL_ID
from scripts.llm.ocr_utils import extract_text_from_images, clean_ocr_text
from scripts.llm.prompt_template import TEST_PROMPT_KR
from scripts.llm.api_client import CLIENT

def parse_image_paths(image_paths_str: str) -> list[str]:
    if image_paths_str.lower() != "nan" and image_paths_str != "":
        return [p.strip() for p in image_paths_str.split(";") if p.strip()]
    else:
        return []

def load_checkpoint(path: str) -> tuple[list[dict], int]:
    # 체크포인트 불러오기
    if os.path.exists(path):
        df = pd.read_csv(path)
        print(f"기존 체크포인트에서 이어서 시작: {len(df)}행부터")
        return df.to_dict(orient="records"), len(df)
    else:
        print("처음부터 시작합니다.")
        return [], 0

def save_results(results: list[dict], path: str):
    pd.DataFrame(results).to_csv(path, index=False, encoding="utf-8-sig")

def run_llm_classification():
    df = pd.read_csv(CSV_PATH, encoding="utf-8")

    # 작성일을 datetime으로 변환 후 최신순 정렬
    df["작성일"] = pd.to_datetime(df["작성일"], errors="coerce")
    df = df.sort_values(by="작성일", ascending=False)

    results, start_idx = load_checkpoint(CHECKPOINT_PATH)
    df = df.iloc[start_idx : start_idx + DAILY_LIMIT]
    
    error_rows = []

    for i, row in tqdm(df.iterrows(), total=len(df), desc="LLM 분류 진행"):
        try:
            title = row.get("제목", "")
            body = row.get("본문내용", "")  
            
            image_paths = parse_image_paths(str(row.get("사진", "")).strip())
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
                    save_results(results, CHECKPOINT_PATH)
                    print(f"{len(results)}개 저장됨 (index {i})")

                # Pre_token: contents에 들어간 입력(prompt+이미지등)을 기준으로 LLM이 생성 전에 사전 계산한 토큰 수
                # Prompt_token: 실체 요청 시 사용된 입력의 토큰 수; pre_token_count와 거의 일치하지만, 가끔 내부 처리 차이로 미세한 차이가 날 수도 있음
                # Response_token: 모델이 생성한 출력의 토큰 수
                # Total_token: 입력+출력을 합친 총 토큰 수 (요금 청구구 기준)
                print(f"[Token Summary] index {i}")
                print(f"  pre_token_count       : {pre_token_count}")
                print(f"  prompt_token_count    : {usage.prompt_token_count if usage else None}")
                print(f"  response_token_count  : {usage.candidates_token_count if usage else None}")
                print(f"  total_token_count     : {usage.total_token_count if usage else None}\n")

            except Exception as e:
                print(f"[PARSE ERROR] index {i} - {e}")
                continue

        except Exception as e:
            print(f"[ERROR] index {i}: {e}")
            error_rows.append(i)
            continue
    
    #마지막 저장
    save_results(results, CHECKPOINT_PATH)
    error_path = f"{CHECKPOINT_DIR}/error_rows_{TODAY}.txt"
    with open(error_path, "w") as f:
        f.write("\n".join(map(str, error_rows)))
        
    print("분류 결과 저장 완료!")

if __name__ == "__main__":
    run_llm_classification()