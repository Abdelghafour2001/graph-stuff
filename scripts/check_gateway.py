"""Check that the Bifrost gateway can serve this project: run on the office network / VPN, with .env filled in.

  python scripts/check_gateway.py

Prints one line per capability (models, chat, Qwen thinking toggle, JSON, tool calling, rerank, embeddings) and the .env
lines to use. Nothing is written anywhere.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
import gateway  # noqa: E402

results = []


def check(name, fn):
    t0 = time.time()
    try:
        ok, detail = fn()
    except Exception as e:  # report and continue: the point is the full picture
        ok, detail = False, f"{type(e).__name__}: {str(e)[:200]}"
    results.append((name, ok, detail, time.time() - t0))
    print(f"{'OK  ' if ok else 'FAIL'} {name:<16} {time.time() - t0:5.1f}s  {detail}", flush=True)


def main():
    assert gateway.configured(), "set BIFROST_BASE_URL and BIFROST_API_KEY in .env"
    c = gateway.client()
    ids = []

    def models():
        ids.extend(m.id for m in c.models.list().data)
        return bool(ids), ", ".join(ids)
    check("models", models)
    chat = os.environ.get("BIFROST_CHAT_MODEL") or next((m for m in ids if "qwen" in m.lower() and "embed" not in m.lower() and "rerank" not in m.lower()), None)
    rerank = os.environ.get("BIFROST_RERANK_MODEL") or next((m for m in ids if "rerank" in m.lower()), None)
    embed = os.environ.get("BIFROST_EMBED_MODEL") or next((m for m in ids if "embed" in m.lower()), None)
    os.environ.setdefault("BIFROST_CHAT_MODEL", chat or "")
    q = [{"role": "user", "content": "What is 17 * 23? Answer with the number only."}]

    def thinking(on):
        def run():
            r = c.chat.completions.create(model=chat, messages=q, max_tokens=2048, extra_body={"chat_template_kwargs": {"enable_thinking": on}})
            m = r.choices[0].message
            reasoning = (m.model_extra or {}).get("reasoning_content") or ("<think>" in (m.content or "") and "inline <think>")
            answer = gateway.strip_thinking(m.content)
            return "391" in answer, f"answer={answer!r} tokens={r.usage.completion_tokens} reasoning={'yes' if reasoning else 'no'}"
        return run
    check("chat thinking", thinking(True))
    check("chat no-think", thinking(False))

    def json_mode():
        r = c.chat.completions.create(model=chat, response_format={"type": "json_object"}, extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                                      messages=[{"role": "system", "content": "Return JSON {low, high} for the price."},
                                                {"role": "user", "content": "DAP prices are unchanged at $695-720/t fob China."}])
        d = json.loads(gateway.strip_thinking(r.choices[0].message.content))
        return d.get("low") == 695 and d.get("high") == 720, json.dumps(d)
    check("json", json_mode)

    def tools():
        spec = [{"type": "function", "function": {"name": "lookup_term", "description": "Find the concept a business word refers to.",
                 "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}}]
        r = c.chat.completions.create(model=chat, tools=spec, extra_body=gateway.extra_body("chat"),
                                      messages=[{"role": "user", "content": "What does ACP mean at OCP? Use the tool."}])
        calls = r.choices[0].message.tool_calls or []
        return bool(calls), (f"{calls[0].function.name}({calls[0].function.arguments})" if calls else
                             "no tool call: vLLM needs --enable-auto-tool-choice and a Qwen tool parser")
    check("tool calling", tools)

    if rerank:
        os.environ["BIFROST_RERANK_MODEL"] = rerank
        def rr():
            docs = ["Le soufre sert à produire l'acide sulfurique.", "Morocco won the football match.", "Sulphur is burned to make sulfuric acid.", "Urea is nitrogen."]
            ranked = gateway.rerank("sulfur input of sulfuric acid", docs)
            return ranked[0][0] in (0, 2) and ranked[-1][0] in (1, 3), " > ".join(f"{i}:{s:.2f}" for i, s in ranked)
        check("rerank", rr)
    else:
        results.append(("rerank", False, "no rerank model listed", 0)); print("FAIL rerank           no rerank model listed")

    if embed:
        def emb():
            v = gateway.embed(["prix du DAP", "DAP price", "football"], embed)
            dot = lambda a, b: sum(x * y for x, y in zip(a, b)) / ((sum(x * x for x in a) * sum(y * y for y in b)) ** 0.5)
            return dot(v[0], v[1]) > dot(v[0], v[2]), f"dim {len(v[0])}, FR~EN {dot(v[0], v[1]):.2f} vs unrelated {dot(v[0], v[2]):.2f}"
        check("embeddings", emb)

    print("\n.env for this gateway:")
    print("LLM_PROVIDER=bifrost")
    print(f"BIFROST_CHAT_MODEL={chat}")
    print(f"BIFROST_RERANK_MODEL={rerank or '<none listed>'}")
    if embed:
        print(f"BIFROST_EMBED_MODEL={embed}")
    print("BIFROST_THINKING=true")
    must = {"models", "chat no-think", "json", "tool calling"}
    ready = all(ok for n, ok, _, _ in results if n in must)
    print(f"\nagent ready: {'yes' if ready else 'no'} (needs models, chat, json, tool calling); graph-build reranking: {'yes' if any(n == 'rerank' and ok for n, ok, _, _ in results) else 'no'}")


if __name__ == "__main__":
    main()
