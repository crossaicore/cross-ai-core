"""
OpenAI GPT Model Family (via OpenAI API at https://api.openai.com)

# GPT-4.5 Family
gpt-4.5-preview                  # Most capable GPT model; requires special API tier access

# GPT-4o Family (Current Default)
gpt-4o                           # Flagship multimodal model; text, image, audio; best speed/quality balance
gpt-4o-mini                      # Fast, cost-efficient; good for high-volume tasks
gpt-4o-audio-preview             # GPT-4o with native audio input/output support

# o-Series Reasoning Models
o3                               # Most powerful reasoning model; best for complex multi-step problems
o3-mini                          # Faster, cost-efficient reasoning; strong at math and coding
o4-mini                          # Latest compact reasoning model; fast and cost-efficient
o1                               # Original deep reasoning model; thorough but slower
o1-mini                          # Lightweight o1; cost-efficient reasoning

# Differences Between OpenAI Model Families

GPT-4.5 Family

gpt-4.5-preview:
  - Most capable GPT model; best for nuanced instruction following and long-form writing
  - Requires special API tier access — not available on standard accounts
  - Higher cost; upgrade path when API access is available

GPT-4o Family (Current Default)

gpt-4o:
  - Flagship multimodal model; handles text, images, and audio natively
  - Best balance of speed, capability, and cost for most tasks
  - Strong for summarization, Q&A, content generation, and data analysis
  - Recommended default for wiki-style report generation
gpt-4o-mini:
  - Lightweight, fast, and cost-efficient variant of GPT-4o
  - Best for high-throughput or latency-sensitive tasks

o-Series Reasoning Models

o3 / o4-mini:
  - Purpose-built for deep, multi-step reasoning tasks
  - Best for math, coding, logic puzzles, and scientific analysis
  - o3: maximum capability; o4-mini: fast and cost-efficient
  - Note: reasoning models do not support system messages or temperature

# API Notes
OpenAI uses the native OpenAI SDK (not an Anthropic-compatible wrapper).
The openai.OpenAI client is used directly.
Authentication uses the OPENAI_API_KEY environment variable (openai_api_key in .env).
Note: o-series reasoning models do not support system role or temperature parameters.
"""

import json
import os

from .ai_base import BaseAIHandler

AI_MAKE = "openai"
AI_MODEL = "gpt-4o"  # 02mar26



class OpenAIHandler(BaseAIHandler):

    @classmethod
    def get_payload(cls, prompt: str, system: str | None = None):
        return get_openai_payload(prompt, system=system)

    @classmethod
    def get_client(cls):
        return get_openai_client()

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
    def get_data_content(cls,  select_data):
        return get_data_content(select_data)

    @classmethod
    def get_usage(cls, response: dict) -> dict:
        """Extract token counts from an OpenAI-format response dict."""
        usage = response.get("usage", {})
        inp = usage.get("prompt_tokens", 0)
        out = usage.get("completion_tokens", 0)
        tot = usage.get("total_tokens") or (inp + out)
        return {"input_tokens": inp, "output_tokens": out, "total_tokens": tot}



def get_openai_payload(prompt_from_file, system: str | None = None):
    payload = {
        "model": AI_MODEL,
        "messages": [
            {
                "role": "system",           # System instruction — consistent with other AI handlers
                "content": system if system is not None else BaseAIHandler.DEFAULT_SYSTEM,
            },
            {
                "role": "user",
                "content": prompt_from_file,
            }
        ],
        "max_completion_tokens": BaseAIHandler.MAX_TOKENS,
        # Use model sampling defaults: reasoning models can reject custom
        # temperature and top_p values. The dispatcher selects the model later.
    }
    return payload


def get_openai_client():
    import openai
    # OpenAI native SDK — not a compatibility wrapper
    client = openai.OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))
    return client




def get_content(gen_response):
    text = gen_response["choices"][0]["message"]["content"]
    return text


def put_content(report, gen_response):
    gen_response["choices"][0]["message"]["content"] = report
    return gen_response


def get_data_content(select_data):
    content = select_data["gen_response"]["choices"][0]["message"]["content"]
    return content
