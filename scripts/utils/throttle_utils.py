import threading
import time
from typing import Optional
from contextlib import contextmanager

__all__ = ["TokenBucket", "Throttler"]

class TokenBucket:
    """
    간단한 토큰 버킷 레이트 리미터.
    - rate_per_sec: 초당 충전 속도(토큰/초)
    - capacity: 최대 보유 토큰 수(기본=rate_per_sec)
    사용:
        bucket = TokenBucket(rate_per_sec=2, capacity=5)
        bucket.wait()  # 1토큰 확보까지 블로킹
    """
    def __init__(self, rate_per_sec: float, capacity: Optional[float] = None):
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be > 0")
        self.rate = float(rate_per_sec)
        self.capacity = float(capacity) if capacity is not None else float(rate_per_sec)
        self.tokens = self.capacity
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        delta = now - self.updated
        if delta <= 0:
            return
        self.updated = now
        self.tokens = min(self.capacity, self.tokens + delta * self.rate)

    def consume(self, tokens: float = 1.0, block: bool = True, timeout: Optional[float] = None) -> bool:
        if tokens <= 0:
            return True
        end = None if timeout is None else time.monotonic() + timeout
        while True:
            with self.lock:
                self._refill()
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True

            if not block:
                return False

            with self.lock:
                needed = max(tokens - self.tokens, 0.0)
            sleep_for = max(needed / self.rate, 0.001)

            if end is not None:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    return False
                sleep_for = min(sleep_for, max(remaining, 0.001))

            time.sleep(sleep_for)

    def acquire(self, tokens: float = 1.0) -> None:
        """tokens만큼 확보될 때까지 블로킹."""
        self.consume(tokens=tokens, block=True)

class Throttler: 
    """
    속도(rps) + 동시성(concurrncy) 제한을 함께 적용하는 통합 가드
    - rps: 초당 시작 허용량
    - burst: 버스트 (capacity)
    - concurrency: 동시에 진행 가능한 작업 수 (None이면 제한 없음)
    """
    def __init__(self, rps: float, *, burst: Optional[float] = None, concurrency: Optional[int] = None):
        self.bucket = TokenBucket(rate_per_sec=rps, capacity=burst)
        self.sem = threading.BoundedSemaphore(concurrency) if concurrency > 0 else None

    @contextmanager
    def slot(self, tokens: float = 1.0):
        if self.sem:
            self.sem.acquire() # 동시성 자리 확보 (없으면 대기)
        try:
            self.bucket.acquire(tokens) # 시작 속도 허가 받을 때까지 대기
            yield
        finally:
            if self.sem:
                self.sem.release() # 끝났으니 자리 반환
    
    def run(self, fn, *args, tokens: float = 1.0, **kwargs):
        with self.slot(tokens=tokens):
            return fn(*args, **kwargs)
