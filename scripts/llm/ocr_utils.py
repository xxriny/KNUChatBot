
import pytesseract
import re
from PIL import Image
import os
from scripts.llm.config import IMAGE_DIR

pytesseract.pytesseract.tesseract_cmd = r"C:/Program Files/Tesseract-OCR/tesseract.exe"
custom_config = r'--oem 3 --psm 6 -l kor+eng'
# pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"
# custom_config = r'--oem 3 --psm 6 -l kor+eng'

def extract_text_from_images(image_paths):
    ocr_texts = []
    for image_path in image_paths:
        image_path = image_path.replace("/", os.sep).replace("\\", os.sep)
        full_image_path = IMAGE_DIR / image_path
        
        if full_image_path.exists():
            try:
                image = Image.open(full_image_path)
                text = pytesseract.image_to_string(image, config=custom_config)
                ocr_texts.append(text.strip())
            except Exception as e:
                print(f"[OCR ERROR] {image_path} - {e}")
        else:
            print(f"[IMAGE NOT FOUND] {image_path}")
    return "\n".join(ocr_texts)

def clean_ocr_text(text: str) -> str:
    # 줄바꿈, 탭 제거 → 공백으로 치환
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    # 연속된 공백 → 하나로 축소
    text = re.sub(r'\s{2,}', ' ', text)
    # 앞뒤 공백 제거
    return text.strip()



