"""Orchestrator + specialists with a fake OpenAI-compatible model: routing, model per role, evidence reaching the Reflector,
parallel specialist calls, prompts that only name tools their role has. No Neo4j (the driver is lazy), no LLM."""
import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
for k, v in {"NEO4J_URI": "bolt://localhost:1", "NEO4J_USER": "x", "NEO4J_PASSWORD": "x", "EXCEL_DIR": "x",
             "MARKET_INTEL_DSN": "x", "AZURE_OPENAI_ENDPOINT": "https://x", "AZURE_OPENAI_API_KEY": "x",
             "AZURE_OPENAI_API_VERSION": "x", "AZURE_OPENAI_AGENT_DEPLOYMENT": "strong"}.items():
    os.environ.setdefault(k, v)
import agent  # noqa: E402
from anthropic import beta_tool  # noqa: E402

ROLES = {"orchestrator": (agent.SYSTEM, agent.TOOLS), "impact": (agent.IMPACT_SYSTEM, agent.IMPACT_TOOLS),
         "workbook": (agent.WORKBOOK_SYSTEM, agent.WORKBOOK_TOOLS), "news": (agent.NEWS_SYSTEM, agent.NEWS_TOOLS)}


def test_each_prompt_only_names_tools_its_role_has():
    every = {t.name for _, tools in ROLES.values() for t in tools}
    for role, (system, tools) in ROLES.items():
        named = {w for w in re.findall(r"\b[a-z_]+\b", system) if w in every}
        assert named <= {t.name for t in tools}, (role, sorted(named - {t.name for t in tools}))


def test_orchestrator_is_small_and_delegates():
    names = {t.name for t in agent.TOOLS}
    assert {"ask_impact_analyst", "ask_workbook_agent", "ask_news_agent"} <= names
    assert not names & {"ocp_exposure", "diagnose_variance", "propose_extraction_spec", "read_range"}
    assert len(agent.TOOLS) <= 10


class Call:
    def __init__(self, i, name, args):
        self.id, self.function = f"c{i}", type("F", (), {"name": name, "arguments": json.dumps(args)})()


class Msg:
    def __init__(self, content=None, calls=None):
        self.content, self.tool_calls = content, calls

    def model_dump(self, exclude_none=True):
        return {"role": "assistant", "content": self.content or "",
                **({"tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                                   for c in self.tool_calls]} if self.tool_calls else {})}


class FakeModel:
    """Plays each role from its system prompt: the orchestrator delegates, the impact analyst calls ocp_exposure."""
    def __init__(self):
        self.models = []
        self.chat = self.completions = self

    def create(self, model, messages, tools, **kw):
        self.models.append(model)
        system, done = messages[0]["content"], [m for m in messages if m["role"] == "tool"]
        if system.startswith("You are the impact analyst"):
            msg = Msg(calls=[Call(1, "ocp_exposure", {"scope": "", "date_from": "2026-01-01", "date_to": "2026-10-09"})]) if not done \
                else Msg("Sulphur headwind: 165.0 to 250.0 $/t (article 2796917).")
        else:
            msg = Msg(calls=[Call(1, "ask_impact_analyst", {"question": "What hit OCP in 2026?"})]) if not done \
                else Msg("The graph has no OCP results. Sulphur went from 165.0 to 250.0 $/t (article 2796917).")
        return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()


@beta_tool
def fake_exposure(scope: str, date_from: str, date_to: str) -> str:
    """Fake exposure.

    Args:
        scope: scope
        date_from: from
        date_to: to
    """
    return json.dumps({"headwind": [{"item": "sulfur", "price": {"from_avg": 165.0, "to_avg": 250.0},
                                     "events": [{"article_id": 2796917}]}]})


fake_exposure.name = "ocp_exposure"


def test_orchestrator_routes_to_the_impact_analyst_with_its_own_model(monkeypatch):
    fake = FakeModel()
    monkeypatch.setenv("LLM_PROVIDER", "azure_openai")
    monkeypatch.setenv("AZURE_OPENAI_IMPACT_DEPLOYMENT", "reasoning")
    monkeypatch.setattr(agent.openai, "AzureOpenAI", lambda **kw: fake)
    monkeypatch.setattr(agent, "IMPACT_TOOLS", [fake_exposure])
    answer, trace = agent.ask([], "OCP a beaucoup perdu cette année, pourquoi ?")
    assert [c["tool"] for c in trace] == ["ask_impact_analyst"]  # the Reflector passed: no "reflector" entry
    reply = json.loads(trace[0]["result"])
    assert reply["specialist"] == "impact" and reply["tool_calls"] == ["ocp_exposure"] and "250.0" in reply["evidence"][0]
    assert fake.models == ["strong", "reasoning", "reasoning", "strong"]  # orchestrator, analyst x2 turns, orchestrator
    assert "250.0" in answer


def test_invented_number_in_final_answer_is_caught(monkeypatch):
    fake = FakeModel()
    original = fake.create

    def lying(model, messages, tools, **kw):
        r = original(model, messages, tools, **kw)
        m = r.choices[0].message
        if m.content and messages[0]["content"].startswith("You are the finance-knowledge agent"):
            m.content = "OCP lost 1200.0 M$ (article 2796917)."  # not in any evidence
        return r
    fake.create = lying
    monkeypatch.setenv("LLM_PROVIDER", "azure_openai")
    monkeypatch.setattr(agent.openai, "AzureOpenAI", lambda **kw: fake)
    monkeypatch.setattr(agent, "IMPACT_TOOLS", [fake_exposure])
    answer, trace = agent.ask([], "OCP a beaucoup perdu cette année ?")
    assert "reflector" in [c["tool"] for c in trace] and "unresolved" in answer


def test_specialists_called_together_run_in_parallel():
    @beta_tool
    def slow(n: int) -> str:
        """Slow tool.

        Args:
            n: id
        """
        time.sleep(0.4)
        return f"done {n}"

    class TwoCalls(FakeModel):
        def create(self, model, messages, tools, **kw):
            done = [m for m in messages if m["role"] == "tool"]
            msg = Msg(calls=[Call(i, "slow", {"n": i}) for i in (1, 2, 3)]) if not done else Msg("ok")
            return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()

    trace = []
    start = time.monotonic()
    assert agent.tool_loop(TwoCalls(), "m", {}, "sys", [slow], [{"role": "user", "content": "q"}], trace) == "ok"
    assert time.monotonic() - start < 1.0  # 3 x 0.4 s in sequence would be 1.2 s
    assert [c["result"] for c in trace] == ["done 1", "done 2", "done 3"]  # order of the calls kept


@pytest.mark.parametrize("role", ["impact", "workbook", "news"])
def test_specialist_prompts_keep_the_number_rule(role):
    system, _ = ROLES[role]
    assert "invent" in system or "Never" in system or "never" in system
