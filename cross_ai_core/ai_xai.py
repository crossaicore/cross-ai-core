"""
xAI Grok Model Family (via Anthropic-compatible API at https://api.x.ai)

grok-4-1-fast-reasoning  # Fast, reasoning-optimized Grok 4 variant; best for interactive tasks

# Grok 4 Family (Current - 2025/2026)
grok-4-latest                    # Most capable Grok model; advanced reasoning, deep analysis
grok-4-0709                      # Dated snapshot of Grok 4 (09 Jul 2025)

# Grok 3 Family
grok-3-latest                    # Balanced capability and speed; strong for long-form content
grok-3-fast-latest               # Faster Grok 3 variant; optimized for throughput
grok-3-mini-latest               # Lightweight Grok 3; cost-efficient, high-volume tasks
grok-3-mini-fast-latest          # Fastest, most cost-efficient Grok 3 variant

# Grok 2 Family (Legacy)
grok-2-latest                    # Previous generation; general-purpose tasks
grok-2-vision-latest             # Grok 2 with vision/multimodal support

# Grok Beta (Legacy)
grok-beta                        # Original public Grok model; superseded by Grok 2+

# Differences Between Grok Model Families

Grok 4 Family (Current)

grok-4-latest:
  - Most intelligent Grok model; best for complex reasoning and research synthesis
  - Designed to compete with frontier models on coding, math, and analysis
  - Highest capability and cost; ideal for wiki-style report generation
  - Uses xAI's Anthropic-compatible API; drop-in with existing Anthropic SDK usage

Grok 3 Family

grok-3-latest:
  - Strong general-purpose model; best balance of quality and speed in Grok 3
  - Excellent for long-form content, summarization, and structured reports
grok-3-fast-latest:
  - Optimized for lower latency; good for interactive or real-time tasks
grok-3-mini-latest / grok-3-mini-fast-latest:
  - Cost-efficient variants for high-volume or simpler tasks

Grok 2 Family (Legacy)

grok-2-latest:       General-purpose; superseded by Grok 3+
grok-2-vision-latest: Adds image/vision understanding to Grok 2

# API Notes
xAI uses an Anthropic-compatible API endpoint (https://api.x.ai).
The Anthropic SDK is used directly with a custom base_url — no separate SDK required.
Authentication uses the XAI_API_KEY environment variable (xai_api_key in .env).
"""

import json
import os

from .ai_base import BaseAIHandler
from .ai_anthropic import _messages_usage
from .usage import UsageReport

AI_MAKE = "xai"
AI_MODEL = "grok-4-1-fast-reasoning"



class XAIHandler(BaseAIHandler):

    @classmethod
    def get_payload(cls, prompt: str, system: str | None = None):
        return get_xai_payload(prompt, system=system)

    @classmethod
    def get_client(cls):
        return get_xai_client()

    @classmethod
    def _call_api(cls, client, payload: dict) -> dict:
        response = client.messages.create(**payload)
        return json.loads(response.to_json())

    @classmethod
    def get_model(cls):
        return AI_MODEL

    @classmethod
    def get_make(cls):
        return AI_MAKE

    @classmethod
    def get_content(cls,  gen_content):
        return get_content(gen_content)

    @classmethod
    def put_content(cls, report, gen_content):
        return put_content(report, gen_content)

    @classmethod
    def get_data_content(cls,  select_data):
        return get_data_content(select_data)

    @classmethod
    def get_usage_report(cls, response: dict) -> UsageReport:
        # This handler uses /v1/messages, not xAI's Chat/Responses endpoints.
        return _messages_usage(cls.get_make(), response)



def get_xai_payload(prompt, system: str | None = None):
    gen_payload = {  # Store parameters into a dictionary for calling xAI and saving with the output
        "model": AI_MODEL,
        "max_tokens": BaseAIHandler.MAX_TOKENS,
        "system": system if system is not None else BaseAIHandler.DEFAULT_SYSTEM,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    }
    return gen_payload


def get_xai_client():
    from anthropic import Anthropic
    # xAI uses an Anthropic-compatible API; the Anthropic SDK is used with a custom base_url
    client = Anthropic(
        api_key=os.getenv("XAI_API_KEY"),
        base_url="https://api.x.ai",
    )
    return client




def get_content(gen_response):
    # Scan content blocks by key in case future Grok models return multiple blocks
    for block in gen_response["content"]:
        if block.get("type") == "text":
            return block["text"]
    return gen_response["content"][0]["text"]  # fallback


def put_content(report, gen_response):
    # Scan content blocks by key; update the text block
    for block in gen_response["content"]:
        if block.get("type") == "text":
            block["text"] = report
            return gen_response
    gen_response["content"][0]["text"] = report  # fallback
    return gen_response


def get_data_content(select_data):
    # Scan content blocks by key; robust against multi-block responses
    for block in select_data["gen_response"]["content"]:
        if "text" in block:
            return block["text"]
    raise ValueError("No element with 'text' key found in content array")
