import pandas as pd
import os
from difflib import SequenceMatcher
import re
from datetime import timedelta
from tqdm import tqdm

# --- 설정 (수정된 부분) ---
# 'data' 폴더는 프로젝트 최상위 폴더에 있다고 가정합니다.
DATA_FOLDER = 'data'
ORIGINAL_CSV = '강원대 통합 공지사항 크롤링.csv'
OUTPUT_CSV = 'candidate_pairs.csv'

SIMILARITY_THRESHOLD = 0.8
DATE_WINDOW = 3

# --- 함수 ---
def preprocess_text(text):
    if not isinstance(text, str): return ""
    text = text.lower()
    text = re.sub(r'[^\w\s]', '', text)
    text = ' '.join(text.split())
    return text

# --- 메인 실행 ---
if __name__ == "__main__":
    original_path = os.path.join(DATA_FOLDER, ORIGINAL_CSV)
    output_path = os.path.join(DATA_FOLDER, OUTPUT_CSV)

    if not os.path.exists(DATA_FOLDER):
        os.makedirs(DATA_FOLDER)

    try:
        df = pd.read_csv(original_path, encoding='utf-8-sig')
        print(f"✅ 원본 파일 로드 완료: {original_path}")

        df.dropna(subset=['제목', '작성일'], inplace=True)
        df['작성일'] = pd.to_datetime(df['작성일'], errors='coerce')
        df.dropna(subset=['작성일'], inplace=True)
        df = df.sort_values(by='작성일', ascending=False).reset_index(drop=True)
        df['정규화제목'] = df['제목'].apply(preprocess_text)
        print(f"정제 후 전체 공지 수: {len(df)}개")

        candidate_pairs = []
        for i in tqdm(range(len(df)), desc="후보군 추출 중"):
            base_date = df.loc[i, '작성일']
            date_limit = base_date - timedelta(days=DATE_WINDOW)
            for j in range(i + 1, len(df)):
                if df.loc[j, '작성일'] < date_limit:
                    break
                
                similarity = SequenceMatcher(None, df.loc[i, '정규화제목'], df.loc[j, '정규화제목']).ratio()
                if similarity >= SIMILARITY_THRESHOLD:
                    candidate_pairs.append({
                        '제목1': df.loc[i, '제목'],
                        '제목2': df.loc[j, '제목'],
                        'seq_score': similarity
                    })
        
        candidate_df = pd.DataFrame(candidate_pairs)
        candidate_df.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"\n✅ 후보군 추출 완료! {len(candidate_df)}개의 쌍을 '{output_path}'에 저장했습니다.")

    except FileNotFoundError:
        print(f"❌ 오류: '{original_path}' 파일을 찾을 수 없습니다.")
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
    