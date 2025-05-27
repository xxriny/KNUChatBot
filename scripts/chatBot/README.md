# ChatBot
KNU CHATBOT 카카오 챗봇 연동 및 실행

# ngkrok 설치하기
Linux 기준

```
brew install ngrok/ngrok/ngrok
```
windows 기준
```
sudo snap install ngrok
```
## ngrok 인증 토큰 등록

- ngrok 대시보드 로그인 후 토큰 발급 후 복사
```
ngrok config add-authtoken <YOUR_AUTH_TOKEN>
```
- ngrok http 5000 으로 외부 접속 주소 생성
- chat_server_beta.py 실행
