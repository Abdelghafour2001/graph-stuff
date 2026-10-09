"""Orchestrator agent (OCP vocabulary, products, org, workbooks) plus specialist sub-agents with their own prompts and tools.

Specialists are exposed to the orchestrator as tools (agent-as-tool); each runs its own tool loop with a fresh history."""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import openai
from anthropic import beta_tool

from entity_tools import ocp_assets, resolve_entity
from excel_tools import describe_formulas, describe_sheet, find_sheets, propose_extraction_spec, read_range
from graph import driver, read_graph
from news_tools import event_timeline, price_assessments, price_monthly, price_routes, read_article, search_articles
from variance_tools import diagnose_variance, submit_diagnosis

MODEL = "claude-opus-5"
MAX_TOOL_ROUNDS = 30
REFLECTION_ROUNDS = 2
PROPOSALS = Path(__file__).parent.parent / "knowledge" / "proposals.jsonl"

SYSTEM = """You are the finance-knowledge agent of OCP Group. You help controllers understand and later compute the P&L across branches and business units.

The Neo4j graph is your source of truth about the business:
- (:Concept) nodes with extra label OrgUnit | Site | Product | Input | Metric | Unit | Incoterm | Route | Country | Region, properties id, kind, name, definition.
- (:Term {text})-[:REFERS_TO]->(:Concept): every word people use (French, English, abbreviations).
- Relations: PART_OF (org tree), PRODUCED_AT (product->site), MADE_FROM (product->product/input),
  DEPENDS_ON (metric->metric/input), MEASURED_IN (product->unit), TRANSITS (a large share of the product's world trade passes the route), IN_REGION (country->region).
- (:Workbook)-[:HAS_SHEET]->(:Sheet {file, name, role, description, layout features, header_cells})-[:MENTIONS {where, n}]->(:Concept):
  the market-intel Excel files (Argus, CRU, S&P). role is contents | data | dashboard | other.

Working with workbooks:
- To find where a fact lives, resolve the words to concepts, then call find_sheets. Prefer role=data sheets; dashboards are formula views with drop-downs, not data.
- Before proposing how to extract a sheet, call describe_sheet, then read_range on the regions you are unsure about (header rows, first data rows, total rows).
  When a workbook has formulas (a branch's own model), call describe_formulas first: its rules tell you which rows are inputs,
  which are computed (never extract computed rows as inputs) and which numbers come from files we do not have.
  Watch for: multi-row headers, several tables stacked in one sheet, formula total rows (never extract them as data), forecast markers, units in preamble rows.
- Express extraction as propose_extraction_spec. It runs your spec and returns checks. If any check fails, fix the spec and propose again
  (up to 4 attempts). Never claim success while checks fail; report the remaining failures honestly.
- Corner cells like "Importers\Exporters" mean rows\columns. Unlabeled rows right under the header are often totals. Units are usually stated
  in the rows above the table (e.g. "Data in 000 tonnes product" means kt).

Rules:
- Resolve every business word through lookup_term before reasoning about it. Users mix French, English and internal abbreviations.
- Answer only from what the graph returns. If the graph does not know a term or fact, say so plainly and call propose_term if you can suggest a mapping; a human will review it.
- Never state or invent numbers (prices, volumes, ratios, costs) that you did not read from a tool result; cite file, sheet and cell range for any number you quote.
- Cite concept ids you relied on at the end of the answer.
- Answer in the user's language.

Specialists:
- For news, geopolitical events (e.g. the 2026 US-Iran war, Hormuz shipping) and realized market prices reported in Argus daily reports,
  call ask_news_agent with a precise sub-question (products, places, period). It returns evidence with article ids and quotes.
- Then connect its evidence to OCP with the graph (MADE_FROM chains, TRANSITS routes, sites, competitors) and say which links are
  hypotheses to verify with OCP data.

- For OCP plants, companies and competitors as named in data sources, use resolve_entity / ocp_assets: ~150 source records were
  resolved into canonical assets (merges are "proposed" until a human approves them; say so when it matters).

Impact playbook (e.g. "how did event X affect the price of product P, and what does it mean for OCP?"):
1. Resolve P and the places/routes involved. Use describe_concept / run_cypher to get P's inputs (MADE_FROM, several hops) and which of
   them TRANSITS a route touched by the event (e.g. hormuz).
2. Ask the news specialist, in ONE precise question, for: the incident timeline for the route and those inputs; monthly prices of P on
   its main routes (at least Morocco fob if available, China fob, India cfr) before vs during the event; and monthly prices of the
   inputs that transit the route (e.g. sulphur and ammonia on their Middle East / Gulf routes: ask it to pick routes with price_routes).
3. Answer with: a dated timeline, a before/during table per route (numbers only from tools), the transmission channels (supply via the route,
   input costs, freight), then OCP implications split into "supported by evidence" and "hypotheses to verify". Cite article ids.
   Check OCP facts in the graph before stating them (e.g. OCP sites are in Morocco and its exports do not transit hormuz).
Variance playbook ("why did metric M of product P move in month X?"):
1. Resolve M, P and the month with lookup_term. Call diagnose_variance(metric_id, product_id, period).
2. Read its report: ranked drivers with their moves, earlier moves still passing through, analogs, incidents, and drivers
   without a series (say they cannot be ruled out). It runs in signal mode: never claim how many $/t a driver cost.
3. Call submit_diagnosis with the JSON it asks for. Fix and resubmit until it is accepted.
4. Answer: ranked drivers with their numbers and evidence ids, the propagation path, related incidents (article ids),
   the outlook only as what analog months did next (no forecast of your own), and the uncertainty.

Numbers: only from tool results; compute differences and percentages with calc. An automatic Reflector rejects other numbers and
answers that do not cite article ids returned by tools.
"""

NEWS_SYSTEM = """You are the news specialist of OCP Group's market-intelligence team. You own the news subgraph:
(:Article {id, headline, published_at})-[:MENTIONS]->(:Concept); (:Event {date, type, summary, quote})-[:AFFECTS {direction, channel}]->(:Concept)
and -[:REPORTED_IN]->(:Article); (:PriceAssessment {date, low, high, mid, incoterm, quote})-[:OF]->(product), -[:AT]->(place), -[:BASIS]->(incoterm).
Events and price assessments were extracted from Argus articles by a model and kept only when their quote was found verbatim in the article.

How to work:
- Resolve words to concept ids with lookup_term first (products, countries, routes like hormuz, incoterms like fob).
- Use event_timeline for what happened and when; use price_monthly for numbers over time (computed by the database) and
  price_assessments or read_article to show the underlying quotes.
- To measure an impact, compare the months before an event with the months after, per location and incoterm; never mix incoterms.
- Every claim must cite an article id (and date). Never invent numbers; only report numbers returned by tools.
- Say plainly when evidence is thin (few assessments, single source).
- For price questions call price_routes first and cover the routes with the most assessments; report each route separately."""


@beta_tool
def lookup_term(text: str) -> str:
    """Find which business concepts a word or abbreviation refers to (case-insensitive, partial match).

    Args:
        text: A single word or short phrase exactly as the user wrote it, e.g. "ACP", "coût de revient", "soufre".
    """
    rows = read_graph(
        "MATCH (t:Term)-[:REFERS_TO]->(c:Concept) "
        "WHERE toLower(t.text) = toLower($q) OR toLower(t.text) CONTAINS toLower($q) "
        "RETURN DISTINCT c.id AS id, c.kind AS kind, c.name AS name, c.definition AS definition, "
        "toLower(t.text) = toLower($q) AS exact ORDER BY exact DESC",
        q=text,
    )
    return json.dumps(rows, ensure_ascii=False) if rows else f"No concept known for '{text}'."


@beta_tool
def describe_concept(concept_id: str) -> str:
    """Get a concept with all its direct relations (in and out).

    Args:
        concept_id: Concept id returned by lookup_term, e.g. "dap".
    """
    rows = read_graph(
        "MATCH (c:Concept {id: $id}) RETURN c {.*} AS concept, "
        "[(c)-[r]->(o:Concept) | {rel: type(r), to: o.id}] AS outgoing, "
        "[(i:Concept)-[r]->(c) | {rel: type(r), from: i.id}] AS incoming, "
        "[(t:Term)-[:REFERS_TO]->(c) | t.text] AS terms",
        id=concept_id,
    )
    return json.dumps(rows[0], ensure_ascii=False) if rows else f"No concept with id '{concept_id}'."


@beta_tool
def run_cypher(query: str) -> str:
    """Run a read-only Cypher query for multi-hop questions (e.g. full supply chain of a product, all inputs a metric depends on). Writes are rejected.

    Args:
        query: Cypher query. Returns at most 50 rows.
    """
    return json.dumps(read_graph(query), ensure_ascii=False, default=str)


@beta_tool
def propose_term(term: str, concept_id: str, reason: str) -> str:
    """Propose adding an unknown term to the glossary. Goes to a human review queue, does not change the graph.

    Args:
        term: The unknown word or abbreviation.
        concept_id: Existing concept id it probably refers to, or "new" if no concept fits.
        reason: Why you think so.
    """
    entry = {"term": term, "concept_id": concept_id, "reason": reason, "at": datetime.now(timezone.utc).isoformat()}
    with PROPOSALS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return "Proposal queued for human review."


@beta_tool
def calc(expression: str) -> str:
    """Evaluate an arithmetic expression exactly (use it for every derived number: differences, percentages, averages).

    Args:
        expression: Numbers, + - * / and parentheses only, e.g. "(897.1 - 705.3) / 705.3 * 100".
    """
    assert re.fullmatch(r"[0-9+\-*/(). ]+", expression) and "**" not in expression, "only numbers, + - * / and parentheses are allowed"
    return f"{expression} = {round(eval(expression, {'__builtins__': {}}), 4)}"


NEWS_TOOLS = [lookup_term, describe_concept, search_articles, read_article, event_timeline, price_routes, price_monthly, price_assessments, calc]


@beta_tool
def ask_news_agent(question: str) -> str:
    """Delegate a sub-question to the news specialist (Argus news, extracted events, realized price assessments).
    Returns its answer with article ids and quotes.

    Args:
        question: Precise sub-question with products, places and period, e.g. "How did DAP fob prices in China and cfr India
            move from February to June 2026, and which Hormuz-related events happened then?"
    """
    trace: list[dict] = []
    answer = run(NEWS_SYSTEM, NEWS_TOOLS, [{"role": "user", "content": question}], trace)
    return json.dumps({"answer": answer, "tool_calls": [c["tool"] for c in trace],
                       "evidence": [c["result"] for c in trace if c["tool"] != "reflector"]}, ensure_ascii=False)


TOOLS = [lookup_term, describe_concept, run_cypher, propose_term, find_sheets, describe_sheet, describe_formulas, read_range, propose_extraction_spec, ask_news_agent,
         resolve_entity, ocp_assets, diagnose_variance, submit_diagnosis, calc]


def ask_anthropic(system: str, tools: list, history: list[dict], trace: list[dict]) -> str:
    runner = anthropic.Anthropic().beta.messages.tool_runner(
        model=MODEL,
        max_tokens=16000,
        system=system,
        tools=tools,
        messages=history,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    for final in runner:
        calls = [b for b in final.content if b.type == "tool_use"]
        if not calls:
            continue
        # The runner caches this response, so the tools run once; the results go into the trace for the Reflector.
        response = runner.generate_tool_call_response() or {"content": []}
        results = {r["tool_use_id"]: r.get("content", "") for r in response["content"]}
        for b in calls:
            result = results.get(b.id, "")
            if not isinstance(result, str):
                result = " ".join(part.get("text", "") for part in result)
            trace.append({"tool": b.name, "input": b.input, "result": result})
    assert final.stop_reason != "refusal", f"refused: {final.stop_details}"
    return "".join(b.text for b in final.content if b.type == "text")


def ask_azure(system: str, tools: list, history: list[dict], trace: list[dict]) -> str:
    client = openai.AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    )
    by_name = {t.name: t for t in tools}
    specs = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}} for t in tools]
    messages = [{"role": "system", "content": system}, *history]
    for _ in range(MAX_TOOL_ROUNDS):
        msg = client.chat.completions.create(model=os.environ["AZURE_OPENAI_AGENT_DEPLOYMENT"], messages=messages, tools=specs).choices[0].message
        if not msg.tool_calls:
            return msg.content
        messages.append(msg.model_dump(exclude_none=True))
        for call in msg.tool_calls:
            print(f"  [tool] {call.function.name}({call.function.arguments[:150]})")
            try:
                result = by_name[call.function.name].call(json.loads(call.function.arguments))
            except Exception as e:  # tool errors go back to the model so it can correct itself
                result = f"Tool error: {e}"
            trace.append({"tool": call.function.name, "input": call.function.arguments, "result": result})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    raise AssertionError(f"no answer after {MAX_TOOL_ROUNDS} tool rounds")


def numbers(text: str) -> list[float]:
    """Numbers written in text, tolerant to thousands separators and decimal commas ("1 769,9", "1,769.9", "705.3")."""
    text = re.sub(r"(?<=\d)[   ,](?=\d{3}\b)", "", text)
    return [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", text)]


def reflect(answer: str, trace: list[dict]) -> list[str]:
    """Deterministic Reflector: numbers must come from tool results; article ids returned by tools must be cited."""
    evidence = " ".join(str(c["result"]) for c in trace)
    known = numbers(evidence)
    unsupported = sorted({n for n in numbers(answer)
                          if n >= 10 and not 1990 <= n <= 2100 and not any(abs(n - k) <= 0.01 * max(abs(k), 1) for k in known)})
    problems = [f"these numbers do not appear in any tool result: {unsupported[:15]}. Remove them, or get them from a tool (use calc for derived numbers)."] if unsupported else []
    article_ids = set(re.findall(r'\\*"article_id\\*": (\d+)', evidence))  # also inside the news agent's nested (escaped) JSON
    if article_ids and not article_ids & set(re.findall(r"\d{6,}", answer)):
        problems.append("cite the article ids (e.g. article 2795774) that support your claims.")
    return problems


def run(system: str, tools: list, history: list[dict], trace: list[dict]) -> str:
    """Tool loop, then the Reflector; failed checks go back to the model (REFLECTION_ROUNDS times)."""
    ask_provider = ask_azure if os.environ["LLM_PROVIDER"] == "azure_openai" else ask_anthropic
    messages = list(history)
    for _ in range(REFLECTION_ROUNDS):
        answer = ask_provider(system, tools, messages, trace)
        problems = reflect(answer, trace)
        if not problems:
            return answer
        trace.append({"tool": "reflector", "input": problems, "result": ""})
        messages += [{"role": "assistant", "content": answer}, {"role": "user", "content": "Reflector (automatic check): " + " ".join(problems)}]
    answer = ask_provider(system, tools, messages, trace)
    problems = reflect(answer, trace)
    return answer + (f"\n\n[Reflector: unresolved: {' '.join(problems)}]" if problems else "")


def ask(history: list[dict], question: str) -> tuple[str, list[dict]]:
    """Answer a question with the orchestrator; returns the answer and its tool calls. Appends both turns to history."""
    history.append({"role": "user", "content": question})
    trace: list[dict] = []
    answer = run(SYSTEM, TOOLS, history, trace)
    history.append({"role": "assistant", "content": answer})
    return answer, trace


if __name__ == "__main__":
    history: list[dict] = []
    print("OCP finance-knowledge agent. Empty line to quit.")
    while question := input("\n> ").strip():
        print(ask(history, question)[0])
    driver.close()
