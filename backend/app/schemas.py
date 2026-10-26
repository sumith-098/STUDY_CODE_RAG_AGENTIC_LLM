"""
schemas.py  --  API ke request/response ka shape (pydantic).

FastAPI in models se automatically input validate karta hai aur docs banata hai.
"""
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """POST /api/chat ka body."""
    session_id: str = Field(min_length=8, max_length=100)   # ek conversation ki ID
    message: str = Field(min_length=1, max_length=4000)     # user ka sawaal


class QuizQuestion(BaseModel):
    """Quiz ka ek MCQ. Quiz agent ka output isi format me aata hai."""
    question: str
    options: list[str]            # 4 options
    correct_index: int            # sahi option ka index (0 se shuru)
    explanation: str              # kyun sahi hai
    source: str = ""              # 'file.pdf p.3' (agar documents se bana ho)


class QuizOutput(BaseModel):
    """Quiz agent ka poora JSON output."""
    intro: str = ""
    questions: list[QuizQuestion]


class ChatResponse(BaseModel):
    """POST /api/chat ka response."""
    session_id: str
    answer: str                         # markdown text
    route: str                          # kis specialist ne jawab diya
    quiz: list[QuizQuestion] | None = None
    sources: list[dict] = []            # [{'source': 'a.pdf', 'page': 3}]
    verified: bool | None = None        # verifier ne check kiya? (None = check nahi hua)
    events: list[dict]                  # agent activity trace (UI me dikhta hai)
    quota: dict                         # abhi ka quota status


class UploadResponse(BaseModel):
    """POST /api/upload ka response."""
    filename: str
    file_hash: str
    chunks_indexed: int
    already_indexed: bool = False
    message: str


# ---------------------------------------------------------------- Code Studio
class PlanFile(BaseModel):
    """Plan ki ek file."""
    path: str                     # relative path, jaise "src/app.js"
    action: str = "create"        # "create" ya "modify"
    purpose: str = ""             # is file ka kaam (1 line)


class CodePlan(BaseModel):
    """Planner agent ka output -- user isse Approve karta hai."""
    project_name: str
    summary: str = ""
    stack: str = ""
    files: list[PlanFile]
    notes: str = ""               # kaise chalana hai
    brief: str = Field(default="", max_length=6000)   # AI-written detailed build prompt (user approve se pehle edit kar sakta hai)


class CodePlanRequest(BaseModel):
    """POST /api/code/plan ka body."""
    request: str = Field(min_length=3, max_length=4000)   # user ka kaam
    project_id: str | None = None                         # purane project me badlaav ke liye


class CodeBuildRequest(BaseModel):
    """POST /api/code/build ka body (approved plan)."""
    project_id: str = Field(min_length=3, max_length=61)
    request: str = Field(min_length=3, max_length=4000)
    plan: CodePlan  