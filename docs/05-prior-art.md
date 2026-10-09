# Prior Art Sweep (2026-09-25)

The question behind this sweep: has someone already built "an agent + graph that understands messy commodity Excels and news, and explains price moves"? **Not end to end.** Every piece has solid prior work, though, and we should reuse it rather than reinvent it.

## A. Messy spreadsheets

| Work | What it does | What we take |
|---|---|---|
| **SheetCompass** (2026) [arXiv 2608.14452](https://arxiv.org/html/2608.14452) | Table → column hierarchical graph; semantic edges; Explorer / Programmer / Reflector agents | Workbook graph design, role split, reflector loop |
| **SpreadsheetAgent**: *Robust Real-World Spreadsheet Understanding with Multi-Agent Multi-Format Reasoning* (2026) [arXiv 2604.12282](https://arxiv.org/html/2604.12282), code: [renhouxing/SpreadsheetAgent](https://github.com/renhouxing/SpreadsheetAgent) | Extraction agent reads **local regions** incrementally (code, image and LaTeX views), writes a **YAML intermediate representation** of layout, hierarchical headers and merged cells, then a **verification module** cross-checks it | Our "extraction spec" should be a YAML layout description. Verify before trusting it. Read regions, not whole sheets |
| **BRTR / FRTR**: *Beyond Rows to Reasoning* (2026) [arXiv 2603.06503](https://arxiv.org/html/2603.06503v1) | Agentic retrieval over multi-sheet enterprise workbooks: row/column/window/image chunks, hybrid search, iterative tool calls, planner–executor | Reports **95% on FINCH (finance workflows) with Claude Opus**, versus 41.9% prior best. Tool-calling retrieval beats one-shot "dump the sheet" |
| **SpreadsheetLLM / SheetCompressor** (Microsoft, 2024) [arXiv 2407.09025](https://arxiv.org/abs/2407.09025); impls: [sheetwise](https://github.com/Khushiyant/sheetwise), [Spreadsheet_LLM_Encoder](https://github.com/kingkillery/Spreadsheet_LLM_Encoder) | Structural anchors + inverted index + format aggregation, about 25× compression; better table detection | How to show a 10,000-row sheet to an LLM cheaply: send a **skeleton**, not the cells |
| **Auto-Tables** (Microsoft/VLDB) [arXiv 2307.14565](https://arxiv.org/abs/2307.14565), [benchmark](https://github.com/LiPengCS/Auto-Tables-Benchmark), [replication](https://github.com/npnkhoi/autotables-replicate) | Turns non-relational tables into relational ones with a **fixed operator set: explode, ffill, pivot, stack, subtitle, transpose, wide_to_long**. Handles >70% of real cases | **Key idea:** the LLM *chooses operators from this closed vocabulary* instead of writing free Python. That makes the specs deterministic, reviewable and replayable, and it would replace most of the 56 hand-written casters |
| **pycel** [github](https://github.com/dgorissen/pycel), **excel-grapher** [github](https://github.com/Teal-Insights/excel-grapher) | Formula → dependency graph; evaluate formulas in Python | Turn `SUMIF` / `=D5+D56…` totals into `AGGREGATES` edges, so totals become checksums instead of double counts |
| Survey list: [Awesome-Tabular-LLMs](https://github.com/SpursGoZmy/Awesome-Tabular-LLMs) | | Reading list |

## B. Graphs + agents for supply chain and events

| Work | What it does | What we take |
|---|---|---|
| **Helicase** (2026) [arXiv 2605.26835](https://arxiv.org/abs/2605.26835), code: [Yunbo-max/Helicase](https://github.com/Yunbo-max/Helicase) | Multi-agent LLM builds **supply-chain KGs** with a planner, web/reasoning/coding agents and **uncertainty per fact** (consensus-based, multiplicative accumulation, stop on convergence). Graph F1 0.85 on multi-hop queries | Confidence scores on self-grown edges (our events layer); entity resolution (fuzzy + LLM fallback) |
| **supply-chain-intelligence** [divanshu0312/supply-chain-intelligence](https://github.com/divanshu0312/supply-chain-intelligence) | Public-data POC: **world events → supplier / plant / revenue risk** for a manufacturer. KG + Monte Carlo + Prophet/LSTM + LLM briefs | **Closest to our use case in shape** (events → plants → P&L exposure). Worth reading for structure |
| **Graphiti / Zep** [getzep/graphiti](https://github.com/getzep/graphiti) (20k+ stars) | **Bi-temporal** KG for agents: every edge has `t_valid` / `t_invalid` plus ingestion time, incremental episode ingestion, entity resolution, runs on **Neo4j** | Strong candidate for the **news/events layer** instead of hand-rolling temporal edges |
| **neo4j-graphrag-python** [neo4j/neo4j-graphrag-python](https://github.com/neo4j/neo4j-graphrag-python) | Official: KG-building pipeline, vector / hybrid / **text2cypher** retrievers, `ToolsRetriever`; **supports Anthropic** | Retrievers and text2cypher instead of writing our own |
| **Neo4j LLM Graph Builder** [labs page](https://neo4j.com/labs/genai-ecosystem/llm-graph-builder/) | Text → graph UI | Quick demo tool, not core |
| **GDELT + KG** [GDELT blog](https://blog.gdeltproject.org/talking-to-gdelt-through-knowledge-graphs/); TKGQA survey [arXiv 2406.14191](https://arxiv.org/pdf/2406.14191); Plan-of-Knowledge [arXiv 2511.04072](https://arxiv.org/pdf/2511.04072) | Event KGs from news; temporal-KG question answering | Event schema ideas; temporal question decomposition |
| **MIRAI** [arXiv 2407.01231](https://arxiv.org/pdf/2407.01231) | Benchmark for LLM agents forecasting events from GDELT with tools | How to evaluate "what happens next" claims |
| Stock-market KG with explainable LLM reasoning [arXiv 2601.11528](https://arxiv.org/html/2601.11528v1) | GraphDB + LLM multi-hop reasoning, text2cypher | Confirms the pattern |

## C. Events → commodity prices: methodology warnings

- **Look-ahead leakage.** [arXiv 2508.06497](https://arxiv.org/pdf/2508.06497) fuses LLM-summarized news with commodity prices and reports 0.94 AUC. A [review](https://pith.science/paper/2508.06497) shows the summaries were written and fact-checked with hindsight, so the news stream carried the answer (AUC fell to 0.46 without it). **Our rule:** every "what did we know at date t" query filters on `publication_date ≤ t` (bitemporal). Event summaries must never be written using later articles.
- Macro multi-agent LLMs for commodity portfolios [arXiv 2606.08283](https://arxiv.org/html/2606.08283v1) show only marginal gains over rules, and the "debate" setup mostly averaged the agents' priors. **Our takeaway:** use LLMs for structure and explanation, not as oracles.
- Event-driven break detection in energy prices around the 2026 Iran war [arXiv 2609.00402](https://arxiv.org/pdf/2609.00402) is a statistical (CNN) change-point method. It could feed `FOLLOWED_BY_MOVE` detection.

## D. Domain context: Hormuz and fertilizers (for grounding, verify before quoting)

Public analyses (e.g. [IFPRI event](https://www.ifpri.org/event/a-narrow-strait-global-consequences-hormuz-strait-and-fertilizer-markets/), [WTO data blog](https://www.wto.org/english/blogs_e/data_blog_e/blog_dta_10jul26_451_e.htm), [StoneX](https://www.stonex.com/en/insights/fertilizer-s-spring-reckoning-now-runs-through-the-strait-of-hormuz/), [Rabobank](https://www.rabobankna.com/knowledge-hub/strait-of-hormuz-impacts-global-fertilizer-market/), [farmdoc](https://farmdocdaily.illinois.edu/2026/04/strait-of-hormuz-disruption-scenarios-and-fertilizer-purchasing-risks-for-u-s-crop-producers.html)) put roughly **~45% of global sulphur exports, ~35% of urea, >25% of ammonia and ~20% of phosphates** through the Strait of Hormuz. That is exactly the multi-hop channel our graph should encode (Hormuz → sulphur → sulfuric acid → phosphoric acid → DAP cost). These figures come from search summaries. **Check the primary source before putting any of them in a deliverable.**

## E. Root-cause analysis and explanations

Added 2026-10-09. Drives the [variance diagnosis design](08-variance-diagnosis.md).

| Work | What it does | What we take |
|---|---|---|
| **KG-guided RAG for root-cause analysis** [arXiv 2608.11277](https://arxiv.org/html/2608.11277) | Automotive test-bench recordings: deterministic evidence against a healthy baseline (z-scores, first abnormal time), candidates scored from a KG (primary > direct > propagation), case retrieval on z-vectors, LLM as reranker with strict JSON, window votes per recording. Gemma-3 27B / Qwen3 32B on-prem best (Top-1 0.90 / 0.94). Only 13 recordings, one fault type | **The whole pipeline shape**, mapped to P&L drivers. Structured z-vectors beat raw values, text and sentence embeddings for retrieval. Leave-one-out against leakage. Injected faults as ground truth |
| **Causal-LLM** [preprint](https://www.preprints.org/manuscript/202602.1711), [ACM](https://dl.acm.org/doi/10.1145/3801228.3801315) | Budget variance: a variance above a threshold (5-10%) triggers causal discovery (PC algorithm) guided by a financial causal KG, then LLM reasoning. 0.87 top-1 vs 0.76 LLM alone, 240 cases, one manufacturer, not peer-reviewed | Threshold trigger; the causal KG as prior = our `DEPENDS_ON` |
| **Cascading disruptions: gas → fertilizers → crops** [arXiv 2605.06411](https://arxiv.org/html/2605.06411v1) | Network model over 208 countries; shocks start upstream (gas, mineral fertilizers) and propagate down | Grounding for propagation edges and role weights |
| **ConflictQA / XoT** [arXiv 2604.11209](https://arxiv.org/html/2604.11209v1) | Benchmark of conflicts between KG and text evidence; LLMs often pick the wrong side. XoT explains each candidate before choosing | When the ontology and an Argus article disagree, show both, do not let the LLM silently pick |
| **Case-based reasoning with LLMs** [CBR-RAG](https://arxiv.org/html/2404.04302v1), [CBR agents](https://arxiv.org/abs/2504.06943v2) | Case retrieval for LLMs; explicit case features help when domain factors are known | Analog episodes as structured cases, not embedded news text |
| **Graph explainability (GNN) list** [flyingdoog/awesome-graph-explainability-papers](https://github.com/flyingdoog/awesome-graph-explainability-papers) | ~500 papers on explaining trained GNNs | Mostly not applicable (no GNN). Keep: fidelity tests (remove the explanation, does the result change?), "GNN explanations are fragile" (ICML 2024), eXpath path rules (VLDB 2025) if we ever predict links |

Not read beyond search snippets: [GALA](https://arxiv.org/pdf/2608.08968) and [Think Locally, Explain Globally](https://arxiv.org/pdf/2601.17915) (graph-guided RCA agents for IT incidents). No published system was found that decomposes P&L movements into drivers and has an agent rank root causes.

## Decisions this sweep drives

1. **Excel extraction specs = YAML using the Auto-Tables operator vocabulary** (plus header parsing into concepts), proposed by the agent, verified, approved once, then replayed deterministically. This aims to replace the 56 casters.
2. **Show sheets to the LLM as SpreadsheetLLM-style skeletons**, and let it pull regions through tools (BRTR / SpreadsheetAgent style).
3. **Parse formulas into `AGGREGATES` edges** (pycel / excel-grapher or a light parser), so totals are recognized and used as checksums.
4. **Evaluate against the existing 5.8M `metrics` rows.** They are an imperfect but large ground truth.
5. **Events layer: try Graphiti on our Neo4j** before building our own. Use `neo4j-graphrag-python` retrievers where they fit.
6. **Every temporal query is "as of" a publication date**, which avoids leakage.
7. **Variance questions go through a deterministic `diagnose_variance` tool** (candidates from the graph, deviations against a baseline, analogs on z-vectors); the LLM only reranks and explains, and the Reflector checks its JSON against the evidence. See [08-variance-diagnosis.md](08-variance-diagnosis.md).
