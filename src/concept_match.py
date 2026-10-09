"""Match free-text labels (branch rows, sheet headers, source entity names) to graph concepts.

Two stages: a cheap lexical pass over every term of every concept picks candidates; the gateway's cross-encoder reranks
them when BIFROST_RERANK_MODEL is set (gateway.rerank), else the lexical score stands. A match above ACCEPT is used
directly; between REVIEW and ACCEPT it goes to the term review queue; below, the label stays unknown.

Concepts and terms come from the graph when it is up, or from knowledge/*.yaml (no database needed).
"""
import os
import re
import unicodedata
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
ACCEPT, REVIEW = 0.75, 0.40
STOP = {"de", "du", "des", "la", "le", "les", "et", "en", "the", "of", "and", "per", "par", "a", "au", "aux", "t", "kt", "mt"}


def norm(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()
    return [w for w in re.findall(r"[a-z0-9]+", text) if w not in STOP]


def concepts_from_yaml() -> list[dict]:
    """[{id, kind, name, terms}] from the ontology and reviewed term additions."""
    onto = yaml.safe_load((ROOT / "knowledge" / "ontology.yaml").read_text(encoding="utf-8"))
    by_id = {c["id"]: {"id": c["id"], "kind": c["kind"], "name": c["name"], "terms": list(c["terms"]) + [c["name"]]} for c in onto["concepts"]}
    extra = ROOT / "knowledge" / "term_additions.yaml"
    for t in (yaml.safe_load(extra.read_text(encoding="utf-8")) or {}).get("terms", []) if extra.exists() else []:
        if t["concept"] in by_id:
            by_id[t["concept"]]["terms"].append(t["text"])
    return list(by_id.values())


def lexical(label: str, concept: dict) -> float:
    """Best term score: a term whose words are all in the label scores by how much of the label it covers; abbreviations
    (DAP, ACP) must match a whole word."""
    words = set(norm(label))
    best = 0.0
    for term in concept["terms"]:
        tw = norm(term)
        if not tw or not set(tw) <= words:
            continue
        best = max(best, 0.5 + 0.5 * len(tw) / max(len(words), 1))
    return best


def candidates(label: str, concepts: list[dict], kinds=None, k: int = 8) -> list[tuple[dict, float]]:
    """kinds: allowed concept kinds; when a sequence, earlier kinds win ties (a consumption ratio is about the input)."""
    order = list(kinds) if isinstance(kinds, (list, tuple)) else []
    pool = [c for c in concepts if not kinds or c["kind"] in kinds]
    scored = sorted(((c, lexical(label, c)) for c in pool), key=lambda x: (-x[1], order.index(x[0]["kind"]) if x[0]["kind"] in order else 0))
    return [x for x in scored[:k] if x[1] > 0]


def match(label: str, concepts: list[dict], kinds=None) -> dict:
    """{label, concept, score, decision: accept | review | unknown, ranked_by}"""
    cands = candidates(label, concepts, kinds)
    if not cands:
        return {"label": label, "concept": None, "score": 0.0, "decision": "unknown", "ranked_by": "lexical"}
    ranked_by = "lexical"
    if os.environ.get("BIFROST_RERANK_MODEL") and len(cands) > 1:
        import gateway
        docs = [f"{c['name']} ({c['kind']}): {', '.join(c['terms'][:6])}" for c, _ in cands]
        order = gateway.rerank(label, docs)
        cands = [(cands[i][0], score) for i, score in order]
        ranked_by = "rerank"
    concept, score = cands[0]
    preferred = isinstance(kinds, (list, tuple)) and len(cands) > 1 and cands[1][1] == score and cands[0][0]["kind"] != cands[1][0]["kind"]
    unique = len(cands) == 1 or cands[1][1] < score or preferred  # no other concept matches as well, or the kind order decides
    decision = "accept" if score >= ACCEPT or (unique and score >= 0.6 and ranked_by == "lexical") else "review" if score >= REVIEW else "unknown"
    return {"label": label, "concept": concept["id"], "kind": concept["kind"], "score": round(score, 3), "decision": decision,
            "ranked_by": ranked_by, "alternatives": [c["id"] for c, _ in cands[1:3]]}
