"""Behavioral coverage for Ward's encounter-aware Tabletop Audio UI."""

import asyncio
import json
import os
import tempfile
from unittest import mock

import app as appmod
from app import BattleApp
from battle import Combatant
from modals import GeneratingModal, ListModal, TextModal
import openai_client
import tabletop_audio
from textual.screen import ModalScreen


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


def test_openai_config_falls_back_to_packaged_defaults_without_checkout_file():
    with tempfile.TemporaryDirectory() as tmp:
        missing_root = os.path.join(tmp, "llm_config.json")
        explicit = os.path.join(tmp, "custom.json")
        with open(explicit, "w", encoding="utf-8") as config_file:
            json.dump({"model": "explicit-model"}, config_file)
        with mock.patch.object(openai_client, "CONFIG_PATH", missing_root), \
             mock.patch.dict(os.environ, {"OPENAI_API_KEY": "package-test-key"}, clear=False):
            config = openai_client.load_config()
            loaded, api_key, model, options = openai_client._client_settings(None)
            assert config["model"] == "gpt-4o-mini"
            assert loaded["model"] == "gpt-4o-mini"
            assert (api_key, model, options["temperature"]) == ("package-test-key", "gpt-4o-mini", 0)
            assert openai_client.load_config(explicit) == {"model": "explicit-model"}


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

    app._session_campaign = "Saved party"
    app._session_encounter_name = "Nora's Moonlit Ruins"
    app.combatants = [Combatant("Goblin", "monster", hp=7, max_hp=7, ac=12)]
    app._campaign_party = lambda _name: [{"name": "Nora"}]
    assert "Nora" not in app._music_encounter_context()
    app._campaign_party = lambda _name: (_ for _ in ()).throw(ValueError("bad campaign data"))
    failed_context = app._music_encounter_context()
    assert "Nora" not in failed_context and "Encounter:" not in failed_context
    assert "Round 4" in failed_context


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
    app = _FlowApp(["battle", "back"])
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
    suggestions = [menu for menu in menus if "ENCOUNTER SUGGESTIONS" in menu._title]
    assert suggestions and any(key == "none" for key, _label in suggestions[0]._options)


def test_music_no_results_can_refine_without_playing():
    app = _FlowApp(["battle", "refine", "foggy bridge", "back"])
    catalog = tabletop_audio.CatalogLoad((_track(),), "network")
    with mock.patch.object(appmod, "run_in_thread", _inline), \
         mock.patch.object(tabletop_audio, "load_catalog", return_value=catalog), \
         mock.patch.object(openai_client, "music_search_terms", return_value=((), ())), \
         mock.patch.object(tabletop_audio, "rank_tracks", return_value=()):
        asyncio.run(app._tabletop_audio_flow())
    menus = [screen for screen in app.screens if isinstance(screen, ListModal)]
    suggestions = [menu for menu in menus if "ENCOUNTER SUGGESTIONS" in menu._title]
    assert len(suggestions) == 2
    assert "TABLETOP AUDIO" in suggestions[0]._title and "CC BY-NC-ND 4.0" in suggestions[0]._title
    assert any(key == "refine" for key, _label in suggestions[0]._options)
    assert any(isinstance(screen, TextModal) for screen in app.screens)
    assert not app.played


def test_tabletop_audio_expands_ai_once_before_local_refines_and_no_results():
    app = _FlowApp(["battle", "refine", "foggy bridge", "none", "back"])
    catalog = tabletop_audio.CatalogLoad((_track(),), "network")
    calls = []
    ranks = []

    def helper(*_args, **_kwargs):
        calls.append("ai")
        return (("ominous",), ("Dungeon",))

    def rank(_tracks, query, limit=5):
        ranks.append(query)
        return ()

    with mock.patch.object(appmod, "run_in_thread", _inline), \
         mock.patch.object(tabletop_audio, "load_catalog", return_value=catalog), \
         mock.patch.object(openai_client, "music_search_terms", helper), \
         mock.patch.object(tabletop_audio, "rank_tracks", rank):
        asyncio.run(app._tabletop_audio_flow())
    assert calls == ["ai"]
    assert len(ranks) == 3 and "foggy bridge" in ranks[-1]
    assert isinstance(app.screens[0], GeneratingModal)


def test_tabletop_audio_escape_while_loading_never_opens_or_reopens_menus():
    catalog = tabletop_audio.CatalogLoad((_track(),), "fresh-cache")

    async def exercise(phase):
        app = _FlowApp(["suggest-tabletop", "battle"])
        started = asyncio.Event()
        release = asyncio.Event()

        async def delayed(fn, *args, **kwargs):
            if (phase == "catalog" and fn is tabletop_audio.load_catalog) or (
                phase == "ai" and fn is openai_client.music_search_terms
            ):
                started.set()
                await release.wait()
            if fn is tabletop_audio.load_catalog:
                return catalog
            if fn is openai_client.music_search_terms:
                return (), ()
            return fn(*args, **kwargs)

        with mock.patch.object(appmod, "run_in_thread", delayed):
            task = asyncio.create_task(app._music_flow())
            await started.wait()
            loading = next(screen for screen in app.screens if isinstance(screen, GeneratingModal))
            with mock.patch.object(loading, "dismiss", return_value=None):
                loading.action_cancel()
            release.set()
            await task
        menus = [screen for screen in app.screens if isinstance(screen, ListModal)]
        assert menus[0]._title.startswith("MUSIC ·")
        assert not any("ENCOUNTER SUGGESTIONS" in menu._title for menu in menus)

    asyncio.run(exercise("catalog"))
    asyncio.run(exercise("ai"))


def test_music_worker_is_named_and_exclusive():
    app = _FlowApp()
    calls = []

    def fake_run_worker(work, **kwargs):
        calls.append((work, kwargs))

    app.run_worker = fake_run_worker
    app.action_music()
    app.action_music()
    for work, _kwargs in calls:
        work.close()
    assert len(calls) == 2
    assert all(kwargs["name"] == "music-controls" for _work, kwargs in calls)
    assert all(kwargs["group"] == "music-controls" and kwargs["exclusive"] for _work, kwargs in calls)


def test_mounted_music_back_naturally_returns_to_the_root_screen():
    class TestApp(BattleApp):
        async def _boot_campaign(self):
            return

    async def exercise():
        app = TestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("ctrl+k")
            for _ in range(20):
                await pilot.pause()
                if isinstance(app.screen, ListModal):
                    break
            else:
                raise AssertionError("music controls did not open")
            await pilot.press("end", "enter")
            for _ in range(20):
                await pilot.pause()
                if not isinstance(app.screen, ModalScreen):
                    break
            else:
                raise AssertionError("music controls did not close")
            assert app.is_mounted and not isinstance(app.screen, ModalScreen)

    asyncio.run(exercise())


def test_invalid_config_still_offers_online_tabletop_audio_and_playback_failure_reopens_controls():
    app = _FlowApp(["back"])
    with mock.patch.object(appmod.music, "load_config", side_effect=ValueError("bad config")):
        asyncio.run(app._music_flow())
    menu = next(screen for screen in app.screens if isinstance(screen, ListModal))
    assert any(key == "suggest-tabletop" for key, _label in menu._options)
    assert any("bad config" in message for message, _kind in app.logs)

    app = _FlowApp(["suggest-tabletop", "battle", "tta:crypt", "back"])
    catalog = tabletop_audio.CatalogLoad((_track(),), "fresh-cache")
    app._play_music_source = lambda *_args, **_kwargs: False
    with mock.patch.object(appmod, "run_in_thread", _inline), \
         mock.patch.object(tabletop_audio, "load_catalog", return_value=catalog), \
         mock.patch.object(openai_client, "music_search_terms", return_value=((), ())):
        asyncio.run(app._music_flow())
    menus = [screen for screen in app.screens if isinstance(screen, ListModal)]
    assert menus[0]._title.startswith("MUSIC ·")
    assert any(menu._title.startswith("TABLETOP AUDIO · CHOOSE") for menu in menus)
    assert any("ENCOUNTER SUGGESTIONS" in menu._title for menu in menus)
    assert menus[-1]._title.startswith("MUSIC ·")


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
    app = _FlowApp(["battle", "tta:crypt"])
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
    assert source.referrer == tabletop_audio.CATALOG_URL
    assert attribution == "Tabletop Audio · CC BY-NC-ND 4.0"
    menu = next(screen for screen in app.screens if isinstance(screen, ListModal) and "ENCOUNTER SUGGESTIONS" in screen._title)
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
