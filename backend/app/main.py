"""
main.py  --  FastAPI server: saare API endpoints yahan hain.

Endpoints:
  GET    /api/health                  server ok? + indexed chunks
  GET    /api/quota                   free-tier quota status (UI badge)
  GET    /api/documents               is workspace ki files
  POST   /api/upload                  file upload + index
  DELETE /api/documents/{file_hash}   file hatao
  POST   /api/chat                    sawaal poochho (multi-agent)
  GET    /api/chat/{session_id}       purani chat wapas laao
  DELETE /api/chat/{session_id}       chat saaf

Har request me header  X-Workspace-Id  (browser ki random ID) bhejna hai -- isse har user ka
data alag rehta hai.
"""
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from . import config, llm
from .errors import AppError, BadInput, QuotaExceeded
from .memory import add_message, clear_session, get_full_history, get_recent_messages, initialize_memory, list_sessions
from .rate_limiter import IPLimiter
from .schemas import (ChatRequest, ChatResponse, CodeBuildRequest, CodePlanRequest, UploadResponse)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("studypilot")

if not config.GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY missing. backend/.env banao (.env.example se copy karke).")
llm.init_gateway(config.GEMINI_API_KEY)

# vector_store import gateway ke baad (wo module load par Chroma kholta hai)
from . import vector_store  # noqa: E402
from .pipeline import run_study_turn  # noqa: E402
from . import code_pipeline  # noqa: E402
from .tools_files import FileToolError, list_projects  # noqa: E402

chat_limiter = IPLimiter(*config.IP_LIMIT_CHAT)
code_limiter = IPLimiter(*config.IP_LIMIT_CODE)
upload_limiter = IPLimiter(*config.IP_LIMIT_UPLOAD)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Server start hote hi SQLite tables ready karta hai."""
    initialize_memory()
    yield


app = FastAPI(title="StudyPilot AI API", version="0.2.0", lifespan=lifespan)


async def catch_all_errors(request: Request, call_next):
    """
    Koi bhi anjaan bug -> detail terminal me log, user ko simple JSON message (traceback nahi).
    Ye CORS middleware ke ANDAR hai, isliye error response par bhi CORS headers lagte hain
    (warna browser sirf 'Failed to fetch' dikhata).
    """
    try:
        return await call_next(request)
    except Exception:
        log.exception("Unhandled error")
        return JSONResponse(AppError("Something went wrong. Please try again.").to_dict(),
                            status_code=500)

# Order important hai: jo baad me add hota hai wo bahar rehta hai. CORS sabse bahar.
app.add_middleware(BaseHTTPMiddleware, dispatch=catch_all_errors)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------ friendly error handlers
@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    """Hamare apne errors -> {'error': {...}} JSON (frontend isi ko padhta hai)."""
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
    return JSONResponse(exc.to_dict(), status_code=exc.status_code, headers=headers)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    """Galat input (khaali message, lamba text...) -> saaf message."""
    return JSONResponse(BadInput("That input isn't valid (empty or too long?).").to_dict(),
                        status_code=422)


# ------------------------------------------------------------------ dependencies
_WS_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")

def workspace_id(x_workspace_id: str = Header(default="")) -> str:
    """Header X-Workspace-Id validate karta hai. Returns: workspace id (str)."""
    if not _WS_RE.match(x_workspace_id):
        raise BadInput("Workspace ID is missing. Please refresh the page.")
    return x_workspace_id

def client_ip(request: Request) -> str:
    """Returns: client ka IP (str) -- IP limiter ke liye."""
    return request.client.host if request.client else "unknown"


# ------------------------------------------------------------------ endpoints
@app.get("/api/health")
def health():
    """Gemini call nahi karta. Returns: {'status': 'ok', 'indexed_chunks': int}"""
    return {"status": "ok", "indexed_chunks": vector_store.collection_count()}


@app.get("/api/quota")
def quota():
    """Returns: QuotaManager.status() -- used/limit/remaining + approx_questions_left."""
    return llm.quota_manager.status()


@app.get("/api/documents")
def documents(ws: str = Depends(workspace_id)):
    """Returns: {'documents': [{'file_hash','name','chunks'}]}"""
    return {"documents": vector_store.list_documents(ws)}


@app.post("/api/upload", response_model=UploadResponse)
async def upload_document(request: Request, file: UploadFile = File(...),
                          ws: str = Depends(workspace_id)):
    """
    multipart/form-data me 'file'. Returns UploadResponse.
    Indexing blocking hai (embedding + wait), isliye threadpool me -- event loop nahi atkta.
    """
    upload_limiter.check(client_ip(request))
    filename = Path(file.filename or "upload.txt").name
    if Path(filename).suffix.lower() not in config.ALLOWED_EXTENSIONS:
        raise BadInput("Only PDF, DOCX or TXT files are supported.")
    data = await file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise BadInput("That file is larger than 15 MB.")
    result = await run_in_threadpool(vector_store.index_file, ws, filename, data)
    if result["chunks"] == 0:
        raise BadInput("No readable text was found in this file (it is empty or a very blurry scan).")
    msg = ("This file is already indexed." if result["already_indexed"]
           else "Document indexed. You can ask questions now.")
    return UploadResponse(filename=filename, file_hash=result["file_hash"],
                          chunks_indexed=result["chunks"],
                          already_indexed=result["already_indexed"], message=msg)


@app.delete("/api/documents/{file_hash}")
def delete_document(file_hash: str, ws: str = Depends(workspace_id)):
    """Ek file ke saare chunks hata deta hai. Returns: {'status': 'deleted'}"""
    vector_store.delete_document(ws, file_hash)
    return {"status": "deleted"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(body: ChatRequest, request: Request, ws: str = Depends(workspace_id)):
    """
    Body: {session_id, message}. Multi-agent pipeline chalata hai.
    BUG FIX: user message tabhi save hota hai jab jawab mil jaye (pehle fail hone par history bigad jaati thi).
    """
    chat_limiter.check(client_ip(request))
    history = get_recent_messages(ws, body.session_id)
    result = run_study_turn(ws, body.session_id, body.message, history)
    add_message(ws, body.session_id, "user", body.message)
    add_message(ws, body.session_id, "assistant", result["answer"],
                {"route": result["route"], "quiz": result["quiz"], "sources": result["sources"],
                 "verified": result["verified"]})
    return ChatResponse(session_id=body.session_id, answer=result["answer"], route=result["route"],
                        quiz=result["quiz"], sources=result["sources"], verified=result["verified"],
                        events=result["events"], quota=llm.quota_manager.status())


@app.get("/api/chats")
def chats(ws: str = Depends(workspace_id)):
    """Returns: {'chats': [{'session_id','title','updated_at','messages'}]} -- purani conversations ki list."""
    return {"chats": list_sessions(ws)}


@app.get("/api/chat/{session_id}")
def chat_history(session_id: str, ws: str = Depends(workspace_id)):
    """Returns: {'messages': [{'role','content','meta'}]} -- page reload par chat wapas dikhane ke liye."""
    return {"messages": get_full_history(ws, session_id)}


@app.delete("/api/chat/{session_id}")
def delete_chat(session_id: str, ws: str = Depends(workspace_id)):
    """Ek conversation ki history delete. Returns: {'status': 'cleared'}"""
    clear_session(ws, session_id)
    return {"status": "cleared"}


# ================================================================== CODE STUDIO
@app.post("/api/code/plan")
def code_plan(body: CodePlanRequest, request: Request, ws: str = Depends(workspace_id)):
    """
    Step 1: user ka kaam -> file plan (disk par kuch nahi likhta). 1 LLM call.
    Body: {request, project_id?}. Returns: {'project_id','is_new','plan':{project_name,summary,stack,files[],notes}}
    """
    code_limiter.check(client_ip(request))
    return code_pipeline.plan_project(ws, body.request, body.project_id)


@app.post("/api/code/build")
def code_build(body: CodeBuildRequest, request: Request, ws: str = Depends(workspace_id)):
    """
    Step 2 (Approve ke baad): Coder + Reviewer chalte hain, files banti hain.
    Response: NDJSON stream (har line ek JSON event):
      {"type":"event","event":{agent,type,message,...}} | {"type":"file","path","action","content","size"}
      {"type":"ping"} | {"type":"done","project_id","files","summary","review","llm_calls","quota"}
      {"type":"error","code","message","retry_after"}
    """
    code_limiter.check(client_ip(request))
    sb, plan = code_pipeline.start_build(ws, body.project_id, body.request, body.plan.model_dump())
    return StreamingResponse(code_pipeline.stream_build(ws, sb, body.request, plan),
                             media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/code/projects")
def code_projects(ws: str = Depends(workspace_id)):
    """Returns: {'projects': [{'id','name','summary','updated','files'}]} -- is workspace ke saare projects."""
    return {"projects": list_projects(ws)}


@app.get("/api/code/projects/{project_id}/files")
def code_project_files(project_id: str, ws: str = Depends(workspace_id)):
    """Returns: {'files': [{'path','size'}], 'meta': {...}|null}. Project na ho to khaali list (error nahi)."""
    sb = code_pipeline.open_sandbox(ws, project_id)
    return {"files": sb.list_files(), "meta": sb.read_meta()}


@app.get("/api/code/projects/{project_id}/file")
def code_project_file(project_id: str, path: str, ws: str = Depends(workspace_id)):
    """Query: ?path=src/app.js. Returns: {'path','content'}."""
    sb = code_pipeline.open_sandbox(ws, project_id, must_exist=True)
    try:
        return sb.read_file(path)
    except FileToolError as exc:
        raise BadInput(str(exc))


@app.get("/api/code/projects/{project_id}/zip")
def code_project_zip(project_id: str, ws: str = Depends(workspace_id)):
    """Returns: poore project ki ZIP file (download)."""
    sb = code_pipeline.open_sandbox(ws, project_id, must_exist=True)
    return Response(content=sb.zip_bytes(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{project_id}.zip"'})


@app.delete("/api/code/projects/{project_id}")
def code_project_delete(project_id: str, ws: str = Depends(workspace_id)):
    """Project ka poora folder delete. Returns: {'status': 'deleted'}"""
    code_pipeline.open_sandbox(ws, project_id).delete()
    return {"status": "deleted"}