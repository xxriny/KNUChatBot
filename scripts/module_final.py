import pandas as pd
import re
from difflib import SequenceMatcher
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.feature_extraction.text import TfidfVectorizer
from datetime import timedelta
from tqdm import tqdm

# --- 내부 전용 함수 ---
def _preprocess_text(text):
    """텍스트를 소문자화하고 특수문자를 제거하는 등 전처리합니다."""
    if not isinstance(text, str): return ""
    text = text.lower()
    text = re.sub(r'[^\w\s]', '', text)
    text = ' '.join(text.split())
    return text

def _is_duplicate(title1, title2, vectorizer_model):
    """두 제목의 유사도를 측정하여 중복 여부를 판단합니다."""
    processed_title1 = _preprocess_text(title1)
    processed_title2 = _preprocess_text(title2)
    
    # 1. 문자열 순서 기반 유사도 측정
    seq_score = SequenceMatcher(None, processed_title1, processed_title2).ratio()
    if seq_score < 0.8: # 임계값 미만이면 바로 False 반환 (성능 최적화)
        return False

    # 2. 단어 벡터 기반 유사도 측정 (TF-IDF & Cosine Similarity)
    vec1 = vectorizer_model.transform([processed_title1])
    vec2 = vectorizer_model.transform([processed_title2])
    cos_score = cosine_similarity(vec1, vec2)[0][0]
    
    # 최종 규칙: 두 유사도 점수가 모두 높을 때만 중복으로 판단
    if cos_score >= 0.80 and seq_score >= 0.90:
        return True
    else:
        return False

# --- 메인 함수 (외부 호출용) ---
def run_deduplication(crawled_df):
    """
    크롤링된 데이터프레임을 받아 중복을 제거하고, 깨끗한 데이터프레임을 반환합니다.
    이 버전은 외부 모델 파일 없이, 입력된 데이터로 직접 TF-IDF 모델을 학습하여 사용합니다.

    :param crawled_df: '제목'과 '작성일' 컬럼이 포함된 pandas 데이터프레임
    :return: 중복이 제거된 pandas 데이터프레임
    """
    # 1. 데이터 정제
    df = crawled_df.copy()
    df.dropna(subset=['제목', '작성일'], inplace=True)
    df['작성일'] = pd.to_datetime(df['작성일'], errors='coerce')
    df.dropna(subset=['작성일'], inplace=True)
    df = df.sort_values(by='작성일', ascending=False).reset_index(drop=True)

    original_count = len(df)
    
    # 2. TF-IDF 벡터화 모델 학습
    print("➡️  입력된 데이터로 중복 제거 모델을 실시간으로 학습합니다...")
    vectorizer = TfidfVectorizer()
    vectorizer.fit(df['제목'].apply(_preprocess_text))
    print("✅ 모델 학습 완료.")
    
    # 3. 중복 제거 실행
    indices_to_remove = set()
    for i in tqdm(range(len(df)), desc="중복 제거 작업 중"):
        if i in indices_to_remove:
            continue
        for j in range(i + 1, len(df)):
            if j in indices_to_remove:
                continue
            
            # 날짜 차이가 3일 이상이면 더 이상 비교하지 않음 (효율성)
            if (df.loc[i, '작성일'] - df.loc[j, '작성일']) > timedelta(days=3):
                break
                
            if _is_duplicate(df.loc[i, '제목'], df.loc[j, '제목'], vectorizer):
                indices_to_remove.add(j)
    
    unique_df = df.drop(index=list(indices_to_remove))
    
    # 4. 결과 요약 출력
    removed_count = original_count - len(unique_df)
    print("\n--- ✨ 중복 제거 완료 ✨ ---")
    print(f"처리 전 데이터: {original_count}개")
    print(f"제거된 중복 데이터: {removed_count}개")
    print(f"최종 데이터: {len(unique_df)}개")
    
    return unique_df