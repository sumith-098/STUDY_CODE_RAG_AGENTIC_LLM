"""
tools_files.py  --  Code Studio ke "haath": folder/file banana, padhna, badalna (SAFE sandbox me).

Gemini khud file nahi bana sakta. Wo sirf bolta hai "write_files chalao, path=..., content=...".
Asli kaam yahan hota hai, aur sirf ek tay kiye hue project folder ke ANDAR:
    backend/data/projects/<workspace-hash>/<project-id>/

Safety rules (sab yahin enforce hote hain):
  * path hamesha relative; "..", "C:\\", "/etc" jaise paths reject
  * sirf allowed extensions (.html .css .js .py ...); .exe/.bat/.sh nahi
  * file size / files ki sankhya / poore project ki size limited
  * purani file badalne se pehle backup (.history/ me)
"""
import hashlib
import io
import json
import os
import re
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from google.genai import types

from . import config


class FileToolError(Exception):
    """File tool ki galti (galat path, bada file...). Ye model ko wapas bheji jaati hai taaki wo khud sudhaar le."""


_SEGMENT = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*$")
_PROJECT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,60}$")
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_META = ".project.json"
_HISTORY = ".history"


def valid_project_id(pid: str) -> bool:
    """Input: project id. Returns: True agar sirf a-z, 0-9, '-' ho (3-61 chars). Path-traversal yahin rukta hai."""
    return isinstance(pid, str) and bool(_PROJECT_ID.match(pid))


def normalize_path(raw) -> str:
    """
    Model/user ke diye path ko saaf aur safe banata hai.
    Input : raw path (str) jaise "src/app.js" ya "src\\app.js".
    Output: normalized relative path (str) jaise "src/app.js".
    Raises: FileToolError agar path unsafe/galat ho.
    """
    if not isinstance(raw, str):
        raise FileToolError("The path must be text.")
    p = raw.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    if not p or len(p) > 150 or "\x00" in p:
        raise FileToolError("The path is empty or too long.")
    if p.startswith("/") or re.match(r"^[A-Za-z]:", p):
        raise FileToolError(f"Absolute paths are not allowed: {raw!r}. Use a relative path such as src/app.js.")
    parts = p.split("/")
    for seg in parts:
        if seg in ("", ".", ".."):
            raise FileToolError(f"Invalid path: {raw!r} ('..' and empty folder names are not allowed).")
        if seg != ".gitignore" and not _SEGMENT.match(seg):
            raise FileToolError(f"Invalid character in folder/file name: {seg!r}. Use only letters, numbers, '.', '_' and '-'.")
        if seg.rstrip(".").split(".")[0].lower() in _RESERVED:
            raise FileToolError(f"Reserved name not allowed: {seg!r}.")
    last = parts[-1]
    ext = ".gitignore" if last == ".gitignore" else Path(last).suffix.lower()
    if ext not in config.CODE_ALLOWED_EXTENSIONS:
        raise FileToolError(f"Extension {ext or '(none)'} is not allowed. Allowed: "
                            f"{', '.join(sorted(config.CODE_ALLOWED_EXTENSIONS))}")
    return "/".join(parts)


class ProjectSandbox:
    """Ek project ka folder + uske upar saare safe operations."""

    def __init__(self, workspace_id: str, project_id: str):
        """Inputs: workspace_id (str), project_id (valid_project_id wala). Folder abhi nahi banta (write par banta hai)."""
        if not valid_project_id(project_id):
            raise FileToolError("Invalid project ID.")
        self.project_id = project_id
        ws_hash = hashlib.sha256(workspace_id.encode()).hexdigest()[:12]
        self.root = config.PROJECTS_DIR / ws_hash / project_id

    # ---------------------------------------------------------------- helpers
    def exists(self) -> bool:
        """Returns: True agar project folder ban chuka hai."""
        return self.root.is_dir()

    def _full(self, rel: str) -> Path:
        """
        Relative path -> asli disk path, symlink/traversal check ke saath.
        Raises FileToolError agar resolve hone ke baad bhi path project folder ke bahar jaaye.
        """
        rel = normalize_path(rel)
        full = (self.root / rel).resolve()
        try:
            full.relative_to(self.root.resolve())
        except ValueError:
            raise FileToolError(f"The path points outside the project folder: {rel!r}")
        return full

    def list_files(self, folder: str = "") -> list[dict]:
        """
        Returns: [{'path': 'src/app.js', 'size': 1234}] sorted. Meta file aur .history chhupa hota hai.
        Input folder (optional): sirf is prefix wali files.
        """
        out = []
        if not self.exists():
            return out
        base = self.root.resolve()
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d != _HISTORY]
            for name in filenames:
                full = Path(dirpath) / name
                rel = full.relative_to(base).as_posix()
                if rel == _META:
                    continue
                out.append({"path": rel, "size": full.stat().st_size})
        prefix = folder.strip().strip("/").replace("\\", "/")
        if prefix:
            out = [f for f in out if f["path"].startswith(prefix + "/") or f["path"] == prefix]
        return sorted(out, key=lambda f: f["path"])

    def _total_bytes(self) -> int:
        return sum(f["size"] for f in self.list_files())

    # ---------------------------------------------------------------- operations
    def read_file(self, rel: str) -> dict:
        """
        Input : rel path.
        Output: {'path': str, 'content': str}. Raises FileToolError agar file na ho ya bahut badi ho.
        """
        full = self._full(rel)
        if not full.is_file():
            raise FileToolError(f"File not found: {rel!r}")
        if full.stat().st_size > config.CODE_MAX_FILE_BYTES * 2:
            raise FileToolError("The file is too large.")
        return {"path": normalize_path(rel), "content": full.read_text(encoding="utf-8", errors="replace")}

    def write_file(self, rel: str, content) -> dict:
        """
        File banata ya poori badal deta hai (folder khud ban jaate hain). Purani file ka backup banta hai.
        Inputs: rel path, content (str).
        Output: {'path', 'bytes', 'action': 'created'|'updated'}.
        Raises FileToolError: size/limit/path ki galti par.
        """
        if not isinstance(content, str):
            raise FileToolError("The content must be text.")
        full = self._full(rel)
        rel = normalize_path(rel)
        data = content.replace("\r\n", "\n")
        if data and not data.endswith("\n"):
            data += "\n"
        size = len(data.encode("utf-8"))
        if size > config.CODE_MAX_FILE_BYTES:
            raise FileToolError(f"{rel} is too large ({size} bytes, max {config.CODE_MAX_FILE_BYTES}). "
                                f"Split it into smaller files.")
        existed = full.is_file()
        old_size = full.stat().st_size if existed else 0
        files = self.list_files()
        if not existed and len(files) >= config.CODE_MAX_FILES:
            raise FileToolError(f"A project can have at most {config.CODE_MAX_FILES} files.")
        if sum(f["size"] for f in files) - old_size + size > config.CODE_MAX_PROJECT_BYTES:
            raise FileToolError("The project would exceed the total size limit.")
        if existed:
            self._backup(rel, full)
        full.parent.mkdir(parents=True, exist_ok=True)
        tmp = full.with_name(full.name + ".tmp")
        tmp.write_text(data, encoding="utf-8", newline="\n")   # pehle temp me, phir replace: adhuri file nahi bachti
        os.replace(tmp, full)
        return {"path": rel, "bytes": size, "action": "updated" if existed else "created"}

    def edit_file(self, rel: str, old_text: str, new_text: str) -> dict:
        """
        File ka sirf ek hissa badalta hai.
        Inputs: rel path, old_text (file me EXACTLY ek baar hona chahiye), new_text.
        Output: write_file jaisa dict. Raises FileToolError agar old_text na mile ya kai baar mile.
        """
        if not isinstance(old_text, str) or not old_text:
            raise FileToolError("old_text must not be empty.")
        if not isinstance(new_text, str):
            raise FileToolError("new_text must be text.")
        current = self.read_file(rel)["content"]
        count = current.count(old_text)
        if count == 0:
            raise FileToolError("old_text was not found in the file. Use read_file to see the current content and give the exact text.")
        if count > 1:
            raise FileToolError(f"old_text matches {count} places. Provide a longer, unique snippet.")
        return self.write_file(rel, current.replace(old_text, new_text, 1))

    def _backup(self, rel: str, full: Path) -> None:
        """Purani file ko .history/<timestamp>/<path> me copy karta hai; sirf last 30 backups rakhta hai."""
        hist = self.root / _HISTORY
        dest = hist / time.strftime("%Y%m%d-%H%M%S") / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(full, dest)
        runs = sorted(p for p in hist.iterdir() if p.is_dir())
        for old in runs[:-30]:
            shutil.rmtree(old, ignore_errors=True)

    # ---------------------------------------------------------------- project-level
    def snapshot(self, max_bytes: int = config.CODE_SNAPSHOT_BYTES) -> str:
        """
        Agent ko dikhane ke liye saari files ka text: <file path="..."> ... </file> blocks.
        Input max_bytes: kul size limit; bada hone par baaki files 'truncated' likh kar chhod di jaati hain.
        """
        parts, used = [], 0
        for f in self.list_files():
            try:
                content = self.read_file(f["path"])["content"]
            except FileToolError:
                continue
            if used + len(content) > max_bytes:
                parts.append(f'<file path="{f["path"]}" truncated="true">(not shown because of the size limit)</file>')
                continue
            used += len(content)
            parts.append(f'<file path="{f["path"]}">\n{content}\n</file>')
        return "\n".join(parts) if parts else "(the project is empty so far)"

    def zip_bytes(self) -> bytes:
        """Returns: poore project ki ZIP (bytes). Andar folder naam = project id."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in self.list_files():
                zf.write(self._full(f["path"]), arcname=f"{self.project_id}/{f['path']}")
        return buf.getvalue()

    def read_meta(self) -> dict | None:
        """Returns: {'name','summary','stack','notes','created','updated'} ya None."""
        path = self.root / _META
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def write_meta(self, **fields) -> dict:
        """Project ki meta info save/update karta hai (updated time automatic). Returns: poora meta dict."""
        self.root.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat()
        meta = self.read_meta() or {"created": now}
        meta.update({k: v for k, v in fields.items() if v is not None})
        meta["updated"] = now
        (self.root / _META).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return meta

    def delete(self) -> None:
        """Poora project folder hata deta hai."""
        if self.exists():
            shutil.rmtree(self.root, ignore_errors=True)


def list_projects(workspace_id: str) -> list[dict]:
    """
    Returns: [{'id','name','summary','updated','files'}] sabse nayi pehle -- is workspace ke sab projects.
    """
    ws_hash = hashlib.sha256(workspace_id.encode()).hexdigest()[:12]
    base = config.PROJECTS_DIR / ws_hash
    out = []
    if base.is_dir():
        for d in base.iterdir():
            if d.is_dir() and valid_project_id(d.name):
                sb = ProjectSandbox(workspace_id, d.name)
                meta = sb.read_meta() or {}
                out.append({"id": d.name, "name": meta.get("name", d.name), "summary": meta.get("summary", ""),
                            "updated": meta.get("updated", ""), "files": len(sb.list_files())})
    return sorted(out, key=lambda p: p["updated"], reverse=True)


# ====================================================================== Gemini ke liye tool descriptions
# FunctionDeclaration(name, description, parameters=JSON-schema) -- model inhe padh kar decide karta hai
# ki kaunsa tool kab aur kin arguments ke saath chalana hai.
_FILE_ITEM = {"type": "OBJECT", "properties": {
    "path": {"type": "STRING", "description": "Relative path, e.g. src/app.js (no leading slash, no '..')."},
    "content": {"type": "STRING", "description": "Complete file content."}},
    "required": ["path", "content"]}

FILE_TOOL_DECLARATIONS = {
    "list_files": types.FunctionDeclaration(
        name="list_files",
        description="List files of the current project with their sizes.",
        parameters={"type": "OBJECT", "properties": {
            "folder": {"type": "STRING", "description": "Optional folder prefix to filter by."}}}),
    "read_file": types.FunctionDeclaration(
        name="read_file",
        description="Read the full content of one project file.",
        parameters={"type": "OBJECT", "properties": {
            "path": {"type": "STRING", "description": "Relative file path."}}, "required": ["path"]}),
    "write_files": types.FunctionDeclaration(
        name="write_files",
        description="Create or fully overwrite one or more project files in a single call. Folders are created automatically.",
        parameters={"type": "OBJECT", "properties": {
            "files": {"type": "ARRAY", "items": _FILE_ITEM, "description": "Files to write (max 12 per call)."}},
            "required": ["files"]}),
    "edit_file": types.FunctionDeclaration(
        name="edit_file",
        description="Replace one exact piece of text inside an existing file (old_text must occur exactly once).",
        parameters={"type": "OBJECT", "properties": {
            "path": {"type": "STRING", "description": "Relative file path."},
            "old_text": {"type": "STRING", "description": "Exact existing text to replace (unique in the file)."},
            "new_text": {"type": "STRING", "description": "Replacement text."}},
            "required": ["path", "old_text", "new_text"]}),
}
FILE_TOOL_NAMES = set(FILE_TOOL_DECLARATIONS)


def _file_event(ctx, path: str, action: str, content: str) -> None:
    """File ban/badal gayi -- UI ko turant dikhane ke liye event + activity log. Input: ctx, path, action, content."""
    ctx.writes += 1
    ctx.written_paths.add(path)
    ctx.log("files", "file", f"{action}: {path}", path=path)
    ctx.emit({"type": "file", "path": path, "action": action, "content": content,
              "size": len(content.encode("utf-8"))})


def execute_file_tool(ctx, name: str, args: dict) -> dict:
    """
    Model ki file-tool request ko chalata hai.
    Inputs: ctx (ctx.sandbox me ProjectSandbox hona chahiye), name (tool naam), args (dict).
    Output: dict jo model ko wapas jaata hai:
        list_files  -> {'files': [{'path','size'}]}
        read_file   -> {'path','content'}
        write_files -> {'written': [{'path','bytes','action'}], 'errors': [{'path','error'}]}
        edit_file   -> {'path','bytes','action'}  ya  {'error': '...'}
    FileToolError kabhi bahar nahi jaata -- {'error': ...} bankar model ko milta hai, taaki wo sudhaar le.
    """
    sb = ctx.sandbox
    if sb is None:
        return {"error": "No project is open."}
    try:
        if name == "list_files":
            return {"files": sb.list_files(str(args.get("folder", "") or ""))}
        if name == "read_file":
            return sb.read_file(args.get("path"))
        if name == "write_files":
            files = args.get("files")
            if not isinstance(files, list) or not files:
                raise FileToolError("files must be a non-empty list.")
            if len(files) > 12:
                raise FileToolError("At most 12 files per call. Send the rest in the next call.")
            written, errors = [], []
            for item in files:
                path = item.get("path") if isinstance(item, dict) else None
                try:
                    if ctx.writes >= config.CODE_MAX_WRITES_PER_JOB:
                        raise FileToolError("This build reached its maximum number of file writes.")
                    result = sb.write_file(path, item.get("content"))
                    written.append(result)
                    _file_event(ctx, result["path"], result["action"], sb.read_file(result["path"])["content"])
                except FileToolError as exc:
                    errors.append({"path": str(path), "error": str(exc)})
            return {"written": written, "errors": errors}
        if name == "edit_file":
            result = sb.edit_file(args.get("path"), args.get("old_text"), args.get("new_text"))
            _file_event(ctx, result["path"], "edited", sb.read_file(result["path"])["content"])
            return result
        return {"error": f"Unknown file tool: {name}"}
    except FileToolError as exc:
        return {"error": str(exc)}