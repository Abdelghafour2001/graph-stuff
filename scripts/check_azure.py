"""Check the Azure OpenAI settings in .env before running the stack: DNS, key, both deployments, tool calling.

  python scripts/check_azure.py

Run it where the API runs: on the host for local Python, or inside the container with
  podman compose run --rm api python /app/scripts/check_azure.py
since a container can fail to resolve a hostname the host resolves (corporate DNS, VPN).
"""
import json
import os
import socket
import sys
from urllib.parse import urlparse

import openai
from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    host = urlparse(endpoint).hostname
    if not host:
        print(f"AZURE_OPENAI_ENDPOINT is not a URL: {endpoint!r}. Expected https://<resource>.openai.azure.com/")
        return 1
    try:
        print(f"ok   DNS {host} -> {socket.gethostbyname(host)}")
    except OSError as e:
        print(f"FAIL DNS {host}: {e}. This machine or container cannot resolve the endpoint (check VPN, proxy, DNS).")
        return 1

    client = openai.AzureOpenAI(azure_endpoint=endpoint, api_key=os.environ.get("AZURE_OPENAI_API_KEY", ""),
                                api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"))
    failed = 0
    for var in ("AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_AGENT_DEPLOYMENT"):
        name = os.environ.get(var, "")
        try:
            r = client.chat.completions.create(model=name, messages=[{"role": "user", "content": "Reply with: ok"}])
            print(f"ok   {var}={name} (model {r.model}): {r.choices[0].message.content!r}")
        except openai.NotFoundError:
            print(f"FAIL {var}={name}: no deployment with this name on {host}. Use the deployment name shown in "
                  "Azure AI Foundry > Deployments for this resource.")
            failed += 1
        except openai.AuthenticationError:
            print(f"FAIL {var}: key rejected (401). AZURE_OPENAI_API_KEY must belong to {host}.")
            return 1
        except openai.APIError as e:
            print(f"FAIL {var}={name}: {getattr(e, 'status_code', '')} {getattr(e, 'message', e)}")
            failed += 1

    if not failed:  # the agent needs tool calling on its deployment
        tool = {"type": "function", "function": {"name": "lookup_term", "description": "Look up a business term",
                "parameters": {"type": "object", "properties": {"term": {"type": "string"}}, "required": ["term"]}}}
        name = os.environ["AZURE_OPENAI_AGENT_DEPLOYMENT"]
        try:
            msg = client.chat.completions.create(model=name, tools=[tool], messages=[
                {"role": "user", "content": "What does ACP mean? Use the tool."}]).choices[0].message
            calls = [(c.function.name, json.loads(c.function.arguments)) for c in msg.tool_calls or []]
            print(f"{'ok  ' if calls else 'FAIL'} tool calling on {name}: {calls or 'no tool call returned'}")
            failed += not calls
        except openai.APIError as e:
            print(f"FAIL tool calling on {name}: {getattr(e, 'message', e)}. If it mentions the API version, raise "
                  "AZURE_OPENAI_API_VERSION.")
            failed += 1
    print("all good" if not failed else f"{failed} problem(s): fix .env, then restart the api container")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
