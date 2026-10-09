"""A made-up branch submission with no template, to exercise structure discovery and the P&L engine end to end.

ILLUSTRATIVE NUMBERS, NOT OCP DATA. The workbook looks like what a site controller might send: a title row, French
labels with units in parentheses, a formula sheet with a hard-typed override and a line linked to a file we do not have,
and a second sheet of pasted values (no formulas) whose logic must be found again by arithmetic.

  python scripts/sample_branch.py data/samples/branche_jorf_budget.xlsx
"""
import sys
from datetime import datetime
from pathlib import Path

import openpyxl

MONTHS = [datetime(2025, m, 1) for m in range(1, 7)]
PRODUCTION = [520, 480, 540, 560, 530, 550]
AMMONIA = [430, 440, 455, 420, 410, 405]
# label, values or formula ({c} = column); rows start at 3 (title on row 1, months on row 2)
ROWS = [
    ("Production DAP (kt)", PRODUCTION),                                   # 3
    ("Prix de vente DAP FOB ($/t)", [650] * 6),                            # 4
    ("Chiffre d'affaires DAP (M$)", "={c}3*{c}4/1000"),                    # 5
    ("Consommation spécifique soufre (t/t DAP)", [0.40] * 6),              # 6
    ("Prix soufre CFR Jorf ($/t)", [165] * 6),                             # 7
    ("Coût soufre (M$)", "={c}3*{c}6*{c}7/1000"),                          # 8
    ("Consommation spécifique ammoniac (t/t DAP)", [0.22] * 6),            # 9
    ("Prix ammoniac CFR ($/t)", AMMONIA),                                  # 10
    ("Coût ammoniac (M$)", "={c}3*{c}9*{c}10/1000"),                       # 11
    ("Roche consommée (M$)", "={c}3*1.6*48/1000"),                         # 12
    ("Coûts fixes (M$)", [42] * 6),                                        # 13
    ("Marge brute (M$)", "={c}5-{c}8-{c}11-{c}12-{c}13"),                  # 14
    ("Taux de change USD/MAD", "=[1]Hypotheses!{c}4"),                     # 15: from a file we do not have
]


def build(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Budget S1 2025"
    ws["A1"] = "Site de Jorf Lasfar - budget DAP S1 2025 (illustratif)"
    ws["A2"] = "Rubrique"
    for j, m in enumerate(MONTHS, start=2):
        ws.cell(2, j, m).number_format = "mmm-yy"
    for i, (label, spec) in enumerate(ROWS, start=3):
        ws.cell(i, 1, label)
        for j in range(2, 2 + len(MONTHS)):
            col = openpyxl.utils.get_column_letter(j)
            ws.cell(i, j, spec[j - 2] if isinstance(spec, list) else spec.format(c=col))
    ws["E8"] = 52.0  # April sulphur cost typed over the formula: a manual override

    pasted = wb.create_sheet("Synthèse (valeurs)")  # the same plan forwarded as values: logic to be found by arithmetic
    pasted["A1"] = "Rubrique"
    for j, m in enumerate(MONTHS, start=2):
        pasted.cell(1, j, m).number_format = "mmm-yy"
    lines = {
        "Production DAP (kt)": PRODUCTION,
        "Prix de vente DAP FOB ($/t)": [650] * 6,
        "Chiffre d'affaires (M$)": [p * 650 / 1000 for p in PRODUCTION],
        "Coût soufre (M$)": [p * 0.40 * 165 / 1000 for p in PRODUCTION],
        "Coût ammoniac (M$)": [p * 0.22 * a / 1000 for p, a in zip(PRODUCTION, AMMONIA)],
        "Coûts fixes (M$)": [42] * 6,
    }
    lines["Marge brute (M$)"] = [lines["Chiffre d'affaires (M$)"][i] - lines["Coût soufre (M$)"][i] - lines["Coût ammoniac (M$)"][i] - 42
                                 for i in range(6)]
    for i, (label, vals) in enumerate(lines.items(), start=2):
        pasted.cell(i, 1, label)
        for j, v in enumerate(vals, start=2):
            pasted.cell(i, j, round(v, 4))
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "data/samples/branche_jorf_budget.xlsx")
    build(out)
    print("written", out)
