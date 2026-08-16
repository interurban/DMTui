"""Small OpenAI client used by the optional in-game DM chat command."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request


CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "llm_config.json")


def load_config(path: str = CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as config_file:
        config = json.load(config_file)
    if not isinstance(config, dict):
        raise RuntimeError("LLM config must be a JSON object")
    local_path = os.path.splitext(path)[0] + ".local.json"
    if os.path.exists(local_path):
        with open(local_path, encoding="utf-8") as local_file:
            local_config = json.load(local_file)
        if not isinstance(local_config, dict):
            raise RuntimeError("Local LLM config must be a JSON object")
        config.update(local_config)
        if isinstance(config.get("options"), dict) and isinstance(local_config.get("options"), dict):
            config["options"] = {**config["options"], **local_config["options"]}
    return config


def chat(question: str, context: str, *, config: dict | None = None) -> str:
    """Ask OpenAI for a concise answer using the current encounter context."""
    config = config or load_config()
    api_key = str(config.get("api_key") or os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    model = str(config.get("model") or "gpt-4o-mini")
    url = str(config.get("url") or "https://api.openai.com/v1/chat/completions")
    options = config.get("options") or {}
    payload = {
        "model": model,
        "temperature": float(options.get("temperature", 0)),
        "max_tokens": int(options.get("max_tokens", 80)),
        "messages": [
            {"role": "system", "content": str(config.get("system_prompt") or "Answer briefly.")},
            {"role": "user", "content": f"Encounter context:\n{context}\n\nQuestion: {question}"},
        ],
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(config.get("timeout_seconds", 60))) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8"))
            message = detail.get("error", {}).get("message", str(exc))
        except Exception:
            message = str(exc)
        raise RuntimeError(f"OpenAI returned HTTP {exc.code}: {message}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("OpenAI is not reachable") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("OpenAI returned invalid JSON") from exc

    choices = result.get("choices") if isinstance(result, dict) else None
    message = choices[0].get("message") if choices else None
    answer = message.get("content") if isinstance(message, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("OpenAI returned an empty answer")
    answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL | re.IGNORECASE)
    answer = " ".join(answer.split()).strip()
    return answer
