# deduplication/scripts/04_analyze_and_visualize.py

import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import os

# --- 설정 ---
DATA_FOLDER = 'data'
LABELED_DATA_CSV = 'sample_with_all_scores.csv' # ◀◀ 레이블링을 마친 파일

# --- 한글 폰트 설정 ---
try:
    font_path = 'c:/Windows/Fonts/malgun.ttf'
    font_prop = fm.FontProperties(fname=font_path)
    plt.rc('font', family=font_prop.get_name())
except FileNotFoundError:
    print("⚠️ '맑은 고딕' 폰트를 찾을 수 없습니다. 그래프의 한글이 깨질 수 있습니다.")


# --- 메인 실행 ---
if __name__ == "__main__":
    file_path = os.path.join(DATA_FOLDER, LABELED_DATA_CSV)

    try:
        df = pd.read_csv(file_path)
        print(f"✅ '{file_path}' 파일을 성공적으로 불러왔습니다.")

        if 'label' not in df.columns:
            raise ValueError("'label' 컬럼이 파일에 없습니다. 파일에 'label' 컬럼을 추가하고 내용을 채워주세요.")

        # --- 데이터 분포 시각화 ---
        fig, axes = plt.subplots(1, 3, figsize=(18, 6))
        fig.suptitle('레이블 별 유사도 점수 분포', fontsize=16)

        # 각 점수별로 Box Plot 그리기
        sns.boxplot(ax=axes[0], x='label', y='seq_score', data=df, hue='label', legend=False)
        axes[0].set_title('SequenceMatcher Score')

        sns.boxplot(ax=axes[1], x='label', y='jac_score', data=df, hue='label', legend=False)
        axes[1].set_title('Jaccard Score')

        sns.boxplot(ax=axes[2], x='label', y='cos_score', data=df, hue='label', legend=False)
        axes[2].set_title('Cosine Score')

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        
        # 그래프를 파일로 저장
        output_graph_path = os.path.join(DATA_FOLDER, 'similarity_distribution.png')
        plt.savefig(output_graph_path)
        print(f"✅ 분석 그래프를 '{output_graph_path}'에 저장했습니다.")
        
        plt.show() # 화면에도 그래프 표시

    except FileNotFoundError:
        print(f"❌ 오류: '{file_path}' 파일을 찾을 수 없습니다.")
    except Exception as e:
        print(f"❌ 오류가 발생했습니다: {e}")