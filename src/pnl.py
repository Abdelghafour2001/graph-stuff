"""Deterministic P&L engine over a discovered branch model (design: docs/10-pnl-agent.md, "The engine").

A model is the sheet's rows: inputs (values per period) and computed rows (expressions over row labels, as recovered by
formula_graph / discovery, e.g. "[Production DAP (kt)]*[Prix DAP ($/t)]/1000"). No LLM computes anything here.

  evaluate      every row, every period
  sensitivities change of a target line for +1% and +1 unit of each input
  shapley       order-independent split of a target's change between two input sets (plan -> market, v1 -> v2)
  mark_to_market  replace price inputs by market values, keep the rest as submitted
"""
import ast
import itertools
import math
import operator
import re

REF = re.compile(r"\[([^\]]+)\]")
FUNCS = {"SUM": lambda *a: sum(_flat(a)), "MIN": lambda *a: min(_flat(a)), "MAX": lambda *a: max(_flat(a)),
         "ABS": abs, "ROUND": lambda x, n=0: round(x, int(n)), "IFERROR": lambda x, y: y if x is None or (isinstance(x, float) and math.isnan(x)) else x}
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow,
       ast.USub: operator.neg, ast.UAdd: operator.pos}


def _flat(args):
    for a in args:
        if isinstance(a, (list, tuple)):
            yield from _flat(a)
        else:
            yield a


class Model:
    def __init__(self, rows: list[dict], periods: list[str]):
        """rows: [{label, values, formula or None}] in sheet order."""
        self.order = [r["label"] for r in rows]
        self.periods = periods
        self.inputs = {r["label"]: list(r["values"]) for r in rows if not r.get("formula")}
        self.exprs = {r["label"]: self._compile(r["formula"], r["label"]) for r in rows if r.get("formula")}

    def _compile(self, formula: str, label: str):
        """Excel-like rule over row labels -> Python AST; '[a .. b]' ranges become the rows between a and b."""
        text = formula.lstrip("=").replace("^", "**").replace("×", "*")
        names = {}

        def ref(m):
            inner = m.group(1).strip()
            if inner == "row":
                raise ValueError(f"{label}: refers to itself")
            if " .. " in inner:
                a, b = (x.strip() for x in inner.split(" .. "))
                i, j = self.order.index(a), self.order.index(b)
                key = f"_r{len(names)}"
                names[key] = self.order[i:j + 1]
            elif inner == "block above":
                i = self.order.index(label)
                key = f"_r{len(names)}"
                names[key] = [x for x in self.order[:i]]
            else:
                key = f"_v{len(names)}"
                names[key] = inner
            return key
        text = REF.sub(ref, text)
        return ast.parse(text, mode="eval").body, names

    def evaluate(self, inputs: dict | None = None) -> dict[str, list[float]]:
        values = {k: list(v) for k, v in (inputs or self.inputs).items()}
        for _ in range(len(self.exprs) + 1):  # rows can depend on rows below them: iterate until every row is known
            for label, (tree, names) in self.exprs.items():
                if label in values:
                    continue
                deps = [d for n in names.values() for d in (n if isinstance(n, list) else [n])]
                if all(d in values for d in deps):
                    values[label] = [self._eval(tree, names, values, t) for t in range(len(self.periods))]
        missing = [l for l in self.exprs if l not in values]
        assert not missing, f"cannot evaluate (unknown rows or a cycle): {missing}"
        return values

    def _eval(self, node, names, values, t):
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            n = names[node.id]
            return [values[x][t] for x in n] if isinstance(n, list) else values[n][t]
        if isinstance(node, ast.BinOp):
            try:
                return OPS[type(node.op)](self._eval(node.left, names, values, t), self._eval(node.right, names, values, t))
            except ZeroDivisionError:
                return float("nan")
        if isinstance(node, ast.UnaryOp):
            return OPS[type(node.op)](self._eval(node.operand, names, values, t))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCS:
            return FUNCS[node.func.id](*[self._eval(a, names, values, t) for a in node.args])
        raise ValueError(f"unsupported in a P&L rule: {ast.dump(node)[:80]}")

    def total(self, target: str, inputs: dict | None = None) -> float:
        return sum(v for v in self.evaluate(inputs)[target] if not math.isnan(v))


EXTERNAL = re.compile(r"\[\d+\][^\[\]]*\[")  # [1]Book[row-11]: a link to a workbook we do not have


def from_discovery(sheet: dict) -> Model:
    """Model of one discovered sheet: its formula rows, its inputs; rows linked to other workbooks become inputs (their
    values as last saved) and are dropped when the file holds no values for them."""
    rows = []
    for r in sheet["rows"]:
        formula = r["formula"] if r["role"] == "computed" and r["formula"] and not EXTERNAL.search(r["formula"]) else None
        if formula or all(v is not None for v in r["values"]):
            rows.append({"label": r["label"], "values": r["values"], "formula": formula})
    return Model(rows, sheet["periods"])


def sensitivities(model: Model, target: str, pct: float = 0.01) -> list[dict]:
    """Change of the target (summed over periods) for +pct and +1 unit of each input, largest first."""
    base = model.total(target)
    out = []
    for label, vals in model.inputs.items():
        up_pct = model.total(target, {**model.inputs, label: [v * (1 + pct) if v is not None else v for v in vals]}) - base
        up_unit = model.total(target, {**model.inputs, label: [v + 1 if v is not None else v for v in vals]}) - base
        if abs(up_pct) > 1e-12 or abs(up_unit) > 1e-12:
            out.append({"input": label, f"per_{int(pct * 100)}pct": round(up_pct, 4), "per_unit": round(up_unit, 6)})
    return sorted(out, key=lambda x: -abs(x[f"per_{int(pct * 100)}pct"]))


def shapley(model: Model, target: str, before: dict, after: dict) -> dict:
    """Exact Shapley split of total(target, after) - total(target, before) over the inputs that changed (order-independent)."""
    changed = [k for k in after if before.get(k) != after.get(k)]
    assert len(changed) <= 12, "too many changed inputs for an exact split; group them first"
    cache = {}

    def value(subset):
        key = frozenset(subset)
        if key not in cache:
            cache[key] = model.total(target, {**before, **{k: after[k] for k in subset}})
        return cache[key]
    n = len(changed)
    contrib = {}
    for k in changed:
        others = [x for x in changed if x != k]
        total = 0.0
        for size in range(n):
            w = math.factorial(size) * math.factorial(n - size - 1) / math.factorial(n)
            for s in itertools.combinations(others, size):
                total += w * (value(s + (k,)) - value(s))
        contrib[k] = round(total, 6)
    delta = value(tuple(changed)) - value(())
    return {"total_change": round(delta, 6), "by_input": dict(sorted(contrib.items(), key=lambda x: -abs(x[1]))),
            "unexplained": round(delta - sum(contrib.values()), 9)}


def mark_to_market(model: Model, market: dict[str, list[float | None]]) -> dict:
    """Inputs with market values in place of the branch's (where the market has a value for the period); the rest as submitted."""
    out = {k: list(v) for k, v in model.inputs.items()}
    for label, series in market.items():
        out[label] = [m if m is not None else v for m, v in zip(series, out[label])]
    return out
