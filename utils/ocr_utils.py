
import re
import requests
from io import BytesIO
from dotenv import load_dotenv
import urllib.parse
import os
import time
from azure.cognitiveservices.vision.computervision import ComputerVisionClient
from azure.cognitiveservices.vision.computervision.models import OperationStatusCodes
from msrest.authentication import CognitiveServicesCredentials

load_dotenv()
subscription_key = os.getenv("VISION_KEY")
endpoint = os.getenv("VISION_ENDPOINT")
computervision_client = ComputerVisionClient(endpoint, CognitiveServicesCredentials(subscription_key))

def extract_text_from_images(image_urls: list[str], use_stream: bool = False) -> str:
    ocr_texts = []

    for url in image_urls:
        try:
            if use_stream:
                # 비공개 Blob: 직접 다운로드 + stream 처리
                response = requests.get(url)
                response.raise_for_status()
                image_stream = BytesIO(response.content)
                read_response = computervision_client.read_in_stream(image_stream, raw=True)
            else:
                # 공개 Blob: URL 직접 전달
                # 퍼센트 인코딩 적용
                decoded_url = urllib.parse.unquote(url)
                encoded_url = urllib.parse.quote(decoded_url, safe=":/")
                read_response = computervision_client.read(encoded_url, raw=True)

            read_operation_location = read_response.headers["Operation-Location"]
            operation_id = read_operation_location.split("/")[-1]

            while True: 
                read_result = computervision_client.get_read_result(operation_id)
                if read_result.status not in ['notStarted', 'running']:
                    break
                time.sleep(1)

            if read_result.status == OperationStatusCodes.succeeded:
                for text_result in read_result.analyze_result.read_results:
                    for line in text_result.lines:
                        ocr_texts.append(line.text.strip())
            else:
                print(f"[OCR FAILED] {url} - Status: {read_result.status}")

        except Exception as e:
            print(f"[OCR ERROR] {url} - {e.__class__.__name__}: {e}")

    return "\n".join(ocr_texts)

def clean_ocr_text(text: str) -> str:
    # 줄바꿈, 탭 제거 → 공백으로 치환
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    # 연속된 공백 → 하나로 축소
    text = re.sub(r'\s{2,}', ' ', text)
    # 앞뒤 공백 제거
    return text.strip()



