from dotenv import load_dotenv
import os
from google import genai
import pandas as pd
import json
import re

# API 키 로드
load_dotenv()
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_ID = "gemini-2.5-flash-preview-04-17"

client = genai.Client(api_key=GOOGLE_API_KEY)

# 프롬프트 템플릿 불러오기
with open("scripts/llm/prompt_template.txt", "r", encoding="utf-8") as f:
    prompt_template = f.read()

# CSV 데이터 불러오기
df = pd.read_csv("data/kangwon_library_notice.csv", encoding="cp949")

# 결과 저장용 리스트
results = []

# 한 행씩 프롬프트에 넣어 결과 생성
for i, row in df.head(5).iterrows():
    title = row.get("제목", "")
    body = row.get("본문", "")
    date = row.get("작성일", "")
    link = row.get("상세 링크", "")    
    
    image_paths_str = str(row.get("이미지 파일 경로", "")).strip()
    image_paths = image_paths_str.split(";") if image_paths_str.lower() != "nan" else []

  
    # 여러 이미지 처리
    for image_path in image_paths:
        image_path = image_path.strip()
        if os.path.exists(image_path):
             uploaded_files = client.files.upload(file=image_path)
        else:
            print(f"⚠️ [NOTICE] index {i} - Image not found or invalid path: {image_path}")



    prompt = prompt_template.format(title=title, body=body, date=date, link=link)
    
    # 출력 텍스트를 파싱 (LLM이 JSON 형식 준다고 가정)
    try:
        # Gemini API 요청
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=[
                uploaded_files,
                prompt
            ]
        )
        
        # 응답에서 텍스트 추출
        answer = response.candidates[0].content.parts[0].text.strip()
        print(f"\n [LLM RAW RESPONSE - index {i}]:\n{answer}\n{'='*40}")
        
        # 백틱 감싼 부분 제거
        if answer.startswith("```"):
            # 백틱으로 감싸진 JSON만 추출
            answer = re.sub(r"^```(?:json)?\n?", "", answer)
            answer = re.sub(r"\n?```$", "", answer)

        #  JSON 파싱
        parsed = json.loads(answer)
        results.append(parsed)

    except Exception as e:
        print(f"[PARSE ERROR] index {i} - {e}")
        continue

# CSV로 저장
output_df = pd.DataFrame(results)
output_df.to_csv("data/llm_classified_results.csv", index=False, encoding="utf-8-sig")
print("분류 결과 저장 완료!")
