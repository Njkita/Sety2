import time
import random
from typing import List
import httpx
from dataclasses import dataclass, field


@dataclass
class Backend:
    name: str
    url: str  # http://service:8000
    failures: int = 0
    last_failure: float = 0.0
    circuit_open_until: float = 0.0
    alive: bool = True

    def is_available(self) -> bool:
        now = time.time()
        if self.circuit_open_until > now:
            return False
        return self.alive

    def record_failure(self):
        now = time.time()
        self.failures += 1
        self.last_failure = now
        self.alive = False
        if self.failures >= 3:
            self.circuit_open_until = now + 10

    def record_success(self):
        self.failures = 0
        self.alive = True
        self.circuit_open_until = 0.0


class BackendPool:
    def __init__(self, backends: List[Backend]):
        self.backends = backends
        self._rr_index = 0

    def pick_backend(self) -> Backend | None:
        alive = [b for b in self.backends if b.is_available()]
        if not alive:
            return None
        b = alive[self._rr_index % len(alive)]
        self._rr_index += 1
        return b

    async def health_check_loop(self):
        async with httpx.AsyncClient(timeout=1.0) as client:
            while True:
                for b in self.backends:
                    try:
                        r = await client.get(f"{b.url}/health")
                        if r.status_code == 200:
                            b.record_success()
                        else:
                            b.record_failure()
                    except Exception:
                        b.record_failure()
                await asyncio.sleep(2.0)


import asyncio
