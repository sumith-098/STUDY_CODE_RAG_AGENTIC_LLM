"""
context.py  --  Ek user-turn (ya ek build job) ka "bag": workspace, events log, aur LLM call counter.

Har agent ko yahi ctx milta hai, taaki:
  * UI ko pura agent activity trace dikhe (ctx.events)
  * ek turn me bahut zyada Gemini calls na ho (ctx.count_llm_call)
  * Code Studio me live progress stream ho sake (ctx.listener) aur user tab band kare to
    build ruk jaye (ctx.cancelled) -- quota na jale
"""
from dataclasses import dataclass, field
from typing import Callable

from .config import MAX_LLM_CALLS_PER_TURN
from .errors import AppError, QuotaExceeded


@dataclass
class TurnContext:
    workspace_id: str
    session_id: str
    events: list = field(default_factory=list)
    llm_calls: int = 0
    sources: list = field(default_factory=list)   # retriever jo passages laya unki list
    max_calls: int = MAX_LLM_CALLS_PER_TURN       # is turn me max LLM calls
    sandbox: object = None                        # Code Studio: ProjectSandbox (file tools yahi use karte hain)
    listener: Callable | None = None              # live event bhejne wala function (streaming ke liye)
    cancelled: bool = False                       # True => agle LLM call par ruk jao
    writes: int = 0                               # is job me kitni file-writes hui
    written_paths: set = field(default_factory=set)

    def _notify(self, payload: dict) -> None:
        """Live listener ko event bhejta hai (agar ho). Listener ka error build ko nahi todta."""
        if self.listener is not None:
            try:
                self.listener(payload)
            except Exception:
                pass

    def log(self, agent: str, kind: str, message: str, **data) -> None:
        """
        Activity event add karta hai (UI me 'Agent activity' me dikhta hai).
        Inputs: agent naam, kind ('start'/'tool'/'result'/'skip'/'info'), message, extra key=value data.
        Event format: {'agent','type','message', ...data}
        Streaming me ye {'type': 'event', 'event': <upar wala dict>} ban kar jaata hai.
        """
        event = {"agent": agent, "type": kind, "message": message, **data}
        self.events.append(event)
        self._notify({"type": "event", "event": event})

    def emit(self, payload: dict) -> None:
        """Sirf live stream ke liye (events list me save nahi hota) -- jaise nayi file ka poora content."""
        self._notify(payload)

    def count_llm_call(self) -> None:
        """Har Gemini chat call se pehle chalta hai. Limit cross hui ya cancel hua to error raise."""
        if self.cancelled:
            raise AppError("The build was cancelled.")
        self.llm_calls += 1
        if self.llm_calls > self.max_calls:
            raise QuotaExceeded("This request is too complex. Please split it into smaller parts.")