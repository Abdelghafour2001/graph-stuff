"""Streamlit UI over the API: chat with the agent, explore workbooks, review extraction specs, see eval results."""
import json
import os

import pandas as pd
import requests
import streamlit as st

API = os.environ["API_URL"]
NEO4J_BROWSER = os.environ["NEO4J_BROWSER_URL"]


def get(path: str, **params):
    r = requests.get(f"{API}{path}", params=params, timeout=120)
    r.raise_for_status()
    return r.json()


def post(path: str, body: dict):
    r = requests.post(f"{API}{path}", json=body, timeout=900)
    r.raise_for_status()
    return r.json()


st.set_page_config(page_title="OCP graph agent", layout="wide")
st.sidebar.title("OCP graph agent")
st.sidebar.markdown(f"[Open Neo4j Browser]({NEO4J_BROWSER}) (neo4j / ocp-poc-password)")
st.sidebar.code("MATCH (p:Product {id:'dap'})-[:MADE_FROM*]->(x) RETURN p, x\n\nMATCH (s:Sheet)-[m:MENTIONS]->(c {id:'dap'}) RETURN s, c LIMIT 50", language="cypher")
counts = get("/health")["counts"]
st.sidebar.dataframe(pd.DataFrame(counts), hide_index=True)

chat, variance_tab, news, entities, workbooks, specs, evals = st.tabs(
    ["Ask the agent", "Variance", "News & prices", "Entities", "Workbooks", "Spec review", "Eval"])

with chat:
    st.session_state.setdefault("history", [])
    st.session_state.setdefault("turns", [])
    for turn in st.session_state.turns:
        st.chat_message("user").write(turn["question"])
        with st.chat_message("assistant"):
            st.write(turn["answer"])
            with st.expander(f"{len(turn['trace'])} tool calls"):
                for call in turn["trace"]:
                    st.code(f"{call['tool']}({json.dumps(call['input'], ensure_ascii=False) if isinstance(call['input'], dict) else call['input']})")
    if question := st.chat_input("Ask about OCP products, sites, workbooks, or ask for an extraction spec"):
        try:
            with st.spinner("Agent working, tool calls can take a minute…"):
                res = post("/ask", {"question": question, "history": st.session_state.history})
        except requests.HTTPError as e:
            try:
                detail = e.response.json().get("detail", e.response.text)
            except ValueError:
                detail = e.response.text[:500]
            st.error(f"The agent could not answer. {detail}")
        else:
            st.session_state.history = res["history"]
            st.session_state.turns.append({"question": question, "answer": res["answer"], "trace": res["trace"]})
            st.rerun()

with variance_tab:
    st.markdown("**Why did a metric move?** Deterministic ranking of drivers (no LLM). Signal mode: ranked by how unusual each "
                "driver's move was, not by $/t. Ask the agent for the explained version; its answers land in the review queue below.")
    c1, c2, c3 = st.columns(3)
    v_metric = c1.text_input("Metric", "gross_margin", key="v_metric")
    v_product = c2.text_input("Product", "dap", key="v_product")
    v_period = c3.text_input("Month (YYYY-MM)", "2026-08", key="v_period")
    if st.button("Diagnose", key="v_run", type="primary"):
        try:
            st.session_state.v_result = get("/variance", metric=v_metric, product=v_product, period=v_period)
        except requests.HTTPError as e:
            st.error(f"Diagnosis failed: {e.response.text[:300]}. Check the metric and product ids and the month (YYYY-MM).")
    res = st.session_state.get("v_result")
    if res:
        st.caption(f"{res['period']} vs baseline {res['baseline'][0]} … {res['baseline'][-1]}; earlier moves passing through "
                   f"searched in {', '.join(res['lookback'])}; as of {res['as_of']}")
        rows = [{"rank": r["rank"], "driver": r["id"], "role": r["role"], "move %": r.get("pct"), "z": r.get("z"),
                 "first abnormal": r.get("first_abnormal"),
                 "earlier move %": (r["earlier_move"] or {}).get("pct") if (r["earlier_move"] or {}).get("first_abnormal") else None,
                 "score": r["score"], "weekly votes": r["votes"], "path": " → ".join(reversed(r["path"])),
                 "routes": ", ".join(r["routes"])} for r in res["ranking"]]
        st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={
            "move %": st.column_config.NumberColumn(format="%+.1f"), "earlier move %": st.column_config.NumberColumn(format="%+.1f"),
            "z": st.column_config.NumberColumn(format="%+.2f"), "score": st.column_config.NumberColumn(format="%.3f")})
        if res["not_ranked"]:
            st.warning("No price series, so not ranked and not ruled out: " + ", ".join(res["not_ranked"]))
        left, right = st.columns(2)
        left.markdown("**Analog months**")
        left.dataframe(pd.DataFrame(res["analogs"]), hide_index=True)
        right.markdown("**Incidents on the top drivers**")
        right.dataframe(pd.DataFrame(res["incidents"]), hide_index=True)
        with st.expander("Report sent to the LLM"):
            st.code(res["report"])

    st.markdown("---\n**Review queue**: diagnoses the agent submitted. Approve or correct the top driver; reviewed months become "
                "labelled analogs for later diagnoses. Reject keeps a month out of the analogs.")
    queue = pd.DataFrame(get("/diagnoses"))
    if queue.empty:
        st.info("No diagnosis submitted yet. Ask the agent a variance question.")
    else:
        st.dataframe(queue, hide_index=True)
        names = list(queue["name"])
        pick = st.selectbox("Open diagnosis", names, index=None, placeholder="Pick a diagnosis to review", key="v_pick")
        if pick:
            d = get(f"/diagnoses/{pick}")
            ranked = [r["id"] for r in d["diag"]["ranking"]]
            a, b = st.columns(2)
            a.markdown("**Model answer**")
            a.json(d["answer"])
            b.markdown("**Deterministic ranking**")
            b.dataframe(pd.DataFrame([{"rank": r["rank"], "driver": r["id"], "score": r["score"], "votes": r["votes"]}
                                      for r in d["diag"]["ranking"]]), hide_index=True)
            if d.get("review"):
                st.success(f"Reviewed: {d['review']['decision']} (top driver {d['review']['top1']}) {d['review']['note']}")
            decision = st.radio("Decision", ["approved", "corrected", "rejected"], horizontal=True, key="v_decision")
            true_top = st.selectbox("True top driver", ranked, key="v_true") if decision == "corrected" else ""
            note = st.text_input("Note (why)", key="v_note")
            reviewer = st.text_input("Reviewer", key="v_reviewer")
            if st.button("Save decision", key="v_save", type="primary"):
                try:
                    post(f"/diagnoses/{pick}/review", {"decision": decision, "top1": true_top, "note": note, "reviewer": reviewer})
                    st.rerun()
                except requests.HTTPError as e:
                    st.error(f"Not saved: {e.response.text[:300]}. Fill in the reviewer and, for a correction, the true top driver.")

with news:
    word = st.text_input("Product", "DAP")
    found = get("/concepts", q=word)
    if not found:
        st.info(f"No concept matches “{word}”. Try a product name such as DAP, MAP or TSP.")
    else:
        product = found[0]["id"]
        prices = pd.DataFrame(get("/news/prices", product=product))
        if prices.empty:
            st.info(f"No price assessments for {product} yet.")
        else:
            routes = prices.groupby("route")["n"].sum().sort_values(ascending=False)
            chosen = st.multiselect("Routes (location + incoterm)", list(routes.index), default=list(routes.index[:5]))
            chart = prices[prices["route"].isin(chosen)].pivot(index="month", columns="route", values="avg_mid")
            st.markdown(f"**{found[0]['name']}: monthly average of Argus price assessments, $/t** (quote-verified extractions)")
            st.line_chart(chart)
            st.dataframe(prices[prices["route"].isin(chosen)], hide_index=True, height=200)
        extra = [w.strip() for w in st.text_input("Events affecting (comma separated)", "Hormuz, sulphur, ammonia, urea").split(",") if w.strip()]
        concept_ids = [product] + [hits[0]["id"] for hits in (get("/concepts", q=w) for w in extra) if hits]
        events = pd.DataFrame(get("/news/events", concept=concept_ids))
        st.markdown(f"**Events** affecting {', '.join(concept_ids)} ({len(events)})")
        if events.empty:
            st.info("No events linked to these concepts yet. Load news with the market-intel pipeline, then reload.")
        else:
            st.dataframe(events, hide_index=True, height=400)

with entities:
    table = pd.DataFrame(get("/entities/assets"))
    if table.empty:
        st.info("No assets yet. Run: python entity_resolution.py propose, then load.")
    else:
        st.markdown(f"**{len(table)} canonical assets** resolved from {int(table['records'].sum())} source records (proposed by the entity agent; approve after review)")
        st.dataframe(table.drop(columns=["source_names"]), hide_index=True, height=350)
        labels = [f"{r.asset} ({r.records} records, {r.confidence}, {r.status})" for r in table.itertuples()]
        choice = st.selectbox("Review asset", labels, index=None, placeholder="Pick an asset to see its source records")
        if choice:
            row = table.iloc[labels.index(choice)]
            st.write(row["reason"])
            st.code("\n".join(row["source_names"]))
            sure = row["status"] != "approved" and st.checkbox("I checked the source records above", key="e_sure")
            if row["status"] != "approved" and st.button("Approve merge", type="primary", disabled=not sure):
                post(f"/entities/assets/{row['asset_id']}/approve", {})
                st.rerun()

with workbooks:
    col1, col2 = st.columns([1, 2])
    with col1:
        words = st.text_input("Concepts (comma separated words, e.g. DAP, Morocco, fob)")
        role = st.selectbox("Role", ["", "data", "dashboard", "contents", "other"])
        concept_ids = []
        for w in [w.strip() for w in words.split(",") if w.strip()]:
            found = get("/concepts", q=w)
            if found:
                concept_ids.append(found[0]["id"])
                st.caption(f"{w} → `{found[0]['id']}` ({found[0]['kind']})")
            else:
                st.caption(f"{w} → unknown term")
        sheets = pd.DataFrame(get("/sheets", concept=concept_ids, role=role))
        st.write(f"{len(sheets)} sheets")
        pick = st.dataframe(sheets, hide_index=True, on_select="rerun", selection_mode="single-row", height=500)
    with col2:
        if pick.selection.rows:
            row = sheets.iloc[pick.selection.rows[0]]
            info = get("/sheet", file=row["file"], name=row["sheet"])
            st.subheader(f"{row['sheet']}")
            st.caption(f"{row['file']} · {info['sheet']['description']}")
            meta = {k: info["sheet"][k] for k in ("role", "rows", "cols", "header_row", "header_depth", "blocks", "formulas", "formula_total_rows", "merged", "time_in_columns")}
            st.dataframe(pd.DataFrame([meta]), hide_index=True)
            st.markdown("**Skeleton (first non-empty rows, 16 columns)**")
            st.code("\n".join(info["skeleton_first_16_cols"]))
            st.markdown("**Linked concepts**")
            if info["mentions"]:
                st.dataframe(pd.DataFrame(info["mentions"]).sort_values("n", ascending=False), hide_index=True, height=250)
            else:
                st.caption("No concept found on this sheet.")
            cells = st.text_input("Read range (A1)", "A1:H20")
            if st.button("Read"):
                st.code(get("/sheet/range", file=row["file"], name=row["sheet"], cells=cells)["text"])

with specs:
    all_specs = pd.DataFrame(get("/specs"))
    if all_specs.empty:
        st.info("No specs yet. Ask the agent to propose one.")
    else:
        st.dataframe(all_specs, hide_index=True, height=250)
        labels = [f"{r.status} · {r.name}" for r in all_specs.itertuples()]
        choice = st.selectbox("Open spec", labels, index=None, placeholder="Pick a spec to review")
        if choice:
            s = all_specs.iloc[labels.index(choice)]
            detail = get(f"/specs/{s['status']}/{s['name']}")
            left, right = st.columns(2)
            left.markdown("**Spec**")
            left.code(detail["yaml"], language="yaml")
            right.markdown("**Checks**")
            right.dataframe(pd.DataFrame(detail["checks"]), hide_index=True)
            st.markdown(f"**Sample rows** ({detail['rows']} total)")
            st.dataframe(pd.DataFrame(detail["sample"]), hide_index=True)
            sure = s["status"] != "approved" and st.checkbox("I checked the spec, the checks and the sample rows", key="s_sure")
            if s["status"] != "approved" and st.button("Approve spec", type="primary", disabled=not sure):
                post(f"/specs/{s['status']}/{s['name']}/approve", {})
                st.rerun()
            if st.button("Compare with old pipeline (DB)"):
                st.json(post(f"/specs/{s['status']}/{s['name']}/compare", {}))
            if st.button("Re-run spec and show all rows"):
                run = post(f"/specs/{s['status']}/{s['name']}/run", {})
                st.dataframe(pd.DataFrame(run["checks"]), hide_index=True)
                st.dataframe(pd.DataFrame(run["sample"]), hide_index=True)

with evals:
    results = get("/eval")
    if not results:
        st.info("Run scripts/eval_agent.py to produce eval results.")
    else:
        df = pd.DataFrame(results)
        passed = (df["final_status"] == "proposed").sum()
        st.metric("Specs passing all checks", f"{passed}/{len(df)}")
        st.dataframe(df[["sheet", "file", "attempts", "final_status", "final_failed", "db_diff", "rows", "seconds"]], hide_index=True)
        for r in results:
            with st.expander(f"{r['sheet']}: {r['final_status']}"):
                st.write(r["answer"])
                st.dataframe(pd.DataFrame(r["history"]), hide_index=True)
