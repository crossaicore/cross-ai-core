"""
Anthropic Claude provider for cross-ai-core.

or direct Anthropic API:

# Claude 3 Family (Legacy)
claude-3-haiku-20240307
claude-3-sonnet-20240229
claude-3-opus-20240229

# Claude 3.5 Family
claude-3-5-haiku-20241022
claude-3-5-sonnet-v2-20241022

# Claude 3.7 Family
claude-3-7-sonnet-20250219       # First hybrid reasoning model; extended thinking mode

# Claude 4 Family (Current - 2025/2026)
claude-sonnet-4-5                # Latest Sonnet; fast, highly capable, best for most tasks
claude-opus-4-5                  # Most intelligent Claude 4 model; best for complex reasoning

# Differences Between Claude Model Families

Claude 4 Family (Current)

claude-opus-4-5:
  - Most intelligent model in the Claude 4 family
  - Best for advanced reasoning, research synthesis, and complex multi-step tasks
  - Highest capability, higher cost; ideal for wiki-style report generation
  - Supports extended thinking for deep analytical work

claude-sonnet-4-5:
  - Balanced intelligence and speed in the Claude 4 family
  - Best for high-throughput tasks, data processing, and content generation
  - Faster and more cost-effective than Opus 4

Claude 3.7 Family

claude-3-7-sonnet-20250219:
  - First hybrid reasoning model on the market
  - Extended thinking capabilities for complex problem-solving and nuanced analysis
  - Strong for strategic analysis and advanced coding tasks

Claude 3.5 Family

claude-3-5-sonnet-v2-20241022:
  - Most intelligent in the 3.5 family; balances top-tier performance with speed
claude-3-5-haiku-20241022:
  - Fastest and most cost-effective in the 3.5 family

Claude 3 Family (Legacy)

Opus:   Strong on highly complex tasks like math and coding; R&D and advanced analysis
Sonnet: Balances intelligence and speed for high-throughput tasks
Haiku:  Near-instant responsiveness; live support, translations, content moderation
"""

import json
import os

from .ai_base import BaseAIHandler
from .usage import UsageReport, _count, _details, _mapping, _report, _sum_counts

AI_MAKE = "anthropic"
AI_MODEL = "claude-opus-4-5"  # 02mar26



class AnthropicHandler(BaseAIHandler):

    @classmethod
    def get_payload(cls, prompt: str, system: str | None = None):
        return get_anthropic_payload(prompt, system=system)

    @classmethod
    def get_client(cls):
        return get_anthropic_client()

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
    def get_content(cls, gen_content):
        return get_content(gen_content)

    @classmethod
    def put_content(cls, report, gen_content):
        return put_content(report, gen_content)

    @classmethod
    def get_data_content(cls, select_data):
        return get_data_content(select_data)

    @classmethod
    def get_usage_report(cls, response: dict) -> UsageReport:
        return _messages_usage(cls.get_make(), response)


def _messages_usage(provider: str, response: dict) -> UsageReport:
    """Anthropic-compatible Messages: cache tokens are additional input."""
    response = _mapping(response)
    raw = response.get("usage")
    usage = _mapping(raw)
    issues = []
    inp = _count(usage, "input_tokens", issues)
    cache_read = _count(usage, "cache_read_input_tokens", issues)
    cache_write = _count(usage, "cache_creation_input_tokens", issues)
    inp = _sum_counts(inp,
        cache_read if "cache_read_input_tokens" in usage else 0,
        cache_write if "cache_creation_input_tokens" in usage else 0)
    return _report(
        provider, response.get("model"), raw, input_tokens=inp,
        output_tokens=_count(usage, "output_tokens", issues),
        total_tokens=_count(usage, "total_tokens", issues),
        cache_read_tokens=cache_read, cache_write_tokens=cache_write,
        reasoning_tokens=_count(_details(usage, "output_tokens_details", issues), "thinking_tokens", issues),
        derive_total=usage.get("total_tokens") is None, issues=issues,
    )


def get_anthropic_payload(prompt, system: str | None = None):
    gen_payload = {  # Store parameters into a dictionary for calling X and saving with the output
        "model": AI_MODEL,
        "max_tokens": BaseAIHandler.MAX_TOKENS,
        "thinking": {                  # Extended thinking: deep reasoning mode (Claude 4 / 3.7+)
            "type": "enabled",
            "budget_tokens": 10000,    # Tokens reserved for internal reasoning (must be < max_tokens)
        },
        "system": system or BaseAIHandler.DEFAULT_SYSTEM,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    }
    return gen_payload


def get_anthropic_client():
    from anthropic import Anthropic
    client = Anthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
    )
    return client




def get_content(gen_response):
    # Extended thinking returns multiple blocks; find the text block
    for block in gen_response["content"]:
        if block.get("type") == "text":
            return block["text"]
    return gen_response["content"][0]["text"]  # fallback


def put_content(report, gen_response):
    # Extended thinking returns multiple blocks; update the text block
    for block in gen_response["content"]:
        if block.get("type") == "text":
            block["text"] = report
            return gen_response
    gen_response["content"][0]["text"] = report  # fallback
    return gen_response


def get_data_content(select_data):
    # Extended thinking responses contain multiple blocks; find the text block
    for block in select_data["gen_response"]["content"]:
        if block.get("type") == "text":
            return block["text"]
    return select_data["gen_response"]["content"][0]["text"]  # fallback
