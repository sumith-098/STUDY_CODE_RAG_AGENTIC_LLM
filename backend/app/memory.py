"""
memory.py  --  Chat history SQLite me (server restart ke baad bhi bachi rehti hai).

Table messages: id, session_id, workspace_id, role, content, meta(JSON), created_at
  role = 'user' ya 'assistant'
  meta = extra data jaise {'route':..., 'quiz': [...], 'sources': [...]}
"""
import json
import sqlite3
from datetime import datetime, timezone

from .config import SQLITE_PATH, DATA_DIR, MAX_HISTORY_MESSAGES


def _connect():
    """No input. Returns: sqlite3.Connection (row_factory se columns naam se milte hain)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(SQLITE_PATH)
    con.row_factory = sqlite3.Row
    return con


def initialize_memory():
    """Table + index banata hai; purane DB me nayi columns jodta hai (migration)."""
    with _connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL)""")
        # PRAGMA table_info -> har column ki row; r[1] = column ka naam
        cols = {r[1] for r in con.execute("PRAGMA table_info(messages)").fetchall()}
        if "workspace_id" not in cols:
            con.execute("ALTER TABLE messages ADD COLUMN workspace_id TEXT NOT NULL DEFAULT ''")
        if "meta" not in cols:
            con.execute("ALTER TABLE messages ADD COLUMN meta TEXT NOT NULL DEFAULT '{}'")
        con.execute("CREATE INDEX IF NOT EXISTS idx_session ON messages(workspace_id, session_id, id)")


def add_message(workspace_id: str, session_id: str, role: str, content: str,
                meta: dict | None = None) -> None:
    """Inputs: workspace, session, role ('user'/'assistant'), text, optional meta dict. Returns None."""
    with _connect() as con:
        con.execute(
            "INSERT INTO messages(workspace_id, session_id, role, content, meta, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (workspace_id, session_id, role, content, json.dumps(meta or {}),
             datetime.now(timezone.utc).isoformat()))


def get_recent_messages(workspace_id: str, session_id: str,
                        limit: int = MAX_HISTORY_MESSAGES) -> list[dict]:
    """Returns: [{'role': 'user'|'assistant', 'content': str}] purane se naya order me (model ke liye)."""
    with _connect() as con:
        rows = con.execute(
            "SELECT role, content FROM messages WHERE workspace_id=? AND session_id=? "
            "ORDER BY id DESC LIMIT ?", (workspace_id, session_id, limit)).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def get_full_history(workspace_id: str, session_id: str) -> list[dict]:
    """Returns: UI ke liye poori history [{'role','content','meta'(dict)}] (page reload par dikhane ko)."""
    with _connect() as con:
        rows = con.execute(
            "SELECT role, content, meta FROM messages WHERE workspace_id=? AND session_id=? "
            "ORDER BY id", (workspace_id, session_id)).fetchall()
    return [{"role": r["role"], "content": r["content"], "meta": json.loads(r["meta"] or "{}")}
            for r in rows]


def clear_session(workspace_id: str, session_id: str) -> None:
    """Inputs: workspace, session. Us conversation ki history delete. Returns None."""
    with _connect() as con:
        con.execute("DELETE FROM messages WHERE workspace_id=? AND session_id=?",
                    (workspace_id, session_id))


def list_sessions(workspace_id: str, limit: int = 30) -> list[dict]:
    """
    Returns: [{'session_id', 'title' (pehla sawaal), 'updated_at', 'messages' (count)}]
    sabse nayi chat pehle -- sidebar ke "Recent chats" ke liye.
    """
    with _connect() as con:
        rows = con.execute(
            "SELECT session_id, MIN(id) AS first_id, MAX(id) AS last_id, COUNT(*) AS n "
            "FROM messages WHERE workspace_id=? GROUP BY session_id ORDER BY last_id DESC LIMIT ?",
            (workspace_id, limit)).fetchall()
        out = []
        for r in rows:
            first = con.execute("SELECT content FROM messages WHERE id=?", (r["first_id"],)).fetchone()
            last = con.execute("SELECT created_at FROM messages WHERE id=?", (r["last_id"],)).fetchone()
            title = " ".join((first["content"] if first else "Chat").split())[:60]
            out.append({"session_id": r["session_id"], "title": title,
                        "updated_at": last["created_at"] if last else "", "messages": r["n"]})
    return out
