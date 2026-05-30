"""llm_client.py — Pure-function LLM API caller.

Supports OpenAI-compatible endpoints (DeepSeek, OpenRouter, etc.).
Returns raw LLM response text. No side effects.

Usage:
    from llm_client import call_llm
    response = call_llm(system_prompt, user_prompt, llm_config)
"""

from __future__ import annotations

import json
import subprocess
import sys

DEFAULT_MODEL = "deepseek/deepseek-v4-pro"
MAX_TOKENS = 16000
REQUEST_TIMEOUT = 180


def call_llm(
    system_prompt: str,
    user_prompt: str,
    llm_cfg: dict,
) -> str:
    """Call LLM API with system + user prompts. Returns response text.

    Args:
        system_prompt: System-level instructions
        user_prompt: User-level data + instructions
        llm_cfg: LLM config dict with keys: api_key, model, endpoint

    Returns:
        Raw response text from LLM

    Raises:
        RuntimeError: On API call failure or parse error
    """
    api_key = llm_cfg.get("api_key", "")
    model = llm_cfg.get("model", DEFAULT_MODEL)
    endpoint = llm_cfg.get("endpoint", "https://api.deepseek.com/v1/chat/completions")

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.3,
    })

    result = subprocess.run(
        ["curl", "-s", "-X", "POST", endpoint,
         "-H", f"Authorization: Bearer {api_key}",
         "-H", "Content-Type: application/json",
         "--data-binary", "@-"],
        input=payload, capture_output=True, text=True, timeout=REQUEST_TIMEOUT,
    )

    if result.returncode != 0:
        raise RuntimeError(f"LLM call failed: {result.stderr}")

    data = json.loads(result.stdout)
    if "error" in data:
        raise RuntimeError(f"LLM API error: {data['error']}")

    try:
        content = data["choices"][0]["message"]["content"]
        return content
    except (KeyError, IndexError) as e:
        raise RuntimeError(
            f"LLM response parse error: {json.dumps(data, indent=2)[:500]}"
        ) from e
