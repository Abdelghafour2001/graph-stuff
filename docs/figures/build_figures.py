"""Architecture figures of the OCP graph agent, as SVG files that import into Figma as editable layers (drag and drop).

Layout follows the ANAPEC architecture-schema conventions: figure title and subtitle, colour-coded layer bands with a swatch
and an uppercase label, white cards with an icon tile, title and description, numbered flow rows with an accent bar, stage
cards joined by chevrons, a legend and a footnote. Colours and font live in PALETTE / FONT below.

  python docs/figures/build_figures.py      # writes docs/figures/*.svg
"""
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).parent
FONT = "Inter"
PALETTE = {
    "ink": "#13202F", "ink2": "#4B5768", "ink3": "#7A8696", "card": "#FFFFFF", "line": "#D6DCE4", "arrow": "#8A96A6",
    # layer roles: fill tint, border, swatch / tile
    "users": ("#F3F5F8", "#DCE2EA", "#5B6B80"),
    "front": ("#EEF4FB", "#D3E2F3", "#2F6FB3"),
    "llm": ("#FCF5E6", "#F0DFB5", "#B7831A"),
    "agents": ("#F4F1FB", "#E0D8F2", "#6A4FB3"),
    "det": ("#EAF5F3", "#C9E5DF", "#1E7A6C"),
    "data": ("#EDF2F7", "#D2DDE8", "#3A5878"),
    "review": ("#EEF6EC", "#D3E8CE", "#3D7F35"),
}


def wrap(s: str, width: float, size: float = 12) -> list[str]:
    per_line = max(8, int(width / (size * 0.56)))
    lines, cur = [], ""
    for word in s.split():
        if len(cur) + len(word) + 1 > per_line and cur:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + [cur]


def card_height(descs: list[str], width: float) -> float:
    """Tile row + description lines + bottom padding, the same for every card of a row."""
    return 61 + (max(len(wrap(d, width - 30)) for d in descs) - 1) * 16.2 + 22


class Svg:
    def __init__(self, w: int, h: int):
        self.w, self.h, self.parts = w, h, []

    def add(self, s: str) -> None:
        self.parts.append(s)

    def rect(self, x, y, w, h, fill, stroke=None, r=0, sw=1, dash=None, name=None):
        attrs = f'x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}"'
        if stroke:
            attrs += f' stroke="{stroke}" stroke-width="{sw}"'
        if dash:
            attrs += f' stroke-dasharray="{dash}"'
        self.add(f'<rect {"id=" + chr(34) + escape(name) + chr(34) + " " if name else ""}{attrs}/>')

    def text(self, x, y, s, size=12, weight=400, fill=None, anchor="start", spacing=0):
        ls = f' letter-spacing="{spacing}"' if spacing else ""
        self.add(f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" '
                 f'fill="{fill or PALETTE["ink"]}" text-anchor="{anchor}"{ls}>{escape(s)}</text>')

    def wrapped(self, x, y, s, width, size=12, fill=None, lh=None) -> int:
        """Greedy wrap on an average glyph width; returns the number of lines."""
        lines = wrap(s, width, size)
        for i, line in enumerate(lines):
            self.text(x, y + i * (lh or size * 1.35), line, size, fill=fill or PALETTE["ink2"])
        return len(lines)

    def group(self, name: str):
        self.add(f'<g id="{escape(name)}">')

    def end(self):
        self.add("</g>")

    def line(self, x1, y1, x2, y2, dash=None, head=True, color=None):
        c = color or PALETTE["arrow"]
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{c}" stroke-width="1.5"{d}/>')
        if head:
            self.head(x2, y2, x1, y1, c)

    def poly(self, pts: list, dash=None, color=None):
        c = color or PALETTE["arrow"]
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<polyline points="{" ".join(f"{x},{y}" for x, y in pts)}" fill="none" stroke="{c}" stroke-width="1.5"{d}/>')
        self.head(*pts[-1], *pts[-2], c)

    def head(self, x, y, fx, fy, color):
        if abs(x - fx) >= abs(y - fy):
            s = 1 if x > fx else -1
            pts = [(x, y), (x - 11 * s, y - 6), (x - 11 * s, y + 6)]
        else:
            s = 1 if y > fy else -1
            pts = [(x, y), (x - 6, y - 11 * s), (x + 6, y - 11 * s)]
        self.add(f'<polygon points="{" ".join(f"{a},{b}" for a, b in pts)}" fill="{color}"/>')

    def chevron(self, x, y):
        self.add(f'<polyline points="{x},{y} {x + 6},{y + 6} {x},{y + 12}" fill="none" stroke="{PALETTE["arrow"]}" '
                 f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>')

    def save(self, path: Path):
        body = "\n".join(self.parts)
        path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}">\n'
                        f'<rect width="{self.w}" height="{self.h}" fill="#FFFFFF"/>\n{body}\n</svg>\n', encoding="utf-8")


# ---------- building blocks ----------

def header(s: Svg, title: str, subtitle: str):
    s.text(64, 88, title, 32, 700)
    s.text(64, 116, subtitle, 15, 400, PALETTE["ink2"])


def band_label(s: Svg, x, y, label, role):
    s.rect(x + 21.5, y + 18, 14, 14, PALETTE[role][2], r=3)
    s.text(x + 45.5, y + 29.5, label.upper(), 12, 700, PALETTE[role][2], spacing=0.6)


def card(s: Svg, x, y, w, h, title, desc, role, code):
    s.group(title)
    s.rect(x, y, w, h, PALETTE["card"], PALETTE["line"], r=8)
    s.rect(x + 15, y + 15, 26, 26, PALETTE[role][2], r=6)
    s.text(x + 28, y + 32.5, code, 10, 700, "#FFFFFF", "middle")
    s.text(x + 51, y + 33, title, 14.5, 600)
    s.wrapped(x + 15, y + 61, desc, w - 30, 12)
    s.end()


def band(s: Svg, x, y, w, label, role, cards, chevrons=False) -> float:
    """A layer band with one row of cards; returns its height."""
    gap = 36 if chevrons else 14
    cw = (w - 43 - gap * (len(cards) - 1)) / len(cards)
    ch = card_height([d for _, d, _ in cards], cw)
    h = 46.5 + ch + 20
    s.group(f"Couche — {label}")
    s.rect(x, y, w, h, PALETTE[role][0], PALETTE[role][1], r=12)
    band_label(s, x, y, label, role)
    for i, (title, desc, code) in enumerate(cards):
        cx = x + 21.5 + i * (cw + gap)
        card(s, round(cx, 1), y + 46.5, round(cw, 1), round(ch, 1), title, desc, role, code)
        if chevrons and i < len(cards) - 1:
            s.chevron(round(cx + cw + 15, 1), y + 46.5 + ch / 2 - 6)
    s.end()
    return h


def side_panel(s: Svg, x, y, w, label, role, cards) -> float:
    ch = card_height([d for _, d, _ in cards], w - 43)
    h = 46.5 + len(cards) * ch + (len(cards) - 1) * 14 + 20
    s.group(f"Panneau — {label}")
    s.rect(x, y, w, h, PALETTE[role][0], PALETTE[role][1], r=12)
    band_label(s, x, y, label, role)
    for i, (title, desc, code) in enumerate(cards):
        card(s, x + 21.5, round(y + 46.5 + i * (ch + 14), 1), w - 43, round(ch, 1), title, desc, role, code)
    s.end()
    return h


def flow_row(s: Svg, x, y, w, h, title, desc, role):
    s.group(title)
    s.rect(x, y, w, h, PALETTE["card"], PALETTE["line"], r=8)
    s.rect(x, y, 4, h, PALETTE[role][2], r=2)
    s.text(x + 19, y + 30, title, 14, 600)
    s.wrapped(x + 19, y + 55, desc, w - 38, 12)
    s.end()


def note_band(s: Svg, x, y, w, h, label, text, role):
    s.group(label)
    s.rect(x, y, w, h, PALETTE[role][0], PALETTE[role][1], r=10)
    s.text(x + 21.5, y + 29, label, 13, 700, PALETTE[role][2])
    s.wrapped(x + 21.5, y + 51, text, w - 43, 12)
    s.end()


def legend(s: Svg, x, y, items):
    s.group("Légende")
    cx = x
    for label, dash, color in items:
        s.add(f'<line x1="{cx}" y1="{y}" x2="{cx + 28}" y2="{y}" stroke="{color or PALETTE["arrow"]}" stroke-width="1.5"'
              + (f' stroke-dasharray="{dash}"' if dash else "") + "/>")
        s.text(cx + 38, y + 4, label, 11.5, 400, PALETTE["ink2"])
        cx += 38 + len(label) * 6.2 + 28
    s.end()


# ---------- figure 1: agentic architecture ----------

def figure_architecture():
    s = Svg(1640, 1500)
    header(s, "Architecture agentique — graphe P&L OCP",
           "Un orchestrateur LLM et des agents spécialistes sur un graphe Neo4j · le LLM choisit et explique, du code déterministe calcule")
    x, w, gap = 64, 1116, 46
    layers = [
        ("Utilisateurs", "users", [
            ("Contrôleur de gestion", "Questions de P&L, de marges et d’écarts par BU ou par site", "CG"),
            ("Analyste market intelligence", "Classeurs Argus / CRU / S&P, prix, événements de marché", "MI"),
            ("Relecteur métier", "Valide les termes, les specs, les fusions et les diagnostics", "RV")]),
        ("Présentation", "front", [
            ("Interface Streamlit", "Chat, Variance, News et prix, Entités, Classeurs, Specs, Évaluation", "UI"),
            ("API FastAPI", "/ask · /variance · /diagnoses · /specs · /news · /entities", "API"),
            ("Neo4j Browser", "Exploration directe du graphe, en lecture", "NB")]),
        ("Orchestrateur (LLM)", "llm", [
            ("Orchestrateur", "Résout le vocabulaire, choisit les outils, assemble une réponse citée", "OR"),
            ("Playbooks", "Impact d’un événement · écart d’une marge · extraction d’une feuille", "PB"),
            ("Reflector", "Rejette tout nombre absent des résultats d’outils et toute réponse sans article cité", "RF")]),
        ("Agents spécialistes", "agents", [
            ("Agent classeurs", "Trouve les feuilles, lit les plages, propose des specs d’extraction", "WB"),
            ("Agent news", "Articles, incidents, prix vérifiés, toujours « as of » une date", "NW"),
            ("Agent entités", "Actifs OCP et concurrents, fusions de sources à valider", "EN"),
            ("Agent marché (prévu)", "Séries de prix et prévisions par modèles déterministes", "MK")]),
        ("Moteurs déterministes", "det", [
            ("Exécuteur de specs", "Rejoue le YAML ; contrôles de totaux, d’unités, d’orientation ; diff avec la base", "SX"),
            ("diagnose_variance", "Candidats du graphe, écarts, explication par l’amont, mois analogues", "DV"),
            ("Calcul et Cypher en lecture", "Toute arithmétique hors du LLM ; requêtes en transaction de lecture", "CA")]),
        ("Données", "data", [
            ("Neo4j — graphe de connaissances", "Ontologie et termes, classeurs, news, entités, diagnostics", "NJ"),
            ("Postgres market intelligence", "5,8 M métriques, référentiels, 37,6 k articles Argus", "PG"),
            ("Fichiers et files de revue", "Classeurs Excel, specs/, data/diagnoses/, proposals.jsonl", "FS")]),
    ]
    ys, y = [], 160
    for i, (label, role, cards) in enumerate(layers):
        if i:
            s.line(x + w / 2, y - gap + 4, x + w / 2, y - 4)
        ys.append(y)
        y += band(s, x, y, w, label, role, cards) + gap
    bottom = y - gap
    py = ys[2]
    h = side_panel(s, 1216, py, 360, "Fournisseurs LLM", "llm", [
        ("Claude API", "Orchestrateur et sous-agents (tool runner)", "CL"),
        ("Azure OpenAI", "Agents gpt-5.4, extraction gpt-4.1-mini", "AZ"),
        ("Passerelle on-premise", "Option OCP, API compatible OpenAI", "OP")])
    s.line(1216 - 4, py + 72, x + w + 4, py + 72)
    ry = max(py + h + 30, ys[4])
    side_panel(s, 1216, ry, 360, "Revue humaine", "review", [
        ("Files de revue", "Termes, specs, fusions, diagnostics : approuver, corriger, rejeter", "RQ"),
        ("Rechargement", "Les décisions reviennent dans le graphe, avec un dry-run avant", "RL")])
    s.line(x + w + 4, ry + 72, 1216 - 4, ry + 72, dash="6 5")
    ly = bottom + 40
    legend(s, 64, ly, [("appel synchrone", None, None), ("proposition vers une file de revue (validation humaine)", "6 5", None)])
    s.wrapped(64, ly + 36, "Le LLM ne calcule ni n’invente aucun nombre : il résout les termes, choisit les outils et explique. Les chiffres viennent des "
              "moteurs déterministes et des données, chaque affirmation cite un nœud, une cellule ou un article, et toute écriture dans le "
              "graphe passe par une revue humaine.", 1512, 12.5)
    s.h = int(ly + 90)
    s.save(OUT / "01-architecture-agentique.svg")


# ---------- figure 2: data flow ----------

def figure_flows():
    s = Svg(1700, 1000)
    header(s, "Flux de données — des sources au graphe",
           "Chargements idempotents · étapes LLM manuelles et mises en cache · toute requête temporelle est « as of » une date de publication")
    gy, gh = 170, 530

    def group(x, label, role, cards):
        s.group(f"Groupe — {label}")
        s.rect(x, gy, 440, gh, PALETTE[role][0], PALETTE[role][1], r=12)
        band_label(s, x, gy, label, role)
        for i, (t, d, c) in enumerate(cards):
            card(s, x + 21.5, gy + 46.5 + i * 118, 397, 104, t, d, role, c)  # 104 fits three lines
        s.end()

    group(64, "Sources", "data", [
        ("Classeurs Excel market intelligence", "40 fichiers, 739 feuilles (Argus, CRU, S&P) ; mises en page hétérogènes, formules, totaux", "XL"),
        ("Base market intelligence (Postgres)", "5,8 M métriques de l’ancien pipeline, référentiels pays, régions, produits, entités", "PG"),
        ("Actualités Argus", "37,6 k articles (corporate_data.argus_news), texte conservé dans Postgres", "AR"),
        ("Connaissance curée (YAML)", "ontology.yaml, term_additions.yaml, référentiel d’ingestion, documentation des casters", "YM")])
    group(1196, "Graphe Neo4j", "front", [
        ("Cœur — concepts et termes", "Org, sites, produits, intrants, métriques, pays, régions, routes ; termes FR / EN", "CO"),
        ("Graphe des classeurs", "Workbook → Sheet → MENTIONS → Concept ; ROUTED_TO → Caster ; specs", "WB"),
        ("Sous-graphe news", "Article, Event, Incident, PriceAssessment ; AFFECTS, OF, AT, BASIS", "NW"),
        ("Sous-graphe entités", "SourceEntity → SAME_AS {statut} → Asset → LOCATED_AT → site", "EN")])
    flows = [
        ("Flux 1 — classeurs → graphe des classeurs", "profile_excels.py profile chaque feuille ; workbook_graph.py relie en-têtes et libellés aux concepts.", "det"),
        ("Flux 2 — référentiels → cœur", "import_referentials et import_referential_yaml : pays, régions, alias de produits, sociétés.", "det"),
        ("Flux 3 — articles → sous-graphe news", "news_graph relie les articles aux concepts ; news_extract ne garde que les citations retrouvées mot pour mot.", "llm"),
        ("Flux 4 — enregistrements → actifs", "entity_resolution propose des regroupements (LLM) ; chargement déterministe au statut « proposé ».", "llm"),
    ]
    for i, (t, d, role) in enumerate(flows):
        y = 216.5 + i * 120
        flow_row(s, 580, y, 520, 104, t, d, role)
        s.line(504 + 8, y + 52, 580 - 2, y + 52)
        s.line(1100 + 12, y + 52, 1196 - 2, y + 52)
    note_band(s, 64, 740, 1572, 72, "Restitution et revue (sortant)",
              "Réponses citées, specs d’extraction et diagnostics de variance partent en file de revue (specs/, data/diagnoses/, proposals.jsonl) ; "
              "une fois validés, ils reviennent dans le graphe au prochain chargement.", "review")
    note_band(s, 64, 828, 1572, 72, "Mécanismes transverses de tous les flux",
              "load_all.sh rejouable · dry-run de l’ontologie avant rechargement · requêtes « as of » sans fuite d’information future · "
              "étapes LLM lancées à la main et mises en cache · lecture seule pour les agents.", "det")
    legend(s, 64, 935, [("chargement déterministe", None, PALETTE["det"][2]), ("étape avec extraction LLM vérifiée", None, PALETTE["llm"][2])])
    s.text(64, 966, "Les volumes cités sont ceux de l’exploration du 25-09-2026 ; les routes de prix utilisées par le diagnostic sont à vérifier "
                    "avec scripts/check_driver_series.py.", 12, 400, PALETTE["ink3"])
    s.save(OUT / "02-flux-de-donnees.svg")


# ---------- figure 3: graph creation process ----------

def figure_build():
    s = Svg(1700, 1400)
    header(s, "Création du graphe — processus de chargement",
           "Ordre de load_all.sh · le LLM enrichit hors ligne, des contrôles déterministes filtrent, un humain valide avant publication")
    x, w, gap = 64, 1572, 46
    y = 160
    y += band(s, x, y, w, "Entrées", "data", [
        ("ontology.yaml", "Concepts, termes et relations, illustratifs, à valider par les contrôleurs", "ON"),
        ("Référentiel d’ingestion", "Alias pays, régions, produits ; sociétés, unités ; règles des casters", "RF"),
        ("Classeurs Excel", "Profil de mise en page : en-têtes, blocs, formules, cellules fusionnées", "XL"),
        ("Postgres market intelligence", "Référentiels, métriques, articles Argus", "PG")]) + gap
    rows = [[("load_knowledge", "Ontologie ; dry-run du diff avant", "1"), ("import_referentials", "Pays et régions", "2"),
             ("import_referential_yaml", "Alias, liens pays → région, sociétés", "3"), ("load_term_additions", "Termes validés", "4"),
             ("workbook_graph", "Classeurs, feuilles, MENTIONS", "5")],
            [("import_caster_knowledge", "Mémoire de mise en page", "6"), ("news_graph", "Articles ↔ concepts", "7"),
             ("news_extract load", "Événements, incidents, prix vérifiés", "8"), ("entity_resolution load", "Actifs, fusions proposées", "9")]]
    cw = (w - 43 - 36 * 4) / 5
    ch = card_height([d for row in rows for _, d, _ in row], cw)
    h = 46.5 + 2 * ch + 16 + 20
    s.group("Étape — Chargement déterministe (load_all.sh)")
    s.rect(x, y, w, h, PALETTE["det"][0], PALETTE["det"][1], r=12)
    band_label(s, x, y, "Chargement déterministe (load_all.sh, dans l’ordre)", "det")
    for r, row in enumerate(rows):
        for i, (t, d, c) in enumerate(row):
            cx = x + 21.5 + i * (cw + 36)
            cy = y + 46.5 + r * (ch + 16)
            card(s, round(cx, 1), round(cy, 1), round(cw, 1), round(ch, 1), t, d, "det", c)
            if i < len(row) - 1:
                s.chevron(round(cx + cw + 15, 1), round(cy + ch / 2 - 6, 1))
    s.end()
    y += h
    stages = [
        ("Enrichissement par LLM (hors ligne, mis en cache)", "llm", [
            ("news_extract extract", "Prix et événements extraits des articles, citation exacte exigée", "NE"),
            ("entity_resolution propose", "Regroupe ~150 enregistrements OCP en actifs canoniques", "ER"),
            ("Agent classeurs", "Propose des specs d’extraction, exécutées et contrôlées aussitôt", "WB"),
            ("propose_term", "Termes inconnus envoyés en file de revue", "PT")]),
        ("Contrôles déterministes", "det", [
            ("Citation vérifiée", "La citation doit se retrouver mot pour mot dans l’article", "CV"),
            ("Garde-fou d’aberrations", "Prix à plus de ×2 de la médiane de sa série : rejeté", "GA"),
            ("Contrôles de specs", "Totaux, unités, orientation, couverture ; diff avec la base", "CS"),
            ("Contrôles de diagnostics", "Pilotes du classement, chemin dans le graphe, preuves citées", "CD")]),
        ("Revue humaine et publication", "review", [
            ("Termes", "Ajoutés à term_additions.yaml puis rechargés", "TE"),
            ("Specs d’extraction", "Approuvées dans l’onglet Spec review", "SP"),
            ("Fusions d’entités", "Approuvées dans l’onglet Entités", "FE"),
            ("Diagnostics de variance", "Approuvés ou corrigés ; deviennent des analogues étiquetés", "DG")]),
    ]
    for label, role, cards in stages:
        s.line(x + w / 2, y + 4, x + w / 2, y + gap - 4)
        y += gap
        y += band(s, x, y, w, label, role, cards)
    s.text(64, y + 40, "Paramétrage : ontology.yaml · term_additions.yaml · driver_series.yaml · .env (fournisseur LLM, NEO4J_URI, "
                       "MARKET_INTEL_DSN, EXCEL_DIR)", 12.5, 400, PALETTE["ink2"])
    s.h = int(y + 70)
    s.save(OUT / "03-creation-du-graphe.svg")


if __name__ == "__main__":
    figure_architecture()
    figure_flows()
    figure_build()
    print("wrote", sorted(p.name for p in OUT.glob("*.svg")))
