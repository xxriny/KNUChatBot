import re
from typing import List
from dotenv import load_dotenv
import os
from azure.ai.vision.imageanalysis import ImageAnalysisClient
from azure.ai.vision.imageanalysis.models import VisualFeatures
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError

from scripts.utils.log_utils import (
    PHASE, init_runtime_logger, capture_exception,
    capture_unhandled_exception, append_failed_index,
    extract_azure_error_fields
)
from scripts.utils.throttle_utils import TokenBucket
from scripts.utils.retry_utils import (
    retry_with_backoff,
    is_retryable_http_error, 
    parse_retry_after,
    jitter
)
from scripts.utils.image_guard import ensure_ocr_safe_bytes

load_dotenv()
key = os.getenv("VISION_KEY")
endpoint = os.getenv("VISION_ENDPOINT")
computervision_client = ImageAnalysisClient(endpoint=endpoint,credential=AzureKeyCredential(key))
logger = init_runtime_logger()

# 무료(F0): 2초당 1건 수준이 안전 → rate=0.5, burst=1 권장
GLOBAL_BUCKET = TokenBucket(rate_per_sec=0.5, capacity=1)

def _analyze_read_bytes(image_bytes: bytes):
    """
    Image Analysis v4는 READ가 **동기**로 동작함.
    비동기 폴링 불필요. 실패 시 HttpResponseError 발생.
    """
    GLOBAL_BUCKET.acquire()  # 전역 QPS 제한
    return computervision_client.analyze(
        image_data=image_bytes,
        visual_features=[VisualFeatures.READ]
    )
    
def _safe_read_once(image_bytes: bytes):
    """
    재시도 래핑: 429/5xx에 대해서만 backoff 재시도.
    """
    def _call():
        return _analyze_read_bytes(image_bytes)
    safe_call = retry_with_backoff(
        func=_call,
        should_retry=is_retryable_http_error,
        base=2.0, factor=2.0, max_delay=32.0, max_retries=5,
        jitter_ratio=0.2,
    )
    return safe_call()

def _flatten_read_result_text(result) -> List[str]:
    """
    v4 결과 파싱: blocks -> lines -> words
    """
    texts: List[str] = []
    if not getattr(result, "read", None) or not getattr(result.read, "blocks", None):
        return texts
    for block in result.read.blocks:
        for line in getattr(block, "lines", []) or []:
            words = [w.text for w in getattr(line, "words", []) or []]
            line_text = " ".join(words).strip()
            if line_text:
                texts.append(line_text)
    return texts


def extract_text_from_images(image_urls: list[str]) -> str:
    """
    여러 이미지 URL에 대해 OCR 수행.
    - 각 URL은 ensure_ocr_safe_bytes로 다운로드/크기제한/포맷보정 후 bytes로 분석
    - 개별 실패는 기록하고 넘어감(파이프라인 지속)
    """
    ocr_texts = []

    for idx, url in enumerate(image_urls or []):
        try:
            # 입력 준비: 안전 바이트로 변환(용량/모드 보정)
            safe_bytes, _ctype = ensure_ocr_safe_bytes(url)

            # READ 호출 (동기) + 재시도
            result = _safe_read_once(safe_bytes)

            # 텍스트 플래튼
            lines = _flatten_read_result_text(result)
            if not lines:
                # 성공이지만 텍스트가 없을 수 있음 → 경고 로그만
                logger.warning(f"[OCR EMPTY] idx={idx} url={url}")
            ocr_texts.extend(lines)

        except HttpResponseError as e:
            # Azure SDK 공통 예외 → 상태/본문 파싱
            status = getattr(e, "status_code", None)
            body = getattr(e, "message", None)
            # 일부 경우 e.response.text가 있을 수 있음
            try:
                resp = getattr(e, "response", None)
                if resp is not None:
                    txt = getattr(resp, "text", None)
                    body = txt() if callable(txt) else (txt or body)
            except Exception:
                pass

            code, msg = extract_azure_error_fields(body)
            capture_exception(
                index=idx, phase=PHASE["OCR"], url=url,
                status_code=status, error_code=code, message=msg or str(e),
                response_body=body
            )
            append_failed_index(idx)
            logger.error(f"OCR HttpError @idx={idx} status={status} code={code} msg={msg}")

        except Exception as e:
            capture_unhandled_exception(index=idx, phase=PHASE["OCR"], url=url, exc=e)
            append_failed_index(idx)
            logger.exception(f"OCR UnknownError @idx={idx}")

    return "\n".join(ocr_texts)

def clean_ocr_text(text: str) -> str:
    # 줄바꿈, 탭 제거 → 공백으로 치환
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    # 연속된 공백 → 하나로 축소
    text = re.sub(r'\s{2,}', ' ', text)
    # 앞뒤 공백 제거
    return text.strip()



