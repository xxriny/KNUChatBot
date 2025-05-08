from flask import Flask, request, jsonify, send_from_directory
import pandas as pd
import os

app = Flask(__name__)

# csv path image path
CSV_PATH = '../../data/icee_crawl.csv'
IMAGE_FOLDER = os.path.abspath('../../data/images')
NGROK_BASE_URL = 'https://b2ae-210-110-128-79.ngrok-free.app'

df = pd.read_csv(CSV_PATH)
@app.route('/images/<path:filename>')
def serve_image(filename):
    return send_from_directory(IMAGE_FOLDER, filename)

@app.route('/message', methods=['POST'])
def message():
    data = request.get_json()
    utterance = data.get('action', {}).get('params', {}).get('utterance', '').strip()

    matches = df[
        df['제목'].fillna('').str.contains(utterance, case=False, na=False) |
        df['본문내용'].fillna('').str.contains(utterance, case=False, na=False)
    ]

    if matches.empty:
        return jsonify({
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": f"'{utterance}'에 해당하는 정보를 찾을 수 없습니다."
                        }
                    }
                ]
            }
        })

    cards = []
    for _, row in matches.head(3).iterrows():

        title = row['제목']
        description = row['본문내용'][:80] + '...' if pd.notna(row['본문내용']) else '내용 없음'
        link = row['링크']
        raw_path = row['사진']
        if pd.notna(raw_path) and raw_path:
            image_file = os.path.basename(raw_path)
            image_url = f"{NGROK_BASE_URL}/images/{image_file}"
        else:
            image_url = None
        card = {
            "title": title,
            "description": description,
            "thumbnail": {
                "imageUrl": image_url
            } if image_url else {},
            "buttons": [
                {
                    "action": "webLink",
                    "label": "자세히 보기",
                    "webLinkUrl": link
                }
            ]
        }
        cards.append(card)

    return jsonify({
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "carousel": {
                        "type": "basicCard",
                        "items": cards
                    }
                }
            ]
        }
    })

if __name__ == '__main__':
    app.run(port=5000)
