"""Focused behavioral checks for the Tabletop Audio provider and loop support."""

from __future__ import annotations

import json
import os
import tempfile

import music
import persistence
import tabletop_audio as ta


HTML = """
<div class="col-md-3 mix dungeon dark">
  <div class="track_title"><h3>Goblin Camp</h3><i>ambience + music</i></div>
  <p class="description">Smoke, drums, and watchfires.</p>
  <span class="saveButton"><a onclick="saveAs('Goblin_Camp')">Save</a></span>
</div>
<div class="col-md-3 mix forest">
  <div class="track_title"><h3>Patron Preview</h3></div>
  <div class="track_type">music</div><p>Patreon-only alternate</p>
</div>
<div class="col-md-3 mix dungeon">
  <div class="track_title"><h3>Bad Action</h3></div>
  <a onclick="saveAs('evil/host')">Save</a>
</div>
<div class="col-md-3 mix dungeon">
  <div class="track_title"><h3>Goblin Camp Duplicate</h3></div>
  <a onclick="saveAs('Goblin_Camp')">Save</a>
</div>
"""

TYPE_HTML = """
<div class="col-md-3 mix one"><div class="track_title"><h3>One</h3><i>ambience + minimal music</i></div><p class="flavor">one</p><a onclick="saveAs('one')">Save</a></div>
<div class="col-md-3 mix two"><div class="track_title"><h3>Two</h3><i>music + ambience</i></div><p class="flavor">two</p><a onclick="saveAs('two')">Save</a></div>
<div class="col-md-3 mix three"><div class="track_title"><h3>Three</h3><i>music + minimal ambience</i></div><p class="flavor">three</p><a onclick="saveAs('three')">Save</a></div>
"""

PROMO_HTML = """
<div class="col-md-3 mix watch"><div class="track_title"><h3>Watchtower</h3><i>ambience + minimal music</i></div>
<p class="flavor">Wind over the wall. [4 Alternate versions available for <a href="https://patreon.com/tabletopaudio">Patreon Patrons</a>]</p>
<a onclick="saveAs('watchtower')">Save</a></div>
"""


def test_parse_and_exclude_non_public_or_invalid_actions() -> None:
    tracks = ta.parse_catalog_html(HTML)
    assert [track.slug for track in tracks] == ["Goblin_Camp"]
    track = tracks[0]
    assert track.title == "Goblin Camp"
    assert track.audio_type == "ambience + music"
    assert track.description == "Smoke, drums, and watchfires."
    assert track.categories == ("dungeon", "dark")


def test_secure_url_derivation() -> None:
    assert ta.derive_playback_url("Goblin_Camp") == "https://sounds.tabletopaudio.com/Goblin_Camp.mp3"
    for slug in ("https://evil.example/a", "../secret", "ok.mp3", ""):
        try:
            ta.derive_playback_url(slug)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe slug was accepted")


def test_displayed_type_variants_are_preserved_without_ontology() -> None:
    assert [track.audio_type for track in ta.parse_catalog_html(TYPE_HTML)] == [
        "ambience + minimal music",
        "music + ambience",
        "music + minimal ambience",
    ]


def test_patreon_alternate_promotion_is_removed_from_flavor_only() -> None:
    variants = (
        "Alternate versions available for Patreon Patrons",
        "[Alternate version available for Patreon Patrons]",
        "[2 Alternate versions for Patreon Patrons]",
        "[Alt. version for Patreon Patrons]",
    )
    for index, promo in enumerate(variants):
        html = PROMO_HTML.replace("[4 Alternate versions available for <a href=\"https://patreon.com/tabletopaudio\">Patreon Patrons</a>]", promo)
        track = ta.parse_catalog_html(html)[0]
        assert track.description == "Wind over the wall.", promo
    ordinary = PROMO_HTML.replace(
        "[4 Alternate versions available for <a href=\"https://patreon.com/tabletopaudio\">Patreon Patrons</a>]",
        "The party once visited Patreon and remembered the strange posters.",
    )
    assert ta.parse_catalog_html(ordinary)[0].description.endswith("strange posters.")
    track = ta.parse_catalog_html(PROMO_HTML)[0]
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "catalog.json")
        with open(path, "w", encoding="utf-8") as output:
            json.dump({"fetched_at": 100, "tracks": [{**track.as_cache_dict(), "description": "Wind. [Alt. version for Patreon Patrons]"}]}, output)
        loaded = ta.load_catalog(path, now=101, fetcher=lambda _timeout: (_ for _ in ()).throw(AssertionError()))
        assert loaded.tracks[0].description == "Wind."


def test_track_model_is_immutable_and_rejects_malformed_fields() -> None:
    track = ta.TabletopAudioTrack("safe", "Safe", "music", "desc", ["forest"])
    assert track.categories == ("forest",)
    try:
        track.title = "changed"
    except Exception:
        pass
    else:
        raise AssertionError("frozen track was mutable")
    invalid = [
        {"title": 3},
        {"audio_type": 3},
        {"description": 3},
        {"categories": "forest"},
        {"categories": ["forest", 3]},
    ]
    for changes in invalid:
        values = {"slug": "safe", "title": "Safe", "audio_type": "music", "description": "desc", "categories": ()}
        values.update(changes)
        try:
            ta.TabletopAudioTrack(**values)
        except ValueError:
            pass
        else:
            raise AssertionError(f"malformed metadata accepted: {changes}")


def _cache(path: str, timestamp: float = 100.0) -> None:
    tracks = ta.parse_catalog_html(HTML)
    with open(path, "w", encoding="utf-8") as output:
        json.dump({"fetched_at": timestamp, "tracks": [track.as_cache_dict() for track in tracks]}, output)


def test_cache_fresh_refresh_stale_and_failure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "catalog.json")
        _cache(path)
        fresh = ta.load_catalog(path, now=101, fetcher=lambda _timeout: (_ for _ in ()).throw(AssertionError()))
        assert fresh.status == "fresh-cache"
        _cache(path, timestamp=200)
        future = ta.load_catalog(path, now=100, fetcher=lambda _timeout: HTML)
        assert future.status == "network"
        network = ta.load_catalog(path, now=100 + ta.CACHE_MAX_AGE_SECONDS + 1, fetcher=lambda _timeout: HTML)
        assert network.status == "network" and network.tracks[0].slug == "Goblin_Camp"
        stale = ta.load_catalog(path, now=100 + 2 * ta.CACHE_MAX_AGE_SECONDS + 2, fetcher=lambda _timeout: (_ for _ in ()).throw(OSError("offline")))
        assert stale.status == "stale-cache"
        os.unlink(path)
        try:
            ta.load_catalog(path, now=100, fetcher=lambda _timeout: (_ for _ in ()).throw(OSError("offline")))
        except RuntimeError as exc:
            assert "unavailable" in str(exc)
        else:
            raise AssertionError("catalog failure was not normalized")


def test_cache_write_failure_does_not_discard_tracks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "catalog.json")
        original = persistence.write_json_atomic
        persistence.write_json_atomic = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("read-only"))
        try:
            result = ta.load_catalog(path, now=100, fetcher=lambda _timeout: HTML)
        finally:
            persistence.write_json_atomic = original
        assert result.status == "network" and result.tracks


def test_malformed_cache_refreshes_or_normalizes_failure_and_ignores_url() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "catalog.json")
        with open(path, "w", encoding="utf-8") as output:
            json.dump({"fetched_at": 100, "tracks": [{"slug": "safe", "title": 3}]}, output)
        refreshed = ta.load_catalog(path, now=101, fetcher=lambda _timeout: HTML)
        assert refreshed.status == "network"
        with open(path, "w", encoding="utf-8") as output:
            json.dump({"fetched_at": 100, "tracks": [{"slug": "safe", "title": 3}]}, output)
        try:
            ta.load_catalog(path, now=101, fetcher=lambda _timeout: (_ for _ in ()).throw(OSError("offline")))
        except RuntimeError:
            pass
        else:
            raise AssertionError("malformed cache bypassed normalized failure")
        track = ta.parse_catalog_html(HTML)[0]
        with open(path, "w", encoding="utf-8") as output:
            json.dump({"fetched_at": 100, "tracks": [{**track.as_cache_dict(), "url": "https://evil.example/x.mp3"}]}, output)
        loaded = ta.load_catalog(path, now=101, fetcher=lambda _timeout: (_ for _ in ()).throw(AssertionError()))
        assert loaded.tracks[0].playback_url == "https://sounds.tabletopaudio.com/Goblin_Camp.mp3"


def test_actual_fetch_uses_https_request_user_agent_and_timeout() -> None:
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return HTML.encode("utf-8")

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return Response()

    original = ta.urlopen
    ta.urlopen = fake_urlopen
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = ta.load_catalog(os.path.join(tmp, "catalog.json"), now=100, timeout=3.25)
    finally:
        ta.urlopen = original
    request, timeout = calls[0]
    assert result.status == "network" and request.full_url == ta.CATALOG_URL and timeout == 3.25
    assert request.get_header("User-agent") == ta.USER_AGENT


def test_ranking_is_local_weighted_and_explicit_for_empty_queries() -> None:
    tracks = (
        ta.TabletopAudioTrack("title", "Dragon", "quiet", "plain", ()),
        ta.TabletopAudioTrack("category", "Plain", "quiet", "plain", ("dragon",)),
        ta.TabletopAudioTrack("kind", "Plain", "dragon", "plain", ()),
        ta.TabletopAudioTrack("description", "Plain", "quiet", "dragon", ()),
        ta.TabletopAudioTrack("z", "Echo", "quiet", "plain", ("same",)),
        ta.TabletopAudioTrack("a", "Echo", "quiet", "plain", ("same",)),
    )
    assert [track.slug for track in ta.rank_tracks(tracks, "dragon")] == ["title", "category", "kind", "description"]
    assert [track.slug for track in ta.rank_tracks(tracks, "same", limit=1)] == ["a"]
    assert len(ta.rank_tracks(tracks, "plain", limit=2)) == 2
    assert ta.rank_tracks(tracks, "", limit=1) == ()
    assert ta.rank_tracks(tracks, "spaceship") == ()
    noise = (
        ta.TabletopAudioTrack("outpost", "Outpost 31", "quiet", "plain", ()),
        ta.TabletopAudioTrack("round", "Round 3", "quiet", "plain", ()),
    )
    assert [track.slug for track in ta.rank_tracks(noise, "Round 3")] == ["round"]
    assert ta.rank_tracks(noise, "31") == ()
    assert ta.rank_tracks(noise, "out") == ()


def test_loop_config_validation_and_exact_player_commands() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "music.json")
        with open(path, "w", encoding="utf-8") as output:
            json.dump({"sources": [{"name": "Loop", "url": "https://a", "loop": True}]}, output)
        assert music.load_config(path).sources[0].loop is True
        with open(path, "w", encoding="utf-8") as output:
            json.dump({"sources": [{"name": "Bad", "url": "https://a", "loop": "yes"}]}, output)
        try:
            music.load_config(path)
        except ValueError:
            pass
        else:
            raise AssertionError("non-boolean loop accepted")

    calls = []
    player = music.MusicPlayer(backend="mpv", volume=40, which=lambda _name: "/bin/player", popen=lambda command, **kwargs: calls.append(command) or _Process())
    player.play(music.MusicSource("Loop", "https://a", loop=True))
    assert calls[-1] == ["/bin/player", "--no-video", "--really-quiet", "--force-window=no", "--volume=40", "--loop=inf", "https://a"]
    player.stop()
    player = music.MusicPlayer(backend="mpv", volume=40, which=lambda _name: "/bin/player", popen=lambda command, **kwargs: calls.append(command) or _Process())
    player.play(music.MusicSource("Tabletop Audio", "https://a", loop=True, referrer="https://tabletopaudio.com/"))
    assert calls[-1] == ["/bin/player", "--no-video", "--really-quiet", "--force-window=no", "--volume=40", "--loop=inf", "--referrer=https://tabletopaudio.com/", "https://a"]
    player.stop()
    player = music.MusicPlayer(backend="ffplay", volume=40, which=lambda _name: "/bin/player", popen=lambda command, **kwargs: calls.append(command) or _Process())
    player.play(music.MusicSource("Tabletop Audio", "https://a", loop=True, referrer="https://tabletopaudio.com/"))
    assert calls[-1] == ["/bin/player", "-nodisp", "-autoexit", "-loglevel", "error", "-volume", "40", "-loop", "0", "-referer", "https://tabletopaudio.com/", "https://a"]
    player.stop()
    player = music.MusicPlayer(backend="mpv", volume=40, which=lambda _name: "/bin/player", popen=lambda command, **kwargs: calls.append(command) or _Process())
    player.play(music.MusicSource("Default", "https://a"))
    assert calls[-1] == ["/bin/player", "--no-video", "--really-quiet", "--force-window=no", "--volume=40", "https://a"]
    player.stop()
    player = music.MusicPlayer(backend="ffplay", volume=40, which=lambda _name: "/bin/player", popen=lambda command, **kwargs: calls.append(command) or _Process())
    player.play(music.MusicSource("Default", "https://a", loop=False))
    assert calls[-1] == ["/bin/player", "-nodisp", "-autoexit", "-loglevel", "error", "-volume", "40", "https://a"]


class _Process:
    def poll(self):
        return None

    def terminate(self):
        pass

    def wait(self, timeout):
        return 0

    def kill(self):
        pass


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"TABLETOP AUDIO TESTS OK ({len(tests)} passed)")


if __name__ == "__main__":
    main()
