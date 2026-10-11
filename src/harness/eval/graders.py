"""LLM-as-judge graders. Each uses a Judge behind a Protocol, so the real judge
(a model call) and a fake judge (for tests) are interchangeable."""

from typing import Protocol

class Judge(Protocol):
    async def score(self, rubric: str, payload: str)->tuple[float, str]:...

async def grade_correctness(judge: Judge, question: str, answer: str, reference:str)->tuple[float, str]:
    rubric = ("Score 0.0-1.0 how well the candidate answer matches the reference answer. Judge the meaning, "
              "not the wording: extra correct detail or a cited source is fine; a missing or wrong fact is not.")
    payload = f"Question:\n{question}\n\nReference answer:\n{reference}\n\nCandidate answer:\n{answer}"
    return await judge.score(rubric, payload)
    
async def grade_faithfulness(judge: Judge, answer: str, context: str)->tuple[float, str]:
    rubric = ("Score 0.0-1.0 whether EVERY claim in the answer is supported by the context. "
        "1.0 = fully grounded, 0.0 = contains unsupported claims (hallucination).")
    payload = f"Context {context}\n Answer:\n {answer}"
    return await judge.score(rubric, payload)
