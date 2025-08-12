class LLMError(Exception):
    """LLM 관련 기본 예외 클래스"""
    pass

class LLMCallError(LLMError):
    """LLM API 호출 실패 (ex. 서버 다운, 인증 문제 등)"""
    pass

class LLMTimeoutError(LLMError):
    """LLM 응답 지연 또는 타임아웃"""
    pass

class LLMParseError(LLMError):
    """LLM 응답의 JSON 파싱 실패"""
    def __init__(self, raw_text: str, msg: str = "JSON 파싱 실패"):
        super().__init__(f"{msg}: {raw_text}\n")
        self.raw_text = raw_text