"""Tests of the deterministic variance diagnosis (src/variance.py). No Neo4j needed: python -m pytest tests"""
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import eval_variance as bench  # noqa: E402
import variance as v  # noqa: E402

EDGES = [tuple(r) for r in yaml.safe_load((ROOT / "knowledge" / "ontology.yaml").read_text(encoding="utf-8"))["relations"]]
CANDS = v.candidates(EDGES, "gross_margin", "dap", set(bench.DRIVERS))
BY_ID = {c["id"]: c for c in CANDS}


def test_candidates_roles_and_paths():
    assert BY_ID["dap"]["role"] == "primary"
    assert BY_ID["ammonia"]["role"] == "direct" and BY_ID["ammonia"]["routes"] == ["hormuz"]
    assert BY_ID["sulfur"]["role"] == "direct"  # cash_cost DEPENDS_ON sulfur
    assert BY_ID["sulfur"]["downstream"] == ["sulfuric_acid", "phosphoric_acid", "dap"]
    assert BY_ID["sulfuric_acid"]["role"] == "propagation"
    assert v.unranked(EDGES, "gross_margin", "dap", set(bench.DRIVERS), {"revenue"}) == ["energy", "freight", "transfer_price"]


def test_evidence_detects_a_shock_and_its_onset():
    series = bench.simulate(1, ("sulfur", date(2025, 6, 9), 0.25))
    base = v.points_in_months(series["sulfur"], v.previous_months("2025-06", 3))
    e = v.evidence(series["sulfur"], v.month_bounds("2025-06"), base)
    assert e["direction"] == 1 and e["z"] > 3 and "2025-06-09" <= e["first_abnormal"] <= "2025-06-16"
    assert v.evidence(series["sulfur"], v.month_bounds("2025-06"), base[:2]) is None  # too little baseline to say anything


def test_downstream_move_is_explained_by_an_earlier_upstream_move_in_the_same_direction():
    up = {"first_abnormal": "2025-06-02", "direction": 1, "abnormality": 0.6}
    down = {"first_abnormal": "2025-06-20", "direction": 1, "abnormality": 0.6}
    cands = [{"id": "sulfur", "role": "direct", "downstream": ["sulfuric_acid"]}, {"id": "sulfuric_acid", "role": "direct", "downstream": []}]
    same = v.kg_scores(cands, {"sulfur": up, "sulfuric_acid": down})
    assert same["sulfur"] > same["sulfuric_acid"]
    opposite = v.kg_scores(cands, {"sulfur": {**up, "direction": -1}, "sulfuric_acid": down})
    assert opposite["sulfuric_acid"] == 0.6  # a falling input cannot explain a rising product


def test_earlier_move_counts_only_when_downstream_moves_now():
    cands = [{"id": "sulfur", "role": "direct", "downstream": ["sulfuric_acid"]}, {"id": "sulfuric_acid", "role": "direct", "downstream": []}]
    before = {"sulfur": {"first_abnormal": "2025-05-05", "direction": 1, "abnormality": 0.7}}
    quiet = {"sulfuric_acid": {"first_abnormal": None, "direction": 1, "abnormality": 0.1}}
    moving = {"sulfuric_acid": {"first_abnormal": "2025-06-10", "direction": 1, "abnormality": 0.5}}
    assert v.kg_scores(cands, quiet, before).get("sulfur", 0) == 0
    assert v.kg_scores(cands, moving, before)["sulfur"] > v.kg_scores(cands, moving, before)["sulfuric_acid"]


def test_diagnosis_finds_injected_shock_and_ignores_the_future():
    series = bench.simulate(2, ("ammonia", date(2025, 9, 4), 0.2))
    d = v.diagnose(CANDS, series, "2025-09", 3)
    assert d["ranking"][0]["id"] == "ammonia"
    future = bench.simulate(2, ("sulfur", date(2025, 10, 6), 0.4))  # a shock after as_of must change nothing
    assert v.diagnose(CANDS, future, "2025-09", 3)["ranking"][0]["id"] == v.diagnose(CANDS, bench.simulate(2), "2025-09", 3)["ranking"][0]["id"]


def test_retrieve_leaves_out_the_query_month_and_later_months():
    eps = [{"period": m, "vector": {"sulfur": 3.0}, "top": "sulfur", "next_change": None} for m in ("2025-05", "2025-06", "2025-07")]
    got = [e["period"] for e in v.retrieve({"sulfur": 2.0}, eps, "2025-06", "2025-06-30")]
    assert got == ["2025-05"]


def test_check_answer():
    d = v.diagnose(CANDS, bench.simulate(3, ("sulfur", date(2025, 3, 3), 0.3)), "2025-03", 3)
    top = d["ranking"][0]
    good = {"top1": top["id"], "top3": [{"driver": top["id"], "why": "x", "evidence": [top["evidence_id"]]}],
            "propagation_path": ["sulfur", "sulfuric_acid", "phosphoric_acid", "dap"], "confidence": "high",
            "uncertainty": "single source", "outlook": []}
    graph = {frozenset(e[::2]) for e in EDGES}
    exists = lambda a, b: frozenset((a, b)) in graph
    assert v.check_answer(good, d, exists) == []
    bad = {**good, "top1": "urea", "propagation_path": ["sulfur", "dap"], "top3": [{"driver": top["id"], "evidence": ["ev:made-up"]}],
           "outlook": [{"claim": "prices will rise", "evidence": []}]}
    problems = " ".join(v.check_answer(bad, d, exists))
    for expected in ("not in the ranking", "not in the graph", "unknown evidence", "without evidence", "deterministic top-1"):
        assert expected in problems
