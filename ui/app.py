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

chat, news, entities, workbooks, specs, evals = st.tabs(["Ask the agent", "News & prices", "Entities", "Workbooks", "Spec review", "Eval"])

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
        with st.spinner("Agent working (tool calls can take a minute)..."):
            res = post("/ask", {"question": question, "history": st.session_state.history})
        st.session_state.history = res["history"]
        st.session_state.turns.append({"question": question, "answer": res["answer"], "trace": res["trace"]})
        st.rerun()

with news:
    word = st.text_input("Product", "DAP")
    found = get("/concepts", q=word)
    if found:
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
        concept_ids = [product] + [get("/concepts", q=w)[0]["id"] for w in extra if get("/concepts", q=w)]
        events = pd.DataFrame(get("/news/events", concept=concept_ids))
        st.markdown(f"**Events** affecting {', '.join(concept_ids)} ({len(events)})")
        st.dataframe(events, hide_index=True, height=400)

with entities:
    table = pd.DataFrame(get("/entities/assets"))
    st.markdown(f"**{len(table)} canonical assets** resolved from {int(table['records'].sum())} source records (proposed by the entity agent; approve after review)")
    st.dataframe(table.drop(columns=["source_names"]), hide_index=True, height=350)
    labels = [f"{r.asset} ({r.records} records, {r.confidence}, {r.status})" for r in table.itertuples()]
    choice = st.selectbox("Review asset", labels, index=None, placeholder="Pick an asset to see its source records")
    if choice:
        row = table.iloc[labels.index(choice)]
        st.write(row["reason"])
        st.code("\n".join(row["source_names"]))
        if row["status"] != "approved" and st.button("Approve merge (human decision)"):
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
            st.dataframe(pd.DataFrame(info["mentions"]).sort_values("n", ascending=False), hide_index=True, height=250)
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
            if s["status"] != "approved" and st.button("Approve (human decision)"):
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
            with st.expander(f"{r['sheet']} — {r['final_status']}"):
                st.write(r["answer"])
                st.dataframe(pd.DataFrame(r["history"]), hide_index=True)
