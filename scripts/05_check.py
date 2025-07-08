import pandas as pd
import numpy as np # numpy 라이브러리 불러오기

# 1. 레이블링된 데이터 로드
try:
    df = pd.read_csv('data/sample_with_all_scores.csv')
except FileNotFoundError:
    print("❌ 'data/sample_with_all_scores.csv' 파일을 찾을 수 없습니다.")
    exit()

# --- 2. 테스트할 임계값 목록 (0.01 단위로 생성) ---
COSINE_THRESHOLDS = np.arange(0.80, 0.96, 0.01)  # 0.80부터 0.95까지 0.01 간격
SEQ_THRESHOLDS = np.arange(0.80, 0.91, 0.01)   # 0.80부터 0.90까지 0.01 간격

results = []

# --- 3. 모든 조합에 대해 테스트 실행 ---
# (이하 로직은 이전과 동일)
for cos_thresh in COSINE_THRESHOLDS:
    for seq_thresh in SEQ_THRESHOLDS:
        def predict(row):
            if row['cos_score'] >= cos_thresh and row['seq_score'] >= seq_thresh:
                return 'duplication'
            else:
                return 'not_duplicate'
        df['predicted_label'] = df.apply(predict, axis=1)

        actual_duplicates = df[df['label'] == 'duplication']
        predicted_duplicates = df[df['predicted_label'] == 'duplication']
        true_positives = predicted_duplicates[predicted_duplicates['label'] == 'duplication']

        recall = len(true_positives) / len(actual_duplicates) if len(actual_duplicates) > 0 else 0
        precision = len(true_positives) / len(predicted_duplicates) if len(predicted_duplicates) > 0 else 0
        
        results.append({
            'cos_threshold': round(cos_thresh, 2), # 소수점 2자리로 반올림
            'seq_threshold': round(seq_thresh, 2),
            'precision': precision,
            'recall': recall
        })

# --- 4. 최종 결과 출력 ---
if results:
    results_df = pd.DataFrame(results)
    sorted_results = results_df.sort_values(by=['precision', 'recall'], ascending=False)
    
    print("--- 임계값 조합별 성능 테스트 결과 ---")
    # 정밀도가 95% 이상인 결과만 필터링해서 보기
    high_precision_results = sorted_results[sorted_results['precision'] >= 0.95]
    print(high_precision_results.to_string())
else:
    print("테스트를 실행할 수 없습니다.")