"""HTTP API over the agent, the workbook graph and the spec review queue. Run: uvicorn api:app --port 8010 (from src/)."""
import json
import os
import shutil
from urllib.parse import urlparse
from pathlib import Path

import openai
import yaml
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

import agent
import excel_tools
from graph import driver, read_graph
from diff_vs_db import compare
from spec_executor import check, execute, validate
import variance
import variance_tools
from variance_tools import run_diagnosis

ROOT = Path(__file__).parent.parent
SPECS = ROOT / "specs"
STATUSES = ("proposed", "rejected", "approved")

app = FastAPI(title="OCP graph agent")


class AskRequest(BaseModel):
    question: str
    history: list[dict]


@app.get("/health")
def health() -> dict:
    return {"ok": True, "counts": read_graph("MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY n DESC")}


@app.post("/ask")
def ask(req: AskRequest) -> dict:
    history = list(req.history)
    try:
        answer, trace = agent.ask(history, req.question)
    except openai.APIError as e:
        raise HTTPException(502, llm_error(e)) from e
    return {"answer": answer, "trace": trace, "history": history}


def llm_error(e: openai.APIError) -> str:
    """What failed when calling the LLM provider, and what to change in .env."""
    provider = os.environ.get("LLM_PROVIDER", "")
    if provider == "azure_openai":
        where = urlparse(os.environ.get("AZURE_OPENAI_ENDPOINT", "")).hostname or "AZURE_OPENAI_ENDPOINT (empty)"
        model = os.environ.get("AZURE_OPENAI_AGENT_DEPLOYMENT", "")
        fix_model = ("set AZURE_OPENAI_AGENT_DEPLOYMENT to a deployment name listed in Azure AI Foundry > Deployments "
                     "for this resource (the deployment name, not the model name)")
    else:
        where, model, fix_model = "the LLM endpoint", "", "check the model settings in .env"
    if isinstance(e, openai.APIConnectionError):
        return (f"Cannot reach {where}: {str(e.__cause__ or e).rstrip('.')}. Check the endpoint in .env, and that this machine (or the "
                "container: DNS, VPN, proxy) can resolve and reach it. Test with: python scripts/check_azure.py")
    if isinstance(e, openai.NotFoundError):
        return f"Deployment '{model}' not found on {where}: {fix_model}. Test with: python scripts/check_azure.py"
    if isinstance(e, openai.AuthenticationError):
        return f"Rejected by {where} (401): check AZURE_OPENAI_API_KEY belongs to this resource."
    status = getattr(e, "status_code", "")
    return f"LLM call to {where} failed {status}: {getattr(e, 'message', e)}"


@app.get("/concepts")
def concepts(q: str) -> list[dict]:
    found = agent.lookup_term(q)
    return json.loads(found) if found.startswith("[") else []


@app.get("/sheets")
def sheets(concept: list[str] = Query(default=[]), role: str = "") -> list[dict]:
    with driver.session() as s:
        return s.run(
            "MATCH (x:Sheet) WHERE ($role = '' OR x.role = $role) "
            "AND all(cid IN $concepts WHERE (x)-[:MENTIONS]->(:Concept {id: cid})) "
            "OPTIONAL MATCH (x)-[m:MENTIONS]->(c:Concept) WHERE c.id IN $concepts "
            "RETURN x.file AS file, x.name AS sheet, x.role AS role, x.description AS description, x.rows AS rows, x.cols AS cols, "
            "x.header_depth AS header_depth, x.blocks AS blocks, x.formulas AS formulas, coalesce(sum(m.n), 0) AS strength "
            "ORDER BY strength DESC, file, sheet",
            role=role, concepts=concept,
        ).data()


@app.get("/sheet")
def sheet(file: str, name: str) -> dict:
    return json.loads(excel_tools.describe_sheet(file, name))


@app.get("/sheet/range")
def sheet_range(file: str, name: str, cells: str) -> dict:
    return {"text": excel_tools.read_range(file, name, cells)}


@app.get("/specs")
def specs() -> list[dict]:
    out = []
    for status in STATUSES:
        for p in sorted((SPECS / status).glob("*.checks.json"), reverse=True):
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append({"status": status, "name": p.name.removesuffix(".checks.json"), "rows": data["rows"],
                        "failed": [c["check"] for c in data["checks"] if not c["ok"]]})
    return out


def spec_path(status: str, name: str, suffix: str = ".yaml") -> Path:
    """Path of a spec file; rejects unknown statuses and names that would leave the specs folder."""
    path = SPECS / status / f"{name}{suffix}"
    if status not in STATUSES or path.resolve().parent != (SPECS / status).resolve():
        raise HTTPException(404, "unknown spec")
    return path


@app.get("/specs/{status}/{name}")
def spec(status: str, name: str) -> dict:
    folder = spec_path(status, name).parent
    if not (folder / f"{name}.yaml").exists():
        raise HTTPException(404, "unknown spec")
    return {"yaml": (folder / f"{name}.yaml").read_text(encoding="utf-8"), **json.loads((folder / f"{name}.checks.json").read_text(encoding="utf-8"))}


@app.post("/specs/{status}/{name}/run")
def run_spec(status: str, name: str) -> dict:
    spec_dict = yaml.safe_load(spec_path(status, name).read_text(encoding="utf-8"))
    validate(spec_dict)
    rows, ctx = execute(spec_dict)
    return {"checks": check(spec_dict, rows, ctx), "rows": len(rows), "sample": rows[:500]}


@app.post("/specs/{status}/{name}/compare")
def compare_spec(status: str, name: str) -> dict:
    """Compare the spec's values with what the old ingestion pipeline stored for the same sheet."""
    spec_dict = yaml.safe_load(spec_path(status, name).read_text(encoding="utf-8"))
    validate(spec_dict)
    return compare(spec_dict)


@app.post("/specs/{status}/{name}/approve")
def approve(status: str, name: str) -> dict:
    """Human decision. A rejected spec can be approved too (reviewer overrides a check)."""
    spec_path(status, name)
    (SPECS / "approved").mkdir(exist_ok=True)
    for suffix in (".yaml", ".checks.json"):
        shutil.move(spec_path(status, name, suffix), SPECS / "approved" / f"{name}{suffix}")
    return {"approved": name}


@app.get("/news/prices")
def news_prices(product: str) -> list[dict]:
    """Monthly averages of quote-verified price assessments for a product, per location and incoterm."""
    with driver.session() as s:
        return s.run(
            "MATCH (p:PriceAssessment)-[:OF]->(:Concept {id: $product}), (p)-[:AT]->(l:Concept), (p)-[:BASIS]->(i:Concept) "
            "RETURN substring(p.date, 0, 7) AS month, l.name + ' ' + i.name AS route, count(*) AS n, round(avg(p.mid), 1) AS avg_mid ORDER BY month",
            product=product,
        ).data()


@app.get("/news/events")
def news_events(concept: list[str] = Query(default=[]), date_from: str = "2026-01-01", date_to: str = "2026-12-31") -> list[dict]:
    with driver.session() as s:
        return s.run(
            "MATCH (i:Incident)-[:AFFECTS]->(c:Concept) WHERE c.id IN $concepts AND i.date >= $from AND i.date <= $to "
            "MATCH (e:Event)-[:INSTANCE_OF]->(i), (e)-[:REPORTED_IN]->(a:Article) "
            "RETURN i.date AS date, i.type AS type, i.summary AS summary, i.reports AS reports, "
            "[(i)-[:AFFECTS]->(x:Concept) | x.id] AS affects, collect(DISTINCT a.id)[..5] AS article_ids ORDER BY date",
            concepts=concept, **{"from": date_from, "to": date_to},
        ).data()


@app.get("/entities/assets")
def assets() -> list[dict]:
    with driver.session() as s:
        return s.run(
            "MATCH (e:SourceEntity)-[r:SAME_AS]->(a:Asset) OPTIONAL MATCH (a)-[:LOCATED_AT]->(site:Concept) "
            "RETURN a.id AS asset_id, a.name AS asset, a.kind AS kind, site.id AS site, a.confidence AS confidence, a.reason AS reason, "
            "head(collect(r.status)) AS status, count(e) AS records, sum(e.metrics) AS metrics, collect(e.name) AS source_names "
            "ORDER BY records DESC, metrics DESC"
        ).data()


@app.post("/entities/assets/{asset_id}/approve")
def approve_asset(asset_id: str) -> dict:
    """Human decision: accept all SAME_AS merges into this asset."""
    with driver.session() as s:
        n = s.run("MATCH (:SourceEntity)-[r:SAME_AS]->(:Asset {id: $id}) SET r.status = 'approved' RETURN count(r) AS n", id=asset_id).single()["n"]
    return {"approved": asset_id, "records": n}


@app.get("/variance")
def variance_diagnosis(metric: str, product: str, period: str, as_of: str = "") -> dict:
    """Deterministic part of a variance diagnosis (no LLM): ranked drivers, analogs, incidents, and the report the LLM would get."""
    diag, incidents, not_ranked = run_diagnosis(metric, product, period, as_of)
    return {**diag, "incidents": incidents, "not_ranked": not_ranked, "report": variance.report(diag, metric, product, incidents, not_ranked)}


class Review(BaseModel):
    decision: str
    top1: str = ""
    note: str = ""
    reviewer: str = ""


@app.get("/diagnoses")
def diagnoses() -> list[dict]:
    return variance_tools.list_diagnoses()


@app.get("/diagnoses/{name}")
def diagnosis(name: str) -> dict:
    try:
        return json.loads(variance_tools.diagnosis_path(name).read_text(encoding="utf-8"))
    except AssertionError as e:
        raise HTTPException(404, str(e))


@app.post("/diagnoses/{name}/review")
def review(name: str, body: Review) -> dict:
    """Human decision on a diagnosis; approved and corrected ones become labelled analogs for later diagnoses."""
    try:
        return variance_tools.review_diagnosis(name, body.decision, body.top1, body.note, body.reviewer)
    except AssertionError as e:
        raise HTTPException(404 if "unknown" in str(e) else 422, str(e))


@app.get("/eval")
def eval_results() -> list[dict]:
    path = ROOT / "data" / "eval_results.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
