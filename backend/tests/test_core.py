"""
Tests -- chalane ke liye:  cd backend && pytest -q
Asli Gemini API use NAHI hoti (FakeGateway), isliye quota nahi lagta.
"""
import pytest

from app import config
from app.config import Limits
from app.documents import chunk_text
from app.errors import QuotaExceeded
from app.rate_limiter import QuotaManager, IPLimiter
from app.tools import calculator


def test_calculator_ok_and_safe():
    assert calculator("(12 + 8) / 4") == {"result": 5.0}
    assert "error" in calculator("__import__('os').system('echo hi')")
    assert "error" in calculator("2 ** 999")
    assert "error" in calculator("1/0")


def test_chunking_overlap():
    chunks = chunk_text("a" * 2500, size=1000, overlap=100)
    assert len(chunks) == 3 and all(len(c) <= 1000 for c in chunks)
    with pytest.raises(ValueError):
        chunk_text("x", size=10, overlap=10)


def test_quota_daily_limit_blocks(tmp_path):
    qm = QuotaManager({"chat": Limits(rpm=100, tpm=10_000, rpd=3)}, db_path=tmp_path / "q.db")
    for _ in range(3):
        qm.acquire("chat", 10)
    with pytest.raises(QuotaExceeded) as e:
        qm.acquire("chat", 10)
    assert e.value.retry_after and "limit" in e.value.message.lower()
    assert qm.status()["chat"]["remaining_today"] == 0


def test_quota_minute_limit_waits_or_fails(tmp_path):
    qm = QuotaManager({"chat": Limits(rpm=2, tpm=10_000, rpd=100)}, db_path=tmp_path / "q.db")
    qm.acquire("chat", 10); qm.acquire("chat", 10)
    with pytest.raises(QuotaExceeded):
        qm.acquire("chat", 10, max_wait=0.2)     # 60s wait lagega, 0.2s se zyada nahi ruk sakte


def test_quota_persists_across_restart(tmp_path):
    lim = {"chat": Limits(rpm=100, tpm=10_000, rpd=5)}
    QuotaManager(lim, db_path=tmp_path / "q.db").acquire("chat", 1)
    assert QuotaManager(lim, db_path=tmp_path / "q.db").status()["chat"]["used_today"] == 1


def test_ip_limiter():
    lim = IPLimiter(2, 60)
    lim.check("1.1.1.1"); lim.check("1.1.1.1")
    with pytest.raises(QuotaExceeded):
        lim.check("1.1.1.1")
    lim.check("2.2.2.2")


def test_pipeline_end_to_end(fake):
    from app import vector_store
    from app.pipeline import run_study_turn
    ws = "workspace-test-1"
    r = vector_store.index_file(ws, "n.txt", b"Photosynthesis lets plants make food from light. " * 30)
    assert r["chunks"] > 0 and not r["already_indexed"]
    assert vector_store.index_file(ws, "n.txt", b"Photosynthesis lets plants make food from light. " * 30)["already_indexed"]

    out = run_study_turn(ws, "sess-12345678", "Explain photosynthesis", [])
    assert out["route"] == "tutor" and out["verified"] is True and out["sources"]
    assert fake.calls and len(fake.calls) == 3          # orchestrator + tutor + verifier

    fake.route = "quiz"
    out = run_study_turn(ws, "sess-12345678", "quiz me", [])
    assert len(out["quiz"]) == 3                        # invalid question chhaant diya gaya

    fake.route = "math"
    out = run_study_turn(ws, "sess-12345678", "12 times 3", [])
    assert "36" in out["answer"]

    # dusre workspace ko pehle ka data nahi dikhna chahiye
    assert vector_store.list_documents("workspace-other") == []
    out = run_study_turn("workspace-other", "sess-12345678", "hello there friend", [])
    assert out["sources"] == []


def test_quick_greeting_uses_no_llm(fake):
    from app.pipeline import run_study_turn
    out = run_study_turn("workspace-test-1", "sess-12345678", "hi", [])
    assert out["route"] == "chat" and fake.calls == []


def test_api_friendly_errors(fake):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        h = {"X-Workspace-Id": "workspace-api-test"}
        assert c.get("/api/health").json()["status"] == "ok"
        assert c.get("/api/quota").json()["approx_questions_left"] > 0
        r = c.post("/api/chat", json={"session_id": "sess-12345678", "message": "hi"})
        assert r.status_code == 400 and r.json()["error"]["code"] == "bad_input"   # workspace header nahi
        r = c.post("/api/chat", headers=h, json={"session_id": "sess-12345678", "message": ""})
        assert r.status_code == 422 and "error" in r.json()
        r = c.post("/api/chat", headers=h, json={"session_id": "sess-12345678", "message": "hi"})
        assert r.status_code == 200 and r.json()["route"] == "chat"
        hist = c.get("/api/chat/sess-12345678", headers=h).json()["messages"]
        assert [m["role"] for m in hist] == ["user", "assistant"]
        r = c.post("/api/upload", headers=h, files={"file": ("a.exe", b"x")})
        assert r.status_code == 400
        r = c.post("/api/upload", headers=h, files={"file": ("n.txt", b"Plants need light. " * 40)})
        assert r.status_code == 200 and r.json()["chunks_indexed"] > 0
        assert len(c.get("/api/documents", headers=h).json()["documents"]) == 1


def test_scanned_pdf_uses_ocr_and_chat_list(fake):
    from io import BytesIO
    from pypdf import PdfWriter
    from app import vector_store
    from app.memory import add_message, initialize_memory, list_sessions
    w = PdfWriter(); w.add_blank_page(200, 200); w.add_blank_page(200, 200)   # text-layer wala nahi = "scanned"
    buf = BytesIO(); w.write(buf)
    r = vector_store.index_file("workspace-ocr-1", "scan.pdf", buf.getvalue())
    assert r["chunks"] == 2                                                  # dono pages OCR se mile
    hits = vector_store.search_chunks("workspace-ocr-1", ["gravity"], 5)
    assert {h["page"] for h in hits} == {1, 2}                               # page numbers sahi

    initialize_memory()
    add_message("workspace-ocr-1", "sess-aaaaaaaa", "user", "pehla sawaal gravity ka")
    add_message("workspace-ocr-1", "sess-aaaaaaaa", "assistant", "jawab")
    add_message("workspace-ocr-1", "sess-bbbbbbbb", "user", "doosri chat")
    chats = list_sessions("workspace-ocr-1")
    assert [c["session_id"] for c in chats] == ["sess-bbbbbbbb", "sess-aaaaaaaa"]
    assert chats[1]["title"].startswith("pehla sawaal") and chats[1]["messages"] == 2
