# ChatBot
강원대학교 챗봇 서비스
공모전, 학사 일정, 비교과 활동 등의 정보를 제공

## 프로젝트 시작
Linux 기준 ngrok 설치
```
brew install ngrok/ngrok/ngrok
```
windows 기준 ngrok 설치
```
sudo snap install ngrok
```
## ngrok 인증 토큰 등록

- ngrok 대시보드 로그인 후 토큰 발급 후 복사
```
ngrok config add-authtoken <YOUR_AUTH_TOKEN>
```
## 사용 방법
- chat_server_beta.py 실행
- default port 5000
- ngrok http 5000 으로 외부 접속 주소 생성
- 카카오 i 오픈빌더와 연동하여 챗봇 서비스 시작
