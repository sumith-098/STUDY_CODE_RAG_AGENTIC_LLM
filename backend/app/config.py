"""
config.py  --  Poore backend ki saari settings EK jagah.

Kuch bhi badalna ho (model, limits, chunk size) to sirf yahi file edit karo.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# backend/.env ko hamesha load karo, chahe uvicorn kisi bhi folder se chale.
BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# ---------------------------------------------------------------- MODELS
# Tumhare dashboard me "Gemini 3.1 Flash Lite" aur "Gemini Embedding 1" use hue hain,
# isliye defaults wahi hain. Embedding 1 ka API ID "gemini-embedding-001" hota hai.
# Agar AI Studio me ID alag dikhe to .env me override karo.
CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.1-flash-lite")
EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
# Embedding vector ki length. 768 chhota hai -> storage kam, search tez, quality achhi.
EMBEDDING_DIMENSIONS = 768

# ---------------------------------------------------------------- PATHS
# STUDYPILOT_DATA_DIR sirf tests ke liye (alag temp folder); normal use me backend/data/
DATA_DIR = Path(os.getenv("STUDYPILOT_DATA_DIR", str(BACKEND_DIR / "data")))
CHROMA_DIR = DATA_DIR / "chroma"
SQLITE_PATH = DATA_DIR / "studypilot.sqlite3"
PROJECTS_DIR = DATA_DIR / "projects"   # Code Studio ke projects yahan banenge (sirf isi folder ke andar)

# ---------------------------------------------------------------- FREE TIER LIMITS
@dataclass(frozen=True)
class Limits:
    """Ek model-bucket ki limits: RPM = requests/minute, TPM = tokens/minute, RPD = requests/day."""
    rpm: int
    tpm: int
    rpd: int

# Google dashboard (screenshot) ke real free-tier numbers:
#   Gemini 3.1 Flash Lite : 15 RPM, 250K TPM, 500 RPD
#   Gemini Embedding 1    : 100 RPM, 30K TPM, 1000 RPD
REAL_LIMITS = {
    "chat": Limits(rpm=15, tpm=250_000, rpd=500),
    "embed": Limits(rpm=100, tpm=30_000, rpd=1_000),
}
# Real limit ka sirf 80% use karte hain, taaki Google kabhi 429 error na de
# (token count hamara andaza hota hai, exact nahi).
SAFETY_FACTOR = 0.8

def safe_limits() -> dict[str, Limits]:
    """Returns: {'chat': Limits, 'embed': Limits} -- SAFETY_FACTOR laga hua version."""
    return {
        name: Limits(
            rpm=max(1, int(l.rpm * SAFETY_FACTOR)),
            tpm=max(1, int(l.tpm * SAFETY_FACTOR)),
            rpd=max(1, int(l.rpd * SAFETY_FACTOR)),
        )
        for name, l in REAL_LIMITS.items()
    }

# Ek chat turn me average itne LLM calls lagte hain (orchestrator + specialist + verifier).
# Sirf UI me "approx questions left" dikhane ke liye use hota hai.
AVG_LLM_CALLS_PER_TURN = 3.5
# Limiter max kitni der wait karega (seconds) jab minute-limit bhar jaye.
MAX_WAIT_CHAT_SECONDS = 25
MAX_WAIT_EMBED_SECONDS = 75   # embed TPM window 60s ka hai, isliye zyada wait

# Per-IP limit (ek user poora quota na kha jaye): (max events, window seconds)
IP_LIMIT_CHAT = (10, 60)
IP_LIMIT_UPLOAD = (5, 60)
IP_LIMIT_CODE = (6, 60)          # Code Studio: 1 minute me max 6 plan/build requests

# ---------------------------------------------------------------- AGENT BEHAVIOUR
MAX_LLM_CALLS_PER_TURN = 8      # ek question par hard ceiling
MAX_HISTORY_MESSAGES = 10       # kitni purani chat model ko dikhani hai
ENABLE_VERIFIER = True          # answer ko documents se cross-check karne wala agent
VERIFIER_MIN_DAILY_REMAINING = 0.25   # quota 25% se kam bacha to verifier skip (calls bachao)
RETRIEVAL_MAX_DISTANCE = 0.80   # cosine distance; isse zyada door wale passages ignore
                                # (agar kuch na mile to 0.9 karke dekho)

# ---------------------------------------------------------------- DOCUMENTS
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
EMBED_BATCH_SIZE = 32                  # ek embed request me kitne chunks
OCR_ENABLED = True               # scanned PDF (sirf images) ko Gemini se padhwana
OCR_MAX_PAGES = 20               # isse bada scanned PDF reject (har 4 pages = 1 chat request)
OCR_PAGES_PER_REQUEST = 4        # ek Gemini request me kitne pages
MAX_EMBED_TOKENS_PER_UPLOAD = 60_000   # ~100 pages; isse bada doc free tier me bahut der lega

# ---------------------------------------------------------------- CODE STUDIO
CODE_MAX_LLM_CALLS = 14               # ek build me max Gemini calls (planner alag, ye coder+reviewer ke liye)
CODE_MIN_QUOTA_TO_START = 8           # aaj ke chat requests isse kam bache to build shuru hi nahi hoga
CODE_MAX_FILES = 25                   # ek project me max files
CODE_MAX_FILE_BYTES = 60_000          # ek file max ~60 KB
CODE_MAX_PROJECT_BYTES = 400_000      # poora project max ~400 KB
CODE_MAX_WRITES_PER_JOB = 40          # ek build me max file-write operations (loop se bachne ke liye)
CODE_SNAPSHOT_BYTES = 40_000          # agent ko existing code dikhane ki max size
# Sirf ye extensions allowed (exe, bat, sh, ps1 jaisi chalne wali files nahi):
CODE_ALLOWED_EXTENSIONS = {".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".json", ".md", ".txt",
                           ".py", ".csv", ".svg", ".yml", ".yaml", ".toml", ".ini", ".xml", ".gitignore"}

# ---------------------------------------------------------------- WEB
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]

# ---------------------------------------------------------------- PER-AGENT GEN SETTINGS
@dataclass(frozen=True)
class AgentSettings:
    """
    Gemini ke generation parameters (types.GenerateContentConfig me jaate hain):
      temperature       : 0 = pakka/same jawab, 1+ = creative. (Gemini 3 ka default 1.0 hai;
                          agar jawab repeat ho ya loop kare to temperature 1.0 kar do.)
      top_p             : 0-1, kitne probable words me se chunna (0.95 normal hai).
      max_output_tokens : jawab ki max length. Chhota rakhoge to kam token = kam quota.
      max_steps         : tool-calling loop ke max rounds (sirf tools wale agents ke liye).
    """
    temperature: float
    top_p: float
    max_output_tokens: int
    max_steps: int = 1

AGENT_SETTINGS = {
    "orchestrator": AgentSettings(temperature=0.2, top_p=0.9, max_output_tokens=400),
    "tutor":        AgentSettings(temperature=0.4, top_p=0.95, max_output_tokens=1800, max_steps=3),
    "quiz":         AgentSettings(temperature=0.7, top_p=0.95, max_output_tokens=2500),
    "summarizer":   AgentSettings(temperature=0.3, top_p=0.95, max_output_tokens=1800),
    "planner":      AgentSettings(temperature=0.5, top_p=0.95, max_output_tokens=1800),
    "math":         AgentSettings(temperature=0.1, top_p=0.9, max_output_tokens=1200, max_steps=4),
    "verifier":     AgentSettings(temperature=0.0, top_p=0.9, max_output_tokens=1800),
    # --- Code Studio agents
    "code_planner":  AgentSettings(temperature=0.3, top_p=0.95, max_output_tokens=4500),
    "coder":         AgentSettings(temperature=0.4, top_p=0.95, max_output_tokens=8192, max_steps=6),
    "code_reviewer": AgentSettings(temperature=0.2, top_p=0.9, max_output_tokens=4096, max_steps=4),
}