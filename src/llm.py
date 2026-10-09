"""Single-shot JSON completion for extraction jobs (no tools). Azure OpenAI for now, matching LLM_PROVIDER."""
import json
import os

import openai
from dotenv import load_dotenv

load_dotenv()
assert os.environ["LLM_PROVIDER"] == "azure_openai", "extraction jobs only support LLM_PROVIDER=azure_openai for now"

client = openai.AzureOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
)


def json_completion(system: str, user: str, deployment: str) -> dict:
    """deployment: AZURE_OPENAI_DEPLOYMENT (cheap, bulk extraction) or AZURE_OPENAI_AGENT_DEPLOYMENT (strong, reasoning tasks)."""
    response = client.chat.completions.create(
        model=os.environ[deployment],
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)
