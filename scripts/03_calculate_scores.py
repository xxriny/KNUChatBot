# deduplication/scripts/03_calculate_scores.py

import pandas as pd
import os
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from tqdm import tqdm

tqdm.pandas(desc="Pandas 작업")

# --- 설정 ---
DATA_FOLDER = 'data'
INPUT_SAMPLE_CSV = 'sample_for_labeling.csv' # ◀◀ 2단계에서 만든 샘플 파일
ORIGINAL_CSV = '강원대 통합 공지사항 크롤링.csv'
OUTPUT_CSV = 'sample_with_all_scores.csv' # ◀◀ 모든 점수가 추가된 새 파일

# --- 함수 ---
def preprocess_text(text):
    if not isinstance(text, str): return ""
    text = text.lower()
    text = re.sub(r'[^\w\s]', '', text)
    text = ' '.join(text.split())
    return text

def calculate_jaccard(texts):
    set1 = set(texts['제목1_정규화'].split())
    set2 = set(texts['제목2_정규화'].split())
    intersection = len(set1.intersection(set2))
    union = len(set1.union(set2))
    return intersection / union if union != 0 else 0

# --- 메인 실행 ---
if __name__ == "__main__":
    input_path = os.path.join(DATA_FOLDER, INPUT_SAMPLE_CSV)
    original_path = os.path.join(DATA_FOLDER, ORIGINAL_CSV)
    output_path = os.path.join(DATA_FOLDER, OUTPUT_CSV)

    try:
        sample_df = pd.read_csv(input_path)
        original_df = pd.read_csv(original_path)
        print(f"✅ 파일 로드 완료: {input_path}, {original_path}")

        # 텍스트 정규화
        sample_df['제목1_정규화'] = sample_df['제목1'].progress_apply(preprocess_text)
        sample_df['제목2_정규화'] = sample_df['제목2'].progress_apply(preprocess_text)
        
        # 자카드 및 코사인 유사도 계산
        print("\n--- 🚀 자카드 & 코사인 유사도 계산 중 ---")
        sample_df['jac_score'] = sample_df.progress_apply(calculate_jaccard, axis=1)

        all_titles = original_df['제목'].dropna().unique()
        vectorizer = TfidfVectorizer(preprocessor=preprocess_text)
        vectorizer.fit(all_titles)

        vec1 = vectorizer.transform(sample_df['제목1'])
        vec2 = vectorizer.transform(sample_df['제목2'])
        cos_sims = [cosine_similarity(v1, v2)[0][0] for v1, v2 in tqdm(zip(vec1, vec2), total=len(sample_df), desc="코사인 유사도")]
        sample_df['cos_score'] = cos_sims

        # 분석에 필요한 컬럼만 선택 (label 컬럼은 이제 없음)
        final_df = sample_df[['제목1', '제목2', 'seq_score', 'jac_score', 'cos_score']]
        
        # 새 파일로 저장
        final_df.to_csv(output_path, index=False, encoding='utf-8-sig')
        
        print(f"\n✅ 모든 유사도 점수 계산 완료! '{output_path}'에 저장했습니다.")
        print("\n▶ 다음 단계: 이제 새로 생성된 이 파일에 'label' 컬럼과 'unrelated' 데이터를 추가해주세요.")

    except FileNotFoundError as e:
        print(f"❌ 오류: 필요한 파일을 찾을 수 없습니다 - {e.filename}")
    except Exception as e:
        print(f"❌ 오류 발생: {e}")