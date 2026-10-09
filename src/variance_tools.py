"""Agent tools for variance questions: diagnose_variance (deterministic report) and submit_diagnosis (Reflector checks on the
LLM's JSON, then the review queue). Design: docs/08-variance-diagnosis.md; the computation is in variance.py."""
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml
from anthropic import beta_tool
from neo4j import READ_ACCESS

import variance as v
from graph import driver
from news_tools import event_timeline

ROOT = Path(__file__).parent.parent
CONFIG = yaml.safe_load((ROOT / "knowledge" / "driver_series.yaml").read_text(encoding="utf-8"))
DIAGNOSES = ROOT / "data" / "diagnoses"
BASELINE_N = 3
_last: dict = {}  # the latest diagnosis, which submit_diagnosis checks the answer against


def read_all(query: str, **params) -> list[dict]:
    """Read-only query without read_graph's 50-row cap (series and edges are longer)."""
    with driver.session(default_access_mode=READ_ACCESS) as s:
        return s.execute_read(lambda tx: [r.data() for r in tx.run(query, **params)])


def load_series(concepts: list[str]) -> dict[str, list[tuple[str, float]]]:
    """Daily mean of verified price assessment midpoints, for each concept that has a series in driver_series.yaml."""
    out = {}
    for cid in concepts:
        spec = CONFIG["series"].get(cid)
        if not spec:
            continue
        rows = read_all(
            "MATCH (p:PriceAssessment)-[:OF]->(:Concept {id: $product}), (p)-[:AT]->(:Concept {id: $location}), "
            "(p)-[:BASIS]->(:Concept {id: $incoterm}) RETURN p.date AS date, avg(p.mid) AS mid ORDER BY date",
            **spec,
        )
        out[cid] = [(r["date"], r["mid"]) for r in rows]
    return out


def edges() -> list[tuple[str, str, str]]:
    rows = read_all("MATCH (a:Concept)-[r:DEPENDS_ON|MADE_FROM|TRANSITS]->(b:Concept) RETURN a.id AS a, type(r) AS rel, b.id AS b")
    return [(r["a"], r["rel"], r["b"]) for r in rows]


def path_exists(a: str, b: str) -> bool:
    return bool(read_all("MATCH (:Concept {id: $a})-[r]-(:Concept {id: $b}) RETURN count(r) AS n", a=a, b=b)[0]["n"])


# ---------- review queue (data/diagnoses) ----------

REVIEW_DECISIONS = ("approved", "corrected", "rejected")


def diagnosis_path(name: str) -> Path:
    """Path of a stored diagnosis; refuses names that would leave the folder."""
    path = DIAGNOSES / name
    assert path.suffix == ".json" and path.resolve().parent == DIAGNOSES.resolve() and path.exists(), f"unknown diagnosis {name}"
    return path


def list_diagnoses() -> list[dict]:
    out = []
    for p in sorted(DIAGNOSES.glob("*.json"), reverse=True) if DIAGNOSES.exists() else []:
        d = json.loads(p.read_text(encoding="utf-8"))
        out.append({"name": p.name, "status": d["status"], "metric": d["metric"], "product": d["product"], "period": d["diag"]["period"],
                    "llm_top1": d["answer"]["top1"], "deterministic_top1": d["diag"]["ranking"][0]["id"] if d["diag"]["ranking"] else None,
                    "reviewed_top1": (d.get("review") or {}).get("top1")})
    return out


def review_diagnosis(name: str, decision: str, top1: str = "", note: str = "", reviewer: str = "") -> dict:
    """Human decision. approved keeps the model's top-1; corrected sets the true top driver; rejected keeps it out of analogs."""
    assert decision in REVIEW_DECISIONS, f"decision must be one of {REVIEW_DECISIONS}"
    path = diagnosis_path(name)
    d = json.loads(path.read_text(encoding="utf-8"))
    ranked = [r["id"] for r in d["diag"]["ranking"]]
    if decision == "corrected":
        assert top1 in ranked, f"the corrected top driver must be one of {ranked}"
    label = {"approved": d["answer"]["top1"], "corrected": top1, "rejected": None}[decision]
    d["status"] = decision
    d["review"] = {"decision": decision, "top1": label, "note": note, "reviewer": reviewer, "at": datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(d, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return d["review"]


def reviewed_labels(metric_id: str, product_id: str) -> dict[str, str]:
    """{month: true top driver} from approved or corrected diagnoses; the latest review of a month wins."""
    labels = {}
    for p in sorted(DIAGNOSES.glob("*.json")) if DIAGNOSES.exists() else []:
        d = json.loads(p.read_text(encoding="utf-8"))
        review = d.get("review") or {}
        if d["metric"] == metric_id and d["product"] == product_id and review.get("top1"):
            labels[d["diag"]["period"]] = review["top1"]
    return labels


def run_diagnosis(metric_id: str, product_id: str, period: str, as_of: str = "") -> tuple[dict, list[dict], list[str]]:
    """Deterministic part: diagnosis, incidents on the top drivers and their routes, drivers without a series."""
    graph_edges = edges()
    series = load_series(list(CONFIG["series"]))
    with_series = {cid for cid, pts in series.items() if pts}
    cands = v.candidates(graph_edges, metric_id, product_id, with_series)
    assert cands, f"no driver of {metric_id} / {product_id} has a price series: check knowledge/driver_series.yaml and price_routes"
    as_of = as_of or v.month_bounds(period)[1]
    months = sorted({d[:7] for pts in series.values() for d, _ in pts if d <= as_of})
    history = [m for m in months if m < period and months and v.previous_months(m, BASELINE_N)[0] >= months[0]]
    ratios = CONFIG["proxy_ratios"].get(product_id)
    outcome = v.next_changes(v.proxy_margin(series, product_id, ratios)) if ratios else None
    episodes = v.library(cands, {c: [(d, x) for d, x in pts if d <= as_of] for c, pts in series.items()}, history, BASELINE_N, outcome,
                         labels=reviewed_labels(metric_id, product_id))
    diag = v.diagnose(cands, series, period, BASELINE_N, as_of, episodes)

    top = [r["id"] for r in diag["ranking"][:3]]
    concepts = sorted(set(top) | {route for r in diag["ranking"][:3] for route in r["routes"]})
    found = event_timeline.call({"concept_ids": concepts, "date_from": v.month_bounds(diag["baseline"][0])[0], "date_to": as_of})
    incidents = json.loads(found) if found.startswith("[") else []
    not_ranked = v.unranked(graph_edges, metric_id, product_id, with_series, set(CONFIG.get("covered", [])))
    return diag, incidents, not_ranked


@beta_tool
def diagnose_variance(metric_id: str, product_id: str, period: str, as_of: str = "") -> str:
    """Rank the drivers behind a metric's move in a month (e.g. why the DAP margin fell in August). Deterministic: candidates
    from the graph, each driver's move against its recent level and volatility, upstream moves that explain downstream ones,
    analog months, incidents. Returns an evidence report and the JSON schema to answer with; then call submit_diagnosis.

    Args:
        metric_id: Metric concept id, e.g. "gross_margin".
        product_id: Product concept id, e.g. "dap".
        period: Month, YYYY-MM.
        as_of: Optional YYYY-MM-DD; nothing published later is used. Default: end of the month.
    """
    diag, incidents, not_ranked = run_diagnosis(metric_id, product_id, period, as_of)
    _last.clear()
    _last.update(metric=metric_id, product=product_id, diag=diag, incidents=incidents)
    return v.report(diag, metric_id, product_id, incidents, not_ranked) + "\n\n" + v.ANSWER_SCHEMA


@beta_tool
def submit_diagnosis(answer_json: str) -> str:
    """Submit your ranking of the latest diagnose_variance report as JSON. Deterministic checks verify it (drivers from the
    ranking, propagation path in the graph, evidence ids from the report, outlook only from analogs, agreement with the
    deterministic top-1). Failed checks come back: fix and submit again. Accepted diagnoses go to human review.

    Args:
        answer_json: The JSON object described at the end of the diagnose_variance report.
    """
    assert _last, "call diagnose_variance first"
    answer = json.loads(answer_json)
    problems = v.check_answer(answer, _last["diag"], path_exists, _last["incidents"])
    if problems:
        return json.dumps({"status": "rejected", "problems": problems}, ensure_ascii=False)
    DIAGNOSES.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    name = f"{_last['metric']}__{_last['product']}__{_last['diag']['period']}__{stamp}.json"
    (DIAGNOSES / name).write_text(json.dumps({"status": "proposed", "answer": answer, **_last}, ensure_ascii=False, indent=1, default=str),
                                  encoding="utf-8")
    return json.dumps({"status": "accepted", "saved": name, "next": "Answer the user from the report and your JSON. Cite evidence ids."})
