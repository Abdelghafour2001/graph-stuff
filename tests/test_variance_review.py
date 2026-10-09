"""Review queue of variance diagnoses (src/variance_tools.py): decisions, labels for analogs, path safety. No Neo4j needed."""
import json
import os
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
for k, val in {"NEO4J_URI": "bolt://localhost:7687", "NEO4J_USER": "neo4j", "NEO4J_PASSWORD": "x"}.items():
    os.environ.setdefault(k, val)  # the driver is created lazily; nothing connects
import eval_variance as bench  # noqa: E402
import variance as v  # noqa: E402
import variance_tools as vt  # noqa: E402
from test_variance import CANDS  # noqa: E402


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.setattr(vt, "DIAGNOSES", tmp_path)
    diag = v.diagnose(CANDS, bench.simulate(5, ("sulfur", date(2025, 5, 5), 0.3)), "2025-05", 3)
    stored = {"status": "proposed", "metric": "gross_margin", "product": "dap", "diag": diag, "incidents": [],
              "answer": {"top1": diag["ranking"][0]["id"]}}
    (tmp_path / "d1.json").write_text(json.dumps(stored), encoding="utf-8")
    return diag


def test_review_decisions_and_labels(queue):
    assert vt.list_diagnoses()[0]["status"] == "proposed"
    assert vt.reviewed_labels("gross_margin", "dap") == {}
    vt.review_diagnosis("d1.json", "approved", reviewer="controller")
    assert vt.reviewed_labels("gross_margin", "dap") == {"2025-05": queue["ranking"][0]["id"]}
    vt.review_diagnosis("d1.json", "corrected", top1="ammonia", note="contract price, not spot")
    assert vt.reviewed_labels("gross_margin", "dap") == {"2025-05": "ammonia"}
    assert vt.list_diagnoses()[0]["reviewed_top1"] == "ammonia"
    vt.review_diagnosis("d1.json", "rejected")
    assert vt.reviewed_labels("gross_margin", "dap") == {}


def test_review_refuses_bad_input(queue):
    with pytest.raises(AssertionError, match="must be one of"):
        vt.review_diagnosis("d1.json", "corrected", top1="urea")
    with pytest.raises(AssertionError, match="decision"):
        vt.review_diagnosis("d1.json", "maybe")
    with pytest.raises(AssertionError, match="unknown diagnosis"):
        vt.review_diagnosis("../../README.md", "approved")


def test_reviewed_label_overrides_the_automatic_one_in_analogs():
    series = bench.simulate(6)
    months = [f"2025-{m:02d}" for m in range(5, 9)]
    auto = {e["period"]: e for e in v.library(CANDS, series, months, 3)}
    labelled = {e["period"]: e for e in v.library(CANDS, series, months, 3, labels={"2025-06": "phosphate_rock"})}
    assert labelled["2025-06"]["top"] == "phosphate_rock" and labelled["2025-06"]["label"] == "reviewed"
    assert labelled["2025-07"]["top"] == auto["2025-07"]["top"] and labelled["2025-07"]["label"] == "automatic"
