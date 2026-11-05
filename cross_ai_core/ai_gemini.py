"""
Google Gemini Model Families (via google-genai SDK, v1beta)
Confirmed available models from list_gemini_models.py (02mar26):

# Gemini 2.5 Family (Current Default — all use short IDs on v1beta)
gemini-2.5-flash                 # Best price/performance; 1M context — CURRENT DEFAULT
gemini-2.5-pro                   # Most capable; deep reasoning, long context
gemini-2.5-flash-lite            # Fastest, most cost-efficient 2.5 variant
gemini-2.5-flash-image           # Flash with image generation support
gemini-2.5-flash-preview-tts     # Text-to-speech preview
gemini-2.5-pro-preview-tts       # Pro text-to-speech preview
gemini-2.5-flash-lite-preview-09-2025  # Dated preview snapshot

# Gemini 2.0 Family (GA)
gemini-2.0-flash                 # Balanced speed and capability; multimodal
gemini-2.0-flash-001             # Pinned snapshot of gemini-2.0-flash
gemini-2.0-flash-lite            # Cost-efficient GA variant
gemini-2.0-flash-lite-001        # Pinned snapshot of gemini-2.0-flash-lite
gemini-2.0-flash-exp-image-generation  # Experimental image generation

# Gemini 3 Family (Very early preview)
gemini-3-pro-preview             # Early preview of Gemini 3 Pro
gemini-3-flash-preview           # Early preview of Gemini 3 Flash
gemini-3.1-pro-preview           # Gemini 3.1 Pro preview
gemini-3.1-flash-image-preview   # 3.1 Flash with image generation

# Convenience Aliases
gemini-flash-latest              # Always latest Flash model
gemini-flash-lite-latest         # Always latest Flash Lite model
gemini-pro-latest                # Always latest Pro model

# Gemma (Open Weights Models)
gemma-3-1b-it / gemma-3-4b-it / gemma-3-12b-it / gemma-3-27b-it
gemma-3n-e4b-it / gemma-3n-e2b-it

# Gemini 1.5 (Legacy — NOT available on this account's v1beta endpoint)

# Differences Between Gemini Model Families

Gemini 2.5 Family (Current)

gemini-2.5-flash:
  - Best balance of speed, cost, and intelligence; recommended for report generation
  - Supports thinking mode (adaptive reasoning budget) for deeper analysis
  - 1M token context window; strong multimodal capabilities
  - Short model ID works on v1beta — no versioned suffix needed

gemini-2.5-pro:
  - Most intelligent model; best for complex reasoning and research
  - Long context window (1M tokens); ideal for wiki-style long-form reports
  - Higher cost; reserve for the most demanding tasks

gemini-2.5-flash-lite:
  - Fastest and most cost-efficient; best for high-volume tasks

Gemini 2.0 Family (GA Fallback)

gemini-2.0-flash:
  - Fully GA; reliable quota on all paid accounts
  - Strong multimodal and agentic capabilities
  - Use as fallback if 2.5 quota is exhausted

Gemini 3 (Very Early Preview)
  - Experimental; expect breaking changes, instability, and limited availability

# API Versions
v1alpha: Early access; unstable
v1beta:  Required for systemInstruction and GenerateContentConfig — use this
v1:      GA endpoint; does NOT support systemInstruction field
"""

import os

from .ai_base import BaseAIHandler
from .usage import UsageReport, _count, _mapping, _report, _sum_counts

AI_MAKE = "gemini"
AI_MODEL = "gemini-2.5-flash"   # 02mar26 — confirmed available via list_gemini_models.py



class GeminiHandler(BaseAIHandler):

    @classmethod
    def get_payload(cls, prompt: str, system: str | None = None):
        return get_gemini_payload(prompt, system=system)

    @classmethod
    def get_client(cls):
        return get_gemini_client()

    @classmethod
    def _call_api(cls, client, payload: dict) -> dict:
        system_instruction = payload.get("system_instruction", BaseAIHandler.DEFAULT_SYSTEM)
        response = client.models.generate_content(
            model=payload["model"],
            contents=payload["contents"],
            config=get_gemini_config(system_instruction),
        )
        return get_json_response(response)

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
    def put_content(cls, report, gen_content):  # Used by st-fix
        return put_content(report, gen_content)

    @classmethod
    def get_data_content(cls, select_data):
        return get_data_content(select_data)

    @classmethod
    def get_usage_report(cls, response: dict) -> UsageReport:
        response = _mapping(response)
        names = {
            "prompt_token_count": "promptTokenCount",
            "candidates_token_count": "candidatesTokenCount",
            "total_token_count": "totalTokenCount",
            "thoughts_token_count": "thoughtsTokenCount",
            "tool_use_prompt_token_count": "toolUsePromptTokenCount",
            "cached_content_token_count": "cachedContentTokenCount",
        }
        legacy = "usageMetadata" not in response and "usage_metadata" not in response
        if "usageMetadata" in response:
            raw = response["usageMetadata"]
            data = _mapping(raw)
            usage = {snake: data[camel] for snake, camel in names.items() if camel in data}
        elif "usage_metadata" in response:
            raw = response["usage_metadata"]
            usage = _mapping(raw)
        else:
            raw = {key: response[key] for key in names if key in response} or None
            usage = _mapping(raw)
        issues = []
        inp = _count(usage, "prompt_token_count", issues)
        out = _count(usage, "candidates_token_count", issues)
        thoughts = _count(usage, "thoughts_token_count", issues)
        tools = _count(usage, "tool_use_prompt_token_count", issues)
        inp = _sum_counts(inp, tools if "tool_use_prompt_token_count" in usage else 0)
        out = _sum_counts(out, thoughts if "thoughts_token_count" in usage else 0)
        total = _count(usage, "total_token_count", issues)
        if (legacy and inp is not None and out is not None and total is not None
                and total > inp + out and "thoughts_token_count" not in usage
                and "tool_use_prompt_token_count" not in usage):
            # Old cache conversion discarded details. The gap is not proof of
            # thinking usage: retain the total and acknowledge missing output.
            out = None
            issues.append("legacy_usage_incomplete")
        return _report(
            cls.get_make(), response.get("modelVersion", response.get("model_version")), raw,
            input_tokens=inp, output_tokens=out, total_tokens=total,
            cache_read_tokens=_count(usage, "cached_content_token_count", issues),
            reasoning_tokens=thoughts,
            derive_total=usage.get("total_token_count") is None, issues=issues,
        )



def get_json_response(response):
    # Preserve SDK details for accounting while keeping the original cache shape
    # readable by existing consumers. Missing metadata must not lose valid text.
    metadata = response.usage_metadata
    dump = getattr(metadata, "model_dump", None)
    usage = dump(mode="json", exclude_none=True) if callable(dump) else metadata
    fields = ("candidates_token_count", "prompt_token_count", "total_token_count")
    return {
        "model_version": response.model_version,
        "text": response.text,
        "usage_metadata": usage,
        **{name: _mapping(usage).get(name) for name in fields},
    }



def get_gemini_config(system_instruction: str | None = None):
    """Return the GenerateContentConfig separately — not stored in the JSON payload."""
    from google.genai import types
    return types.GenerateContentConfig(
        system_instruction=system_instruction if system_instruction is not None else BaseAIHandler.DEFAULT_SYSTEM,
        max_output_tokens=BaseAIHandler.MAX_TOKENS,
        temperature=0.7,        # 0.0 = deterministic, 1.0 = creative; 0.7 balances both
        top_p=0.95,             # Nucleus sampling; limits token selection to top 95% probability mass
    )


def get_gemini_payload(prompt_from_file, system: str | None = None):
    # Gemini payload contains only JSON-serializable fields for storage and hashing.
    # system_instruction is stored here so it becomes part of the cache key;
    # get_gemini_config() reads it back at call time.
    payload = {
        "model": AI_MODEL,
        "contents": prompt_from_file,
        "system_instruction": system if system is not None else BaseAIHandler.DEFAULT_SYSTEM,
    }
    return payload


def get_gemini_client():
    from google import genai
    from google.genai import types
    client = genai.Client(
        api_key=os.environ.get("GEMINI_API_KEY"),
        http_options=types.HttpOptions(api_version='v1beta')  # v1beta required: v1 does not support systemInstruction
    )
    return client




def get_content(gen_response):
    text = gen_response["text"]
    return text


def put_content(report, gen_response):
    gen_response["text"] = report
    return gen_response


def get_data_content(select_data):
    content = select_data["gen_response"]["text"]
    return content
