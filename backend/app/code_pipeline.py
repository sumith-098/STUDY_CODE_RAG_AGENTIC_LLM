"""
code_pipeline.py  --  Code Studio ka poora flow (Planner -> [Approve] -> Coder -> Reviewer).

   user ka kaam
        |
   plan_project()        CodePlannerAgent -> file plan                     (1 LLM call)
        |   user UI me plan dekhta hai aur "Approve" dabata hai
   stream_build()        CoderAgent  -> write_files tool se files bante hain (2 calls)
        |                CodeReviewerAgent -> bugs dhundh kar fix           (1-3 calls)
        v
   live events (NDJSON stream): event / file / done / error

Build ek alag thread me chalta hai aur events queue se UI tak stream hote hain.
Tab band hone par ctx.cancelled=True ho jaata hai -> agle LLM call par ruk jaata hai (quota nahi jalta).
"""
import json
import logging
import queue
import re
import secrets
import threading

from . import config, llm
from .agents.code_planner import CodePlannerAgent
from .agents.code_reviewer import CodeReviewerAgent
from .agents.coder import CoderAgent
from .context import TurnContext
from .errors import AppError, BadInput, QuotaExceeded
from .tools_files import FileToolError, ProjectSandbox, valid_project_id

log = logging.getLogger("studypilot.code")

_BUILDING: set[str] = set()          # jin projects par abhi build chal raha hai
_BUILDING_LOCK = threading.Lock()


def open_sandbox(workspace_id: str, project_id: str, must_exist: bool = False) -> ProjectSandbox:
    """
    Inputs: workspace_id, project_id, must_exist (True => folder hona zaroori).
    Returns: ProjectSandbox. Raises BadInput agar id galat ho ya (must_exist par) project na mile.
    """
    if not valid_project_id(project_id):
        raise BadInput("Invalid project ID.")
    sb = ProjectSandbox(workspace_id, project_id)
    if must_exist and not sb.exists():
        raise BadInput("Project not found.")
    return sb


def new_project_id(name: str) -> str:
    """Input: project naam. Returns: unique id jaise 'todo-app-3fa9' (sirf a-z, 0-9, '-')."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30].strip("-") or "project"
    return f"{slug}-{secrets.token_hex(2)}"


def _require_quota() -> None:
    """Aaj ke chat requests kam bache hon to build shuru hi nahi karte (beech me atakne se behtar)."""
    left = llm.quota_manager.status()["chat"]["remaining_today"]
    if left < config.CODE_MIN_QUOTA_TO_START:
        raise QuotaExceeded("Today's free AI limit is almost used up, so the build was not started. "
                            "Please try again tomorrow.")


def plan_project(workspace_id: str, request: str, project_id: str | None = None) -> dict:
    """
    Step 1: sirf plan banata hai (disk par kuch nahi likhta).
    Inputs: workspace_id, request, project_id (agar purane project me badlaav karna ho).
    Output: {'project_id': str, 'is_new': bool, 'plan': {...}}
    """
    _require_quota()
    existing, sb = [], None
    if project_id and valid_project_id(project_id):
        sb = ProjectSandbox(workspace_id, project_id)
        if sb.exists():
            existing = sb.list_files()
    ctx = TurnContext(workspace_id=workspace_id, session_id="code-plan", max_calls=3)
    plan = CodePlannerAgent().make_plan(ctx, request, existing)
    is_new = not existing
    pid = project_id if (project_id and sb is not None and sb.exists()) else new_project_id(plan["project_name"])
    return {"project_id": pid, "is_new": is_new, "plan": plan}


def _validate_plan(plan: dict) -> dict:
    """Client se aaye plan ko dobara safe banata hai (client par bharosa nahi). Returns: clean plan dict."""
    return CodePlannerAgent._sanitize(plan, "", set())


def _run_build(ctx: TurnContext, sb: ProjectSandbox, request: str, plan: dict) -> dict:
    """
    Coder -> (missing files ho to ek retry) -> Reviewer. Ye worker thread me chalta hai.
    Output: {'project_id','files','summary','review','llm_calls'}
    """
    existing = {f["path"] for f in sb.list_files()}
    # modify wali files ke liye plan ko disk ki sachchai se match karo
    for f in plan["files"]:
        f["action"] = "modify" if f["path"] in existing else "create"
    sb.write_meta(name=plan["project_name"], summary=plan["summary"], stack=plan["stack"], notes=plan["notes"],
                  brief=plan.get("brief", ""))
    ctx.sandbox = sb

    ctx.log("pipeline", "info", f"Build started: {len(plan['files'])} files planned")
    summary = CoderAgent().build(ctx, request, plan, sb.snapshot())

    planned = [f["path"] for f in plan["files"]]
    missing = [p for p in planned if p not in ctx.written_paths and p not in {f['path'] for f in sb.list_files()}]
    if missing:
        ctx.log("pipeline", "info", f"{len(missing)} file(s) missing, asking the Coder to finish them", missing=missing)
        summary = CoderAgent().fill_missing(ctx, request, plan, missing, sb.snapshot()) or summary
    if not ctx.written_paths:
        raise AppError("The Coder didn't write any files. Try a smaller or clearer request.")

    review = ""
    if ctx.llm_calls < ctx.max_calls - 1:
        review = CodeReviewerAgent().review(ctx, request, plan.get("brief", ""), sb.snapshot())
        ctx.log("code_reviewer", "result", review.splitlines()[0][:160] if review else "review done")
    else:
        ctx.log("code_reviewer", "skip", "Few calls left, review skipped")

    sb.write_meta()
    ctx.log("pipeline", "info", f"Total LLM calls: {ctx.llm_calls}")
    return {"project_id": sb.project_id, "files": sb.list_files(), "summary": summary, "review": review,
            "llm_calls": ctx.llm_calls}


def start_build(workspace_id: str, project_id: str, request: str, plan: dict) -> tuple[ProjectSandbox, dict]:
    """
    Build shuru karne se pehle ke saare checks (HTTP error ke roop me turant dikhte hain, stream shuru hone se pehle).
    Output: (sandbox, clean plan). Raises BadInput/QuotaExceeded.
    """
    sb = open_sandbox(workspace_id, project_id)
    clean = _validate_plan(plan)
    _require_quota()
    with _BUILDING_LOCK:
        if project_id in _BUILDING:
            raise BadInput("A build is already running for this project. Please wait.")
        _BUILDING.add(project_id)
    return sb, clean


def stream_build(workspace_id: str, sb: ProjectSandbox, request: str, plan: dict):
    """
    Generator: build chalata hai aur live events NDJSON lines (bytes) me yield karta hai.
    Event types: 'event' (agent activity), 'file' (nayi/badli file + content), 'ping' (connection zinda rakhne ko),
                 'done' (final), 'error' (friendly message).
    """
    q: queue.Queue = queue.Queue()
    done_marker = object()
    ctx = TurnContext(workspace_id=workspace_id, session_id="code-build",
                      max_calls=config.CODE_MAX_LLM_CALLS, listener=q.put)

    def worker():
        try:
            result = _run_build(ctx, sb, request, plan)
            q.put({"type": "done", **result, "quota": llm.quota_manager.status()})
        except AppError as exc:
            q.put({"type": "error", **exc.to_dict()["error"]})
        except FileToolError as exc:
            q.put({"type": "error", "code": "bad_input", "message": str(exc), "retry_after": None})
        except Exception:
            log.exception("Code build failed")
            q.put({"type": "error", "code": "server_error", "retry_after": None,
                   "message": "Something went wrong during the build. Please try again."})
        finally:
            with _BUILDING_LOCK:
                _BUILDING.discard(sb.project_id)
            q.put(done_marker)

    threading.Thread(target=worker, daemon=True).start()
    try:
        while True:
            try:
                item = q.get(timeout=15)
            except queue.Empty:
                yield (json.dumps({"type": "ping"}) + "\n").encode()
                continue
            if item is done_marker:
                break
            yield (json.dumps(item, ensure_ascii=False) + "\n").encode()
    finally:
        ctx.cancelled = True     # client chala gaya ho to agla LLM call nahi hoga (poora ho chuka ho to koi asar nahi)