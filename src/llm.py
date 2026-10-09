"""Single-shot JSON completion for extraction jobs (no tools), on the provider named by LLM_PROVIDER.

azure_openai: deployment = AZURE_OPENAI_DEPLOYMENT (cheap, bulk) or AZURE_OPENAI_AGENT_DEPLOYMENT (strong).
bifrost: the same two names map to BIFROST_FAST_MODEL (thinking off) and BIFROST_CHAT_MODEL (thinking on).
"""
import json
import os

import openai
from dotenv import load_dotenv

import gateway

load_dotenv()
PROVIDER = os.environ["LLM_PROVIDER"]
assert PROVIDER in ("azure_openai", "bifrost"), "extraction jobs support LLM_PROVIDER=azure_openai or bifrost"

if PROVIDER == "azure_openai":
    client = openai.AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    )
else:
    client = gateway.client()


def json_completion(system: str, user: str, deployment: str) -> dict:
    """deployment: AZURE_OPENAI_DEPLOYMENT (cheap, bulk extraction) or AZURE_OPENAI_AGENT_DEPLOYMENT (strong, reasoning tasks)."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if PROVIDER == "azure_openai":
        response = client.chat.completions.create(model=os.environ[deployment], messages=messages, response_format={"type": "json_object"})
    else:
        role = "chat" if deployment == "AZURE_OPENAI_AGENT_DEPLOYMENT" else "fast"
        response = client.chat.completions.create(model=gateway.model(role), messages=messages, response_format={"type": "json_object"},
                                                  extra_body=gateway.extra_body(role))
    return json.loads(gateway.strip_thinking(response.choices[0].message.content))
