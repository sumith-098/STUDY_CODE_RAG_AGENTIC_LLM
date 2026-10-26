"""
pipeline.py  --  Poora multi-agent flow ek jagah (orchestration ka "script").

   user message
        |
   [quick reply?]--haan--> bina AI call ke jawab (quota bachao)
        |nahi
   OrchestratorAgent  -> route + search queries              (1 LLM call)
        |
   RetrieverAgent     -> documents se passages               (embedding only)
        |
   Specialist: Tutor / Quiz / Summarizer / Planner / Math    (1-3 LLM calls)
        |
   VerifierAgent      -> answer ko documents se check        (1 LLM call, optional)
        |
   final answer + sources + activity trace
"""
import re

from . import config, vector_store
from .agents.math_agent import MathAgent
from .agents.orchestrator import OrchestratorAgent
from .agents.planner import PlannerAgent
from .agents.quiz import QuizAgent
from .agents.retriever import RetrieverAgent, format_passages
from .agents.summarizer import SummarizerAgent
from .agents.tutor import TutorAgent
from .agents.verifier import VerifierAgent
from .context import TurnContext
from . import llm

# Greeting/thanks par AI call bekaar hai -- seedha jawab.
_QUICK = re.compile(r"^\s*(hi+|hello+|hey+|namaste|thanks?|thank you|thx|ok(ay)?|bye)\W*$", re.I)
_QUICK_REPLY = ("Hello! I'm StudyPilot. Upload your notes and ask me anything: I can explain concepts, "
                "make quizzes, summarize chapters or plan your revision.")

# route -> (specialist agent, kitne passages retrieve karne hain)
_TOP_K = {"tutor": 5, "quiz": 8, "summary": 8, "planner": 5, "math": 3}


def run_study_turn(workspace_id: str, session_id: str, message: str, history: list[dict]) -> dict:
    """
    Ek poora user turn chalata hai.
    Inputs: workspace_id, session_id, message (user ka sawaal), history (pichhli baat-cheet,
            [{'role': 'user'|'assistant', 'content': str}], current message us me nahi).
    Output: {'answer': str, 'route': str, 'quiz': list|None, 'sources': list[dict],
             'verified': bool|None, 'events': list[dict]}
    """
    ctx = TurnContext(workspace_id=workspace_id, session_id=session_id)

    if _QUICK.match(message):
        ctx.log("pipeline", "skip", "Greeting, no AI call needed")
        return {"answer": _QUICK_REPLY, "route": "chat", "quiz": None, "sources": [],
                "verified": None, "events": ctx.events}

    docs = vector_store.list_documents(workspace_id)
    doc_names = [d["name"] for d in docs]

    # 1) Orchestrator: kaun karega?
    plan = OrchestratorAgent().decide(ctx, message, history, doc_names)
    route = plan["route"]
    ctx.log("orchestrator", "result", f"Route: {route}", plan=plan)

    # 2) Retriever: evidence laao (agar chahiye)
    passages = []
    if plan["use_documents"]:
        passages = RetrieverAgent().run(ctx, plan["search_queries"], _TOP_K[route])

    prompt = f"Student request: {message}\n\n{format_passages(passages)}"
    quiz = None
    answer = ""

    # 3) Specialist
    if route == "quiz":
        intro, quiz = QuizAgent().make_quiz(ctx, prompt, plan["quiz_count"])
        answer = intro or "Here's your practice quiz."
        if not quiz:
            answer = "I couldn't build a quiz this time. Try a more specific topic or ask again."
            quiz = None
    elif route == "summary":
        answer = SummarizerAgent().run(ctx, prompt, history).text
    elif route == "planner":
        answer = PlannerAgent().run(ctx, prompt, history).text
    elif route == "math":
        answer = MathAgent().run(ctx, prompt, history).text
    else:
        answer = TutorAgent().run(ctx, prompt, history).text

    if not answer:
        answer = "I couldn't produce an answer this time. Try rephrasing your question."

    # 4) Verifier (sirf document-based text answers par, aur sirf agar quota bacha ho)
    verified = None
    if config.ENABLE_VERIFIER and passages and route in {"tutor", "summary"}:
        remaining = llm.quota_manager.daily_remaining_fraction("chat")
        if remaining >= config.VERIFIER_MIN_DAILY_REMAINING:
            check = VerifierAgent().check(ctx, answer, passages)
            verified, answer = check["ok"], check["answer"]
            ctx.log("verifier", "result",
                    "Answer matches your documents ✔" if check["ok"]
                    else "Answer was corrected", problems=check["problems"])
        else:
            ctx.log("verifier", "skip", "Quota is low, verification skipped")

    # sources dedupe (order bachakar)
    seen, sources = set(), []
    for s in ctx.sources:
        key = (s["source"], s["page"])
        if key not in seen:
            seen.add(key)
            sources.append(s)
    ctx.log("pipeline", "info", f"Total LLM calls: {ctx.llm_calls}")
    return {"answer": answer, "route": route, "quiz": quiz, "sources": sources,
            "verified": verified, "events": ctx.events}