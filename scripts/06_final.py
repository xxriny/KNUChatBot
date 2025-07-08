import pandas as pd
import os
import re
from difflib import SequenceMatcher
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from datetime import timedelta
from tqdm import tqdm

# --- 1. 텍스트 전처리 함수 ---
def preprocess_text(text):
    if not isinstance(text, str): return ""
    text = text.lower()
    text = re.sub(r'[^\w\s]', '', text)
    text = ' '.join(text.split())
    return text

# --- 2. 최종 앙상블 모델 함수 ---
def is_duplicate(title1, title2, vectorizer_model, cos_thresh, seq_thresh):
    """ 두 제목의 중복 여부를 최종 규칙에 따라 판단합니다. """
    processed_title1 = preprocess_text(title1)
    processed_title2 = preprocess_text(title2)
    
    seq_score = SequenceMatcher(None, processed_title1, processed_title2).ratio()
    
    # 코사인 점수가 임계값보다 낮으면, 시퀀스 점수를 계산할 필요 없이 바로 False 반환 (최적화)
    if seq_score < seq_thresh:
        return False

    vec1 = vectorizer_model.transform([processed_title1])
    vec2 = vectorizer_model.transform([processed_title2])
    cos_score = cosine_similarity(vec1, vec2)[0][0]
    
    if cos_score >= cos_thresh and seq_score >= seq_thresh:
        return True
    else:
        return False

# ======================================================================
# ## 🚀 메인 실행 부분
# ======================================================================
if __name__ == "__main__":
    
    # --- 설정 ---
    DATA_FOLDER = 'data'
    INPUT_CSV = '강원대 통합 공지사항 크롤링.csv'
    OUTPUT_CSV = 'unique_announcements.csv' # 중복 제거 후 저장될 파일 이름

    # 우리가 찾은 최종 임계값
    COSINE_THRESHOLD = 0.80
    SEQ_THRESHOLD = 0.90
    
    # 비교할 날짜 범위
    DATE_WINDOW = 3

    input_path = os.path.join(DATA_FOLDER, INPUT_CSV)
    output_path = os.path.join(DATA_FOLDER, OUTPUT_CSV)

    try:
        # 1. 원본 데이터 로드 및 정제
        df = pd.read_csv(input_path, encoding='utf-8-sig')
        df.dropna(subset=['제목', '작성일'], inplace=True)
        df['작성일'] = pd.to_datetime(df['작성일'], errors='coerce')
        df.dropna(subset=['작성일'], inplace=True)
        df = df.sort_values(by='작성일', ascending=False).reset_index(drop=True)
        
        original_count = len(df)
        print(f"✅ 원본 데이터 로드 완료: 총 {original_count}개")

        # 2. 모델 준비 (TF-IDF 벡터화기 학습)
        print("--- 모델을 준비하는 중입니다... ---")
        all_titles = df['제목'].dropna().unique()
        vectorizer = TfidfVectorizer(preprocessor=preprocess_text)
        vectorizer.fit(all_titles)
        print("✅ 모델 준비 완료.")

        # 3. 중복 제거 실행
        indices_to_remove = set()
        for i in tqdm(range(len(df)), desc="중복 제거 작업 진행 중"):
            if i in indices_to_remove:
                continue

            base_title = df.loc[i, '제목']
            base_date = df.loc[i, '작성일']
            date_limit = base_date - timedelta(days=DATE_WINDOW)

            for j in range(i + 1, len(df)):
                if df.loc[j, '작성일'] < date_limit:
                    break
                
                if j in indices_to_remove:
                    continue
                
                compare_title = df.loc[j, '제목']
                
                # is_duplicate 함수로 중복 여부 판단
                if is_duplicate(base_title, compare_title, vectorizer, COSINE_THRESHOLD, SEQ_THRESHOLD):
                    indices_to_remove.add(j) # 중복이면 제거 목록에 추가 (더 오래된 것을 제거)
        
        # 4. 중복 데이터 제거 및 결과 저장
        unique_df = df.drop(index=list(indices_to_remove))
        unique_df.to_csv(output_path, index=False, encoding='utf-8-sig')
        
        # 5. 최종 결과 요약 출력
        final_count = len(unique_df)
        removed_count = original_count - final_count
        
        print("\n--- ✨ 최종 결과 ✨ ---")
        print(f"원본 데이터: {original_count}개")
        print(f"중복으로 판단되어 제거된 데이터: {removed_count}개")
        print(f"최종 데이터: {final_count}개")
        print(f"✅ 중복 제거된 결과가 '{output_path}'에 저장되었습니다.")

    except FileNotFoundError:
        print(f"❌ 오류: '{input_path}' 파일을 찾을 수 없습니다.")
    except Exception as e:
        print(f"❌ 오류가 발생했습니다: {e}")