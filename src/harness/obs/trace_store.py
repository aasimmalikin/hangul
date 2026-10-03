from collections import deque
from harness.obs.tracing import Trace, cost_usd

class TraceStore:
    def __init__(self, maxlen:int = 200)->None:
        self._traces: deque = deque(maxlen=maxlen)
    
    def add(self, trace:Trace, model:str)->None:
        s = trace.summary()
        s["cost_usd"] = cost_usd(model, s["input_tokens"], s["output_tokens"], s.get("cached_input_tokens", 0))
        self._traces.append(s)
    
    def recent(self, n:int = 20)-> list[dict]:
        return list(self._traces)[-n:][::-1]
    
    def metrics(self) -> dict:
        if not self._traces:
            return {"runs": 0}
        n = len(self._traces)
        return {
            "runs": n,
            "avg_latency_ms": round(sum(t["total_ms"] for t in self._traces) / n, 1),
            "avg_cost_usd": round(sum(t["cost_usd"] for t in self._traces) / n, 6),
            "total_cost_usd": round(sum(t["cost_usd"] for t in self._traces), 6),
            "avg_tool_calls": round(sum(t["tool_calls"] for t in self._traces) / n, 2),
            "error_rate": round(sum(1 for t in self._traces if t["errors"]) / n, 3),
        } 