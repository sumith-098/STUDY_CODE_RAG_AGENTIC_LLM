# StudyPilot AI v0.2

React + Vite · FastAPI · Gemini (free tier) · ChromaDB RAG · SQLite memory · **multi-agent orchestrator**

## Run (Windows)

Backend:
```bash
cd backend
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # phir .env me GEMINI_API_KEY daalo
uvicorn app.main:app --reload --port 8000
```
Frontend (naya terminal):
```bash
cd frontend
npm install
npm run dev
```
Open http://localhost:5173

Pehle ek baar setup check (2 requests lagti hain): `cd backend && python check_setup.py`

Tests (Gemini quota use nahi hota): `cd backend && pip install -r requirements-dev.txt && pytest -q`

## Agents (har ek alag file: backend/app/agents/)

| Agent | LLM call? | Kaam |
|---|---|---|
| orchestrator.py | 1 (JSON) | route chunta hai + search queries banata hai |
| retriever.py | 0 (sirf embedding) | documents se passages laata hai |
| tutor.py | 1-3 | concept samjhata hai (search tool bhi use kar sakta hai) |
| quiz.py | 1 (JSON) | interactive MCQ quiz |
| summarizer.py | 1 | notes/summary |
| planner.py | 1 | study plan |
| math_agent.py | 1-4 | calculator tool se numeric problems |
| verifier.py | 1 (optional) | answer ko documents se cross-check |

Scanned PDF: text na mile to Gemini vision se OCR (max 20 pages, har 4 pages = 1 chat request).
Chat memory: model ko har chat ke last 10 messages dikhte hain (`MAX_HISTORY_MESSAGES`); purani chats sidebar me.

Flow: `pipeline.py` -> orchestrator -> retriever -> specialist -> verifier.
Greeting ("hi", "thanks") par 0 AI calls. Ek turn me max 8 calls (config.py).

## Free tier protection (rate_limiter.py + llm.py)

* Limits (dashboard se): chat 15 RPM / 250K TPM / 500 RPD, embedding 100 RPM / 30K TPM / 1000 RPD.
* Hum real limit ka 80% hi use karte hain (`SAFETY_FACTOR`).
* Minute limit bhari -> backend khud wait karta hai. Din ki limit bhari -> saaf message + kitne ghante baad reset.
* Daily count SQLite me save hota hai (restart par reset nahi), Pacific midnight par reset (Google jaisa).
* Google 429/503 par auto-retry; har error user ke liye friendly Hinglish message.
* Embeddings batch me (32 chunks/request) aur same file dobara upload ho to embedding dobara nahi.
* Per-IP limit: chat 10/min, upload 5/min.

## Kya badalna ho to
Sab `backend/app/config.py` me: models, limits, chunk size, agent temperature/max tokens, verifier on/off.
Models ke ID AI Studio me dikhne wale ID se match hone chahiye (`.env` me override).
