"""Structure discovery for a branch submission that follows no template (design: docs/10-pnl-agent.md).

Layers, most reliable first, every one deterministic:
  1. formulas  (formula_graph): which rows are computed, how; hard-typed overrides; links to files we do not have
  2. identities on pasted values: row = a ± b ± c, row = k·a·b, row = k·a (unit cost, consumption ratio), constant growth
  3. meaning: label -> concept (concept_match, reranked when the gateway is up), driver type and unit from the label words
  4. questions back to the branch for what cannot be resolved, including drivers the graph expects but the file lacks
The LLM is not needed for any of this; it can phrase the questions and name what the rules mean.
"""
import itertools
import re
from pathlib import Path

import openpyxl
import yaml

import concept_match
import formula_graph
from periods import FORECAST_FORMAT, parse_period

ROOT = Path(__file__).parent.parent
REL_TOL = 0.005          # identities must hold within 0.5% in every period
MAX_TERMS = 4            # sums of up to four amount rows
AMOUNTS = {"revenue", "cost", "margin", "fixed_cost", "freight", "unknown"}   # money lines: the only ones explained by others
KINDS = {  # concept kinds a label can map to, by driver type, preferred first (a consumption ratio is about the input)
    "price": ("input", "product"), "cost": ("input", "product"), "consumption_ratio": ("input", "product"),
    "freight": ("route", "input", "product"), "volume": ("product",), "revenue": ("product", "metric"), "margin": ("metric",),
    "fixed_cost": ("metric",)}
PRIORITY = ["margin", "revenue", "cost", "fixed_cost", "freight", "unknown"]  # which row an equation is "about"
DRIVER_WORDS = [         # (driver type, words in the label), first match wins; FR and EN
    ("consumption_ratio", ["consommation specifique", "conso specifique", "ratio", "t/t", "par tonne de"]),
    ("margin", ["marge", "margin", "ebitda", "resultat", "ebit"]),
    ("revenue", ["chiffre d affaires", "revenue", "sales value", "ca "]),
    ("fixed_cost", ["couts fixes", "cout fixe", "fixed cost", "frais fixes"]),
    ("freight", ["fret", "freight", "transport"]),
    ("fx", ["taux de change", "usd/mad", "fx", "exchange rate"]),
    ("price", ["prix", "price", "netback", "$/t", "usd/t"]),
    ("cost", ["cout", "cost", "charges", "depenses", "achats", "consommee", "consumed"]),
    ("volume", ["production", "volume", "tonnage", "quantite", "ventes", "exports", "kt"]),
]
UNIT = re.compile(r"\(([^)]*(?:\$|t|kt|m|mad|usd|%)[^)]*)\)", re.IGNORECASE)


UNIT_FACTORS = {"1", "10", "100", "1000", "1000000", "1e3", "1e6", "0.001", "12", "0"}  # scale and unit conversions, not assumptions


def hidden_constants(expr: str) -> list[str]:
    """Numbers written inside a formula (outside references): assumptions nobody can see in the sheet."""
    bare = re.sub(r"\[[^\]]*\]", "", expr)
    return [n for n in dict.fromkeys(re.findall(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])", bare)) if n not in UNIT_FACTORS]


def driver_type(label: str) -> str:
    text = " ".join(concept_match.norm(label)) + " " + label.lower()
    for kind, words in DRIVER_WORDS:
        if any(w in text for w in words):
            return kind
    return "unknown"


def unit(label: str) -> str | None:
    m = UNIT.search(label)
    return m.group(1).strip() if m else None


# ---------- reading a sheet with no template ----------

def read_table(ws) -> dict:
    """Period columns (the first row with 2+ parseable periods), row labels, values and forecast flags per row."""
    rows = list(ws.iter_rows())
    header, periods = None, {}
    for cells in rows[:30]:
        found = {c.column: parse_period(c.value) for c in cells if parse_period(c.value)}
        if len(found) >= 2:
            header, periods = cells[0].row, found
            break
    if not header:
        return {"header_row": None, "periods": [], "rows": []}
    _, labels = formula_graph.sheet_cells(ws)
    cols = sorted(periods)
    forecast_cols = {c.column for c in rows[header - 1] if c.column in periods and FORECAST_FORMAT.search(c.number_format or "")}
    out = []
    for cells in rows[header:]:
        r = cells[0].row
        if r not in labels:
            continue
        by_col = {c.column: c for c in cells}
        vals = [by_col[c].value if c in by_col and isinstance(by_col[c].value, (int, float)) else None for c in cols]
        formulas = [c for c in cols if c in by_col and isinstance(by_col[c].value, str) and by_col[c].value.startswith("=")]
        if any(v is not None for v in vals) or formulas:
            out.append({"row": r, "label": labels[r], "values": vals, "has_formulas": bool(formulas)})
    return {"header_row": header, "periods": [periods[c].isoformat() for c in cols],
            "forecast_periods": [periods[c].isoformat() for c in cols if c in forecast_cols], "rows": out}


# ---------- identities on pasted values ----------

def close(a: float, b: float) -> bool:
    return abs(a - b) <= REL_TOL * max(abs(a), abs(b), 1e-9)


def constant(xs: list[float]) -> float | None:
    return xs[0] if xs and all(close(x, xs[0]) for x in xs) else None


def identities(rows: list[dict]) -> list[dict]:
    """Relations that hold in every period between rows of pasted values, using what each row is (its driver type).

    Flat rows are reported as flat and never used to explain anything: any constant is a product of other constants.
    Only money lines are explained by other rows: a margin as a sum or difference of amounts, revenue as k·volume·price,
    a cost as k·volume·price, or else as k·volume (an implied unit cost or consumption ratio)."""
    full = [r for r in rows if r["values"] and all(isinstance(v, (int, float)) for v in r["values"])]
    if not full or len(full[0]["values"]) < 3:
        return []
    vals = {r["label"]: r["values"] for r in full}
    kind = {r["label"]: r.get("driver") or driver_type(r["label"]) for r in full}
    concept = {r["label"]: (r.get("concept") or {}).get("concept") for r in full}
    flat = {l for l, v in vals.items() if constant(v) is not None}
    n = len(full[0]["values"])
    found = [{"target": l, "kind": "flat", "expr": "constant", "terms": []} for l in vals if l in flat]
    by = lambda *kinds: [l for l in vals if kind[l] in kinds]

    def fits(target, combine):
        return all(close(vals[target][i], combine(i)) for i in range(n))

    equations = set()  # one sum identity is one equation, reported once, about its highest-priority row
    for t in sorted([l for l in vals if kind[l] in AMOUNTS and l not in flat], key=lambda l: PRIORITY.index(kind[l])):
        hit = None
        amounts = [l for l in vals if l != t and kind[l] in AMOUNTS]
        for size in range(2, MAX_TERMS + 1):
            for combo in itertools.combinations(amounts, size):
                for signs in itertools.product((1, -1), repeat=size - 1):
                    sg = (1,) + signs
                    if fits(t, lambda i: sum(s_ * vals[x][i] for s_, x in zip(sg, combo))):
                        if frozenset((t, *combo)) in equations:
                            continue
                        equations.add(frozenset((t, *combo)))
                        hit = {"target": t, "kind": "sum", "terms": list(combo),
                               "expr": " ".join(("+ " if s_ > 0 else "- ") + f"[{x}]" for s_, x in zip(sg, combo)).removeprefix("+ ")}
                        break
                if hit:
                    break
            if hit:
                break
        if not hit and kind[t] in ("revenue", "cost", "unknown"):
            for v_ in by("volume"):
                # the price must be the cost's own concept: a sulphur cost is not volume x DAP price, even when it fits
                for p_ in [x for x in by("price") if kind[t] == "revenue" or not concept.get(t) or concept.get(x) == concept.get(t)]:
                    ks = [vals[t][i] / (vals[v_][i] * vals[p_][i]) for i in range(n) if vals[v_][i] and vals[p_][i]]
                    k = constant(ks) if len(ks) == n else None
                    if k is not None:
                        hit = {"target": t, "kind": "product", "terms": [v_, p_], "k": k, "expr": f"{k:.6g} × [{v_}] × [{p_}]"}
                        break
                if hit:
                    break
        if not hit and kind[t] in ("cost", "unknown", "freight"):
            for v_ in [x for x in by("volume") if x not in flat]:
                ks = [vals[t][i] / vals[v_][i] for i in range(n) if vals[v_][i]]
                k = constant(ks) if len(ks) == n else None
                if k is not None:
                    hit = {"target": t, "kind": "ratio", "terms": [v_], "k": k, "expr": f"{k:.6g} × [{v_}]  (implied cost per unit of volume)"}
                    break
        if hit:
            found.append(hit)
    for t in [l for l in vals if l not in flat and not any(f["target"] == l for f in found)]:
        growth = [vals[t][i + 1] / vals[t][i] for i in range(n - 1) if vals[t][i]]
        g = constant(growth) if len(growth) == n - 1 else None
        if g is not None:
            found.append({"target": t, "kind": "growth", "terms": [], "expr": f"{100 * (g - 1):+.2f}% per period"})
    return found


# ---------- the whole submission ----------

def expected_inputs(product: str) -> list[str]:
    onto = yaml.safe_load((ROOT / "knowledge" / "ontology.yaml").read_text(encoding="utf-8"))
    edges = [tuple(r) for r in onto["relations"]]
    direct = [d for s, rel, d in edges if s == product and rel == "MADE_FROM"]
    # inputs that sit behind intermediates the branch buys or makes (phosphoric acid <- rock, sulfuric acid <- sulfur)
    deeper = [d2 for d in direct for s, rel, d2 in edges if s == d and rel == "MADE_FROM"]
    deepest = [d3 for d in deeper for s, rel, d3 in edges if s == d and rel == "MADE_FROM"]
    return list(dict.fromkeys(direct + deeper + deepest))


def discover(path: Path) -> dict:
    concepts = concept_match.concepts_from_yaml()
    harvest = formula_graph.harvest(path)
    wb = openpyxl.load_workbook(path)
    sheets, questions = {}, []
    for ws in wb.worksheets:
        table = read_table(ws)
        if not table["rows"]:
            continue
        rules = {r["row"]: r for r in harvest["sheets"].get(ws.title, {}).get("row_rules", [])}
        rows = []
        for r in table["rows"]:
            rule = rules.get(r["row"])
            drv = driver_type(r["label"])
            m = concept_match.match(r["label"], concepts, KINDS.get(drv, ("product", "input", "metric")))
            site = concept_match.match(r["label"], concepts, {"site"})
            rows.append({**r, "role": "computed" if r["has_formulas"] else "input", "formula": rule["expr"] if rule else None,
                         "overrides": rule["overrides"] if rule else [], "driver": drv, "unit": unit(r["label"]), "concept": m,
                         "site": site["concept"] if site["decision"] != "unknown" else None})
            hidden = hidden_constants(rule["expr"]) if rule else []
            if hidden:
                questions.append(f"{ws.title} / {r['label']}: the formula hides the numbers {', '.join(hidden)}. What are they "
                                 f"(a consumption ratio, a price, a rate)? They should be lines of their own so they can be checked.")
            if rule and rule["overrides"]:
                questions.append(f"{ws.title} / {r['label']}: numbers typed over the formula in column(s) {', '.join(rule['overrides'])}. Manual override, or stale?")
            if not unit(r["label"]) and r["has_formulas"] is False:
                questions.append(f"{ws.title} / {r['label']}: no unit in the label. Which unit is it in?")
            if m["decision"] == "unknown" and r["has_formulas"] is False and drv not in ("fixed_cost", "fx"):
                questions.append(f"{ws.title} / {r['label']}: what does this line refer to (product, input, site)?")
        inputs = [r for r in rows if r["role"] == "input"]
        ids = identities(inputs) if len(inputs) >= 3 else []  # rows carry their driver and concept
        ids = [i for i in ids if i["kind"] != "flat"] + [i for i in ids if i["kind"] == "flat"]
        by_label = {r["label"]: r for r in rows}
        for i in ids:  # a pasted row explained by others is computed in fact
            if i["kind"] in ("sum", "product", "ratio") and i["target"] in by_label:
                by_label[i["target"]]["role"] = "computed (identity)"
                by_label[i["target"]]["formula"] = i["expr"]
        sheets[ws.title] = {"periods": table["periods"], "forecast_periods": table["forecast_periods"], "rows": rows, "identities": ids}
    for ext, n in harvest["external_links"].items():
        questions.append(f"{n} cells take their value from another workbook ({ext}). Can you send it, or say where those numbers come from?")
    # drivers the graph expects for each product the branch produces
    rows_all = [r for s in sheets.values() for r in s["rows"]]
    seen = {r["concept"]["concept"] for r in rows_all if r["concept"]["concept"]}
    for product in sorted({r["concept"]["concept"] for r in rows_all if r["concept"].get("kind") == "product" and r["driver"] in ("volume", "revenue", "price")}):
        missing = [i for i in expected_inputs(product) if i not in seen]
        if missing:
            questions.append(f"{product}: the graph says it is made from {', '.join(missing)}, but no line mentions them. Bought in, included elsewhere, or missing?")
    return {"file": path.name, "sheets": sheets, "external_links": harvest["external_links"],
            "dependencies": harvest["depends_on"], "questions": list(dict.fromkeys(questions))}
