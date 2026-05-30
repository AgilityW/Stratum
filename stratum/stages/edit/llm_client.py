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
    max_tokens = int(llm_cfg.get("max_tokens", MAX_TOKENS))
    temperature = float(llm_cfg.get("temperature", 0.3))
    timeout = int(llm_cfg.get("timeout_seconds", REQUEST_TIMEOUT))

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    })

    result = subprocess.run(
        ["curl", "-sS", "-w", "\nHTTP_STATUS:%{http_code}\n", "-X", "POST", endpoint,
         "-H", f"Authorization: Bearer {api_key}",
         "-H", "Content-Type: application/json",
         "--max-time", str(timeout),
         "--data-binary", "@-"],
        input=payload, capture_output=True, text=True, timeout=timeout + 5,
    )

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr or stdout[-500:] or "no curl diagnostics"
        raise RuntimeError(f"curl exited {result.returncode}: {detail}")

    body, http_status = _split_curl_http_status(result.stdout)
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        preview = (body or "").strip()[:500]
        raise RuntimeError(
            f"LLM response JSON parse error (http={http_status or 'unknown'}): {preview}"
        ) from exc
    if http_status and not http_status.startswith("2"):
        raise RuntimeError(
            f"LLM HTTP {http_status}: {json.dumps(data, ensure_ascii=False)[:500]}"
        )
    if "error" in data:
        raise RuntimeError(f"LLM API error: {data['error']}")

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(
            f"LLM response parse error: {json.dumps(data, indent=2)[:500]}"
        ) from e
    if not content:
        choice = data.get("choices", [{}])[0]
        raise RuntimeError(
            "LLM returned empty content: "
            f"finish_reason={choice.get('finish_reason')}, "
            f"usage={data.get('usage')}"
        )
    return content


def _split_curl_http_status(stdout: str) -> tuple[str, str]:
    """Split curl body from the trailing HTTP_STATUS line."""
    marker = "\nHTTP_STATUS:"
    if marker not in stdout:
        return stdout, ""
    body, status = stdout.rsplit(marker, 1)
    return body, status.strip()
