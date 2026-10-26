"""
conftest.py  --  Tests ke liye setup: temp data folder + FAKE Gemini (asli API/quota use nahi hota).
"""
import os
import sys
import tempfile
import hashlib
from pathlib import Path
from types import SimpleNamespace

os.environ["STUDYPILOT_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GEMINI_API_KEY"] = "test-key"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest


def _resp(text=None, function_call=None):
    """Nakli Gemini response banata hai (sirf wo fields jo hamara code padhta hai)."""
    parts = []
    if function_call:
        parts.append(SimpleNamespace(text=None, function_call=function_call))
    if text is not None:
        parts.append(SimpleNamespace(text=text, function_call=None))
    return SimpleNamespace(text=text, candidates=[SimpleNamespace(content=SimpleNamespace(role="model", parts=parts))])


class FakeGateway:
    """Agent ke system_instruction se pehchanta hai ki kaun bol raha hai aur scripted jawab deta hai."""
    def __init__(self):
        self.calls = []
        self.route = "tutor"

    def generate(self, ctx, contents, cfg):
        if ctx is not None:
            ctx.count_llm_call()
        if any(getattr(p, 'inline_data', None) for p in contents[-1].parts):
            return _resp('=== PAGE 1 ===\nScanned notes about gravity.\n=== PAGE 2 ===\nSecond page text.')
        si = cfg.system_instruction or ''
        self.calls.append(si[:30])
        if "Orchestrator" in si:
            import json
            return _resp(json.dumps({"route": self.route, "use_documents": True,
                                     "search_queries": ["photosynthesis"], "quiz_count": 3,
                                     "rationale": "test"}))
        if "Quiz Master" in si:
            import json
            q = {"question": "Q?", "options": ["a", "b", "c", "d"], "correct_index": 1,
                 "explanation": "because", "source": "n.txt p.1"}
            return _resp(json.dumps({"intro": "hi", "questions": [q, {"question": "bad"}, q, q]}))
        if "fact-checker" in si:
            import json
            return _resp(json.dumps({"verdict": "ok", "problems": []}))
        if "Math Solver" in si:
            last = contents[-1].parts[0]
            if getattr(last, "function_response", None) is None and "Ab tools" not in (last.text or ""):
                return _resp(function_call=SimpleNamespace(name="calculator", args={"expression": "12*3"}))
            return _resp("Final answer: 36")
        return _resp("Plants make food using light. (Source: n.txt, p.1)")

    def embed(self, texts, task_type):
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode()).digest()
            out.append([b / 255 for b in h[:16]] * 48)  # 768 dims
        return out


@pytest.fixture()
def fake():
    import app.main  # noqa -- pehle import (wo real gateway banata hai), phir hum fake laga denge
    from app import llm
    from app.rate_limiter import QuotaManager
    from app import config
    fg = FakeGateway()
    fg.quota = QuotaManager(config.safe_limits(), db_path=Path(os.environ["STUDYPILOT_DATA_DIR"]) / "q.db")
    llm.gateway = fg
    llm.quota_manager = fg.quota
    return fg
