"""Behavioral coverage for Ward's encounter-aware Tabletop Audio UI."""

import asyncio
import json
import os
from unittest import mock

import app as appmod
from app import BattleApp
from battle import Combatant
from modals import GeneratingModal, ListModal, TextModal
import openai_client
import tabletop_audio


def _response(content):
    return {"choices": [{"message": {"content": json.dumps(content)}}]}


def _track(slug="crypt", title="Crypt Tension", categories=("Dungeon",)):
    return tabletop_audio.TabletopAudioTrack(
        slug=slug,
        title=title,
        audio_type="Music",
        description="Ominous stone corridors and distant bells.",
        categories=categories,
    )


def test_music_search_terms_uses_strict_categories_and_rejects_malformed_output():
    captured = {}

    def fake_post(_config, _key, payload):
        captured.update(payload)
        return _response({"terms": ["ominous rain", "pursuit"], "categories": ["Dungeon"]})

    config = {"api_key": "test-key", "model": "test-model", "options": {}}
    with mock.patch.object(openai_client, "_post_json", fake_post):
        terms, categories = openai_client.music_search_terms(
            "Encounter: Old Crypt. Opponents: 2 Ghouls. Round 3.",
            ["Dungeon", "Weather"],
            config=config,
        )
    assert terms == ("ominous rain", "pursuit")
    assert categories == ("Dungeon",)
    schema = captured["response_format"]["json_schema"]["schema"]
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert schema["additionalProperties"] is False
    assert schema["properties"]["categories"]["items"]["enum"] == ["Dungeon", "Weather"]
    assert "tracks" not in captured["messages"][1]["content"].lower()

    with mock.patch.object(openai_client, "_post_json", return_value=_response({
        "terms": ["https://bad.example/track.mp3"], "categories": ["Made up"],
    })):
        try:
            openai_client.music_search_terms("A fight", ["Dungeon"], config=config)
        except RuntimeError as exc:
            assert "unsafe" in str(exc) or "unknown" in str(exc)
        else:
            raise AssertionError("unsafe terms and unknown categories must be rejected")


def test_music_context_groups_foes_and_excludes_party_names():
    app = BattleApp()
    app._session_encounter_name = "Zephyr's Old Toll Road Ambush"
    app.round = 4
    app.combatants = [
        Combatant("Zephyr", "PC", hp=10, max_hp=10, ac=12),
        Combatant("Lyra", "PC", hp=10, max_hp=10, ac=12),
        Combatant("Goblin", "monster", hp=7, max_hp=7, ac=12),
        Combatant("Goblin 2", "monster", hp=7, max_hp=7, ac=12),
        Combatant("Ogre", "monster", hp=59, max_hp=59, ac=11),
    ]
    context = app._music_encounter_context()
    assert "Zephyr" not in context and "Lyra" not in context
    assert "2 Goblins" in context and "1 Ogre" in context
    assert "Round 4" in context
    app._session_encounter_name = ""
    app.combatants = []
    assert "Fantasy tabletop encounter" in app._music_encounter_context()


class _FlowApp(BattleApp):
    def __init__(self, replies=()):
        super().__init__()
        self.replies = list(replies)
        self.screens = []
        self.logs = []
        self.played = []
        self._session_encounter_name = "Crypt Assault"
        self.combatants = [Combatant("Mira", "PC", hp=10, max_hp=10, ac=12),
                            Combatant("Ghoul", "monster", hp=10, max_hp=10, ac=12)]

    def push_screen(self, screen, *, wait_for_dismiss=False, **_kwargs):
        self.screens.append(screen)
        if not wait_for_dismiss:
            return None

        async def reply():
            return self.replies.pop(0) if self.replies else None

        return reply()

    def _log(self, message, kind="info", **_kwargs):
        self.logs.append((message, kind))

    def _sync_music_status(self):
        return None


def _inline(fn, *args, **kwargs):
    async def call():
        return fn(*args, **kwargs)
    return call()


def test_music_ai_failure_falls_back_to_local_catalog_search():
    app = _FlowApp(["back"])
    catalog = tabletop_audio.CatalogLoad((_track(),), "fresh-cache")
    queries = []

    def rank(_tracks, query, limit=5):
        queries.append(query)
        return ()

    with mock.patch.object(appmod, "run_in_thread", _inline), \
         mock.patch.object(tabletop_audio, "load_catalog", return_value=catalog), \
         mock.patch.object(openai_client, "music_search_terms", side_effect=RuntimeError("no key")), \
         mock.patch.object(tabletop_audio, "rank_tracks", rank):
        asyncio.run(app._tabletop_audio_flow())
    assert queries and "Ghoul" in queries[0]
    assert any("AI helper unavailable" in message for message, _kind in app.logs)
    menus = [screen for screen in app.screens if isinstance(screen, ListModal)]
    assert menus and any(key == "none" for key, _label in menus[0]._options)


def test_music_no_results_can_refine_without_playing():
    app = _FlowApp(["refine", "foggy bridge", "back"])
    catalog = tabletop_audio.CatalogLoad((_track(),), "network")
    with mock.patch.object(appmod, "run_in_thread", _inline), \
         mock.patch.object(tabletop_audio, "load_catalog", return_value=catalog), \
         mock.patch.object(openai_client, "music_search_terms", return_value=((), ())), \
         mock.patch.object(tabletop_audio, "rank_tracks", return_value=()):
        asyncio.run(app._tabletop_audio_flow())
    menus = [screen for screen in app.screens if isinstance(screen, ListModal)]
    assert len(menus) == 2
    assert "TABLETOP AUDIO" in menus[0]._title and "CC BY-NC-ND 4.0" in menus[0]._title
    assert any(key == "refine" for key, _label in menus[0]._options)
    assert any(isinstance(screen, TextModal) for screen in app.screens)
    assert not app.played


def test_tabletop_audio_back_reopens_music_controls_for_results_and_no_results():
    catalog = tabletop_audio.CatalogLoad((_track(),), "fresh-cache")

    for has_results in (True, False):
        app = _FlowApp(["suggest-tabletop", "back", "back"])
        rank = (lambda _tracks, _query, limit=5: catalog.tracks) if has_results else (
            lambda _tracks, _query, limit=5: ()
        )
        with mock.patch.object(appmod, "run_in_thread", _inline), \
             mock.patch.object(tabletop_audio, "load_catalog", return_value=catalog), \
             mock.patch.object(openai_client, "music_search_terms", return_value=((), ())), \
             mock.patch.object(tabletop_audio, "rank_tracks", rank):
            asyncio.run(app._music_flow())
        menus = [screen for screen in app.screens if isinstance(screen, ListModal)]
        assert len(menus) == 3
        assert menus[0]._title.startswith("MUSIC ·")
        assert menus[1]._title.startswith("TABLETOP AUDIO ·")
        assert menus[2]._title.startswith("MUSIC ·")
        assert any(key == "suggest-tabletop" for key, _label in menus[2]._options)


def test_confirmed_catalog_track_streams_derived_looped_url_with_attribution():
    app = _FlowApp(["tta:crypt"])
    track = _track()
    catalog = tabletop_audio.CatalogLoad((track,), "stale-cache")

    def play(source, *, attribution=""):
        app.played.append((source, attribution))
        return True

    app._play_music_source = play
    with mock.patch.object(appmod, "run_in_thread", _inline), \
         mock.patch.object(tabletop_audio, "load_catalog", return_value=catalog), \
         mock.patch.object(openai_client, "music_search_terms", return_value=(("ominous",), ("Dungeon",))):
        asyncio.run(app._tabletop_audio_flow())
    source, attribution = app.played[0]
    assert source.loop is True and source.url == track.playback_url
    assert attribution == "Tabletop Audio · CC BY-NC-ND 4.0"
    menu = next(screen for screen in app.screens if isinstance(screen, ListModal))
    assert "TABLETOP AUDIO" in menu._title and "CC BY-NC-ND 4.0" in menu._title
    selected_label = next(label for key, label in menu._options if key == "tta:crypt")
    assert "\n" in selected_label and "Music" in selected_label
    assert any("stale metadata" in message for message, _kind in app.logs)


def test_tabletop_audio_errors_and_offline_mode_never_fetch_or_play():
    app = _FlowApp()
    with mock.patch.object(appmod, "run_in_thread", _inline), \
         mock.patch.object(tabletop_audio, "load_catalog", side_effect=RuntimeError("down")):
        asyncio.run(app._tabletop_audio_flow())
    assert any("suggestions unavailable" in message for message, _kind in app.logs)

    app = _FlowApp()
    with mock.patch.dict(os.environ, {"WARD_OFFLINE": "1"}), \
         mock.patch.object(appmod, "run_in_thread", side_effect=AssertionError("must not fetch")):
        asyncio.run(app._tabletop_audio_flow())
    assert any("unavailable offline" in message for message, _kind in app.logs)


def test_generating_modal_keeps_defaults_and_escapes_custom_copy():
    default = GeneratingModal()
    custom = GeneratingModal("Finding <tracks>", "Loading & ranking")
    assert default._title == "Building encounter…"
    assert default._detail.startswith("Choosing existing")
    assert custom._title == "Finding <tracks>"
    assert custom._detail == "Loading & ranking"
