"""
agents/retriever.py  --  RetrieverAgent: documents me se evidence dhoondhta hai.

Ye agent LLM call NAHI karta (sirf embedding search) -- isliye chat quota nahi khata.
"""
from .. import vector_store
from ..context import TurnContext


class RetrieverAgent:
    name = "retriever"

    def run(self, ctx: TurnContext, queries: list[str], top_k: int) -> list[dict]:
        """
        Inputs: ctx, queries (orchestrator ne jo 1-3 search lines banayi), top_k (kitne passages).
        Output: [{'label': 'S1', 'text', 'source', 'page', 'distance'}] -- label se citation hota hai.
        """
        ctx.log(self.name, "start", "Searching your documents", queries=queries)
        hits = vector_store.search_chunks(ctx.workspace_id, queries, top_k)
        passages = [{"label": f"S{i}", **h} for i, h in enumerate(hits, start=1)]
        seen = set()
        for p in passages:                           # UI ke liye unique sources
            key = (p["source"], p["page"])
            if key not in seen:
                seen.add(key)
                ctx.sources.append({"source": p["source"], "page": p["page"]})
        ctx.log(self.name, "result", f"Found {len(passages)} passages",
                found=[f"{p['source']} p.{p['page']}" for p in passages])
        return passages


def format_passages(passages: list[dict]) -> str:
    """
    Passages ko prompt me daalne ka format. <document> tags isliye ki model inhe
    'data' samjhe, 'instructions' nahi (prompt-injection se bachav).
    Input: passages list. Output: str.
    """
    if not passages:
        return "<retrieved_documents>NONE FOUND</retrieved_documents>"
    body = "\n".join(
        f'<document id="{p["label"]}" source="{p["source"]}" page="{p["page"]}">\n{p["text"]}\n</document>'
        for p in passages)
    return f"<retrieved_documents>\n{body}\n</retrieved_documents>"