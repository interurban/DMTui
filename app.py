"""Battle Tracker — a terminal combat tracker for D&D 5e DMs.

A demo TUI inspired by modern VTT encounter builders. One screen shows the
whole battle at once: a token map on top (mirror your physical board), the
initiative order, and a detail card for the selected creature. Health bars,
condition chips, damage/heal/condition/monster actions are all simulated but
the interaction is real.

Run:  .venv/bin/python app.py
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import random
import re

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.widgets import Header, Input, Static
from rich.markup import escape
from rich.text import Text

from battle import (
    CONDITIONS,
    DEATH_LINES,
    HEAL_LINES,
    DAMAGE_LINES,
    MONSTERS,
    MAP_COLS,
    MAP_ROWS,
    Combatant,
    coord_name,
    encounter_monster,
    find_free_spot,
    resolve_attack,
    roll_dice,
    short_label,
)
import ddb
import openai_client
from ddb import ABILITY_NAMES
from modals import HelpModal, ImportingModal, ListModal, MonsterLibrary, NumberModal, SpellBrowser, TextModal
import srd as srd_client
from widgets import CombatantRow, InitiativeList, LEFT_W, LogView, MapGrid
from dm_screen import panel_text

SAVE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "encounter.json")
CAMPAIGN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "campaigns.json")

DEFAULT_CAMPAIGN = "My Campaign"
DEFAULT_RULESET = "2014"
DEFAULT_CHARACTER_IDS = [112516506, 90060479, 91566422, 90060446]


def _parse_coord(s: str) -> tuple[int, int] | None:
    """Parse an Excel-style map coordinate like 'B3' or 'AA1' -> (x, y)."""
    s = s.strip().upper()
    i = 0
    while i < len(s) and s[i].isalpha():
        i += 1
    if i == 0 or not s[i:].isdigit():
        return None
    x = 0
    for ch in s[:i]:
        x = x * 26 + (ord(ch) - ord("A") + 1)
    return (x - 1, int(s[i:]) - 1)

LOG_COLORS = {
    "info": "#c9d3e0",
    "warn": "#d95841",
    "damage": "#e05a5a",
    "death": "#ff5a5a",
    "heal": "#3fae6a",
    "condition": "#d9a441",
    "turn": "#4db6e2",
    "monster": "#e89a4f",
    "import": "#a8d0ff",
    "move": "#7d8794",
    "select": "#8a93a3",
    "remove": "#b39ddb",
    "dm": "#c678dd",
}


def hint(key: str, word: str) -> str:
    """Render a command hint: the keybind letter highlighted inside the word
    where it appears, otherwise the key shown before the word."""
    if len(key) == 1 and key.isalpha():
        i = word.lower().find(key.lower())
        if i >= 0:
            return f"{word[:i]}[bold #e6ebf2]{word[i]}[/][dim]{word[i + 1:]}[/]"
    return f"[bold #e6ebf2]{key}[/] [dim]{word}[/]"


class BattleApp(App[None]):
    TITLE = "⚔  THE OLD TOLL ROAD"
    SUB_TITLE = "Round 1 — ambush in progress"
    CSS_PATH = None

    CSS = """
    Screen { background: #10131a; }

    Header { background: #1d2330; color: #e6ebf2; }

    VerticalScroll {
        scrollbar-color: #31415c;
        scrollbar-background: #10131a;
    }

    #grid {
        layout: grid;
        grid-size: 2 2;
        grid-gutter: 1;
        height: 1fr;
        margin: 1 2 0 2;
    }
    #map-panel,
    #initiative-panel,
    #log-panel,
    #detail-panel {
        width: 100%;
        height: 100%;
        padding: 0 1;
        background: #15181f;
        border: round #2a3446;
    }
    #map-title,
    #init-title,
    #log-title,
    #detail-title {
        background: #1d2330;
        color: #e6ebf2;
        text-style: bold;
        padding: 0 2;
        height: 1;
        margin: 0 -1;
    }
    #map { height: 1fr; }
    #map-status { height: 1; color: #8a93a3; }
    #initiative { height: 1fr; width: 100%; }
    #init-reference { height: 1fr; width: 100%; padding: 1 0; }
    #init-status,
    #log-status,
    #detail-status {
        height: 1;
        color: #8a93a3;
        padding: 0 1;
    }
    CombatantRow { height: 1; width: 100%; }
    #log { height: 1fr; width: 100%; }
    #log-content { width: 100%; }
    #detail-scroll { height: 1fr; width: 100%; }
    #detail { width: 100%; padding: 0 1; }

    #message {
        height: 3;
        margin: 1 2 0 2;
        padding: 0 2;
        background: #1d2330;
        border: round #2a3446;
        color: #c9d3e0;
    }
    #message-hints { width: 100%; }
    #chat-input {
        width: 100%;
        height: 1;
        margin: 0;
        padding: 0 1;
        background: #1d2330;
        border: none;
        color: #e6ebf2;
    }

    ModalScreen { align: center middle; background: rgba(8, 10, 14, 0.75); }
    .modal-title { text-style: bold; color: #e6ebf2; margin-bottom: 1; }
    .modal-box { width: 57; max-width: 92%; height: auto; border: thick #4a5b7a; background: #1b2029; padding: 1 2; }
    .library-box { width: 92%; max-width: 120; height: 92%; }
    #lib-list { height: 1fr; border: round #2a3446; margin-top: 1; }
    #modal-list { height: 15; border: round #2a3446; margin-top: 1; }
    .modal-item { padding: 0 1; color: #c9d3e0; }
    ListView:focus .modal-item { background: #2f3f5c; color: #ffffff; }
    .modal-hint { margin-top: 1; color: #8a93a3; }
    .modal-help { margin: 0 0 1 0; }
    Input { margin-top: 1; }
    """

    BINDINGS = [
        Binding("f1", "combat_view", "Combat"),
        Binding("f2", "dm_screen", "DM Screen"),
        Binding("ctrl+1", "combat_view", "Combat"),
        Binding("ctrl+2", "dm_screen", "DM Screen"),
        Binding("ctrl+tab", "toggle_view", "Toggle view"),
        Binding("up, k", "arrow_up", "Select"),
        Binding("down, j", "arrow_down", "Select"),
        Binding("left", "arrow_left", "-HP"),
        Binding("right", "arrow_right", "+HP"),
        Binding("g", "grab", "Grab"),
        Binding("n", "next_turn", "Next turn"),
        Binding("enter", "attack", "Attack"),
        Binding("r", "roll_monster_init", "Monster init"),
        Binding("shift+r", "reset", "Reset"),
        Binding("t", "set_init", "Set init"),
        Binding("shift+i", "initiative_pass", "Initiative pass"),
        Binding("plus", "duplicate", "Duplicate"),
        Binding("d", "damage", "Damage"),
        Binding("h", "heal", "Heal"),
        Binding("a", "attack", "Attack"),
        Binding("0", "hp_digit(0)", "0"),
        Binding("1", "hp_digit(1)", "1"),
        Binding("2", "hp_digit(2)", "2"),
        Binding("3", "hp_digit(3)", "3"),
        Binding("4", "hp_digit(4)", "4"),
        Binding("5", "hp_digit(5)", "5"),
        Binding("6", "hp_digit(6)", "6"),
        Binding("7", "hp_digit(7)", "7"),
        Binding("8", "hp_digit(8)", "8"),
        Binding("9", "hp_digit(9)", "9"),
        Binding("backspace", "hp_backspace", "Backspace"),
        Binding("c", "condition", "Condition"),
        Binding("C", "campaign", "Campaign"),
        Binding("m", "monster", "Quick monster"),
        Binding("b", "browse", "Monster library"),
        Binding("shift+m", "browse", "Monster library"),
        Binding("v", "spell", "Spellbook"),
        Binding("i", "import_pc", "Import PC"),
        Binding("f", "find", "Find"),
        Binding("e", "edit", "Edit"),
        Binding("p", "add_pc", "Add PC"),
        Binding("ctrl+n", "new_encounter", "New encounter"),
        Binding("x", "remove", "Remove"),
        Binding("question_mark", "help", "Help"),
        Binding("escape", "release", "Drop"),
        Binding("u", "undo", "Undo"),
        Binding("shift+u", "redo", "Redo"),
        Binding("s", "save", "Save"),
        Binding("l", "load", "Load"),
        Binding("ctrl+p", "command_palette", "Palette"),
        Binding("q", "quit", "Quit"),
        Binding("slash", "chat", "Chat"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.combatants: list[Combatant] = []
        self._rows: dict[int, CombatantRow] = {}
        self._turn: Combatant | None = None
        self._sel: Combatant | None = None
        self._moving = False
        self.round = 1
        self._messages: list[tuple[str, str, bool]] = []
        self._log_view: LogView | None = None
        self._rng = random.Random()
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self._hp_entry: str | None = None
        self._hp_sign: int = 1
        self._init_entry: str | None = None
        self._chat_mode = False
        self._chat_busy = False
        self._chat_frame = 0
        self._chat_timer = None
        self._library_screen: MonsterLibrary | None = None
        self._spell_screen: SpellBrowser | None = None
        self.view_mode = "combat"
        self._initiative_pass = False
        self._setup()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Keep the reference screen glanceable and mutation-free."""
        if self.view_mode == "dm_screen" and action not in {
            "combat_view", "dm_screen", "toggle_view", "chat", "help", "quit", "release",
        }:
            return False
        return True

    # -- lifecycle ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="grid"):
            with Container(id="map-panel"):
                yield Static("", id="map-title")
                yield MapGrid("", id="map")
                yield Static("", id="map-status")
            with Container(id="initiative-panel"):
                with InitiativeList(id="initiative"):
                    yield Static("INITIATIVE ORDER", id="init-title")
                    yield Static("", id="init-reference")
                    for c in self.combatants:
                        row = CombatantRow(c)
                        self._rows[id(c)] = row
                        yield row
                yield Static("", id="init-status")
            with Container(id="log-panel"):
                yield Static("BATTLE LOG", id="log-title")
                self._log_view = LogView(id="log")
                with self._log_view:
                    yield Static("", id="log-content")
                yield Static("", id="log-status")
            with Container(id="detail-panel"):
                yield Static("COMBATANT", id="detail-title")
                with VerticalScroll(id="detail-scroll"):
                    yield Static("", id="detail")
                yield Static("", id="detail-status")
        with Container(id="message"):
            yield Static("", id="message-hints")
            yield Input(placeholder="Ask the DM assistant…", id="chat-input")

    def on_mount(self) -> None:
        self._refresh_all()
        self.call_after_refresh(self._refresh_all)
        self.call_after_refresh(self._scroll_to_selected)
        self.run_worker(self._boot_campaign())

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "chat-input" or not self._chat_mode or self._chat_busy:
            return
        question = event.value.strip()
        if not question:
            self._exit_chat_mode()
            return
        if self._local_chat_command(question):
            event.input.value = ""
            self._exit_chat_mode()
            return
        self._chat_busy = True
        self._chat_frame = 0
        event.input.value = ""
        self._refresh_message()
        self._chat_timer = self.set_interval(0.12, self._tick_chat_animation)
        self.run_worker(self._answer_chat(question))

    def _setup(self) -> None:
        self.combatants = []
        self.round = 1
        self._turn = None
        self._sel = None
        self._moving = False
        self._messages = []
        self.view_mode = "combat"
        self._initiative_pass = False

    def _refresh_message(self) -> None:
        hints = self.query_one("#message-hints", Static)
        chat_input = self.query_one("#chat-input", Input)
        hints.display = not self._chat_mode
        chat_input.display = self._chat_mode
        if not self._chat_mode:
            if self.view_mode == "dm_screen":
                hints.update("  ·  ".join([hint("f1", "combat"), hint("f2", "DM screen"), hint("ctrl+tab", "toggle"), hint("/", "lookup"), hint("?", "help"), hint("q", "quit")]))
            else:
                hints.update(
                    "  ·  ".join(
                        [hint("i", "import"), hint("f", "find"), hint("ctrl+p", "palette"), hint("/", "chat"), hint("?", "help"), hint("q", "quit")]
                    )
                )
        elif self._chat_busy:
            frames = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
            chat_input.placeholder = f"{frames[self._chat_frame]} Thinking…"

    def _tick_chat_animation(self) -> None:
        if self._chat_busy:
            self._chat_frame = (self._chat_frame + 1) % 10
            self._refresh_message()

    def action_chat(self) -> None:
        if self._chat_busy:
            return
        self._chat_mode = True
        self._refresh_message()
        self.query_one("#chat-input", Input).focus()

    def action_combat_view(self) -> None:
        self.view_mode = "combat"
        self._refresh_all()

    def action_dm_screen(self) -> None:
        self._initiative_pass = False
        self._init_entry = None
        self._hp_entry = None
        self.view_mode = "dm_screen"
        self._refresh_all()

    def action_toggle_view(self) -> None:
        if self.view_mode == "dm_screen":
            self.action_combat_view()
        else:
            self.action_dm_screen()

    def _exit_chat_mode(self) -> None:
        if self._chat_timer is not None:
            self._chat_timer.stop()
            self._chat_timer = None
        self._chat_mode = False
        self._chat_busy = False
        self._refresh_message()

    def _local_chat_command(self, question: str) -> bool:
        match = re.fullmatch(r"/(?:r|roll)\s+(.+)", question, re.IGNORECASE)
        if not match:
            return False
        try:
            total, rolls, bonus = roll_dice(match.group(1), self._rng)
        except ValueError as exc:
            self._log(f"ROLL ERROR: {exc}", kind="warn")
            return True
        bonus_text = f" {bonus:+d}" if bonus else ""
        self._log(f"ROLL {match.group(1)} → {total} ({', '.join(map(str, rolls))}{bonus_text})", kind="turn")
        return True

    def _chat_context(self, question: str = "") -> str:
        rows = []
        if self._sel is not None:
            c = self._sel
            conditions = ", ".join(sorted(c.conditions)) or "none"
            init = "--" if c.init is None else str(c.init)
            rows.append(f"Selected: {c.name}: {c.hp}/{c.max_hp} HP, AC {c.ac}, init {init}, conditions {conditions}")
        recent = [
            text for text, kind, in_log in self._messages
            if in_log and kind not in {"select", "dm"} and not text.startswith(("CHAT >", "DM:"))
        ][-3:]
        context = (
            f"Ruleset: {self._campaign_ruleset()}\n"
            f"Round {self.round}; turn: {self._turn.name if self._turn else 'none'}\n"
            + "\n".join(rows)
        )
        if recent:
            context += "\nRecent log:\n" + "\n".join(recent)
        normalized = question.casefold()
        if normalized:
            spells = srd_client.load_cache("spells") or []
            matches = [
                s for s in spells
                if isinstance(s, dict)
                and re.search(rf"(?<!\w){re.escape(str(s.get('name', '')).casefold())}(?!\w)", normalized)
            ]
            if matches:
                spell = min(matches, key=lambda item: len(str(item.get("name", ""))))
                context += (
                    "\nMatched SRD spell:\n"
                    f"{spell.get('name')}: level {spell.get('level')}, "
                    f"casting {spell.get('casting_time')}, range {spell.get('range')}, "
                    f"duration {spell.get('duration')}\n{spell.get('desc', '')[:1200]}"
                )
        return context

    async def _answer_chat(self, question: str) -> None:
        self._log(f"CHAT > {escape(question)}", kind="select")
        try:
            answer = await asyncio.to_thread(openai_client.chat, question, self._chat_context(question))
        except Exception as exc:
            self._log(f"CHAT ERROR: {escape(str(exc))}", kind="warn")
        else:
            self._log(f"DM: {escape(answer)}", kind="dm")
        finally:
            self._exit_chat_mode()

    # -- campaigns -----------------------------------------------------------

    def _campaigns_read(self) -> dict:
        try:
            with open(CAMPAIGN_PATH) as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("campaigns"), dict):
                return data
        except (OSError, ValueError):
            pass
        data = {
            "active": DEFAULT_CAMPAIGN,
            "campaigns": {
                DEFAULT_CAMPAIGN: {
                    "character_ids": list(DEFAULT_CHARACTER_IDS),
                    "ruleset": DEFAULT_RULESET,
                }
            },
        }
        try:
            self._campaigns_write(data)
        except OSError:
            pass
        return data

    def _campaigns_write(self, data: dict) -> None:
        with open(CAMPAIGN_PATH, "w") as f:
            json.dump(data, f, indent=2)

    def _campaign_ids(self, name: str, data: dict) -> list[int]:
        camp = data.get("campaigns", {}).get(name)
        if not isinstance(camp, dict):
            return []
        ids = camp.get("character_ids") or []
        return [int(x) for x in ids if isinstance(x, int) or str(x).isdigit()]

    def _campaign_ruleset(self) -> str:
        data = self._campaigns_read()
        active = data.get("active") or DEFAULT_CAMPAIGN
        campaign = data.get("campaigns", {}).get(active, {})
        if isinstance(campaign, dict):
            return str(campaign.get("ruleset") or DEFAULT_RULESET)
        return DEFAULT_RULESET

    def _set_active_campaign(self, name: str) -> None:
        try:
            data = self._campaigns_read()
            if name in data.get("campaigns", {}):
                data["active"] = name
                self._campaigns_write(data)
        except OSError:
            pass

    async def _fetch_combatant(self, cid: int) -> Combatant | None:
        """Fetch and parse a D&D Beyond character; None when it can't be read."""
        data = await asyncio.to_thread(ddb.fetch_character_data, cid)
        pc = ddb.extract_combatant(cid, data)
        if pc.name == f"Char {cid}":
            return None
        pc.ddb_id = cid
        return pc

    def _placeholder_pc(self, cid: int) -> Combatant:
        return Combatant(
            name=f"Char {cid}", kind="PC", hp=10, max_hp=10, ac=10, init_mod=0,
            role="Unimported",
            note="D&D Beyond access denied — set this character to Public, then retry the import.",
            x=0, y=0, stats={i: 10 for i in range(1, 7)}, ddb_id=cid,
        )

    def _place_pc(self, pc: Combatant) -> bool:
        """Place a PC as close to the map centre as possible, spiralling
        outward so a loaded party spreads out from the middle."""
        occupied = {(c.x, c.y) for c in self.combatants}
        cx, cy = MAP_COLS // 2, MAP_ROWS // 2
        cells = sorted(
            ((x, y) for y in range(MAP_ROWS) for x in range(MAP_COLS)),
            key=lambda xy: ((xy[0] - cx) ** 2 + (xy[1] - cy) ** 2, xy[1], xy[0]),
        )
        for x, y in cells:
            if (x, y) not in occupied:
                pc.x, pc.y = x, y
                return True
        return False

    async def _import_campaign(self, name: str) -> int:
        ids = self._campaign_ids(name, self._campaigns_read())
        modal = ImportingModal()
        self.push_screen(modal)
        placed = 0
        try:
            for cid in ids:
                import_error = None
                try:
                    pc = await self._fetch_combatant(cid)
                except Exception as exc:
                    pc = None
                    import_error = str(exc)
                if pc is None:
                    pc = self._placeholder_pc(cid)
                    if import_error:
                        self._log(f"Character {cid} not imported: {import_error}", kind="warn")
                if not self._place_pc(pc):
                    break
                self.combatants.append(pc)
                placed += 1
        finally:
            modal.dismiss()
        self._set_active_campaign(name)
        return placed

    async def _wait_map_ready(self) -> None:
        """Wait until the map grid has a real size so centred placement lands
        on the visible grid, not the pre-layout default."""
        for _ in range(100):
            grid = self.query_one("#map", MapGrid)
            if grid.size.width > 8 and grid.size.height > 4:
                self._refresh_map()
                return
            await asyncio.sleep(0.02)

    async def _boot_campaign(self) -> None:
        await self._wait_map_ready()
        data = self._campaigns_read()
        name = data.get("active") or DEFAULT_CAMPAIGN
        placed = await self._import_campaign(name)
        self.round = 1
        self._turn = self.combatants[0] if self.combatants else None
        self._sel = self.combatants[0] if self.combatants else None
        self._sort_combatants()
        if placed:
            self._log(f"Campaign '{name}' loaded — {placed} PC{'s' if placed != 1 else ''} at the ready.", kind="import")
        else:
            self._log(f"Campaign '{name}' has no characters yet — press [bold]p[/] to add or [bold]i[/] to import.", kind="info")

    def action_campaign(self) -> None:
        self.run_worker(self._campaign_flow())

    async def _campaign_flow(self) -> None:
        data = self._campaigns_read()
        active = data.get("active")
        options = []
        for name, camp in sorted(data.get("campaigns", {}).items(), key=lambda kv: (kv[0] != active, kv[0])):
            n = len(camp.get("character_ids", [])) if isinstance(camp, dict) else 0
            mark = "  [green]✓[/]" if name == active else ""
            options.append((f"load:{name}", f"[bold #a8d0ff]LOAD[/] {name}{mark}  [dim]({n} PC{'s' if n != 1 else ''})[/]"))
        options.append(("save", "Save current party as a new campaign"))
        options.append(("blank", "[bold #d95841]Start a blank encounter[/]"))
        picked = await self.push_screen(ListModal("CAMPAIGNS", options), wait_for_dismiss=True)
        if not picked:
            return
        if picked.startswith("load:"):
            await self._load_campaign_flow(picked[5:])
        elif picked == "save":
            await self._save_campaign_flow()
        elif picked == "blank":
            self.action_new_encounter()

    async def _load_campaign_flow(self, name: str) -> None:
        self._push_undo(restore_nav=True)
        self.combatants = []
        self._moving = False
        placed = await self._import_campaign(name)
        self.round = 1
        self._turn = self.combatants[0] if self.combatants else None
        self._sel = self.combatants[0] if self.combatants else None
        self._sort_combatants()
        self._log(f"Campaign '{name}' loaded — {placed} PC{'s' if placed != 1 else ''}.", kind="import")
        self._rebuild_rows()

    async def _save_campaign_flow(self) -> None:
        name = await self.push_screen(
            TextModal("SAVE CAMPAIGN", "campaign name (e.g. My Campaign)", confirm="Save"),
            wait_for_dismiss=True,
        )
        if not name:
            return
        ids = [c.ddb_id for c in self.combatants if c.ddb_id]
        data = self._campaigns_read()
        data.setdefault("campaigns", {})
        data["campaigns"][name] = {"character_ids": ids, "ruleset": self._campaign_ruleset()}
        data["active"] = name
        self._campaigns_write(data)
        self._log(f"Campaign '{name}' saved — {len(ids)} character{'s' if len(ids) != 1 else ''}.", kind="import")

    # -- undo / redo / persistence ------------------------------------------

    def _combatant_snap(self, c: Combatant) -> dict:
        return {
            "name": c.name, "kind": c.kind, "hp": c.hp, "max_hp": c.max_hp, "ac": c.ac,
            "init": c.init, "init_mod": c.init_mod, "conditions": sorted(c.conditions),
            "role": c.role, "note": c.note, "x": c.x, "y": c.y,
            "stats": dict(c.stats), "saves": sorted(c.saves), "speed": c.speed,
            "proficiency": c.proficiency, "hit_dice": c.hit_dice, "skills": dict(c.skills),
            "passive_perception": c.passive_perception, "attacks": list(c.attacks),
            "traits": list(c.traits), "spells": list(c.spells), "ddb_id": c.ddb_id,
            "reminder": c.reminder,
        }

    def _snapshot(self) -> dict:
        return {
            "version": 1,
            "combatants": [self._combatant_snap(c) for c in self.combatants],
            "round": self.round,
            "turn": self.combatants.index(self._turn) if self._turn is not None else None,
            "sel": self.combatants.index(self._sel) if self._sel is not None else None,
            "moving": self._moving,
            "view_mode": self.view_mode,
        }

    def _push_undo(self, restore_nav: bool = False) -> None:
        snap = self._snapshot()
        snap["restore_nav"] = restore_nav
        self._undo.append(snap)
        if len(self._undo) > 50:
            self._undo.pop(0)
        self._redo.clear()

    def _restore(self, snap: dict, keep_nav: bool = True) -> None:
        new_combatants = []
        for s in snap.get("combatants", []):
            s = dict(s)
            stats = s.get("stats") or {}
            s["stats"] = {int(k): v for k, v in stats.items()}
            c = Combatant(**s)
            c.conditions = set(s.get("conditions", []))
            c.saves = set(s.get("saves", []))
            if not c.stats:
                # backfill so a hand-edited save never yields a None mod (detail card crash)
                c.stats = {i: 10 for i in range(1, 7)}
            new_combatants.append(c)
        n = len(new_combatants)
        # coerce every field that feeds the mutation below BEFORE touching
        # self.combatants, so a corrupt save fails atomically instead of
        # leaving us half-restored (round swap done, nav stale, save bricked)
        try:
            round_val = int(snap.get("round", 1))
        except (TypeError, ValueError):
            round_val = 1
        sel_i = snap.get("sel")
        turn_i = snap.get("turn")
        self.combatants = new_combatants
        self._sel = new_combatants[sel_i] if n and isinstance(sel_i, int) and 0 <= sel_i < n else None
        if keep_nav:
            # undo/redo revert combatant state, NOT navigation: keep the current
            # round and re-map the current turn by name so we don't rewind time
            cur_name = self._turn.name if self._turn is not None else None
            self._turn = next(
                (c for c in new_combatants if c.name == cur_name),
                self._sel or (new_combatants[0] if n else None),
            )
            self._moving = bool(snap.get("moving", False))
        else:
            self.round = round_val
            self.view_mode = snap.get("view_mode", "combat") if snap.get("view_mode") in {"combat", "dm_screen"} else "combat"
            self._turn = (
                new_combatants[turn_i]
                if n and isinstance(turn_i, int) and 0 <= turn_i < n
                else self._sel or (new_combatants[0] if n else None)
            )
            self._moving = False
        self._rebuild_rows()

    def action_undo(self) -> None:
        if not self._undo:
            self._log("Nothing to undo.", kind="warn")
            return
        snap = self._undo.pop()
        cur = self._snapshot()
        cur["restore_nav"] = snap.get("restore_nav", False)
        self._redo.append(cur)
        self._restore(snap, keep_nav=not snap.get("restore_nav", False))
        self._log("Undid last change.", kind="select")

    def action_redo(self) -> None:
        if not self._redo:
            self._log("Nothing to redo.", kind="warn")
            return
        snap = self._redo.pop()
        cur = self._snapshot()
        cur["restore_nav"] = snap.get("restore_nav", False)
        self._undo.append(cur)
        self._restore(snap, keep_nav=not snap.get("restore_nav", False))
        self._log("Redid change.", kind="select")

    def action_save(self) -> None:
        try:
            with open(SAVE_PATH, "w") as f:
                json.dump(self._snapshot(), f, indent=2)
        except OSError as exc:
            self._log(f"Save failed: {exc}", kind="warn")
            return
        self._log(f"Encounter saved to {SAVE_PATH}.", kind="import")

    def action_load(self) -> None:
        try:
            with open(SAVE_PATH) as f:
                snap = json.load(f)
        except OSError as exc:
            self._log(f"No saved encounter ({exc}).", kind="warn")
            return
        except (ValueError, TypeError) as exc:
            self._log(f"Save file corrupt: {exc}", kind="warn")
            return
        if not isinstance(snap, dict) or not isinstance(snap.get("combatants"), list):
            self._log("Save file corrupt: expected an encounter snapshot.", kind="warn")
            return
        before = self._snapshot()
        try:
            self._restore(snap, keep_nav=False)
        except (TypeError, ValueError, KeyError) as exc:
            self._log(f"Save file corrupt: {exc}", kind="warn")
            return
        before["restore_nav"] = True
        self._undo.append(before)
        if len(self._undo) > 50:
            self._undo.pop(0)
        self._redo.clear()
        self._log(f"Loaded encounter — {len(self.combatants)} creatures, round {self.round}.", kind="import")

    # -- rows & refresh ----------------------------------------------------

    def _rebuild_rows(self) -> None:
        sc = self.query_one("#initiative", InitiativeList)
        for child in list(sc.children):
            if isinstance(child, CombatantRow):
                child.remove()
        self._rows = {}
        for c in self.combatants:
            row = CombatantRow(c)
            self._rows[id(c)] = row
            sc.mount(row)
        self._refresh_all()
        self.call_after_refresh(self._scroll_to_selected)

    def _refresh_rows(self) -> None:
        self.query_one("#init-title", Static).update(
            "INITIATIVE ORDER" if self.view_mode == "combat" else "CONDITIONS"
        )
        reference = self.query_one("#init-reference", Static)
        reference.display = self.view_mode == "dm_screen"
        if self.view_mode == "dm_screen":
            reference.update(panel_text("conditions"))
        for row in self._rows.values():
            row.display = self.view_mode == "combat"
            row.current = row.combatant is self._turn
            row.selected = row.combatant is self._sel
            row.refresh()

    def _scroll_to_selected(self) -> None:
        sc = self.query_one("#initiative", InitiativeList)
        row = self._rows.get(id(self._sel))
        if row is not None:
            sc.scroll_to_widget(row, animate=False)

    def _refresh_all(self) -> None:
        self._refresh_rows()
        self._refresh_map()
        self._refresh_detail()
        self._refresh_log()
        for status_id in ("#map-status", "#init-status", "#log-status", "#detail-status"):
            self.query_one(status_id, Static).display = self.view_mode == "combat"
        self.query_one("#init-status", Static).update(self._init_status_text())
        self.query_one("#log-status", Static).update(self._log_status_text())
        self.query_one("#detail-status", Static).update(self._detail_status_text())
        self._refresh_message()
        turn = self._turn
        self.sub_title = (
            f"Round {self.round} · {turn.name if turn else '—'} to act"
            if self.view_mode == "combat" else "DM Screen · quick reference"
        )

    def _refresh_map(self) -> None:
        global MAP_COLS, MAP_ROWS
        grid = self.query_one("#map", MapGrid)
        if self.view_mode == "dm_screen":
            grid.update(panel_text("actions"))
            self.query_one("#map-title", Static).update("COMMON ACTIONS")
            self.query_one("#map-status", Static).update("F1 / Ctrl+1 combat  ·  F2 / Ctrl+2 DM Screen  ·  / lookup  ·  ? help")
            return
        avail_w = max(1, grid.size.width - LEFT_W)
        cell_w = 4 if avail_w >= 20 else 3
        MAP_COLS = min(30, max(5, avail_w // cell_w))
        # the map renders a header line + MAP_ROWS data lines, so the grid must
        # hold one more line than the row count (off-by-one: last row was clipped)
        MAP_ROWS = min(40, max(1, grid.size.height - 1))
        grid.cell_w = cell_w
        grid.update(self._map_text(cell_w))
        self.query_one("#map-title", Static).update(self._map_title_text())
        self.query_one("#map-status", Static).update(self._map_status_text())

    def _refresh_detail(self) -> None:
        detail = self.query_one("#detail", Static)
        self.query_one("#detail-title", Static).update(
            "COMBATANT" if self.view_mode == "combat" else "DCs / ROLLS"
        )
        if self.view_mode == "dm_screen":
            detail.update(panel_text("rolls"))
            return
        detail.update(self._detail_markup())

    def _detail_markup(self) -> str:
        c = self._sel
        if c is None:
            return "[dim]No combatant selected.[/]"
        kind = "PC" if c.kind == "PC" else "Monster"
        name_col = "#a8d0ff" if c.kind == "PC" else "#ff9d9d"
        frac = c.hp_frac
        bcol = "#3fae6a" if frac > 0.5 else ("#d9a441" if frac > 0.25 else "#d95841")
        fill = round(frac * 18)
        bar = "█" * fill + "░" * (18 - fill)
        status = ("[bold #d95841]DOWN[/]" if not c.alive else "[bold #3fae6a]UP[/]")
        if c.bloodied:
            status += "  [bold #d9a441]BLOODIED[/]"
        hd = f"  ·  HD [bold]{c.hit_dice}[/]" if c.hit_dice else ""
        lines = [
            f"[bold {name_col}]{c.name}[/]  [dim]{c.role} · {kind}[/]",
            f"[bold]HP[/]  [bold {bcol}]{c.hp}[/] / {c.max_hp}  [{bcol}]{bar}[/]{hd}",
        ]

        vitals = [f"[bold]AC[/] [bold #c9a227]{c.ac}[/]"]
        if c.speed is not None:
            vitals.append(f"[bold]SPD[/] {c.speed}")
        init_s = "--" if c.init is None else f"[bold #e0c04c]{c.init}[/]"
        vitals.append(f"[bold]INIT[/] {init_s}")
        if c.proficiency is not None:
            vitals.append(f"[bold]PROF[/] +{c.proficiency}")
        if c.passive_perception is not None:
            vitals.append(f"[bold]PP[/] [bold #6aa6d9]{c.passive_perception}[/]")
        vitals.append(f"[bold]STATUS[/] {status}")
        lines.append("  ".join(vitals))
        lines.append("")

        if c.stats:
            for r in range(2):
                parts = []
                for a in (r * 3 + 1, r * 3 + 2, r * 3 + 3):
                    m = c.mod(a)
                    m_s = f"[bold]({m:+d})[/]" if m is not None else "(—)"
                    parts.append(f"[bold]{ABILITY_NAMES[a - 1]}[/] {c.stats.get(a, '—')} {m_s}")
                lines.append("  ".join(parts))

        if c.saves:
            parts = []
            for a in sorted(c.saves):
                sv = c.save(a)
                parts.append(f"[bold]{ABILITY_NAMES[a - 1]}[/] {sv:+d}" if sv is not None else f"[bold]{ABILITY_NAMES[a - 1]}[/] (—)")
            lines.append(f"[bold]SAVES[/]  {'  '.join(parts)}")
        if c.skills:
            sk = "  ".join(f"[bold]{k.capitalize()}[/] {v:+d}" for k, v in sorted(c.skills.items()))
            lines.append(sk)
            lines.append("")
        if c.attacks:
            for atk in c.attacks:
                lines.append(f"[bold #e89a4f]⚔[/] {atk}")
        if c.spells:
            for sp in c.spells:
                lines.append(f"[bold #e0c04c]✦[/] {sp}")
        if c.traits:
            for tr in c.traits:
                lines.append(f"[bold #c678dd]◆[/] {tr}")
        if c.conditions:
            conds = "  ".join(f"[{CONDITIONS[cn]['color']}]{CONDITIONS[cn]['glyph']} {cn}[/]" for cn in sorted(c.conditions))
            lines.append(f"[bold]CONDITIONS[/]  {conds}")
        if c.note:
            lines.append("")
            lines.append(f"[dim]{c.note}[/]")
        if c.reminder:
            lines.append("")
            lines.append(f"[bold #e0c04c]REMINDER[/] {c.reminder}")
        return "\n".join(lines)

    def _refresh_log(self) -> None:
        content = self.query_one("#log-content", Static)
        self.query_one("#log-title", Static).update(
            "BATTLE LOG" if self.view_mode == "combat" else "COMBAT QUICK RULES"
        )
        if self.view_mode == "dm_screen":
            content.update(panel_text("combat"))
            return
        content.update(self._log_text())
        if self._log_view is not None:
            self._log_view.scroll_home(animate=False)

    def _log_text(self) -> str:
        lines = [
            f"[{LOG_COLORS.get(kind, '#c9d3e0')}]{text}[/]"
            for text, kind, in_log in reversed(self._messages)
            if in_log
        ]
        if not lines:
            return "[dim]— nothing recorded yet —[/]"
        return "\n".join(lines)

    def _log(self, text: str, kind: str = "info", in_log: bool = True) -> None:
        self._messages.append((text, kind, in_log))
        if len(self._messages) > 200:
            self._messages.pop(0)
        self._refresh_log()

    # -- battle map ----------------------------------------------------------

    def _map_title_text(self) -> str:
        turn = self._turn
        turn_s = f"{turn.name} @ {coord_name(turn.x, turn.y)}" if turn else "—"
        return f"BATTLE MAP  ·  R{self.round}  ·  TURN: [bold #c9a227]{turn_s}[/]"

    def _map_status_text(self) -> str:
        sel = self._sel
        if self._moving and sel:
            return f"[bold #3fae6a]MOVING {sel.name}[/] — [bold #e6ebf2]arrows[/] [dim]place[/], [bold #e6ebf2]g[/]/[bold #e6ebf2]esc[/] [dim]drop[/]"
        sel_s = f"[bold #ffffff]{sel.name}[/] @ {coord_name(sel.x, sel.y)}" if sel else "none"
        hint_text = "  ·  ".join([hint("↑↓", "select"), hint("←→", "±HP"), hint("g", "grab")])
        return f"{sel_s}   ·   {hint_text}"

    def _init_status_text(self) -> str:
        if self.view_mode == "dm_screen":
            return "F1 / Ctrl+1 combat  ·  F2 / Ctrl+2 DM Screen  ·  / lookup  ·  ? help"
        if self._init_entry is not None and self._sel is not None:
            return (
                f"[bold #e0c04c]INIT[/] [bold #e6ebf2]{self._init_entry or '--'}[/] → "
                f"[bold #ffffff]{self._sel.name}[/]   ·   "
                "[bold #e6ebf2]Enter[/] apply · [bold #e6ebf2]Esc[/] cancel"
            )
        if self._hp_entry is not None and self._sel is not None:
            label = "DAMAGE" if self._hp_sign < 0 else "HEAL"
            color = "#e05a5a" if self._hp_sign < 0 else "#3fae6a"
            entry = self._hp_entry or "?"
            return (
                f"[bold {color}]{label}[/] [bold #e6ebf2]{entry}[/] → "
                f"[bold #ffffff]{self._sel.name}[/]   ·   "
                "[bold #e6ebf2]Enter[/] apply · [bold #e6ebf2]Esc[/] cancel"
            )
        return "  ·  ".join([hint("↑↓", "select"), hint("n", "next"), hint("r", "roll init"), hint("t", "set init")])

    def _log_status_text(self) -> str:
        if self.view_mode == "dm_screen":
            return "Fixed 5e quick reference  ·  F1 / Ctrl+1 combat"
        return "  ·  ".join(
            [hint("s", "save"), hint("l", "load"), hint("u", "undo"), hint("shift+u", "redo")]
        )

    def _detail_status_text(self) -> str:
        if self.view_mode == "dm_screen":
            return "Rules lookup: /  ·  F1 / Ctrl+1 combat"
        return "  ·  ".join(
            [
                hint("a", "attack"),
                hint("d", "damage"),
                hint("h", "heal"),
                hint("c", "condition"),
                hint("e", "edit"),
                hint("x", "remove"),
                hint("m", "quick monster"),
            ]
        )

    def _map_text(self, cell_w: int) -> Text:
        tokens: dict[tuple[int, int], list] = {}
        for c in self.combatants:
            if 0 <= c.x < MAP_COLS and 0 <= c.y < MAP_ROWS:
                tokens.setdefault((c.x, c.y), []).append(c)

        text = Text()
        text.append(" " * LEFT_W, style="bold #8a93a3")
        for col in range(MAP_COLS):
            text.append(coord_name(col, 0)[:-1].ljust(cell_w), style="bold #8a93a3")
        text.append("\n")
        for y in range(MAP_ROWS):
            text.append(f"{y + 1:>2}  ", style="bold #8a93a3")
            for x in range(MAP_COLS):
                text.append(self._map_cell(x, y, tokens.get((x, y)), cell_w))
            text.append("\n")
        return text

    def _map_cell(self, x: int, y: int, occupants: list | None, cell_w: int) -> Text:
        if not occupants:
            return Text("·" + " " * (cell_w - 1), style="#2a3446")
        c = occupants[0]
        label = short_label(c.name)
        active = c is self._turn
        sel = c is self._sel
        down = not c.alive

        if active:
            token, fg, bg, bold = "▶" + label, "#16130a", "#c9a227", True
        elif down:
            token, fg, bg, bold = "✝" + label, "#5b6471", "#20242c", False
        else:
            token, fg, bg, bold = label, "#d7e9ff", "#2a4a6a", False
            if c.kind != "PC":
                fg, bg = "#ffd9d9", "#5a2f2f"

        if sel and self._moving:
            fg, bg, bold = "#ffffff", "#3f7a4f", True
        elif sel and not active:
            bg = "#3f6a96" if c.kind == "PC" else "#8a4a4a"
            bold = True

        token = token[:cell_w]
        pad = cell_w - len(token)
        if pad > 0:
            token = " " * (pad // 2) + token + " " * (pad - pad // 2)

        style = f"bold {fg} on {bg}" if bold else f"{fg} on {bg}"
        return Text(token, style=style)

    def _move_token(self, dx: int, dy: int) -> None:
        sel = self._sel
        if sel is None:
            return
        nx, ny = sel.x + dx, sel.y + dy
        if not (0 <= nx < MAP_COLS and 0 <= ny < MAP_ROWS):
            self._log(f"Cannot move {sel.name} — off the map.", kind="warn")
            return
        for c in self.combatants:
            if c is not sel and (c.x, c.y) == (nx, ny):
                self._log(f"{coord_name(nx, ny)} is held by {c.name}.", kind="warn")
                return
        self._push_undo()
        sel.x, sel.y = nx, ny
        self._refresh_all()

    def select_at(self, cx: int, cy: int) -> bool:
        if self.view_mode == "dm_screen":
            return False
        for c in self.combatants:
            if (c.x, c.y) == (cx, cy):
                self._init_entry = None
                was_moving = self._moving
                self._moving = False
                if self._sel is not c:
                    self._sel = c
                self._refresh_all()
                self._scroll_to_selected()
                return True
        return False

    # -- selection & turn ---------------------------------------------------

    @property
    def _sel_index(self) -> int:
        for i, c in enumerate(self.combatants):
            if c is self._sel:
                return i
        return 0

    def action_arrow_up(self) -> None:
        if self._moving:
            self._move_token(0, -1)
        else:
            self.action_cursor_up()

    def action_arrow_down(self) -> None:
        if self._moving:
            self._move_token(0, 1)
        else:
            self.action_cursor_down()

    def action_arrow_left(self) -> None:
        if self._moving:
            self._move_token(-1, 0)
        else:
            self.action_damage_one()

    def action_arrow_right(self) -> None:
        if self._moving:
            self._move_token(1, 0)
        else:
            self.action_heal_one()

    def action_grab(self) -> None:
        if self._sel is None:
            return
        self._moving = not self._moving
        self._refresh_all()

    def action_release(self) -> None:
        if self._init_entry is not None:
            self._init_entry = None
            self._initiative_pass = False
            self._refresh_all()
            return
        if self._hp_entry is not None:
            self._hp_entry = None
            self._refresh_all()
            return
        if self._moving and self._sel is not None:
            self._moving = False
            self._refresh_all()

    def action_cursor_up(self) -> None:
        n = len(self.combatants)
        if n == 0:
            return
        self._init_entry = None
        self._sel = self.combatants[(self._sel_index - 1) % n]
        self._refresh_all()
        self._scroll_to_selected()

    def action_cursor_down(self) -> None:
        n = len(self.combatants)
        if n == 0:
            return
        self._init_entry = None
        self._sel = self.combatants[(self._sel_index + 1) % n]
        self._refresh_all()
        self._scroll_to_selected()

    def action_next_turn(self) -> None:
        n = len(self.combatants)
        if n == 0:
            return
        if self._turn is None:
            self._turn = self.combatants[0]
        start = self.combatants.index(self._turn)
        nxt = (start + 1) % n
        scanned = 0
        while scanned < n and not self.combatants[nxt].alive:
            nxt = (nxt + 1) % n
            scanned += 1
        # if every living creature was skipped — including wrapping past the
        # current turn, or the whole list with everyone dead — the scan began
        # or returned to a new round
        if nxt <= start or scanned == n:
            self.round += 1
        self._turn = self.combatants[nxt]
        self._log(f"Turn → {self._turn.name} (round {self.round})", kind="turn")
        if self._turn.reminder:
            self._log(f"REMINDER: {self._turn.reminder}", kind="condition")
        self._refresh_all()

    # -- initiative ----------------------------------------------------------

    def _sort_combatants(self) -> None:
        """Sort by initiative (highest first); un-rolled combatants sink to the end."""
        self.combatants.sort(key=lambda c: (c.init is None, -(c.init or 0)))
        self._rebuild_rows()

    def action_roll_monster_init(self) -> None:
        monsters = [c for c in self.combatants if c.kind != "PC"]
        if not monsters:
            self._log("No monsters in the encounter to roll for.", kind="warn")
            return
        pending = [m for m in monsters if m.init is None]
        targets = pending or monsters
        if not targets:
            return
        self._push_undo()
        for m in targets:
            d20 = self._rng.randint(1, 20)
            m.init = d20 + m.init_mod
            self._log(f"{m.name} rolls {d20 + m.init_mod:>2} (d20 {d20} {m.init_mod:+d}).", kind="monster")
        self._sort_combatants()

    def action_set_init(self) -> None:
        if self._sel is None:
            return
        self._init_entry = ""
        self._hp_entry = None
        self._refresh_all()

    def action_initiative_pass(self) -> None:
        pending = [c for c in self.combatants if c.kind == "PC" and c.init is None]
        if not pending:
            self._log("All PCs already have initiative.", kind="warn")
            return
        self._initiative_pass = True
        self._sel = pending[0]
        self._init_entry = ""
        self._hp_entry = None
        self._refresh_all()

    # -- damage / heal -------------------------------------------------------

    def action_damage(self) -> None:
        if self._sel is None:
            return
        self._hp_sign = -1
        self._hp_entry = self._hp_entry or ""
        self._refresh_all()

    def action_heal(self) -> None:
        if self._sel is None:
            return
        self._hp_sign = 1
        self._hp_entry = self._hp_entry or ""
        self._refresh_all()

    def action_hp_digit(self, digit: int) -> None:
        if self._init_entry is not None and self._sel is not None:
            if len(self._init_entry) < 3:
                self._init_entry += str(digit)
                self._refresh_all()
            return
        if self._hp_entry is None and self._sel is not None and self._sel.init is None:
            self._init_entry = str(digit)
            self._refresh_all()
            return
        if self._hp_entry is None or self._sel is None:
            return
        if len(self._hp_entry) < 4:
            self._hp_entry += str(digit)
            self._refresh_all()

    def action_hp_backspace(self) -> None:
        if self._init_entry is not None:
            self._init_entry = self._init_entry[:-1]
            self._refresh_all()
            return
        if self._hp_entry is None:
            return
        self._hp_entry = self._hp_entry[:-1]
        if not self._hp_entry:
            self._hp_entry = None
        self._refresh_all()

    def _finish_hp_entry(self) -> None:
        if self._init_entry is not None and self._sel is not None:
            entry, self._init_entry = self._init_entry, None
            if not entry:
                self._refresh_all()
                return
            self._push_undo()
            self._sel.init = int(entry)
            self._log(f"{self._sel.name} set to initiative {entry}.", kind="turn")
            if self._initiative_pass:
                pending = [c for c in self.combatants if c.kind == "PC" and c.init is None]
                if pending:
                    self._sel = pending[0]
                    self._init_entry = ""
                else:
                    self._initiative_pass = False
                    self._sort_combatants()
            self._refresh_all()
            return
        if self._hp_entry is None or self._sel is None:
            return
        entry, self._hp_entry = self._hp_entry, None
        if not entry:
            self._refresh_all()
            return
        amount = self._hp_sign * int(entry)
        if amount == 0:
            self._log("Damage/heal amount must be a positive number.", kind="warn")
        else:
            self._apply_hp(self._sel, amount)

    def action_damage_one(self) -> None:
        if self._sel is not None:
            self._apply_hp(self._sel, -1)

    def action_heal_one(self) -> None:
        if self._sel is not None:
            self._apply_hp(self._sel, 1)

    def _apply_hp(self, c: Combatant, delta: int) -> None:
        if delta == 0:
            return
        was_alive = c.alive
        before = c.hp
        new_hp = max(0, min(c.max_hp, c.hp + delta))
        applied = new_hp - before
        if applied == 0:
            if delta > 0:
                self._log(f"{c.name} is already at max HP.", kind="heal")
            else:
                self._log(f"{c.name} is already down.", kind="damage")
            return
        self._push_undo()
        c.hp = new_hp
        if delta > 0:
            line = self._rng.choice(HEAL_LINES).format(name=c.name, amount=applied)
            kind = "heal"
        elif was_alive and not c.alive:
            line = self._rng.choice(DEATH_LINES).format(name=c.name)
            kind = "death"
        else:
            line = self._rng.choice(DAMAGE_LINES).format(name=c.name, amount=-applied)
            kind = "damage"
        if not c.alive and c.conditions:
            c.conditions.discard("concentrating")
        self._log(line, kind=kind)
        self._refresh_all()

    # -- attack resolution -----------------------------------------------------

    def action_attack(self) -> None:
        if self._init_entry is not None or self._hp_entry is not None:
            self._finish_hp_entry()
            return
        if self._sel is not None:
            self.run_worker(self._attack_flow())

    async def _attack_flow(self) -> None:
        c = self._sel
        if c is None:
            return
        actions = [(a, f"[bold #e89a4f]⚔[/] {a}") for a in c.attacks]
        actions += [(s, f"[bold #e0c04c]✦[/] {s}") for s in c.spells]
        if not actions:
            self._log(f"{c.name} has no attacks or spells.", kind="warn")
            return
        picked = await self.push_screen(ListModal("ATTACK WITH", actions), wait_for_dismiss=True)
        if picked is None or self._sel is not c:
            return
        alive = [t for t in self.combatants if t.alive and t is not c]
        if not alive:
            self._log("No living targets.", kind="warn")
            return
        options = [(t.name, f"{t.name}  [dim]hp {t.hp}/{t.max_hp} · ac {t.ac}[/]") for t in alive]
        target_name = await self.push_screen(ListModal("TARGET", options), wait_for_dismiss=True)
        if target_name is None:
            return
        target = next((t for t in alive if t.name == target_name), None)
        if target is None:
            return
        result = resolve_attack(c, picked, target, rng=self._rng)
        self._apply_attack_result(c, target, result)

    def _apply_attack_result(self, c: Combatant, target: Combatant, res: dict) -> None:
        if res["kind"] == "attack":
            head = f"{c.name}: {res['name']} → [bold #e6ebf2]{res['roll']}[/] vs AC {target.ac} — "
            if not res["hit"]:
                self._log(head + "[bold #8a93a3]miss[/].", kind="damage")
                return
            parts = " + ".join(str(r) for r in res["dice"])
            if res["dice_bonus"]:
                parts += f" {res['dice_bonus']:+d}"
            crit = " [bold #e0c04c]CRIT![/]" if res["crit"] else ""
            self._log(
                head + f"[bold #3fae6a]hit[/] for [bold #e05a5a]{res['damage']} damage[/] ({parts}){crit}",
                kind="damage",
            )
            if res["damage"] > 0:
                self._push_undo()
                was_alive = target.alive
                target.hp = max(0, min(target.max_hp, target.hp - res["damage"]))
                if was_alive and not target.alive:
                    target.conditions.discard("concentrating")
                    self._log(self._rng.choice(DEATH_LINES).format(name=target.name), kind="death")
            self._refresh_all()
            return
        # spell
        parts = " + ".join(str(r) for r in res["dice"])
        if res["dice_bonus"]:
            parts += f" {res['dice_bonus']:+d}"
        save_note = ""
        if res.get("save"):
            s = res["save"]
            save_note = " [dim]saved[/]" if s["saved"] else f" [dim]failed ({s['roll']} vs DC {s['dc']})[/]"
        if res.get("heal", False):
            applied = min(target.max_hp, target.hp + res["damage"]) - target.hp
            if applied <= 0:
                self._log(f"{target.name} is already at full HP.", kind="heal")
                return
            self._log(
                f"{c.name} casts {res['name']} on {target.name} — "
                f"[bold #3fae6a]{applied} HP restored[/] ({parts}).",
                kind="heal",
            )
            self._push_undo()
            target.hp += applied
            self._refresh_all()
            return
        if res["damage"]:
            self._log(
                f"{c.name} casts {res['name']} — [bold #e0c04c]{res['damage']} damage[/] "
                f"to {target.name} ({parts}).{save_note}",
                kind="monster",
            )
            self._push_undo()
            was_alive = target.alive
            target.hp = max(0, min(target.max_hp, target.hp - res["damage"]))
            if was_alive and not target.alive:
                target.conditions.discard("concentrating")
                self._log(self._rng.choice(DEATH_LINES).format(name=target.name), kind="death")
            self._refresh_all()
            return
        # control-style spell with no damage: report it, nothing to apply
        self._log(f"{c.name} casts {res['name']} on {target.name}.{save_note}", kind="monster")

    # -- find a combatant --------------------------------------------------------

    def action_find(self) -> None:
        self.run_worker(self._find_flow())

    async def _find_flow(self) -> None:
        query = await self.push_screen(
            TextModal("FIND COMBATANT", "name or @coordinate", confirm="Find"),
            wait_for_dismiss=True,
        )
        if not query or not self.combatants:
            return
        q = query.strip()
        if q.startswith("@"):
            pos = _parse_coord(q[1:])
            if pos is not None:
                x, y = pos
                target = next((m for m in self.combatants if m.x == x and m.y == y), None)
                if target is not None:
                    self._sel = target
                    self._refresh_all()
                    self._scroll_to_selected()
                    self._log(f"Found {target.name} at {coord_name(x, y)}.", kind="select")
                    return
            self._log(f"No combatant at {q.upper()} on the map.", kind="warn")
            return
        ql = q.lower()
        for m in self.combatants:
            if ql in m.name.lower() or ql in m.role.lower():
                self._sel = m
                self._refresh_all()
                self._scroll_to_selected()
                self._log(f"Found {m.name} — {coord_name(m.x, m.y)}.", kind="select")
                return
        self._log(f"No combatant matches {q!r}.", kind="warn")

    # -- import PC from D&D Beyond ---------------------------------------------

    def action_import_pc(self) -> None:
        self.run_worker(self._import_flow())

    async def _import_flow(self) -> None:
        url = await self.push_screen(
            TextModal(
                "IMPORT PC — D&D BEYOND",
                "https://www.dndbeyond.com/characters/12345678",
            ),
            wait_for_dismiss=True,
        )
        if not url:
            return
        cid = ddb.parse_ddb_url(url)
        if cid is None:
            self._log("Could not find a character id in that URL.", kind="warn")
            return
        self._log(f"Importing character {cid} from D&D Beyond…", kind="import")
        import_modal = None
        try:
            import_modal = ImportingModal()
            self.push_screen(import_modal)
            data = await asyncio.to_thread(ddb.fetch_character_data, cid)
        except Exception as exc:
            self._log(f"Import failed: {exc}", kind="warn")
            return
        finally:
            if import_modal is not None:
                import_modal.dismiss()
        pc = ddb.extract_combatant(cid, data)
        if pc.name == f"Char {cid}":
            source = data.get("character")
            if not isinstance(source, dict):
                source = data if isinstance(data, dict) else {}
            keys = ", ".join(sorted(source.keys())[:14]) if source else "none"
            self._log(
                f"Import failed: could not read character fields (response keys: {keys}). "
                "The character may be private — make it public or share it in a campaign.",
                kind="warn",
            )
            return
        pc.ddb_id = cid
        spot = find_free_spot(self.combatants, MAP_COLS, MAP_ROWS)
        if spot is None:
            self._log("Battle map is full — import skipped.", kind="warn")
            return
        pc.x, pc.y = spot
        self._push_undo()
        self.combatants.append(pc)
        self._sort_combatants()
        self._log(f"Imported {pc.name} ({pc.role}) — HP {pc.hp}/{pc.max_hp}, AC {pc.ac}.", kind="import")

    # -- conditions / monsters ------------------------------------------------

    def action_condition(self) -> None:
        if self._sel is None:
            return
        self.run_worker(self._condition_flow())

    async def _condition_flow(self) -> None:
        picked = await self.run_condition_picker()
        if picked is None or self._sel is None:
            return
        self.toggle_condition(self._sel, picked)

    async def run_condition_picker(self) -> str | None:
        if self._sel is None:
            return None
        options = []
        for name, meta in sorted(CONDITIONS.items()):
            mark = "  [green]✓[/]" if name in self._sel.conditions else ""
            label = f"{meta['glyph']}  {name}{mark}"
            options.append((name, label))
        return await self.push_screen(ListModal("TOGGLE CONDITION", options), wait_for_dismiss=True)

    def toggle_condition(self, c: Combatant, picked: str) -> None:
        self._push_undo()
        if picked in c.conditions:
            c.conditions.discard(picked)
            self._log(f"{picked} cleared on {c.name}", kind="condition")
        else:
            c.conditions.add(picked)
            self._log(f"{picked} applied to {c.name}", kind="condition")
        self._refresh_all()

    def action_monster(self) -> None:
        options = [
            (name, f"{name}   [dim]hp {m['max_hp']} · ac {m['ac']} · init {m['init']:+d}[/]")
            for name, m in sorted(MONSTERS.items())
        ]
        self.run_worker(self._monster_flow(options))

    async def _monster_flow(self, options: list[tuple[str, str]]) -> None:
        picked = await self.push_screen(ListModal("ADD MONSTER", options), wait_for_dismiss=True)
        if picked is None:
            return
        self._spawn_monster(picked)

    def action_browse(self) -> None:
        self.run_worker(self._browse_flow())

    async def _browse_flow(self) -> None:
        srd_data = srd_client.load_cache("monsters")
        if srd_data is None and not os.environ.get("VTT_OFFLINE"):
            # No cached library yet — open with the built-ins and fetch SRD in
            # the background so it populates the picker without blocking.
            self.run_worker(self._fetch_srd_worker())
        screen = MonsterLibrary(MONSTERS, srd_data or [], self._add_monster_entry, self._fetch_srd)
        self._library_screen = screen
        await self.push_screen(screen, wait_for_dismiss=True)
        self._library_screen = None

    def _add_monster_entry(self, payload: tuple[str, object]) -> str | None:
        source, data = payload
        if source == "builtin":
            return self._spawn_monster(data)
        return self._spawn_srd(data)

    def _fetch_srd(self) -> None:
        self.run_worker(self._fetch_srd_worker())

    async def _fetch_srd_worker(self) -> None:
        self._log("Fetching SRD monsters from Open5e…", kind="import")
        try:
            data = await asyncio.to_thread(srd_client.get_srd_monsters, False)
        except Exception as exc:
            self._log(f"SRD fetch failed: {exc}", kind="warn")
            return
        screen = self._library_screen
        if screen is not None:
            try:
                screen.update_srd(data)
            except Exception:
                pass
        self._log(f"Loaded {len(data)} SRD monsters from Open5e.", kind="import")

    def _number_name(self, base: str, names: set[str]) -> str:
        if base not in names:
            return base
        count = 2
        while f"{base} {count}" in names:
            count += 1
        return f"{base} {count}"

    def _add_combatant(self, c: Combatant, msg: str) -> None:
        self._push_undo()
        self.combatants.append(c)
        self._sort_combatants()
        self._log(msg, kind="monster")
        self._refresh_all()

    def _spawn_monster(self, template: str) -> str | None:
        names = {c.name for c in self.combatants}
        n = self._number_name(template, names)
        spot = find_free_spot(self.combatants, MAP_COLS, MAP_ROWS)
        if spot is None:
            self._log("Battle map is full — nothing spawned.", kind="warn")
            return None
        x, y = spot
        mob = encounter_monster(template, n, x=x, y=y)
        self._add_combatant(mob, f"{n} joins the fight at {coord_name(x, y)} — press [bold]r[/] to roll its initiative.")
        return n

    def _spawn_srd(self, fields: dict) -> str | None:
        names = {c.name for c in self.combatants}
        base = fields.get("name", "Monster")
        n = self._number_name(base, names)
        spot = find_free_spot(self.combatants, MAP_COLS, MAP_ROWS)
        if spot is None:
            self._log("Battle map is full — nothing spawned.", kind="warn")
            return None
        c = Combatant(**fields)
        c.name = n
        c.conditions = set(c.conditions or [])
        c.saves = set(c.saves or [])
        c.stats = {int(k): v for k, v in (c.stats or {}).items()}
        c.x, c.y = spot
        self._add_combatant(
            c,
            f"{n} (SRD) joins at {coord_name(spot[0], spot[1])} — press [bold]r[/] to roll initiative.",
        )
        return n

    def action_duplicate(self) -> None:
        c = self._sel
        if c is None or c.kind == "PC":
            self._log("Select a monster to duplicate.", kind="warn")
            return
        spot = find_free_spot(self.combatants, MAP_COLS, MAP_ROWS)
        if spot is None:
            self._log("Battle map is full — duplicate skipped.", kind="warn")
            return
        names = {item.name for item in self.combatants}
        name = self._number_name(re.sub(r" \d+$", "", c.name), names)
        duplicate = copy.deepcopy(c)
        duplicate.name = name
        duplicate.hp = duplicate.max_hp
        duplicate.init = None
        duplicate.conditions = set()
        duplicate.reminder = ""
        duplicate.x, duplicate.y = spot
        duplicate.ddb_id = None
        self._push_undo()
        self.combatants.append(duplicate)
        self._sel = duplicate
        self._sort_combatants()
        self._log(f"{name} duplicated at {coord_name(*spot)}.", kind="monster")

    def action_reset(self) -> None:
        if not self.combatants:
            return
        self._push_undo(restore_nav=True)
        for c in self.combatants:
            c.hp = c.max_hp
            c.conditions.clear()
            c.init = None
            c.reminder = ""
        self.round = 1
        self._turn = self.combatants[0]
        self._sel = self._turn
        self._sort_combatants()
        self._log("Encounter reset — full HP, clear conditions, initiative unrolled.", kind="select")

    # -- SRD spellbook -------------------------------------------------------

    def action_spell(self) -> None:
        self.run_worker(self._spell_flow())

    async def _spell_flow(self) -> None:
        spells = srd_client.load_cache("spells")
        if spells is None and not os.environ.get("VTT_OFFLINE"):
            # No cached library yet — open the picker and fetch in the background.
            self.run_worker(self._fetch_spells_worker())
        screen = SpellBrowser(
            spells or [],
            self._add_spell_entry,
            self._fetch_spells,
            self._warn_no_selection,
        )
        self._spell_screen = screen
        await self.push_screen(screen, wait_for_dismiss=True)
        self._spell_screen = None

    def _add_spell_entry(self, fields: dict) -> str | None:
        if self._sel is None:
            return None
        self._push_undo()
        self._sel.spells.append(fields["cast"])
        self._log(f"{self._sel.name} learns {fields['name']} — {fields['cast']}.", kind="import")
        self._refresh_all()
        return fields["name"]

    def _warn_no_selection(self) -> None:
        self._log("Select a creature first (arrows), then add a spell.", kind="warn")

    def _fetch_spells(self) -> None:
        self.run_worker(self._fetch_spells_worker())

    async def _fetch_spells_worker(self) -> None:
        self._log("Fetching SRD spells from Open5e…", kind="import")
        try:
            data = await asyncio.to_thread(srd_client.get_srd_spells, False)
        except Exception as exc:
            self._log(f"SRD spell fetch failed: {exc}", kind="warn")
            return
        screen = self._spell_screen
        if screen is not None:
            try:
                screen.update_srd(data)
            except Exception:
                pass
        self._log(f"Loaded {len(data)} SRD spells from Open5e.", kind="import")

    def action_remove(self) -> None:
        if self._sel is not None:
            self.run_worker(self._remove_flow())

    async def _remove_flow(self) -> None:
        gone = self._sel
        if gone is None:
            return
        options = [
            (f"yes:{gone.name}", f"[bold #d95841]✝ Remove {gone.name}[/]"),
            ("no", "Cancel"),
        ]
        picked = await self.push_screen(ListModal(f"REMOVE {gone.name}?", options), wait_for_dismiss=True)
        if not picked or not picked.startswith("yes:"):
            return
        self._push_undo()
        if gone is self._turn:
            self._turn = None
        self.combatants.remove(gone)
        self._log(f"{gone.name} removed from the encounter.", kind="remove")
        if self.combatants:
            self._sel = self._turn or self.combatants[0]
            if self._turn is None:
                self.action_next_turn()
                self._sel = self._turn or self._sel
        else:
            self._sel = None
        self._rebuild_rows()

    # -- edit --------------------------------------------------------------

    def action_edit(self) -> None:
        if self._sel is not None:
            self.run_worker(self._edit_flow())

    async def _edit_number(self, title: str, target: str, current: int) -> int | None:
        return await self.push_screen(NumberModal(title, target, str(current)), wait_for_dismiss=True)

    async def _edit_flow(self) -> None:
        c = self._sel
        if c is None:
            return
        fields = [
            ("name", "Name", c.name[:20]),
            ("max_hp", "Max HP", str(c.max_hp)),
            ("ac", "AC", str(c.ac)),
            ("init_mod", "Init mod", f"{c.init_mod:+d}"),
            ("role", "Role", (c.role or "")[:16]),
            ("note", "Note", (c.note or "")[:24]),
            ("reminder", "Turn reminder", (c.reminder or "")[:24]),
        ]
        for i in range(1, 7):
            fields.append((f"stat:{i}", ABILITY_NAMES[i - 1], str(c.stats.get(i, 10))))
        options = [(key, f"{label:<11} [dim]{cur}[/]") for key, label, cur in fields]
        picked = await self.push_screen(ListModal(f"EDIT {c.name}", options), wait_for_dismiss=True)
        if picked is None or self._sel is not c:
            return

        def do(mutate) -> None:
            self._push_undo()
            mutate()
            self._log(f"{c.name} updated.", kind="select")

        if picked == "name":
            val = await self.push_screen(TextModal("EDIT NAME", c.name, confirm="Save"), wait_for_dismiss=True)
            if val and val != c.name:
                do(lambda: setattr(c, "name", val))
        elif picked == "max_hp":
            val = await self._edit_number("MAX HP", c.name, c.max_hp)
            if val is not None and val != c.max_hp:
                def _max_hp() -> None:
                    c.max_hp = max(1, val)
                    c.hp = min(c.hp, c.max_hp)
                do(_max_hp)
        elif picked == "ac":
            val = await self._edit_number("AC", c.name, c.ac)
            if val is not None and val != c.ac:
                do(lambda: setattr(c, "ac", max(0, val)))
        elif picked == "init_mod":
            val = await self._edit_number("INIT MOD", c.name, c.init_mod)
            if val is not None and val != c.init_mod:
                do(lambda: setattr(c, "init_mod", val))
        elif picked == "role":
            val = await self.push_screen(TextModal("EDIT ROLE", c.role, confirm="Save"), wait_for_dismiss=True)
            if val and val != c.role:
                do(lambda: setattr(c, "role", val))
        elif picked == "note":
            val = await self.push_screen(TextModal("EDIT NOTE", c.note, confirm="Save"), wait_for_dismiss=True)
            if val and val != c.note:
                do(lambda: setattr(c, "note", val))
        elif picked == "reminder":
            val = await self.push_screen(TextModal("EDIT TURN REMINDER", c.reminder, confirm="Save"), wait_for_dismiss=True)
            if val != c.reminder:
                do(lambda: setattr(c, "reminder", val or ""))
        elif picked.startswith("stat:"):
            aid = int(picked.split(":")[1])
            val = await self._edit_number(f"{ABILITY_NAMES[aid - 1]} SCORE", c.name, c.stats.get(aid, 10))
            if val is not None and 1 <= val <= 30 and val != c.stats.get(aid, 10):
                do(lambda: c.stats.__setitem__(aid, val))
        else:
            return
        self._refresh_all()

    # -- add PC & new encounter ---------------------------------------------

    def action_add_pc(self) -> None:
        self.run_worker(self._add_pc_flow())

    async def _add_pc_flow(self) -> None:
        name = await self.push_screen(TextModal("ADD PC", "character name", confirm="Add"), wait_for_dismiss=True)
        if not name:
            return
        spot = find_free_spot(self.combatants, MAP_COLS, MAP_ROWS)
        if spot is None:
            self._log("Battle map is full — no PC added.", kind="warn")
            return
        x, y = spot
        pc = Combatant(
            name=name, kind="PC", hp=10, max_hp=10, ac=10, init=None, init_mod=0,
            role="Adventurer", note="New PC — tune with [bold]e[/].",
            x=x, y=y, stats={i: 10 for i in range(1, 7)},
        )
        self._push_undo()
        self.combatants.append(pc)
        self._sel = pc
        self._sort_combatants()
        self._log(f"{pc.name} joins the party at {coord_name(x, y)}.", kind="import")

    def action_new_encounter(self) -> None:
        self.run_worker(self._new_encounter_flow())

    async def _new_encounter_flow(self) -> None:
        if self.combatants:
            options = [
                ("yes", "[bold #d95841]Start a blank encounter[/]"),
                ("no", "Cancel"),
            ]
            picked = await self.push_screen(ListModal("NEW ENCOUNTER?", options), wait_for_dismiss=True)
            if picked != "yes":
                return
        self._push_undo(restore_nav=True)
        self.combatants = []
        self.round = 1
        self._turn = None
        self._sel = None
        self._moving = False
        self._rebuild_rows()
        self._log("Blank encounter — add PCs ([bold]p[/]) and monsters ([bold]m[/]).", kind="select")

    # -- misc ---------------------------------------------------------------

    def action_help(self) -> None:
        self.push_screen(HelpModal())


def main() -> None:
    BattleApp().run()


if __name__ == "__main__":
    main()
