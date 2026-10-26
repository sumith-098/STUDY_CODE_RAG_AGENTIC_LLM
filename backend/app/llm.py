"""
llm.py  --  Gemini se baat karne ka EKLAUTA darwaza (gateway).

Koi bhi agent seedha Gemini ko call nahi karta; sab yahin se jaate hain. Isse:
  * har call se pehle quota check hota hai (rate_limiter)
  * Google ke 429/503 errors par automatic retry
  * har error user ke liye friendly message me badal jaata hai
  * ek turn me max calls ki hard limit
"""
import logging
import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from . import config
from .errors import ConfigProblem, QuotaExceeded, UpstreamBusy, AppError
from .rate_limiter import QuotaManager, estimate_tokens

log = logging.getLogger("studypilot.llm")

def _contents_size(contents, config_obj=None) -> int:
    """Inputs: contents list (+ config). Returns: estimated input tokens (int) -- sirf text ginta hai."""
    total = 0
    for c in contents:
        for part in (getattr(c, "parts", None) or []):
            if getattr(part, "text", None):
                total += estimate_tokens(part.text)
            elif getattr(part, "inline_data", None):
                total += 1500   # PDF/image bytes: ~4 pages ka andaza
            elif getattr(part, "function_response", None):
                total += estimate_tokens(str(part.function_response.response))
    si = getattr(config_obj, "system_instruction", None)
    if isinstance(si, str):
        total += estimate_tokens(si)
    return total + 200  # tools/schema ka overhead


class GeminiGateway:
    def __init__(self, api_key: str, quota: QuotaManager):
        """Inputs: Gemini API key (str), QuotaManager object."""
        # genai.Client(api_key=...) -> Gemini SDK ka main object; client.models.* me saare calls hain.
        self.client = genai.Client(api_key=api_key)
        self.quota = quota

    # ------------------------------------------------------------------ chat
    def generate(self, ctx, contents: list, gen_config: types.GenerateContentConfig):
        """
        Ek Gemini chat call (quota + retry ke saath).

        Inputs:
          ctx        : TurnContext (calls count karne ke liye) ya None
          contents   : list[types.Content] -- poori baat-cheet (role 'user'/'model')
          gen_config : types.GenerateContentConfig

        Returns: GenerateContentResponse. Isme:
          response.text                          -> final text (str ya None)
          response.candidates[0].content         -> model ka Content (parts me text / function_call)
          response.candidates[0].finish_reason   -> STOP / MAX_TOKENS / SAFETY ...
          response.parsed                        -> JSON schema mode me ready object
        """
        if ctx is not None:        # ctx=None => agent ke bahar ki call (jaise OCR)
            ctx.count_llm_call()
        tokens = _contents_size(contents, gen_config)
        for attempt in range(3):
            self.quota.acquire("chat", tokens, max_wait=config.MAX_WAIT_CHAT_SECONDS)
            try:
                # client.models.generate_content(model=str, contents=list, config=GenerateContentConfig)
                return self.client.models.generate_content(
                    model=config.CHAT_MODEL, contents=contents, config=gen_config)
            except genai_errors.APIError as exc:
                self._handle_api_error(exc, attempt)
        raise UpstreamBusy("The AI is busy right now. Please try again in a moment.")

    # ------------------------------------------------------------------ embeddings
    def embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        """
        Text ko numbers (vectors) me badalta hai -- ek hi request me kai texts.

        Inputs:
          texts     : list[str] (max ~100 ek saath; hum 32 bhejte hain)
          task_type : 'RETRIEVAL_DOCUMENT' (documents index karte time)
                      ya 'RETRIEVAL_QUERY' (question search karte time)
        Returns: list[list[float]] -- har text ke liye EMBEDDING_DIMENSIONS floats.
        """
        if not texts:
            return []
        tokens = sum(estimate_tokens(t) for t in texts)
        # task_type sirf gemini-embedding-001 par pakka supported hai.
        kwargs = {"output_dimensionality": config.EMBEDDING_DIMENSIONS}
        if config.EMBEDDING_MODEL.endswith("embedding-001"):
            kwargs["task_type"] = task_type
        for attempt in range(3):
            self.quota.acquire("embed", tokens, max_wait=config.MAX_WAIT_EMBED_SECONDS)
            try:
                # client.models.embed_content(model=str, contents=str|list[str], config=EmbedContentConfig)
                # Returns: response.embeddings = list[ContentEmbedding]; har ek .values = list[float]
                response = self.client.models.embed_content(
                    model=config.EMBEDDING_MODEL, contents=texts,
                    config=types.EmbedContentConfig(**kwargs))
                if not response.embeddings or len(response.embeddings) != len(texts):
                    raise UpstreamBusy("The embedding service returned an incomplete response. Please try again.")
                return [e.values for e in response.embeddings]
            except genai_errors.APIError as exc:
                self._handle_api_error(exc, attempt)
        raise UpstreamBusy("The AI is busy right now. Please try again in a moment.")

    # ------------------------------------------------------------------ errors
    def _handle_api_error(self, exc: genai_errors.APIError, attempt: int):
        """
        Google ke error ko samajh kar: retry (sleep karke return) ya friendly AppError raise.
        genai_errors.APIError ke fields: .code (HTTP int), .status (str), .message (str)
        """
        code = getattr(exc, "code", 0)
        log.warning("Gemini API error code=%s status=%s msg=%s", code,
                    getattr(exc, "status", ""), str(getattr(exc, "message", exc))[:300])
        if code in (429, 500, 502, 503, 504) and attempt < 2:
            time.sleep(2 ** (attempt + 1) * 2)        # 4s, phir 8s
            return
        if code == 429:
            raise QuotaExceeded("Google's free-tier limit is active right now. Please try again in a minute.",
                                retry_after=60)
        if code in (500, 502, 503, 504):
            raise UpstreamBusy("Google's AI server is busy. Please try again shortly.")
        if code in (401, 403) or (code == 400 and "API key" in str(exc)):
            raise ConfigProblem("The server's API key is invalid. Please tell the app owner.")
        if code == 404:
            raise ConfigProblem("The selected AI model isn't available. The app owner should check the configuration.")
        raise AppError("The AI couldn't respond. Please try again.")


# Module-level singleton: main.py startup par init_gateway() chalata hai.
gateway: GeminiGateway | None = None
quota_manager: QuotaManager | None = None

def init_gateway(api_key: str) -> GeminiGateway:
    """Input: API key. Quota manager + gateway banata hai aur globals me rakhta hai. Returns: gateway."""
    global gateway, quota_manager
    quota_manager = QuotaManager(config.safe_limits())
    gateway = GeminiGateway(api_key, quota_manager)
    return gateway

def get_gateway() -> GeminiGateway:
    """Returns: ready gateway (agar init nahi hua to RuntimeError)."""
    if gateway is None:
        raise RuntimeError("Gateway is not initialised. Call init_gateway() first.")
    return gateway