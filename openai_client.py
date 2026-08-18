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
        base_options = config.get("options")
        config.update(local_config)
        if isinstance(base_options, dict) and isinstance(local_config.get("options"), dict):
            config["options"] = {**base_options, **local_config["options"]}
    return config


def _client_settings(config: dict | None) -> tuple[dict, str, str, dict]:
    config = config or load_config()
    api_key = str(config.get("api_key") or os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    model = str(config.get("model") or "gpt-4o-mini")
    options = config.get("options") or {}
    return config, api_key, model, options


def _post_json(config: dict, api_key: str, payload: dict) -> dict:
    url = str(config.get("url") or "https://api.openai.com/v1/chat/completions")
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
            error = detail.get("error") if isinstance(detail, dict) else None
            message = error.get("message", str(exc)) if isinstance(error, dict) else str(exc)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            message = str(exc)
        raise RuntimeError(f"OpenAI returned HTTP {exc.code}: {message}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("OpenAI is not reachable") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("OpenAI returned invalid JSON") from exc
    return result


def _choice_content(result: dict, empty_error: str) -> str:
    choices = result.get("choices") if isinstance(result, dict) else None
    message = choices[0].get("message") if choices else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError(empty_error)
    return content


def chat(question: str, context: str, *, config: dict | None = None) -> str:
    """Ask OpenAI for a concise answer using the current encounter context."""
    config, api_key, model, options = _client_settings(config)
    payload = {
        "model": model,
        "temperature": float(options.get("temperature", 0)),
        "max_tokens": int(options.get("max_tokens", 80)),
        "messages": [
            {"role": "system", "content": str(config.get("system_prompt") or "Answer briefly.")},
            {"role": "user", "content": f"Encounter context:\n{context}\n\nQuestion: {question}"},
        ],
    }
    answer = _choice_content(_post_json(config, api_key, payload), "OpenAI returned an empty answer")
    answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL | re.IGNORECASE)
    answer = answer.replace("\r\n", "\n").replace("\r", "\n")
    answer = "\n".join(" ".join(line.split()).strip() for line in answer.split("\n"))
    answer = re.sub(r"\n{3,}", "\n\n", answer).strip()
    return answer


def music_search_terms(
    encounter_context: str,
    available_categories: list[str] | tuple[str, ...],
    *,
    config: dict | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Expand an encounter into safe local-catalog search vocabulary.

    The model receives category names, never tracks or URLs.  The caller still
    ranks only its own catalog metadata, so this helper cannot select or invent
    playable audio.
    """
    if not isinstance(encounter_context, str) or not encounter_context.strip():
        raise ValueError("Encounter context is required for music search")
    if isinstance(available_categories, (str, bytes)):
        raise ValueError("Available music categories must be a sequence")
    categories = tuple(
        dict.fromkeys(
            category.strip()
            for category in available_categories
            if isinstance(category, str) and category.strip()
        )
    )
    if len(categories) > 80:
        categories = categories[:80]

    config, api_key, model, options = _client_settings(config)
    category_items: dict = {"type": "string"}
    if categories:
        category_items["enum"] = list(categories)
    payload = {
        "model": model,
        "temperature": float(options.get("music_temperature", 0)),
        "max_tokens": int(options.get("music_max_tokens", 120)),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "music_search_terms",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "terms": {
                            "type": "array",
                            "minItems": 0,
                            "maxItems": 8,
                            "items": {"type": "string", "minLength": 1, "maxLength": 48},
                        },
                        "categories": {
                            "type": "array",
                            "minItems": 0,
                            "maxItems": 8,
                            "items": category_items,
                        },
                    },
                    "required": ["terms", "categories"],
                },
            },
        },
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return only search vocabulary for a local Tabletop Audio catalog. "
                    "Do not name tracks, URLs, artists, download ids, or playback instructions. "
                    "Use concise mood, setting, and action words. Categories must exactly match the supplied list."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Encounter context:\n{encounter_context.strip()}\n\n"
                    f"Allowed categories (exact spelling only):\n{', '.join(categories) or '(none)'}"
                ),
            },
        ],
    }
    content = _choice_content(_post_json(config, api_key, payload), "OpenAI returned empty music search terms")
    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenAI returned invalid music search JSON") from exc
    if not isinstance(result, dict) or set(result) != {"terms", "categories"}:
        raise RuntimeError("OpenAI returned malformed music search terms")
    terms = result.get("terms")
    picked_categories = result.get("categories")
    if not isinstance(terms, list) or not isinstance(picked_categories, list):
        raise RuntimeError("OpenAI returned malformed music search terms")
    if len(terms) > 8 or len(picked_categories) > 8:
        raise RuntimeError("OpenAI returned too many music search terms")

    cleaned_terms: list[str] = []
    for term in terms:
        if not isinstance(term, str):
            raise RuntimeError("OpenAI returned malformed music search terms")
        term = " ".join(term.split())
        if not term or len(term) > 48 or re.search(r"://|[\\/\\\\]|\.(?:mp3|m3u|wav)\b", term, re.I):
            raise RuntimeError("OpenAI returned unsafe music search terms")
        cleaned_terms.append(term)
    if any(not isinstance(category, str) or category not in categories for category in picked_categories):
        raise RuntimeError("OpenAI returned an unknown music category")
    return tuple(dict.fromkeys(cleaned_terms)), tuple(dict.fromkeys(picked_categories))


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
    config, api_key, model, options = _client_settings(config)
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
                        "pressure": {"type": "string", "enum": ["Low", "Moderate", "High", "Extreme", "Unknown"]},
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
                    "required": ["title", "theme", "pressure", "monsters"],
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
                    "Give only a rough, non-authoritative pressure signal from character levels and actual "
                    "party strength (HP, AC, attacks, and spellcasting) when provided. This is not encounter "
                    "balancing. For published adventures, use Unknown unless the request gives enough context. "
                    "Keep the plan practical for a table-side DM."
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
    content = _choice_content(
        _post_json(config, api_key, payload), "OpenAI returned an empty encounter plan",
    )
    try:
        plan = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenAI returned invalid encounter JSON") from exc
    if not isinstance(plan, dict) or not isinstance(plan.get("monsters"), list) or not plan["monsters"]:
        raise RuntimeError("OpenAI returned an empty encounter plan")
    return plan
