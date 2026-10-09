"""diagnose_variance: rank the drivers behind a metric's move in a period (design: docs/08-variance-diagnosis.md).

Deterministic, no LLM: candidates from the graph, deviation of each driver's series against a baseline, a role-weighted
score, analog months retrieved by z-vector, a combined ranking voted over weekly windows. The LLM only reranks and
explains the report; check_answer() verifies its JSON against the diagnosis.

Everything here is pure (series and edges come in as arguments), so it runs and is tested without Neo4j.
Series format: {concept_id: [(YYYY-MM-DD, value), ...]}. Edges: [(src, REL, dst), ...] as in ontology.yaml.
"""
import math
from collections import defaultdict, deque
from datetime import date, timedelta
from statistics import fmean, pstdev

ROLE_WEIGHT = {"primary": 1.0, "direct": 1.0, "propagation": 0.9}  # a mild prior: the graph mainly explains away (below)
EXPLAIN_AWAY = 0.8         # a move that follows an earlier upstream move is mostly its consequence
PROPAGATION_SUPPORT = 0.2  # weight of downstream confirmation (sulfur moved, then so did sulfuric acid)
PASS_THROUGH = 1.0         # weight of an earlier move whose consequences show up in the period
K_SIGMA = 2.0              # a point is abnormal beyond K_SIGMA baseline standard deviations
CLIP = 30.0                # z beyond this adds nothing; below it, a log scale keeps one wild point from dominating
ALPHA = 0.8                # weight of evidence vs analogs in the combined score
TOP_K_ANALOGS = 3
LOOKBACK = 1               # months before the period also searched for causes: a July jump explains an August pass-through
TRAVERSED = {"DEPENDS_ON", "MADE_FROM"}


# ---------- periods ----------

def month_bounds(period: str) -> tuple[str, str]:
    y, m = map(int, period.split("-"))
    start = date(y, m, 1)
    end = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
    return start.isoformat(), end.isoformat()


def previous_months(period: str, n: int) -> list[str]:
    y, m = map(int, period.split("-"))
    out = []
    for _ in range(n):
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        out.append(f"{y:04d}-{m:02d}")
    return out[::-1]


def weeks(period: str) -> list[tuple[str, str]]:
    """Days 1-7, 8-14, 15-21, 22-end of the month."""
    start, end = month_bounds(period)
    p = period + "-"
    return [(p + "01", p + "07"), (p + "08", p + "14"), (p + "15", p + "21"), (p + "22", end)]


def in_months(points, months: list[str]) -> list[float]:
    return [v for d, v in points if d[:7] in months]


def points_in_months(points, months: list[str]) -> list[tuple[str, float]]:
    return [(d, v) for d, v in points if d[:7] in months]


def between(points, start: str, end: str) -> list[tuple[str, float]]:
    return [(d, v) for d, v in points if start <= d <= end]


# ---------- 1. candidates ----------

def candidates(edges: list, metric: str, product: str, with_series: set[str]) -> list[dict]:
    """Drivers that can move `metric` of `product`, with role and path.

    primary: the product itself (its price is the revenue side).
    direct: a direct MADE_FROM input of the product, or a leaf reached from the metric through DEPENDS_ON.
    propagation: reached only through two MADE_FROM hops or more.
    Only concepts with a series can be ranked; routes they TRANSITS are attached as context.
    """
    out = defaultdict(list)
    for s, rel, d in edges:
        if rel in TRAVERSED:
            out[s].append((rel, d))
    made_from_paths = _paths(out, product, {"MADE_FROM"})
    depends_paths = _paths(out, metric, {"DEPENDS_ON"})
    routes = defaultdict(list)
    for s, rel, d in edges:
        if rel == "TRANSITS":
            routes[s].append(d)

    found = {}
    if product in with_series:
        found[product] = {"id": product, "role": "primary", "path": [product]}
    for cid, path in made_from_paths.items():
        if cid in with_series and cid != product:
            found[cid] = {"id": cid, "role": "direct" if len(path) == 2 else "propagation", "path": path}
    for cid, path in depends_paths.items():
        if cid in with_series and cid != product and (cid not in found or found[cid]["role"] == "propagation"):
            # keep the physical MADE_FROM path when there is one: it is what propagation support follows
            found[cid] = {"id": cid, "role": "direct", "path": found.get(cid, {}).get("path") or path}
    for c in found.values():
        c["routes"] = sorted(routes.get(c["id"], []))
        c["downstream"] = [x for x in made_from_paths.get(c["id"], [])[:-1] if x in with_series][::-1]  # toward the product
    return sorted(found.values(), key=lambda c: (list(ROLE_WEIGHT).index(c["role"]), c["id"]))


def unranked(edges: list, metric: str, product: str, with_series: set[str], covered: set[str] = frozenset()) -> list[str]:
    """Leaf drivers the graph reaches but that have no series: they cannot be ranked, and the report must say so."""
    out = defaultdict(list)
    for s, rel, d in edges:
        if rel in TRAVERSED:
            out[s].append((rel, d))
    reached = set(_paths(out, product, {"MADE_FROM"})) | set(_paths(out, metric, {"DEPENDS_ON"}))
    leaves = {n for n in reached if not out.get(n)}
    return sorted(leaves - with_series - set(covered) - {metric, product})


def _paths(out: dict, start: str, rels: set[str]) -> dict[str, list[str]]:
    """Shortest path from start to every reachable node through rels (BFS)."""
    paths, queue = {start: [start]}, deque([start])
    while queue:
        n = queue.popleft()
        for rel, d in out.get(n, []):
            if rel in rels and d not in paths:
                paths[d] = paths[n] + [d]
                queue.append(d)
    return paths


# ---------- 2. evidence ----------

def evidence(points, window: tuple[str, str], baseline: list[tuple[str, float]]) -> dict | None:
    """How surprising the window is for this driver. None when there is not enough data to say anything.

    Prices drift like random walks, so a move is measured from the most recent level (the last baseline month), and scaled
    by the driver's own volatility (std of log returns between consecutive baseline observations), grown with the distance
    between the two windows. A 10% move is routine for ammonia and exceptional for phosphate rock.
    """
    win = between(points, *window)
    baseline = sorted(baseline)
    if len(baseline) < 4 or not win or min(x for _, x in baseline + win) <= 0:
        return None
    returns = [math.log(b / a) for (_, a), (_, b) in zip(baseline, baseline[1:])]
    sigma = max(pstdev(returns), 1e-4)
    last_month = baseline[-1][0][:7]
    recent = [x for d, x in baseline if d[:7] == last_month]
    ref = fmean(recent)
    values = [x for _, x in win]
    scale = sigma * math.sqrt(max(1.0, (len(recent) + len(values)) / 2))
    move = math.log(fmean(values) / ref)
    z = abs(move) / scale
    max_z = max(abs(math.log(x / ref)) for x in values) / scale
    onset = next((d for d, x in win if abs(math.log(x / ref)) > K_SIGMA * scale), None)
    score = math.log1p(min(CLIP, 0.5 * z + 0.5 * max_z)) / math.log1p(CLIP)
    return {"delta": round(fmean(values) - ref, 2), "pct": round(100 * (fmean(values) / ref - 1), 1), "z": round(z, 2),
            "max_z": round(max_z, 2), "direction": (move > 0) - (move < 0), "first_abnormal": onset,
            "abnormality": round(score, 3), "reference": round(ref, 2), "n": len(values)}


# ---------- 3. KG score ----------

def kg_scores(cands: list[dict], now: dict[str, dict | None], before: dict[str, dict | None] | None = None) -> dict[str, float]:
    """Score each driver under two hypotheses and keep the stronger one.

    moved now:      w_role x a_now(c) x (1 - EXPLAIN_AWAY x min(1, a(u*) / a_now(c)))
                    + PROPAGATION_SUPPORT x a_now(c) x mean a_now(downstream that moved later, the same way)
                    u* = most abnormal upstream driver that moved first (now or in the look-back) and the same way:
                    a small upstream wobble cannot explain a large downstream jump, a falling input cannot explain a rising product.
    passing through: PASS_THROUGH x a_before(c) x mean a_now(downstream moving now the same way)
                    a move in the look-back month counts only when its consequences show up now.
    """
    before = before or {}
    upstream = defaultdict(list)
    for c in cands:
        for d in c["downstream"]:
            upstream[d].append(c["id"])
    scores = {}
    for c in cands:
        cid, own, past = c["id"], now.get(c["id"]), before.get(c["id"])
        if not own and not past:
            continue
        moved_now = 0.0
        if own:
            onset = own["first_abnormal"] or "9999"
            explainers = [now[u]["abnormality"] for u in upstream[cid] if now.get(u) and now[u]["first_abnormal"]
                          and now[u]["first_abnormal"] <= onset and now[u]["direction"] == own["direction"]]
            explainers += [before[u]["abnormality"] for u in upstream[cid] if before.get(u) and before[u]["first_abnormal"]
                           and before[u]["direction"] == own["direction"]]
            a = own["abnormality"]
            share = min(1.0, max(explainers, default=0.0) / a) if a else 0.0
            later = [now[d]["abnormality"] for d in c["downstream"] if now.get(d) and own["first_abnormal"] and now[d]["first_abnormal"]
                     and now[d]["first_abnormal"] >= own["first_abnormal"] and now[d]["direction"] == own["direction"]]
            moved_now = ROLE_WEIGHT[c["role"]] * a * (1 - EXPLAIN_AWAY * share) + PROPAGATION_SUPPORT * a * (fmean(later) if later else 0.0)
        passing = 0.0
        if past and past["first_abnormal"]:
            confirming = [now[d]["abnormality"] for d in c["downstream"] if now.get(d) and now[d]["first_abnormal"]
                          and now[d]["direction"] == past["direction"]]
            passing = PASS_THROUGH * past["abnormality"] * (fmean(confirming) if confirming else 0.0) ** 0.5
        scores[cid] = round(max(moved_now, passing), 4)
    return scores


# ---------- 4. analogs ----------

def z_vector(ev: dict[str, dict | None]) -> dict[str, float]:
    return {cid: e["z"] * e["direction"] for cid, e in ev.items() if e}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(a[k] * b.get(k, 0.0) for k in a)
    na, nb = math.sqrt(sum(v * v for v in a.values())), math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def month_evidence(cands: list[dict], series: dict, period: str, baseline_n: int) -> dict[str, dict | None]:
    """Evidence of every candidate for one month, against the baseline_n months before it."""
    base = previous_months(period, baseline_n)
    return {c["id"]: evidence(series.get(c["id"], []), month_bounds(period), points_in_months(series.get(c["id"], []), base)) for c in cands}


def lookback_evidence(cands: list[dict], series: dict, period: str, baseline_n: int, lookback: int) -> dict[str, dict | None]:
    """Evidence over the look-back months before the period, against the baseline before them (for pass-through)."""
    if not lookback:
        return {}
    months = previous_months(period, lookback)
    base = previous_months(months[0], baseline_n)
    window = (month_bounds(months[0])[0], month_bounds(months[-1])[1])
    return {c["id"]: evidence(series.get(c["id"], []), window, points_in_months(series.get(c["id"], []), base)) for c in cands}


def library(cands: list[dict], series: dict, months: list[str], baseline_n: int, outcome: dict[str, float] | None = None,
            lookback: int = LOOKBACK, labels: dict[str, str] | None = None) -> list[dict]:
    """One episode per past month: its z-vector over the candidates and its top driver. The top driver is the reviewed one
    when a controller approved or corrected a diagnosis of that month (labels: {month: driver}), else the deterministic
    top-1, a weak label. outcome: optional {month: change of the metric over the next month}."""
    labels = labels or {}
    episodes = []
    for m in months:
        ev = month_evidence(cands, series, m, baseline_n)
        scores = kg_scores(cands, ev, lookback_evidence(cands, series, m, baseline_n, lookback))
        if not scores:
            continue
        top = labels.get(m) or max(scores, key=scores.get)
        episodes.append({"period": m, "vector": z_vector(ev), "top": top, "label": "reviewed" if m in labels else "automatic",
                         "next_change": (outcome or {}).get(m)})
    return episodes


def retrieve(query: dict[str, float], episodes: list[dict], period: str, as_of: str, k: int = TOP_K_ANALOGS) -> list[dict]:
    """Most similar past episodes. Leave-one-period-out and as-of: never the queried month, never a month ending after as_of."""
    allowed = [e for e in episodes if e["period"] != period and month_bounds(e["period"])[1] <= as_of]
    scored = sorted(({**e, "similarity": round(cosine(query, e["vector"]), 3)} for e in allowed), key=lambda e: -e["similarity"])
    return [e for e in scored[:k] if e["similarity"] > 0]


def analog_support(analogs: list[dict]) -> dict[str, float]:
    total = sum(a["similarity"] for a in analogs)
    support = defaultdict(float)
    for a in analogs:
        support[a["top"]] += a["similarity"] / total
    return dict(support)


# ---------- 5. diagnosis ----------

def diagnose(cands: list[dict], series: dict, period: str, baseline_n: int = 3, as_of: str | None = None,
             episodes: list[dict] | None = None, alpha: float = ALPHA, lookback: int = LOOKBACK) -> dict:
    as_of = as_of or month_bounds(period)[1]
    series = {cid: [(d, v) for d, v in pts if d <= as_of] for cid, pts in series.items()}  # nothing after as_of, ever
    base_months = previous_months(period, baseline_n)
    baselines = {c["id"]: points_in_months(series.get(c["id"], []), base_months) for c in cands}
    month_ev = month_evidence(cands, series, period, baseline_n)
    before = lookback_evidence(cands, series, period, baseline_n, lookback)
    s_evid = kg_scores(cands, month_ev, before)
    analogs = retrieve(z_vector(month_ev), episodes or [], period, as_of)
    s_ret = analog_support(analogs)
    a = alpha if analogs else 1.0
    combined = {cid: round(a * s + (1 - a) * s_ret.get(cid, 0.0), 4) for cid, s in s_evid.items()}

    # weeks of the period with an abnormal driver vote (Borda 3-2-1 on their top 3), so one noisy week cannot decide the month
    votes, weekly = defaultdict(int), []
    for w in weeks(period):
        w_ev = {c["id"]: evidence(series.get(c["id"], []), w, baselines[c["id"]]) for c in cands}
        w_scores = {c: x for c, x in kg_scores(cands, w_ev, before).items() if (w_ev.get(c) or {}).get("first_abnormal")
                    or (before.get(c) or {}).get("first_abnormal")}
        top3 = sorted(w_scores, key=lambda c: -w_scores[c])[:3]
        weekly.append({"window": w, "top3": top3})
        for rank, cid in enumerate(top3):
            votes[cid] += 3 - rank
    ranking = sorted(combined, key=lambda c: (-votes[c], -combined[c], (month_ev.get(c) or {}).get("first_abnormal") or "9999"))

    by_id = {c["id"]: c for c in cands}
    return {
        "period": period, "lookback": previous_months(period, lookback), "baseline": base_months, "as_of": as_of, "mode": "signal", "alpha": a,
        "ranking": [{"rank": i + 1, "id": cid, "role": by_id[cid]["role"], "path": by_id[cid]["path"], "routes": by_id[cid]["routes"],
                     "s_evid": s_evid[cid], "s_ret": round(s_ret.get(cid, 0.0), 3), "score": combined[cid], "votes": votes[cid],
                     "evidence_id": f"ev:{cid}:{period}", **(month_ev.get(cid) or {}),
                     "earlier_move": before.get(cid)} for i, cid in enumerate(ranking)],
        "no_data": sorted(cid for cid in month_ev if month_ev[cid] is None and not before.get(cid)),
        "weekly": weekly,
        "analogs": [{"evidence_id": f"analog:{e['period']}", "period": e["period"], "similarity": e["similarity"],
                     "top_driver": e["top"], "label": e.get("label", "automatic"), "next_change": e["next_change"]} for e in analogs],
    }


# ---------- proxy metric (illustrative while P&L actuals are missing) ----------

def monthly_means(points) -> dict[str, float]:
    by = defaultdict(list)
    for d, v in points:
        by[d[:7]].append(v)
    return {m: fmean(v) for m, v in by.items()}


def proxy_margin(series: dict, product: str, ratios: dict[str, float]) -> dict[str, float]:
    """price(product) - sum(ratio x price(input)), by month, for months where every term has data."""
    means = {cid: monthly_means(series.get(cid, [])) for cid in [product, *ratios]}
    months = set(means[product]).intersection(*(means[c] for c in ratios))
    return {m: means[product][m] - sum(r * means[c][m] for c, r in ratios.items()) for m in sorted(months)}


def next_changes(monthly: dict[str, float]) -> dict[str, float]:
    ms = sorted(monthly)
    return {a: round(monthly[b] - monthly[a], 2) for a, b in zip(ms, ms[1:])}


# ---------- 6. report and 8. checks ----------

ANSWER_SCHEMA = """Return JSON only:
{"top1": driver id, "top3": [{"driver": id, "why": one sentence, "evidence": [evidence ids from the report]}],
 "propagation_path": [concept ids, from the cause to the product], "confidence": "high|medium|low",
 "uncertainty": one sentence, "outlook": [{"claim": one sentence, "evidence": ["analog:YYYY-MM", ...]}]}
Drivers must come from the ranking. Quote only numbers present in the report. The outlook may only restate what analogs did next."""


def report(diag: dict, metric: str, product: str, incidents: list[dict] | None = None, not_ranked: list[str] | None = None) -> str:
    lines = [f"Diagnosis of {metric} for {product}, period {diag['period']} vs baseline {diag['baseline'][0]}..{diag['baseline'][-1]} "
             f"(earlier moves passing through searched in {', '.join(diag['lookback']) or 'none'}), "
             f"as of {diag['as_of']}. Mode: {diag['mode']} (drivers ranked by how unusual their move was; no $/t attribution)."]
    for r in diag["ranking"]:
        now = (f"{r['delta']:+} ({r['pct']:+}%) vs reference {r['reference']} (last baseline month), z {r['z']}, max z {r['max_z']}, "
               f"first abnormal {r['first_abnormal'] or 'none'}") if "z" in r else "no data in the period"
        e = r["earlier_move"]
        earlier = f"; earlier move {e['pct']:+}% (z {e['z']}, from {e['first_abnormal']})" if e and e["first_abnormal"] else ""
        lines.append(f"{r['rank']}. {r['id']} [{r['role']}] {r['evidence_id']}: {now}{earlier}; score {r['score']}, weekly votes {r['votes']}; "
                     f"path {' <- '.join(r['path'])}" + (f"; transits {', '.join(r['routes'])}" if r["routes"] else ""))
    if not_ranked:
        lines.append("Drivers in the graph without a price series (not ranked, cannot be ruled out): " + ", ".join(not_ranked))
    if diag["no_data"]:
        lines.append("No data in the period or baseline for: " + ", ".join(diag["no_data"]))
    for a in diag["analogs"]:
        lines.append(f"{a['evidence_id']}: similarity {a['similarity']}, top driver then {a['top_driver']} ({a['label']})"
                     + (f", metric changed {a['next_change']:+} the following month" if a["next_change"] is not None else ""))
    for i in incidents or []:
        lines.append(f"incident {i['date']} {i['type']}: {i['summary']} (affects {', '.join(i['affects'])}; articles {', '.join(map(str, i['article_ids']))})")
    return "\n".join(lines)


def check_answer(answer: dict, diag: dict, path_exists, incidents: list[dict] | None = None) -> list[str]:
    """Reflector checks on the LLM's JSON. path_exists(a, b) -> bool tells whether the graph links a and b (either direction)."""
    problems = []
    for key in ("top1", "top3", "propagation_path", "confidence", "uncertainty", "outlook"):
        if key not in answer:
            problems.append(f"missing key {key}")
    if problems:
        return problems
    ranked = [r["id"] for r in diag["ranking"]]
    named = [answer["top1"], *(t.get("driver") for t in answer["top3"])]
    outside = sorted({d for d in named if d not in ranked})
    if outside:
        problems.append(f"drivers not in the ranking: {outside}. Only rank the candidates of the report.")
    path = answer["propagation_path"]
    broken = [f"{a}-{b}" for a, b in zip(path, path[1:]) if not path_exists(a, b)]
    if broken:
        problems.append(f"propagation_path has links that are not in the graph: {broken}")
    known = {r["evidence_id"] for r in diag["ranking"]} | {a["evidence_id"] for a in diag["analogs"]} \
        | {f"article:{x}" for i in incidents or [] for x in i["article_ids"]}
    cited = [e for t in answer["top3"] + answer["outlook"] for e in t.get("evidence", [])]
    unknown = sorted({e for e in cited if e not in known})
    if unknown:
        problems.append(f"unknown evidence ids: {unknown}")
    uncited = [t.get("driver") or t.get("claim", "")[:40] for t in answer["top3"] + answer["outlook"] if not t.get("evidence")]
    if uncited:
        problems.append(f"claims without evidence: {uncited}")
    if any(not e.startswith("analog:") for t in answer["outlook"] for e in t.get("evidence", [])):
        problems.append("the outlook may only cite analogs")
    if ranked and answer["top1"] != ranked[0] and "deterministic" not in answer["uncertainty"].lower():
        problems.append(f"top1 {answer['top1']} differs from the deterministic top-1 {ranked[0]}: say so in uncertainty and give both")
    return problems
