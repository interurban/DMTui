"""Small, dependency-free client for Tabletop Audio's public 10-minute catalog.

Only catalog metadata is cached.  Audio is always streamed by the player from
the URL derived by :class:`TabletopAudioTrack`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from html.parser import HTMLParser
import json
from collections.abc import Sequence
import math
import re
import time
from typing import Any, Callable, Iterable
from urllib.request import Request, urlopen

import persistence


CATALOG_URL = "https://tabletopaudio.com/"
SOUNDS_URL = "https://sounds.tabletopaudio.com"
CACHE_MAX_AGE_SECONDS = 24 * 60 * 60
MAX_FETCH_TIMEOUT_SECONDS = 30.0
USER_AGENT = "Ward/1.0 (Tabletop Audio catalog; +https://tabletopaudio.com/)"
_SLUG_RE = re.compile(r"^[A-Za-z0-9_]+$")
_SAVE_RE = re.compile(r"\bsaveAs\s*\(\s*(['\"])([A-Za-z0-9_]+)\1\s*\)")
_PATREON_PROMO_RE = re.compile(
    r"\s*(?:[\[(]\s*)?(?:\d+\s+)?(?:alternate|alt\.)\s+versions?"
    r"(?:,\s*plus\s+[^\]\)]*?)?\s+"
    r"(?:available\s+)?for\b[^\]\)]*\bpatreon\b[^\]\)]*(?:[\])]\s*)?$",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True)
class TabletopAudioTrack:
    """Immutable metadata for a publicly downloadable Tabletop Audio track."""

    slug: str
    title: str
    audio_type: str
    description: str
    categories: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.slug, str) or not _SLUG_RE.fullmatch(self.slug):
            raise ValueError("Tabletop Audio download id must be alphanumeric or underscore")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("Tabletop Audio track title cannot be empty")
        if not isinstance(self.audio_type, str) or not isinstance(self.description, str):
            raise ValueError("Tabletop Audio type and description must be strings")
        if isinstance(self.categories, (str, bytes)) or not isinstance(self.categories, Sequence):
            raise ValueError("Tabletop Audio categories must be a sequence of strings")
        if any(not isinstance(category, str) for category in self.categories):
            raise ValueError("Tabletop Audio categories must be a sequence of strings")
        object.__setattr__(self, "categories", tuple(self.categories))

    @property
    def download_id(self) -> str:
        """The public download id (kept separate from any URL/cache input)."""
        return self.slug

    @property
    def kind(self) -> str:
        """Short alias useful to ranking and UI callers."""
        return self.audio_type

    @property
    def playback_url(self) -> str:
        """Derive the only supported playback URL from the validated slug."""
        return derive_playback_url(self.slug)

    def as_cache_dict(self) -> dict[str, Any]:
        return asdict(self)


def derive_playback_url(slug: str) -> str:
    """Return a safe direct MP3 URL, rejecting paths, hosts, and punctuation."""
    if not isinstance(slug, str) or not _SLUG_RE.fullmatch(slug):
        raise ValueError("Tabletop Audio download id must match [A-Za-z0-9_]+")
    return f"{SOUNDS_URL}/{slug}.mp3"


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str]
    children: list["_Node | str"]


class _TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root", {}, [])
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag.lower(), {key.lower(): value or "" for key, value in attrs}, [])
        self._stack[-1].children.append(node)
        if tag.lower() not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._stack[-1].children.append(
            _Node(tag.lower(), {key.lower(): value or "" for key, value in attrs}, [])
        )

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._stack[-1].children.append(data)


def _classes(node: _Node) -> set[str]:
    return set(node.attrs.get("class", "").split())


def _descendants(node: _Node) -> Iterable[_Node]:
    for child in node.children:
        if isinstance(child, _Node):
            yield child
            yield from _descendants(child)


def _text(node: _Node) -> str:
    return " ".join(
        part for child in node.children for part in ([child] if isinstance(child, str) else [_text(child)]) if part
    ).strip()


def _strip_patreon_promo(description: str) -> str:
    """Remove only the paid alternate-version notice appended to flavor text."""
    return _PATREON_PROMO_RE.sub("", description).strip()


def _find_class(node: _Node, *names: str) -> list[_Node]:
    wanted = tuple(name.casefold() for name in names)
    return [candidate for candidate in _descendants(node) if any(name in {item.casefold() for item in _classes(candidate)} for name in wanted)]


def _card_nodes(root: _Node) -> Iterable[_Node]:
    for node in _descendants(root):
        classes = _classes(node)
        if node.tag == "div" and "col-md-3" in classes and "mix" in classes:
            yield node


def _card_track(card: _Node) -> TabletopAudioTrack | None:
    slug: str | None = None
    for node in _descendants(card):
        action = node.attrs.get("onclick", "")
        match = _SAVE_RE.search(action)
        if match:
            slug = match.group(2)
            break
    if slug is None:
        return None

    title = ""
    title_nodes = _find_class(card, "track_title", "track-title", "title")
    for node in title_nodes:
        headings = [child for child in _descendants(node) if child.tag in {"h1", "h2", "h3", "h4"}]
        title = _text(headings[0] if headings else node)
        if title:
            break
    if not title:
        headings = [node for node in _descendants(card) if node.tag in {"h1", "h2", "h3", "h4"}]
        title = _text(headings[0]) if headings else ""
    if not title:
        return None

    # The site's type line is part of the title block.  Read that displayed
    # element (rather than recognizing a hardcoded set of type phrases), so
    # new official labels remain intact.
    audio_type = ""
    for title_node in title_nodes:
        type_nodes = _find_class(title_node, "audio_type", "audio-type", "track_type", "track-type", "type")
        candidates = type_nodes + [
            node for node in _descendants(title_node) if node.tag in {"i", "em", "small"}
        ]
        for node in candidates:
            candidate = _text(node)
            if candidate and candidate.casefold() != title.casefold():
                audio_type = candidate
                break
        if audio_type:
            break
        # A type line may be an unclassed element immediately after the h3.
        heading_seen = False
        for child in title_node.children:
            if not isinstance(child, _Node):
                if heading_seen and child.strip():
                    audio_type = child
                    break
                continue
            if child.tag in {"h1", "h2", "h3", "h4"}:
                heading_seen = True
                continue
            if heading_seen:
                candidate = _text(child)
                if candidate:
                    audio_type = candidate
                    break
        if audio_type:
            break
    if not audio_type:
        # Some revisions place the type line beside (rather than inside) the
        # title block.  It remains structurally marked; preserve its complete
        # displayed text without interpreting the vocabulary.
        type_nodes = _find_class(card, "audio_type", "audio-type", "track_type", "track-type", "type")
        for node in type_nodes:
            candidate = _text(node)
            if candidate and candidate.casefold() != title.casefold():
                audio_type = candidate
                break
    audio_type = re.sub(r"\s+", " ", audio_type).strip()

    description = ""
    description_nodes = _find_class(
        card,
        "description",
        "flavor",
        "flavour",
        "track_flavor",
        "track-flavor",
        "flavor_text",
        "track_description",
        "track-description",
    )
    for node in description_nodes:
        description = _text(node)
        if description:
            break
    # Older cards did not have a dedicated description class.  Their visible
    # flavor text is still useful, but controls and Patreon notices are not.
    if not description:
        pieces = []
        for node in _descendants(card):
            if node.tag not in {"p", "span", "div"}:
                continue
            classes = _classes(node)
            if classes.intersection({"track_title", "track-title", "track_type", "track-type", "audio_type", "audio-type"}):
                continue
            text = _text(node)
            if text and text.casefold() not in {title.casefold(), audio_type.casefold()}:
                if "patreon" not in text.casefold() and not any(label in text.casefold() for label in ("save", "add", "play")):
                    pieces.append(text)
        description = pieces[0] if pieces else ""
    description = _strip_patreon_promo(description)

    categories = tuple(
        dict.fromkeys(
            category
            for category in card.attrs.get("class", "").split()
            if category not in {"col-md-3", "mix"}
        )
    )
    return TabletopAudioTrack(slug, title, audio_type, description, categories)


def parse_catalog_html(html: str) -> tuple[TabletopAudioTrack, ...]:
    """Parse public card metadata and deduplicate by download id."""
    if not isinstance(html, str):
        raise ValueError("Tabletop Audio catalog must be text HTML")
    parser = _TreeParser()
    parser.feed(html)
    parser.close()
    tracks: list[TabletopAudioTrack] = []
    seen: set[str] = set()
    for card in _card_nodes(parser.root):
        try:
            track = _card_track(card)
        except ValueError:
            continue
        if track is not None and track.slug not in seen:
            seen.add(track.slug)
            tracks.append(track)
    return tuple(tracks)


@dataclass(frozen=True)
class CatalogLoad:
    tracks: tuple[TabletopAudioTrack, ...]
    status: str  # fresh-cache, network, stale-cache

    @property
    def source(self) -> str:
        return self.status


def _cache_tracks(raw: Any) -> tuple[float, tuple[TabletopAudioTrack, ...]]:
    if not isinstance(raw, dict):
        raise ValueError("invalid cache object")
    stamp = raw.get("fetched_at")
    if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
        timestamp = float(stamp)
        if not math.isfinite(timestamp):
            raise ValueError("cache timestamp invalid")
    elif isinstance(stamp, str):
        timestamp = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    else:
        raise ValueError("cache timestamp missing")
    entries = raw.get("tracks")
    if not isinstance(entries, list):
        raise ValueError("cache tracks missing")
    tracks = []
    seen: set[str] = set()
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("cache track must be an object")
        try:
            track = TabletopAudioTrack(
                slug=item["slug"], title=item["title"], audio_type=item.get("audio_type", ""),
                description=_strip_patreon_promo(item.get("description", "")),
                categories=item.get("categories", ()),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("cache contains malformed track metadata") from exc
        if track.slug not in seen:
            seen.add(track.slug)
            tracks.append(track)
    return timestamp, tuple(tracks)


def _read_cache(path: str) -> tuple[float, tuple[TabletopAudioTrack, ...]] | None:
    try:
        with open(path, encoding="utf-8") as cache_file:
            return _cache_tracks(json.load(cache_file))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _fetch_catalog(timeout: float) -> str:
    timeout = max(0.1, min(float(timeout), MAX_FETCH_TIMEOUT_SECONDS))
    request = Request(CATALOG_URL, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urlopen(request, timeout=timeout) as response:
        body = response.read()
    return body.decode("utf-8", errors="replace")


def load_catalog(
    cache_path: str,
    *,
    now: float | None = None,
    timeout: float = 10.0,
    fetcher: Callable[[float], str] | None = None,
) -> CatalogLoad:
    """Load fresh metadata, refresh it, or fall back to valid stale metadata."""
    current = time.time() if now is None else float(now)
    cached = _read_cache(cache_path)
    cache_age = current - cached[0] if cached is not None else None
    if cached is not None and cache_age is not None and 0 <= cache_age < CACHE_MAX_AGE_SECONDS and cached[1]:
        return CatalogLoad(cached[1], "fresh-cache")
    try:
        if fetcher is None:
            html = _fetch_catalog(timeout)
        else:
            html = fetcher(timeout)
        tracks = parse_catalog_html(html)
        if not tracks:
            raise ValueError("catalog contained no public downloads")
        cache_data = {"fetched_at": current, "tracks": [track.as_cache_dict() for track in tracks]}
        try:
            persistence.write_json_atomic(cache_path, cache_data, indent=2)
        except Exception:
            pass
        return CatalogLoad(tracks, "network")
    except Exception as exc:
        if cached is not None and cached[1]:
            return CatalogLoad(cached[1], "stale-cache")
        raise RuntimeError(f"Tabletop Audio catalog unavailable: {exc}") from exc


def rank_tracks(tracks: Iterable[TabletopAudioTrack], query: str, limit: int = 10) -> tuple[TabletopAudioTrack, ...]:
    """Rank local metadata deterministically; an empty query returns no matches."""
    if (
        not isinstance(query, str)
        or not query.strip()
        or not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit <= 0
    ):
        return ()
    terms = tuple(
        dict.fromkeys(
            word.casefold()
            for word in _WORD_RE.findall(query)
            if not word.isdigit()
        )
    )
    if not terms:
        return ()
    scored: list[tuple[int, str, str, TabletopAudioTrack]] = []
    for track in tracks:
        title = {word.casefold() for word in _WORD_RE.findall(track.title)}
        categories = {word.casefold() for category in track.categories for word in _WORD_RE.findall(category)}
        kind = {word.casefold() for word in _WORD_RE.findall(track.audio_type)}
        description = {word.casefold() for word in _WORD_RE.findall(track.description)}
        score = sum(
            (100 if term in title else 0)
            + (30 if term in categories else 0)
            + (20 if term in kind else 0)
            + (10 if term in description else 0)
            for term in terms
        )
        if score:
            scored.append((score, track.title.casefold(), track.slug.casefold(), track))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    return tuple(item[3] for item in scored[:limit])


search_tracks = rank_tracks
