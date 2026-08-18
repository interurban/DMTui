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
  <div class="track_title"><h3>Goblin Camp</h3></div>
  <div class="track_type">ambience + music</div>
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


def test_parse_and_exclude_non_public_or_invalid_actions() -> None:
    tracks = ta.parse_catalog_html(HTML)
    assert [track.slug for track in tracks] == ["Goblin_Camp"]
    track = tracks[0]
    assert track.title == "Goblin Camp"
    assert track.audio_type == "ambience + music"
    assert track.description == "Smoke, drums, and watchfires."
    assert track.categories == ("dark", "dungeon")


def test_secure_url_derivation() -> None:
    assert ta.derive_playback_url("Goblin_Camp") == "https://sounds.tabletopaudio.com/Goblin_Camp.mp3"
    for slug in ("https://evil.example/a", "../secret", "ok.mp3", ""):
        try:
            ta.derive_playback_url(slug)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe slug was accepted")


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
            result = ta.load_catalog(path, now=100, fetcher=lambda: HTML)
        finally:
            persistence.write_json_atomic = original
        assert result.status == "network" and result.tracks


def test_ranking_is_local_weighted_and_explicit_for_empty_queries() -> None:
    tracks = ta.parse_catalog_html(HTML)
    assert ta.rank_tracks(tracks, "goblin", limit=1)[0].slug == "Goblin_Camp"
    assert ta.rank_tracks(tracks, "", limit=1) == ()
    assert ta.rank_tracks(tracks, "spaceship") == ()


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
    player = music.MusicPlayer(backend="ffplay", volume=40, which=lambda _name: "/bin/player", popen=lambda command, **kwargs: calls.append(command) or _Process())
    player.play(music.MusicSource("Loop", "https://a", loop=True))
    assert calls[-1] == ["/bin/player", "-nodisp", "-autoexit", "-loglevel", "error", "-volume", "40", "-loop", "0", "https://a"]


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
