"""
agents/base.py  --  Saare agents ka common "dhaancha" (parent class).

Ek Agent = (system instruction) + (generation settings) + (optional tools) + (loop).
Har specialist agent is class ko inherit karke sirf name, instruction aur tools batata hai.
"""
import json
from dataclasses import dataclass
from typing import Any

from google.genai import types

from .. import config
from ..context import TurnContext
from ..llm import get_gateway
from ..tools import TOOL_DECLARATIONS, execute_tool


@dataclass
class AgentResult:
    text: str                  # model ka final text
    parsed: Any = None         # JSON mode me: dict (json.loads ke baad), warna None


def history_to_contents(history: list[dict]) -> list[types.Content]:
    """
    Input : [{'role': 'user'|'assistant', 'content': str}]
    Output: list[types.Content] -- Gemini 'assistant' ko 'model' bolta hai, isliye role badalte hain.
    types.Content(role='user'|'model', parts=[types.Part(text=...)])
    """
    out = []
    for m in history:
        if m.get("content"):
            role = "model" if m["role"] == "assistant" else "user"
            out.append(types.Content(role=role, parts=[types.Part(text=m["content"])]))
    return out


def safe_text(response) -> str:
    """Input: Gemini response. Output: text (str) -- safety-block/empty ho to '' (crash nahi)."""
    try:
        return (response.text or "").strip()
    except Exception:
        return ""


class BaseAgent:
    name = "agent"
    settings_key = "tutor"               # config.AGENT_SETTINGS ki key
    instruction = "You are a helpful assistant."
    tool_names: list[str] = []           # is agent ko kaunse tools allowed hain

    def build_config(self, json_mode: bool = False, with_tools: bool = True) -> types.GenerateContentConfig:
        """
        GenerateContentConfig banata hai. Parameters:
          system_instruction : agent ka "character + rules"
          temperature / top_p / max_output_tokens : config.AGENT_SETTINGS se
          tools              : [types.Tool(function_declarations=[...])] -- tool calling ke liye
          response_mime_type : 'application/json' => model sirf valid JSON dega
          automatic_function_calling.disable=True : SDK khud tool na chalaye, hum manually chalate hain
        """
        s = config.AGENT_SETTINGS[self.settings_key]
        kwargs = dict(system_instruction=self.instruction, temperature=s.temperature,
                      top_p=s.top_p, max_output_tokens=s.max_output_tokens)
        if json_mode:
            kwargs["response_mime_type"] = "application/json"
        elif with_tools and self.tool_names:
            kwargs["tools"] = [types.Tool(function_declarations=[
                TOOL_DECLARATIONS[n] for n in self.tool_names])]
            kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
        return types.GenerateContentConfig(**kwargs)

    def run(self, ctx: TurnContext, prompt: str, history: list[dict] | None = None,
            json_mode: bool = False) -> AgentResult:
        """
        Agent chalata hai.
        Inputs: ctx, prompt (is turn ka user-side text), history (purani chat), json_mode (bool).
        Output: AgentResult(text, parsed).
        Loop: model jawab -> agar tool request ho to chalao, result wapas bhejo -> repeat (max_steps tak).
        """
        gateway = get_gateway()
        max_steps = config.AGENT_SETTINGS[self.settings_key].max_steps
        contents = history_to_contents(history or [])
        contents.append(types.Content(role="user", parts=[types.Part(text=prompt)]))
        ctx.log(self.name, "start", f"{self.name} started")

        for step in range(max_steps):
            response = gateway.generate(ctx, contents, self.build_config(json_mode))
            if not response.candidates:
                break
            model_content = response.candidates[0].content
            calls = [p.function_call for p in (getattr(model_content, "parts", None) or [])
                     if getattr(p, "function_call", None)]
            if not calls:
                return self._finish(response, json_mode)
            contents.append(model_content)   # poora content wapas (Gemini 3 'thought signature' bachane ke liye)
            responses = []
            for call in calls:
                args = dict(call.args or {})
                ctx.log(self.name, "tool", f"Tool chala: {call.name}", tool=call.name, arguments=_brief(args))
                result = execute_tool(ctx, call.name, args, self.tool_names)
                ctx.log(self.name, "result", f"Tool result: {call.name}", tool=call.name,
                        result=_shorten(result))
                # Part.from_function_response(name=str, response=dict) -> tool ka jawab model ko
                responses.append(types.Part.from_function_response(name=call.name,
                                                                   response={"result": result}))
            contents.append(types.Content(role="user", parts=responses))

        # Steps khatam: tools band karke ab seedha jawab maango.
        contents.append(types.Content(role="user", parts=[types.Part(
            text="Do not call any more tools. Give your final answer using the information you already have.")]))
        response = gateway.generate(ctx, contents, self.build_config(json_mode, with_tools=False))
        return self._finish(response, json_mode)

    @staticmethod
    def _finish(response, json_mode: bool) -> AgentResult:
        """Input: response, json_mode. Output: AgentResult; JSON galat ho to parsed=None (caller fallback le)."""
        text = safe_text(response)
        if not json_mode:
            return AgentResult(text=text)
        try:
            cleaned = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            return AgentResult(text=text, parsed=json.loads(cleaned))
        except (json.JSONDecodeError, ValueError):
            return AgentResult(text=text, parsed=None)


def _shorten(result: dict, limit: int = 600) -> dict:
    """UI trace chhota rakhne ke liye: lambe text ko kaat deta hai. Output: dict (same shape)."""
    raw = json.dumps(result, ensure_ascii=False, default=str)
    return result if len(raw) <= limit else {"preview": raw[:limit] + "…"}


def _brief(value, limit: int = 120):
    """
    Trace/stream chhota rakhne ke liye: bade text (jaise poori file ka content) ko kaat deta hai.
    Input : koi bhi nested value (dict/list/str). Output: same shape, strings max `limit` chars.
    """
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"… (+{len(value) - limit} chars)"
    if isinstance(value, dict):
        return {k: _brief(v, limit) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_brief(v, limit) for v in value]
    return value