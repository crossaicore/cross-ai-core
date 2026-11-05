"""
Perplexity Sonar Model Family (via OpenAI-compatible API at https://api.perplexity.ai)

# Sonar Family (Current - 2025/2026)
sonar-pro                        # Most capable Sonar model; deep research, cited web search
sonar                            # Balanced speed and capability; general-purpose web search
sonar-reasoning-pro              # Advanced reasoning with chain-of-thought + web search
sonar-reasoning                  # Faster reasoning variant; good for structured analysis

# Sonar Deep Research
sonar-deep-research              # Autonomous multi-step research; produces exhaustive reports
                                 # Best for wiki-style, long-form report generation

# Legacy Models
r1-1776                          # Offline DeepSeek R1-based model; no web search, no citations
                                 # Best for sensitive topics requiring no data collection

# Differences Between Perplexity Model Families

Sonar Pro Family (Current)

sonar-pro:
  - Most capable online model; best for complex, citation-backed research reports
  - Performs multiple search queries per request for comprehensive coverage
  - Ideal for wiki-style report generation with cited sources
  - Higher cost; worth it for accuracy and depth

sonar:
  - Fast, cost-efficient general-purpose model
  - Single search pass; best for straightforward Q&A and summaries
  - Default choice for high-volume tasks

sonar-reasoning-pro:
  - Combines chain-of-thought reasoning with live web search
  - Best for analytical tasks requiring step-by-step logic and current data
  - Extended thinking visible in response

sonar-reasoning:
  - Faster reasoning variant; lower cost than sonar-reasoning-pro
  - Good for structured analysis without deep web crawling

sonar-deep-research:
  - Performs autonomous, multi-step research across many sources
  - Produces the most exhaustive, citation-dense reports
  - Highest latency and cost; best reserved for comprehensive wiki reports

# API Notes
Perplexity uses an OpenAI-compatible API (https://api.perplexity.ai).
The OpenAI SDK is used directly with a custom base_url — no separate SDK required.
All Sonar models include live web search with citations in the response.
Authentication uses the PERPLEXITY_API_KEY environment variable.
"""

import json
import os

from .ai_base import BaseAIHandler
from .ai_openai import _chat_usage
from .usage import UsageReport

AI_MAKE = "perplexity"
AI_MODEL = "sonar-pro"  # 02mar26



class PerplexityHandler(BaseAIHandler):

    @classmethod
    def get_payload(cls, prompt: str, system: str | None = None):
        return get_perplexity_payload(prompt, system=system)

    @classmethod
    def get_client(cls):
        return get_perplexity_client()

    @classmethod
    def _call_api(cls, client, payload: dict) -> dict:
        response = client.chat.completions.create(**payload)
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
    def get_data_content(cls, select_data):
        return get_data_content(select_data)

    @classmethod
    def get_usage_report(cls, response: dict) -> UsageReport:
        return _chat_usage(cls.get_make(), response)



def get_perplexity_payload(prompt_from_file, system: str | None = None):
    payload = {
        "model": AI_MODEL,
        "messages": [
            {
                "role": "system",           # System instruction now explicit — consistent with other AI handlers
                "content": system if system is not None else BaseAIHandler.DEFAULT_SYSTEM,
            },
            {
                "role": "user",
                "content": prompt_from_file,
            }
        ],
        "max_tokens": BaseAIHandler.MAX_TOKENS,
        "temperature": 0.7,         # 0.0 = deterministic, 1.0 = creative; 0.7 balances both
        "top_p": 0.95,              # Nucleus sampling; limits token selection to top 95% probability mass
    }
    return payload


def get_perplexity_client():
    from openai import OpenAI
    # Perplexity uses an OpenAI-compatible API; the OpenAI SDK is used with a custom base_url
    client = OpenAI(
        api_key=os.environ.get('PERPLEXITY_API_KEY'),
        base_url="https://api.perplexity.ai",
    )
    return client




def get_content(gen_response):
    content = gen_response["choices"][0]["message"]["content"]
    return content


def put_content(report, gen_response):
    gen_response["choices"][0]["message"]["content"] = report
    return gen_response


def get_data_content(select_data):
    content = select_data["gen_response"]["choices"][0]["message"]["content"]
    return content
