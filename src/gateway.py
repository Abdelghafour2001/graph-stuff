"""Bifrost gateway (OpenAI-compatible, in front of vLLM): chat with Qwen reasoning, embeddings, rerank.

Settings (.env):
  LLM_PROVIDER=bifrost
  BIFROST_BASE_URL=http://<gateway>:8080/v1
  BIFROST_API_KEY=sk-bf-...            virtual key; sent as x-bf-vk and as Bearer (Bifrost accepts both)
  BIFROST_CHAT_MODEL=<qwen model id>   high reasoning model for agents (ids may carry a provider prefix, e.g. vllm/qwen3...)
  BIFROST_FAST_MODEL=<model id>        optional, bulk extraction without thinking; defaults to the chat model
  BIFROST_RERANK_MODEL=<model id>      cross-encoder used to rank candidates when building the graph
  BIFROST_THINKING=true                Qwen3 thinking for the agent model (chat_template_kwargs.enable_thinking)

Use Chat Completions, not the Responses API: Bifrost drops the reasoning block on /v1/responses for non-OpenAI model
names (maximhq/bifrost#6779). Qwen reasoning on vLLM is switched with chat_template_kwargs, which Bifrost passes through.
"""
import os
import re

import requests
from dotenv import load_dotenv

load_dotenv()
THINK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def configured() -> bool:
    return bool(os.environ.get("BIFROST_BASE_URL") and os.environ.get("BIFROST_API_KEY"))


def headers() -> dict:
    key = os.environ["BIFROST_API_KEY"]
    return {"x-bf-vk": key, "Authorization": f"Bearer {key}"}


def client():
    import openai
    return openai.OpenAI(base_url=os.environ["BIFROST_BASE_URL"], api_key=os.environ["BIFROST_API_KEY"],
                         default_headers={"x-bf-vk": os.environ["BIFROST_API_KEY"]}, timeout=300)


def model(role: str = "chat") -> str:
    if role == "fast":
        return os.environ.get("BIFROST_FAST_MODEL") or os.environ["BIFROST_CHAT_MODEL"]
    return os.environ["BIFROST_CHAT_MODEL"]


def extra_body(role: str = "chat") -> dict:
    """Thinking on for the agent model (if BIFROST_THINKING), off for bulk extraction and strict JSON."""
    thinking = role == "chat" and os.environ.get("BIFROST_THINKING", "true").lower() == "true"
    return {"chat_template_kwargs": {"enable_thinking": thinking}}


def strip_thinking(text: str | None) -> str:
    """Qwen may return its reasoning inline as <think>...</think>; answers and JSON must not contain it."""
    return THINK.sub("", text or "").strip()


def rerank(query: str, documents: list[str], top_n: int | None = None) -> list[tuple[int, float]]:
    """[(document index, relevance score)] best first, from the gateway's cross-encoder (/v1/rerank, then /rerank)."""
    if not documents:
        return []
    body = {"model": os.environ["BIFROST_RERANK_MODEL"], "query": query, "documents": documents}
    if top_n:
        body["top_n"] = top_n
    base = os.environ["BIFROST_BASE_URL"].rstrip("/")
    last = None
    for url in (f"{base}/rerank", f"{base.removesuffix('/v1')}/rerank"):
        resp = requests.post(url, headers=headers(), json=body, timeout=120)
        if resp.ok:
            results = resp.json().get("results", [])
            return sorted(((r["index"], float(r["relevance_score"])) for r in results), key=lambda x: -x[1])
        last = f"{url} -> {resp.status_code} {resp.text[:200]}"
    raise RuntimeError(f"rerank failed: {last}")


def embed(texts: list[str], embed_model: str | None = None) -> list[list[float]]:
    m = embed_model or os.environ["BIFROST_EMBED_MODEL"]
    return [d.embedding for d in client().embeddings.create(model=m, input=texts).data]
