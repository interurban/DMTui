"""Small OpenAI client used by the optional in-game DM chat command."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request


CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "llm_config.json")


def _load_dotenv(path: str) -> None:
    """Load simple KEY=VALUE settings without overriding the shell."""
    try:
        with open(path, encoding="utf-8") as env_file:
            lines = env_file.readlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def load_config(path: str = CONFIG_PATH) -> dict:
    _load_dotenv(os.path.join(os.path.dirname(path), ".env"))
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
    answer = answer.replace("\r\n", "\n").replace("\r", "\n")
    answer = "\n".join(" ".join(line.split()).strip() for line in answer.split("\n"))
    answer = re.sub(r"\n{3,}", "\n\n", answer).strip()
    return answer


def plan_encounter(
    description: str,
    available_names: list[str],
    party_context: str = "",
    *,
    config: dict | None = None,
) -> dict:
    """Turn a DM's encounter description into a safe, catalog-only plan.

    The model chooses names and counts, but never supplies creature stats.
    Statblocks are resolved by the caller from its built-in/SRD catalog.
    """
    config = config or load_config()
    api_key = str(config.get("api_key") or os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    model = str(config.get("model") or "gpt-4o-mini")
    url = str(config.get("url") or "https://api.openai.com/v1/chat/completions")
    options = config.get("options") or {}
    catalog = ", ".join(available_names)
    payload = {
        "model": model,
        "temperature": float(options.get("temperature", 0.2)),
        "max_tokens": int(options.get("encounter_max_tokens", 300)),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "encounter_plan",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "title": {"type": "string"},
                        "theme": {"type": "string"},
                        "difficulty": {"type": "string", "enum": ["Easy", "Medium", "Hard", "Deadly", "Unknown"]},
                        "monsters": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 8,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "name": {"type": "string"},
                                    "count": {"type": "integer", "minimum": 1, "maximum": 12},
                                },
                                "required": ["name", "count"],
                            },
                        },
                    },
                    "required": ["title", "theme", "difficulty", "monsters"],
                },
            },
        },
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a fast D&D encounter setup assistant. Return only the structured plan. "
                    "Choose only exact names from the supplied catalog. Prefer existing SRD statblocks; "
                    "never invent a monster name, statblock, or ability. Use the party context to estimate "
                    "difficulty when provided. For published adventures, mark difficulty Unknown unless "
                    "the description gives enough context. Keep the plan practical for a table-side DM."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Available monster catalog:\n{catalog}\n\n"
                    f"Party context:\n{party_context or 'not provided'}\n\n"
                    f"Encounter request:\n{description}"
                ),
            },
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
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("OpenAI returned an empty encounter plan")
    try:
        plan = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenAI returned invalid encounter JSON") from exc
    if not isinstance(plan, dict) or not isinstance(plan.get("monsters"), list) or not plan["monsters"]:
        raise RuntimeError("OpenAI returned an empty encounter plan")
    return plan
