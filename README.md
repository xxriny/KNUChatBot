# KNU-ChatBot
강원대 학생들을 위한 통합 챗본 서비스

## 프로젝트 개요
KNU-ChatBot은 강원대 재학생들이 다양한 교내 정보를 쉽고 빠르게 접근할 수 있도록 설계된 챗봇 기반 서비스입니다. 카카오톡 챗봇을 이용하여, 복잡하게 흩어진 교내 정보들을 쉽게 확인할 수 있도록 정보 시스템을 자동화하였습니다.<br>

KNU-ChatBot is a chatbot-based service designed to help Kangwon National University students easily and quickly access a wide range of campus information.
By utilizing a KakaoTalk chatbot, the system automates the process of collecting and delivering scattered university information in a simple and accessible way.

## 프로젝트 동기
1. 교내의 비교과 프로그램, 공모전, 대외활동, 장학 안내 등 정보가 웹사이트에 흩어져 있습니다.<br>
2. 학생들은 개별 사이트를 방문하며 수집하는 대신 자동화된 KNU-ChatBot을 이용하여 원하는 정보를 얻을 수 있습니다.<br>
3. 정보 접근성이 낮은 신입생, 복학생 등도 쉽게 접근할 수 있도록 정보를 제공합니다.<br>

## Tech Stack
Web Crawling, OPEN API, DataBase, Kakao i Open Builder, Flask, ngrok

## 📁 Directory Structure
```
./
├── 📁 data/<
│ ├── 📄 origin_data.csv
│ └── 📁 images/
│ └── ... (크롤링된 이미지 저장)
├── 📁 scripts/
│ ├── 📁 chatBot/
│ │ └── chat_server.py
│ ├── 📁 crawl/
│ │ ├── all_crawl.py
│ │ └── today_crawl.py
│ └── 📁 llm/
│ ├── llm.py
│ └── prompt.txt
└── 📄 README.md (설치 및 실행 방법 포함)
```

## 프로젝트 시작

```
git clone https://github.com/wheeze01/KNU-ChatBot.git
cd KNU-ChatBot
```
```
pip install -r requirements.txt
```
```
python app.py
```
```
ngrok http 5000
```

## RoadMap
- <strong> Demo</strong> : 기본 기능 구현<br>
- <strong>Demo Ver.1</strong> : 학과별 정보 필터링, 챗봇 디자인<br>
- <strong>Demo Ver.2</strong> : 머신러닝 기반 정보 분류 모델 적용 및 시연<br>
- <strong>Demo Ver.3</strong> : RAG 기반 LLM 챗봇 고도화<br>

## 향후 개선 사항
- 데모 배포 및 버그 발생 시 해결<br>
- 분류 모델과 생성 모델 선정<br>
- 챗봇 고도화