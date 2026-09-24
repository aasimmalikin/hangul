import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field

from harness.vault.redact import redactor

@dataclass
class Span:
    name: str
    span_id: str
    start: float
    end: float | None = None
    attributes: dict = field(default_factory = dict)
    status: str = "ok"

    @property
    def duration_ms(self)->float:
        return round(((self.end or time.time())-self.start)*1000, 1)

@dataclass
class Trace:
    trace_id: str
    spans: list[Span] = field(default_factory = list)

    @contextmanager
    def span(self, name:str, **attributes):
        s = Span(name = name, span_id = uuid.uuid4().hex[:8], start = time.time(),
                 attributes = redactor.scrub(dict(attributes)))
        self.spans.append(s)
        try:
            yield s
        except Exception:
            s.status = "Error"
            s.end = time.time()
            raise
        else:
            s.end = time.time()
        
    def summary(self)->dict:
        model_spans = [s for s in self.spans if s.name =="gen_ai.chat"]
        tool_spans = [s for s in self.spans if s.name =="gen_ai.tool.execute"]
        return {
            "trace_id": self.trace_id,
            "total_ms": round(sum(s.duration_ms for s in self.spans if s.name =="agent.run"),1),
            "model_calls": len(model_spans),
            "tool_calls": len(tool_spans),
            "input_tokens": sum(s.attributes.get("gen_ai.usage.input_tokens", 0)for s in model_spans),
            "output_tokens": sum(s.attributes.get("gen_ai.usage.output_tokens", 0)for s in model_spans),
            "errors": [s.name for s in self.spans if s.status == "error"]

        }

def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Dollar cost of a run, priced from providers.registry (unknown model → 0)."""
    # Imported here: registry pulls in config, and tracing must stay import-light.
    from harness.providers.registry import get_model
    from harness.logging import log

    spec = get_model(model)
    if spec is None:
        log.warning("no pricing for model; cost recorded as 0", model=model)
        return 0.0
    return round(input_tokens / 1_000_000 * spec.input_usd_per_m
                 + output_tokens / 1_000_000 * spec.output_usd_per_m, 6)


