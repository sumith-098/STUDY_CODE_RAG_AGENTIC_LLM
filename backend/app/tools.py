"""
tools.py  --  Agents ke "haath": calculator aur document search.

Gemini sirf REQUEST karta hai ("calculator chalao, expression=2+2"). Asli Python function
hum chalate hain, validation ke baad. Is file me:
  * calculator()            -- safe arithmetic
  * TOOL_DECLARATIONS       -- Gemini ko batata hai ki kaunsa tool hai aur uske parameters
  * execute_tool()          -- tool request ko validate karke chalata hai
"""
import ast
import operator

from google.genai import types

from . import vector_store
from .errors import AppError
from .tools_files import FILE_TOOL_DECLARATIONS, FILE_TOOL_NAMES, execute_file_tool


def calculator(expression: str) -> dict:
    """
    Safe arithmetic (eval() use nahi hota -- AST allow-list se).
    Input : expression (str) jaise "(12 + 8) / 4". Allowed: + - * / // % ** aur brackets.
    Output: {'result': number}  ya  {'error': 'message'}
    """
    allowed = {
        ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
        ast.Pow: operator.pow, ast.Mod: operator.mod,
        ast.USub: operator.neg, ast.UAdd: operator.pos,
    }

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in allowed:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 10:
                raise ValueError("Exponents above 10 are not allowed.")
            value = allowed[type(node.op)](left, right)
            if abs(value) > 1e100:
                raise ValueError("The result is too large.")
            return value
        if isinstance(node, ast.UnaryOp) and type(node.op) in (ast.USub, ast.UAdd):
            return allowed[type(node.op)](visit(node.operand))
        raise ValueError("Only basic arithmetic is supported.")

    try:
        if len(expression) > 200:
            raise ValueError("The expression is too long.")
        # ast.parse(source, mode='eval') -> Expression node; .body = asli expression tree
        return {"result": visit(ast.parse(expression.strip(), mode="eval").body)}
    except ZeroDivisionError:
        return {"error": "Cannot divide by zero."}
    except Exception as exc:
        return {"error": f"Calculation failed: {exc}"}


def search_documents(ctx, query: str, top_k: int = 5) -> dict:
    """
    User ke uploaded documents me meaning-based search.
    Inputs: ctx (workspace ke liye), query (str), top_k (1-5).
    Output: {'results': [{'text','source','page'}], 'message': str}
    """
    hits = vector_store.search_chunks(ctx.workspace_id, [query], max(1, min(int(top_k), 5)))
    ctx.sources.extend({"source": h["source"], "page": h["page"]} for h in hits)
    return {"results": [{"text": h["text"], "source": h["source"], "page": h["page"]} for h in hits],
            "message": "Retrieved passages." if hits else "No results found."}


# ------------------------------------------------------------------ Gemini ko tool ka description
# types.FunctionDeclaration(name, description, parameters)
#   name        : tool ka naam (execute_tool me wahi key)
#   description : model isse padh kar decide karta hai ki tool kab use kare
#   parameters  : JSON-schema (type OBJECT, properties, required)
TOOL_DECLARATIONS = {
    "search_documents": types.FunctionDeclaration(
        name="search_documents",
        description="Search the student's uploaded documents for passages relevant to a query.",
        parameters={"type": "OBJECT", "properties": {
            "query": {"type": "STRING", "description": "Concept or question to search for."},
            "top_k": {"type": "INTEGER", "description": "How many passages, 1 to 5."}},
            "required": ["query"]}),
    "calculator": types.FunctionDeclaration(
        name="calculator",
        description="Evaluate a basic arithmetic expression exactly. Use it instead of mental math.",
        parameters={"type": "OBJECT", "properties": {
            "expression": {"type": "STRING", "description": "Example: (12 + 8) / 4"}},
            "required": ["expression"]}),
}


# Code Studio ke file tools (list_files, read_file, write_files, edit_file) bhi isi registry me:
TOOL_DECLARATIONS.update(FILE_TOOL_DECLARATIONS)


def execute_tool(ctx, name: str, args: dict, allowed: list[str]) -> dict:
    """
    Model ki tool request ko validate karke chalata hai. Kabhi exception bahar nahi phenkta.
    Inputs: ctx, name (tool naam), args (dict), allowed (is agent ko jo tools allowed hain).
    Output: tool ka dict result, ya {'error': '...'} (model ko wapas bhej diya jaata hai).
    """
    if name not in allowed:
        return {"error": f"Tool '{name}' is not allowed for this agent."}
    try:
        if name == "search_documents":
            query = str(args.get("query", "")).strip()
            if not query:
                raise ValueError("query must not be empty")
            return search_documents(ctx, query, int(args.get("top_k", 5) or 5))
        if name == "calculator":
            return calculator(str(args.get("expression", "")))
        if name in FILE_TOOL_NAMES:
            return execute_file_tool(ctx, name, args)
        return {"error": f"Unknown tool: {name}"}
    except AppError:
        raise   # quota/config errors user tak pahunchne do (friendly message)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}