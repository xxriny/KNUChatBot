from flask import Flask, request, jsonify
import pandas as pd

df = pd.read_csv('../../data/icee_crawl.csv') 
df = df.fillna('') 

app = Flask(__name__)

@app.route("/message", methods=["POST"])
def message():
    user_msg = request.json['userRequest']['utterance'].strip()

    result = df[df['본문내용'].str.contains(user_msg, case=False) | df['제목'].str.contains(user_msg, case=False)]

    if not result.empty:
        row = result.iloc[0]
        response_text = f"📌 *{row['제목']}*\n\n📝 {row['본문내용'][:100]}...\n🔗 {row['링크']}"
    else:
        response_text = f"'{user_msg}' 관련 정보를 찾지 못했습니다."

    return jsonify({
        "version": "2.0",
        "template": {
            "outputs": [{"simpleText": {"text": response_text}}]
        }
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
