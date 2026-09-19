---
name: builtin-llm-models
description: Wire an LLM API into an application the sandbox builds. Use when the user asks for AI features in a deliverable (chat, summarization, classification, generation) or asks which model and calling pattern to use.
---

# Built-in LLM Models

## When to Use

- A built web app or script needs AI features (chatbot, summarizer, extractor)
- The user asks how to connect an app to a model provider
- The user asks which model endpoint to use and how to keep the key safe

## Calling Pattern (OpenAI-compatible)

Most modern gateways — including NVIDIA NIM (`https://integrate.api.nvidia.com/v1`),
OpenAI, OpenRouter, and self-hosted vLLM — speak the same OpenAI-compatible
protocol. One client shape covers all of them:

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["LLM_API_KEY"],          # NEVER hardcode
    base_url=os.environ.get("LLM_API_BASE", "https://integrate.api.nvidia.com/v1"),
)
resp = client.chat.completions.create(
    model=os.environ.get("LLM_MODEL", "nvidia/nemotron-3-super-120b-a12b"),
    messages=[{"role": "user", "content": prompt}],
)
print(resp.choices[0].message.content)
```

## Rules That Prevent Rework

- **Key hygiene**: read keys from environment variables or a `.env` the user
  fills in; ship a `.env.example`. A committed key is a leaked key.
- **Base URL is config, not code**: switching providers must be a `.env` edit.
- **Streaming**: for chat UIs prefer `stream=True` (SSE) — perceived latency
  drops dramatically even when total time is identical.
- **Failure handling**: wrap calls with one retry on transient errors
  (timeouts, 429, 5xx) and a readable user-facing error after that.
- **Token budget**: set sensible `max_tokens` and trim history server-side;
  never ship an unbounded conversation loop.

## What This Sandbox Cannot Do

- No model runs inside the sandbox — calls go to the provider over the network.
- Do not invent provider-specific features (function calling, tool use) without
  testing them in the delivered app's flow; verify with one real call when a
  key is available, otherwise mark it clearly as untested in the README.
