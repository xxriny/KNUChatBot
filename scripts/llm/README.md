# LLM 분류 및 prompt
크롤링된 텍스트 및 이미지 기반 공지사항 데이터를 Gemini LLM API를 이용해 분류/요약하는 자동화 도구입니다. 텍스트 내용뿐 아니라 이미지에서 OCR(광학 문자 인식)을 수행한 결과도 함께 LLM에 입력되어 더 정확한 분류를 도출합니다.

## 주요 기능
- CSV에서 크롤링된 데이터 로드 (제목, 본문내용, 사진 등)

- 이미지가 포함된 경우 OCR 수행 (Tesseract 엔진 사용)

- Gemini API에 프롬프트 전송 → 분류 및 요약 결과 수신

- 결과를 csv로 저장

- 요청에 따른 토큰 사용량(요금 기준) 출력

## 프로젝트 시작
1. 환경 설정
```
GEMINI_API_KEY=your_google_gemini_api_key_here
```
2. 필요 라이브러리 설치
```
pip install -r requirements.txt
```
3. Tesseract 설치
- https://github.com/tesseract-ocr/tesseract<br>
- 설치 후 경로 수정
```
pytesseract.pytesseract.tesseract_cmd = r"C:/Program Files/Tesseract-OCR/tesseract.exe"
```
## 사용 방법
```
python scripts/llm/llm_classify.py
```
- 내부적으로 data/xxx.csv에서 10개의 샘플 데이터를 추출해 처리

- 각 행의 "제목", "본문내용", "사진" 필드를 사용

- 사진 필드는 ;로 구분된 다중 이미지 경로 지원

- OCR 및 LLM 분류 결과를 CSV로 저장

## 주의사항
- OCR 처리 중 image not found, OCR 실패 등이 발생할 수 있으므로 이미지 경로 확인 필수

- 응답 포맷은 백틱(```)으로 감싸진 JSON 형식이므로 파싱에 실패할 경우 무시

- 토큰 수 초과 시 API 에러가 발생할 수 있으므로 입력 길이 주의
