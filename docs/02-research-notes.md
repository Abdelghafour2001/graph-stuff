# Research Notes

*Papers shared on 2026-09-25 and what we take from each one. The summaries are ours; read the originals for detail.*

## 1. SheetCompass: Hierarchical Relation Graphs for Agentic Spreadsheet Reasoning

Link: https://arxiv.org/html/2608.14452

**Problem.** LLMs fail on complex spreadsheets because flattening sheets into text destroys layout and cross-sheet dependencies.

**Method.**
- A hierarchical graph where table nodes have column nodes as children. Each column is described by its header plus sample values.
- Structural edges (table contains column, adjacent columns) and semantic edges (embedding similarity plus LLM-scored key/foreign-key logic).
- Three agents:
  - The **Explorer** splits the request into steps and extracts the relevant subgraph.
  - The **Programmer** writes code restricted to verified nodes and runs it in a sandbox.
  - The **Reflector** checks the result against a checklist and retries at most twice.
- Two memories: stable expert rules and templates, plus a per-task memory of reasoning trajectories. Successful paths are promoted to the expert memory.

**Results.** Beats SheetAgent and SheetCopilot. It loses much less accuracy when going from single-table to multi-table tasks. Removing the graph hurts the most in ablations.

**For us.** This is the blueprint for phase 4 (messy Excels):
- Model every incoming workbook as tables → columns.
- Link columns to our core concepts, e.g. column "Prix soufre CFR Jorf" → `sulfur`, unit USD/t.
- Generate extraction code that may only touch verified columns.
- Keep a Reflector with a finance checklist (units, currency, period, sums reconcile).
- Save each approved mapping as a reusable template.

## 2. Agentic Reasoning Graphs (topic overview)

Link: https://www.emergentmind.com/topics/agentic-reasoning-graph

**Idea.** Make the agent's reasoning explicit as a graph: states, steps, evidence and control flow, instead of leaving it hidden inside the model. The term covers a family of systems (GraphSearch, LEDGER, GraphBit, MemDreamer, …).

**Relevant takeaways.**
- **Deterministic orchestration** (GraphBit: an engine routes over a workflow DAG, not the LLM) cuts hallucinations and makes runs reproducible.
- **Keep provenance.** Pure triples lose their grounding, so link graph facts back to the source text (A2RAG).
- **Tiered memory** keeps context small.
- **Explicit graphs don't guarantee correctness.** Planning can still be brittle and extraction quality still matters.

**For us.**
- Store every answer as a reasoning trace (Layer 4) for audit and reuse.
- Keep calculation and routing deterministic wherever possible.
- Always link `Event`s back to their `Article`s.

## 3. Agentic Deep Graph Reasoning Yields Self-Organizing Knowledge Networks (Graph-PReFLexOR)

Link: https://arxiv.org/html/2502.13025v1

**Method.**
- An iterative loop of more than 1,000 cycles.
- Each cycle: the model reasons, a local graph is extracted from its output and merged into a global graph, and the next prompt is built from the newest nodes.
- There is no fixed ontology; structure emerges.

**Results.** The graph becomes scale-free (hub nodes) with stable modularity (~0.70). Persistent bridge nodes connect domains, and growth keeps going without saturating.

**For us.**
- This fits the **events/news layer** well, where new entities and relations appear constantly.
- It is **not acceptable for the finance core**, which must stay curated and reviewed. That leads to the split: curated core, plus a self-growing event layer with confidence, source and review status on every edge.
- The paper's advice to "seed with an expert taxonomy" is what phase 1 does.
- Graph health metrics (modularity, bridge nodes, path length) are worth monitoring once the event layer grows.
