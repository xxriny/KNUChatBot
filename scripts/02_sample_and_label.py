# deduplication/scripts/02_sample_and_label.py

import pandas as pd
import os

# --- 설정 ---
DATA_FOLDER = 'data'
CANDIDATE_CSV = 'candidate_pairs.csv'
OUTPUT_CSV = 'sample_for_labeling.csv'
NUM_SAMPLES = 400

# --- 메인 실행 ---
if __name__ == "__main__":
    candidate_path = os.path.join(DATA_FOLDER, CANDIDATE_CSV)
    output_path = os.path.join(DATA_FOLDER, OUTPUT_CSV)

    try:
        df = pd.read_csv(candidate_path)
        print(f"✅ 후보군 파일 로드 완료: {candidate_path} ({len(df)}개)")

        # 유사도 1.0인 데이터 제외 (수정된 부분)
        ambiguous_df = df[df['seq_score'] < 0.99999] # ◀◀ 1.0 대신 0.99999를 기준으로 필터링
        
        print(f"  - 유사도 1.0에 가까운 값을 제외한 애매한 후보군: {len(ambiguous_df)}개")
        
        # 샘플링
        num_to_sample = min(NUM_SAMPLES, len(ambiguous_df))
        sample_df = ambiguous_df.sample(n=num_to_sample, random_state=42)
        
        sample_df.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"\n✅ 샘플링 완료! {len(sample_df)}개의 샘플을 '{output_path}'에 저장했습니다.")

    except FileNotFoundError:
        print(f"❌ 오류: '{candidate_path}' 파일을 찾을 수 없습니다. 1단계 코드를 먼저 실행해주세요.")
    except Exception as e:
        print(f"❌ 오류 발생: {e}")