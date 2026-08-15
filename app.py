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
import json
import random
import re
import urllib.error
import urllib.request

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import (
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
)
from textual.widget import Widget
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
    build_encounter,
    coord_name,
    find_free_spot,
    resolve_attack,
    short_label,
)

COND_SHORT = {
    "concentrating": "conc",
    "frightened": "fright",
    "incapacitated": "incap",
    "exhaustion": "exh",
    "unconscious": "uncon",
    "invisible": "invis",
    "restrained": "rest",
    "paralyzed": "para",
    "deafened": "deaf",
    "grappled": "grap",
    "petrified": "petr",
    "blinded": "blind",
    "charmed": "charm",
    "prone": "prone",
    "stunned": "stun",
    "poisoned": "pois",
}

CELL_W = 4  # battle-map cell width in columns
LEFT_W = 4  # battle-map left gutter (row labels)

SAVE_PATH = "encounter.json"  # where 's' writes / 'l' reads the session


def _abbrev(name: str) -> str:
    return COND_SHORT.get(name, name[:6])


def parse_ddb_url(url: str) -> int | None:
    """Pull a character id out of a D&D Beyond character URL (or a bare id)."""
    m = re.search(r"characters/(\d+)", url)
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"\s*(\d+)\s*", url)
    if m:
        return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Row widget — one combatant in the initiative list
# ---------------------------------------------------------------------------


class CombatantRow(Widget):
    def __init__(self, combatant: Combatant) -> None:
        super().__init__()
        self.combatant = combatant
        self.current = False
        self.selected = False

    def _style(self, color: str, bold: bool = False, extra: str = "") -> str:
        bg = "#2f3f5c" if self.selected else ("#232b3a" if self.current else "#15181f")
        return f"{'bold ' if bold else ''}{color} on {bg}{extra}"

    def render(self) -> Text:
        c = self.combatant
        w = self.size.width
        bar_w = 14 if w >= 70 else (10 if w >= 56 else 8)
        name_cap = 16 if w < 64 else 18
        ac_w = 6
        name_w = min(name_cap, max(8, w - (16 + bar_w + ac_w)))
        bg = self._style("#15181f")

        t = Text()
        arrow = "▶" if self.current else ("✝" if not c.alive else " ")
        init_s = "--" if c.init is None else f"{c.init:>2}"
        t.append(f"{arrow} {init_s} ", self._style("#e6ebf2" if self.current else "#8a93a3", self.current))

        name = c.name[:name_w].ljust(name_w)
        if not c.alive:
            t.append(name, self._style("#66707d"))
        else:
            col = "#a8d0ff" if c.kind == "PC" else "#ff9d9d"
            t.append(name, self._style(col, self.current))
        t.append(" ", bg)

        frac = c.hp_frac
        if c.alive:
            fill = round(frac * bar_w)
            bcol = "#3fae6a" if frac > 0.5 else ("#d9a441" if frac > 0.25 else "#d95841")
            t.append("█" * fill, self._style(bcol))
            t.append("░" * (bar_w - fill), self._style("#39414f"))
        else:
            t.append("░" * bar_w, self._style("#39414f"))
        t.append(" ", bg)

        hp = f"{c.hp}/{c.max_hp}"
        hcol = "#3fae6a" if frac > 0.5 else ("#d9a441" if frac > 0.25 else ("#d95841" if c.alive else "#66707d"))
        t.append(hp.ljust(8), self._style(hcol, c.alive and frac <= 0.25))
        t.append(" ", bg)

        t.append(f"AC {c.ac}".ljust(ac_w), self._style("#cfd6e0"))

        used = t.cell_len
        for cn in sorted(c.conditions):
            chip = f"{CONDITIONS[cn]['glyph']} {_abbrev(cn)}"
            if used + len(chip) + 2 > w:
                break
            t.append(chip, self._style(CONDITIONS[cn]["color"]))
            used = t.cell_len
            if used + 2 <= w:
                t.append("  ", bg)
                used = t.cell_len
        return t


# ---------------------------------------------------------------------------
# Map widget — the token grid, clickable to select
# ---------------------------------------------------------------------------


class MapGrid(Static):
    def __init__(self, content: str = "", *, id: str | None = None) -> None:
        super().__init__(content, id=id)
        self.cell_w = CELL_W

    def on_click(self, event: events.Click) -> None:
        cx = (event.x - LEFT_W) // self.cell_w
        cy = event.y - 1
        if isinstance(self.app, BattleApp):
            self.app.select_at(cx, cy)
        event.stop()

    def on_resize(self, event: events.Resize) -> None:
        self.cell_w = 4 if event.size.width >= 20 else 3
        if isinstance(self.app, BattleApp):
            self.app._refresh_map()


class InitiativeList(VerticalScroll, inherit_bindings=False):
    """Initiative list that never eats the arrow keys (arrows drive the app)."""

    BINDINGS: list[Binding] = []


class LogView(VerticalScroll, inherit_bindings=False):
    """Scrolling battle log that never eats the arrow keys."""

    BINDINGS: list[Binding] = []


# ---------------------------------------------------------------------------
# Modal screens
# ---------------------------------------------------------------------------


class NumberModal(ModalScreen[int]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str, target: str, placeholder: str) -> None:
        super().__init__()
        self._title = title
        self._target = target
        self._placeholder = placeholder
        self._input: Input | None = None

    def compose(self) -> ComposeResult:
        with Container(classes="modal-box"):
            yield Static(f"[bold #e6ebf2]{self._title} — [white]{self._target}[/][/]", classes="modal-title")
            self._input = Input(placeholder=self._placeholder, type="integer")
            yield self._input
            yield Static("[dim][bold]Enter[/] apply · [bold]Esc[/] cancel[/]", classes="modal-hint")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self._finish()

    def _finish(self) -> None:
        try:
            self.dismiss(int(self.query_one(Input).value))
        except ValueError:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ListModal(ModalScreen[str]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str, options: list[tuple[str, str]]) -> None:
        super().__init__()
        self._title = title
        self._options = options

    def compose(self) -> ComposeResult:
        with Container(classes="modal-box"):
            yield Static(f"[bold #e6ebf2]{self._title}[/]", classes="modal-title")
            yield ListView(
                *[ListItem(Label(label, classes="modal-item")) for _, label in self._options],
                id="modal-list",
            )
            yield Static("[dim][bold]Enter[/] select · [bold]Esc[/] cancel[/]", classes="modal-hint")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is not None and 0 <= idx < len(self._options):
            self.dismiss(self._options[idx][0])

    def action_cancel(self) -> None:
        self.dismiss(None)


class TextModal(ModalScreen[str]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str, placeholder: str, confirm: str = "Import") -> None:
        super().__init__()
        self._title = title
        self._placeholder = placeholder
        self._confirm = confirm

    def compose(self) -> ComposeResult:
        with Container(classes="modal-box"):
            yield Static(f"[bold #e6ebf2]{self._title}[/]", classes="modal-title")
            self._input = Input(placeholder=self._placeholder)
            yield self._input
            yield Static(f"[dim][bold]Enter[/] {self._confirm} · [bold]Esc[/] cancel[/]", classes="modal-hint")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self._finish()

    def _finish(self) -> None:
        value = self.query_one(Input).value.strip()
        self.dismiss(value if value else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class HelpModal(ModalScreen[None]):
    BINDINGS = [("escape", "cancel", "Cancel"), ("enter", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Container(classes="modal-box"):
            yield Static(
                "[bold #e6ebf2]Battle Tracker[/]\n\n"
                "[#8a93a3]A terminal combat tracker for D&D 5e DMs.\n"
                "Everything lives on one screen: map, initiative, detail.[/]\n\n"
                "[bold #a8d0ff]Keys[/]\n"
                "  [bold]↑↓[/] select   [bold]←→[/] ±1 HP\n"
                "  [bold]g[/] grab/place   [bold]n[/] next turn\n"
                "  [bold]a[/] attack   [bold]d[/] damage   [bold]h[/] heal\n"
                "  [bold]c[/] condition   [bold]m[/] monster   [bold]x[/] remove   [bold]r[/] reset\n"
                "  [bold]o[/] roll monster init   [bold]t[/] set init\n"
                "  [bold]i[/] import PC   [bold]f[/] find\n"
                "  [bold]?[/] help   [bold]q[/] quit   [bold]ctrl+p[/] palette\n"
                "  [bold]u[/] undo   [bold]shift+u[/] redo   [bold]s[/] save   [bold]l[/] load\n\n"
                "[bold #a8d0ff]Map[/]\n"
                "  click a token to select it; [bold]g[/] grabs, arrows place it\n"
                "  [bold][#c9a227]▶ gold[/][/] = turn   [bold][#5b6471]✝ dim[/][/] = down\n"
                "  blue = PC · red = monster · green = placing",
                classes="modal-help",
            )
            yield Static("[dim][bold]Enter[/] or [bold]Esc[/] close[/]", classes="modal-hint")

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------


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
}


def _iter_modifiers(character: dict):
    mods = character.get("modifiers") or {}
    if isinstance(mods, dict):
        for group in mods.values():
            if isinstance(group, list):
                yield from group
    elif isinstance(mods, list):
        yield from mods


ABILITY_NAMES = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]

_ABILITY_NAME_TO_ID = {
    "strength": 1, "dexterity": 2, "constitution": 3,
    "intelligence": 4, "wisdom": 5, "charisma": 6,
}

_SKILL_ABILITY = {
    "acrobatics": 2, "animal handling": 5, "arcana": 4, "athletics": 1,
    "deception": 6, "history": 4, "insight": 5, "intimidation": 6,
    "investigation": 4, "medicine": 5, "nature": 4, "perception": 5,
    "performance": 6, "persuasion": 6, "religion": 4, "sleight of hand": 2,
    "stealth": 2, "survival": 5,
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

    ModalScreen { align: center top; padding-top: 3; background: rgba(8, 10, 14, 0.75); }
    .modal-title { text-style: bold; color: #e6ebf2; margin-bottom: 1; }
    .modal-box { width: 38; height: auto; border: thick #4a5b7a; background: #1b2029; padding: 1 2; }
    #modal-list { height: 12; border: round #2a3446; margin-top: 1; }
    .modal-item { padding: 0 1; color: #c9d3e0; }
    ListView:focus .modal-item { background: #2f3f5c; color: #ffffff; }
    .modal-hint { margin-top: 1; color: #8a93a3; }
    .modal-help { margin: 0 0 1 0; }
    Input { margin-top: 1; }
    """

    BINDINGS = [
        Binding("up, k", "arrow_up", "Select"),
        Binding("down, j", "arrow_down", "Select"),
        Binding("left", "arrow_left", "-HP"),
        Binding("right", "arrow_right", "+HP"),
        Binding("g", "grab", "Grab"),
        Binding("n, enter", "next_turn", "Next turn"),
        Binding("o", "roll_monster_init", "Monster init"),
        Binding("t", "set_init", "Set init"),
        Binding("d", "damage", "Damage"),
        Binding("h", "heal", "Heal"),
        Binding("a", "attack", "Attack"),
        Binding("c", "condition", "Condition"),
        Binding("m", "monster", "Monster"),
        Binding("i", "import_pc", "Import PC"),
        Binding("f", "find", "Find"),
        Binding("x", "remove", "Remove"),
        Binding("r", "reset", "Reset"),
        Binding("plus", "heal_one", "+1"),
        Binding("minus", "damage_one", "-1"),
        Binding("question_mark", "help", "Help"),
        Binding("escape", "release", "Drop"),
        Binding("u", "undo", "Undo"),
        Binding("shift+u", "redo", "Redo"),
        Binding("s", "save", "Save"),
        Binding("l", "load", "Load"),
        Binding("q", "quit", "Quit"),
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
        self._setup()

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
        yield Static(
            "  ·  ".join([hint("i", "import"), hint("f", "find"), hint("ctrl+p", "palette"), hint("?", "help"), hint("q", "quit")]),
            id="message",
        )

    def on_mount(self) -> None:
        self._refresh_all()
        self.call_after_refresh(self._refresh_all)
        self.call_after_refresh(self._scroll_to_selected)

    def _setup(self) -> None:
        self.combatants = build_encounter()
        self.round = 1
        self._turn = self.combatants[0]
        self._sel = self.combatants[0]
        self._moving = False
        self._messages = [("Encounter set. Round 1 — high initiative acts first.", "info", True)]

    def _reset_encounter(self) -> None:
        self._setup()
        self._rebuild_rows()

    # -- undo / redo / persistence ------------------------------------------

    def _combatant_snap(self, c: Combatant) -> dict:
        return {
            "name": c.name, "kind": c.kind, "hp": c.hp, "max_hp": c.max_hp, "ac": c.ac,
            "init": c.init, "init_mod": c.init_mod, "conditions": sorted(c.conditions),
            "role": c.role, "note": c.note, "x": c.x, "y": c.y,
            "stats": dict(c.stats), "saves": sorted(c.saves), "speed": c.speed,
            "proficiency": c.proficiency, "hit_dice": c.hit_dice, "skills": dict(c.skills),
            "passive_perception": c.passive_perception, "attacks": list(c.attacks),
            "traits": list(c.traits), "spells": list(c.spells),
        }

    def _snapshot(self) -> dict:
        return {
            "version": 1,
            "combatants": [self._combatant_snap(c) for c in self.combatants],
            "round": self.round,
            "turn": self.combatants.index(self._turn) if self._turn is not None else None,
            "sel": self.combatants.index(self._sel) if self._sel is not None else None,
            "moving": self._moving,
        }

    def _push_undo(self) -> None:
        self._undo.append(self._snapshot())
        if len(self._undo) > 50:
            self._undo.pop(0)
        self._redo.clear()

    def _restore(self, snap: dict) -> None:
        new_combatants = []
        for s in snap.get("combatants", []):
            s = dict(s)
            stats = s.get("stats") or {}
            s["stats"] = {int(k): v for k, v in stats.items()}
            c = Combatant(**s)
            c.conditions = set(s.get("conditions", []))
            c.saves = set(s.get("saves", []))
            new_combatants.append(c)
        self.combatants = new_combatants
        self.round = int(snap.get("round", 1))
        n = len(new_combatants)
        turn_i = snap.get("turn")
        sel_i = snap.get("sel")
        self._turn = new_combatants[turn_i] if n and isinstance(turn_i, int) and 0 <= turn_i < n else None
        self._sel = new_combatants[sel_i] if n and isinstance(sel_i, int) and 0 <= sel_i < n else (self._turn or (new_combatants[0] if n else None))
        self._moving = False
        self._rebuild_rows()

    def action_undo(self) -> None:
        if not self._undo:
            self._log("Nothing to undo.", kind="warn")
            return
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())
        self._log("Undid last change.", kind="select")

    def action_redo(self) -> None:
        if not self._redo:
            self._log("Nothing to redo.", kind="warn")
            return
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())
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
        self._push_undo()
        self._restore(snap)
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
        for row in self._rows.values():
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
        self.query_one("#init-status", Static).update(self._init_status_text())
        self.query_one("#log-status", Static).update(self._log_status_text())
        self.query_one("#detail-status", Static).update(self._detail_status_text())
        turn = self._turn
        self.sub_title = f"Round {self.round} · {turn.name if turn else '—'} to act"

    def _refresh_map(self) -> None:
        global MAP_COLS, MAP_ROWS
        grid = self.query_one("#map", MapGrid)
        avail_w = max(1, grid.size.width - LEFT_W)
        cell_w = 4 if avail_w >= 20 else 3
        MAP_COLS = min(30, max(5, avail_w // cell_w))
        MAP_ROWS = min(40, max(5, grid.size.height))
        grid.cell_w = cell_w
        grid.update(self._map_text(cell_w))
        self.query_one("#map-title", Static).update(self._map_title_text())
        self.query_one("#map-status", Static).update(self._map_status_text())

    def _refresh_detail(self) -> None:
        detail = self.query_one("#detail", Static)
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

        if c.stats:
            for r in range(2):
                parts = []
                for a in (r * 3 + 1, r * 3 + 2, r * 3 + 3):
                    m = c.mod(a)
                    m_s = f"[bold]({m:+d})[/]" if m is not None else "(—)"
                    parts.append(f"[bold]{ABILITY_NAMES[a - 1]}[/] {c.stats.get(a, '—')} {m_s}")
                lines.append("  ".join(parts))

        if c.saves:
            sv = "  ".join(f"[bold]{ABILITY_NAMES[a - 1]}[/] {c.save(a):+d}" for a in sorted(c.saves))
            lines.append(f"[bold]SAVES[/]  {sv}")
        if c.skills:
            sk = "  ".join(f"[bold]{k.capitalize()}[/] {v:+d}" for k, v in sorted(c.skills.items()))
            lines.append(f"[bold]SKILLS[/]  {sk}")
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
            lines.append(f"[dim]{c.note}[/]")
        return "\n".join(lines)

    def _refresh_log(self) -> None:
        content = self.query_one("#log-content", Static)
        content.update(self._log_text())
        if self._log_view is not None:
            self._log_view.scroll_end(animate=False)

    def _log_text(self) -> str:
        lines = [
            f"[{LOG_COLORS.get(kind, '#c9d3e0')}]{text}[/]"
            for text, kind, in_log in self._messages
            if in_log
        ]
        if not lines:
            return "[dim]— nothing recorded yet —[/]"
        return "\n".join(lines)

    def _log(self, text: str, kind: str = "info", in_log: bool = True) -> None:
        self._messages.append((text, kind, in_log))
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
        return "  ·  ".join([hint("↑↓", "select"), hint("n", "next"), hint("o", "roll init"), hint("t", "set init")])

    def _log_status_text(self) -> str:
        return "  ·  ".join(
            [hint("r", "reset"), hint("s", "save"), hint("l", "load"), hint("u", "undo"), hint("?", "help"), hint("q", "quit")]
        )

    def _detail_status_text(self) -> str:
        return "  ·  ".join(
            [hint("a", "attack"), hint("d", "damage"), hint("h", "heal"), hint("m", "monster"), hint("x", "remove")]
        )

    def _map_text(self, cell_w: int) -> Text:
        tokens: dict[tuple[int, int], list] = {}
        for c in self.combatants:
            if 0 <= c.x < MAP_COLS and 0 <= c.y < MAP_ROWS:
                tokens.setdefault((c.x, c.y), []).append(c)

        text = Text()
        text.append(" " * LEFT_W, style="bold #8a93a3")
        for col in range(MAP_COLS):
            text.append(chr(ord("A") + col).ljust(cell_w), style="bold #8a93a3")
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
        cap = cell_w - 1

        if active:
            body, fg, bg, bold = "▶" + label[:cap], "#16130a", "#c9a227", True
        elif down:
            body, fg, bg, bold = "✝" + label[:cap], "#5b6471", "#20242c", False
        else:
            body, fg, bg, bold = " " + label[:cap], "#d7e9ff", "#2a4a6a", False
            if c.kind != "PC":
                fg, bg = "#ffd9d9", "#5a2f2f"

        if sel and self._moving:
            fg, bg, bold = "#ffffff", "#3f7a4f", True
        elif sel and not active:
            bg = "#3f6a96" if c.kind == "PC" else "#8a4a4a"
            bold = True

        style = f"bold {fg} on {bg}" if bold else f"{fg} on {bg}"
        return Text(body.ljust(cell_w), style=style)

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
        for c in self.combatants:
            if (c.x, c.y) == (cx, cy):
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
        if self._moving and self._sel is not None:
            self._moving = False
            self._refresh_all()

    def action_cursor_up(self) -> None:
        n = len(self.combatants)
        if n == 0:
            return
        self._sel = self.combatants[(self._sel_index - 1) % n]
        self._refresh_all()
        self._scroll_to_selected()

    def action_cursor_down(self) -> None:
        n = len(self.combatants)
        if n == 0:
            return
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
        if nxt == 0:
            self.round += 1
        scanned = 0
        while scanned < n and not self.combatants[nxt].alive:
            nxt = (nxt + 1) % n
            scanned += 1
        self._turn = self.combatants[nxt]
        self._log(f"Turn → {self._turn.name} (round {self.round})", kind="turn")
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
        self.run_worker(self._init_flow())

    async def _init_flow(self) -> None:
        target = self._sel
        value = await self.push_screen(
            NumberModal("Initiative", target.name, "initiative value"),
            wait_for_dismiss=True,
        )
        if value is None:
            return
        self._push_undo()
        target.init = value
        self._log(f"{target.name} set to initiative {value}.", kind="turn")
        self._sort_combatants()

    # -- damage / heal -------------------------------------------------------

    def action_damage(self) -> None:
        if self._sel is not None:
            self._run_number("Damage", self._sel)

    def action_heal(self) -> None:
        if self._sel is not None:
            self._run_number("Heal", self._sel)

    def action_damage_one(self) -> None:
        if self._sel is not None:
            self._apply_hp(self._sel, -1)

    def action_heal_one(self) -> None:
        if self._sel is not None:
            self._apply_hp(self._sel, 1)

    def _run_number(self, title: str, target: Combatant) -> None:
        self.run_worker(self._number_flow(title, target))

    def _make_number_modal(self, title: str, target: Combatant) -> NumberModal:
        ph = "damage amount" if title == "Damage" else "heal amount"
        return NumberModal(title, target.name, ph)

    async def _number_flow(self, title: str, target: Combatant) -> None:
        amount = await self.push_screen(self._make_number_modal(title, target), wait_for_dismiss=True)
        if amount is None:
            return
        if title == "Heal":
            self._apply_hp(target, amount)
        else:
            self._apply_hp(target, -amount)

    def _apply_hp(self, c: Combatant, delta: int) -> None:
        if delta == 0:
            return
        self._push_undo()
        was_alive = c.alive
        c.hp = max(0, min(c.max_hp, c.hp + delta))
        if delta > 0:
            line = self._rng.choice(HEAL_LINES).format(name=c.name, amount=delta)
            kind = "heal"
        elif was_alive and not c.alive:
            line = self._rng.choice(DEATH_LINES).format(name=c.name)
            kind = "death"
        else:
            line = self._rng.choice(DAMAGE_LINES).format(name=c.name, amount=-delta)
            kind = "damage"
        if not c.alive and c.conditions:
            c.conditions.discard("concentrating")
        self._log(line, kind=kind)
        self._refresh_all()

    # -- attack resolution -----------------------------------------------------

    def action_attack(self) -> None:
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
        self._push_undo()
        if res["kind"] == "attack":
            head = f"{c.name}: {res['name']} → [bold #e6ebf2]{res['roll']}[/] vs AC {target.ac} — "
            if not res["hit"]:
                self._log(head + "[bold #8a93a3]miss[/].", kind="damage")
            else:
                parts = " + ".join(str(r) for r in res["dice"])
                if res["dice_bonus"]:
                    parts += f" {res['dice_bonus']:+d}"
                crit = " [bold #e0c04c]CRIT![/]" if res["crit"] else ""
                self._log(
                    head + f"[bold #3fae6a]hit[/] for [bold #e05a5a]{res['damage']} damage[/] ({parts}){crit}",
                    kind="damage",
                )
        else:
            parts = " + ".join(str(r) for r in res["dice"])
            if res["dice_bonus"]:
                parts += f" {res['dice_bonus']:+d}"
            if res["damage"]:
                self._log(
                    f"{c.name} casts {res['name']} — [bold #e0c04c]{res['damage']} damage[/] to {target.name} ({parts}).",
                    kind="monster",
                )
            else:
                self._log(f"{c.name} casts {res['name']} on {target.name}.", kind="monster")
        if res["damage"]:
            was_alive = target.alive
            target.hp = max(0, min(target.max_hp, target.hp - res["damage"]))
            if was_alive and not target.alive:
                target.conditions.discard("concentrating")
                self._log(self._rng.choice(DEATH_LINES).format(name=target.name), kind="death")
        self._refresh_all()

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
            c = q[1:].strip().upper()
            if len(c) >= 2 and c[0].isalpha() and c[1:].isdigit():
                x = ord(c[0]) - ord("A")
                y = int(c[1:]) - 1
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
        cid = parse_ddb_url(url)
        if cid is None:
            self._log("Could not find a character id in that URL.", kind="warn")
            return
        self._log(f"Importing character {cid} from D&D Beyond…", kind="import")
        try:
            data = await asyncio.to_thread(self._fetch_character_data, cid)
        except Exception as exc:
            self._log(f"Import failed: {exc}", kind="warn")
            return
        pc = self._extract_combatant(cid, data)
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
        pc.x, pc.y = find_free_spot(self.combatants, MAP_COLS, MAP_ROWS)
        self._push_undo()
        self.combatants.append(pc)
        self._sort_combatants()
        self._log(f"Imported {pc.name} ({pc.role}) — HP {pc.hp}/{pc.max_hp}, AC {pc.ac}.", kind="import")

    @staticmethod
    def _fetch_character_data(character_id: int) -> dict:
        """Fetch a character from D&D Beyond's (unofficial) character service.

        This is an internal endpoint, not a supported API contract — treat it
        as best-effort and expect it to change.
        """
        url = f"https://character-service.dndbeyond.com/character/v5/character/{character_id}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "battle-tracker/1.0", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8"))
                message = detail.get("message") or str(exc)
            except Exception:
                message = str(exc)
            raise ValueError(f"D&D Beyond returned {exc.code}: {message}") from exc
        data = payload.get("data") or {}
        if data.get("character") is None and not payload.get("success", True):
            raise ValueError(payload.get("message", "character not found"))
        return data

    @staticmethod
    def _extract_combatant(character_id: int, data: dict) -> Combatant:
        character = data.get("character")
        if not isinstance(character, dict) or not character:
            character = data if isinstance(data, dict) else {}
        name = character.get("name") or f"Char {character_id}"

        total_level = 0
        parts = []
        classes = character.get("classes") or []
        if isinstance(classes, dict):
            classes = list(classes.values())
        for cls in classes:
            if not isinstance(cls, dict):
                continue
            definition = cls.get("definition")
            if isinstance(definition, str):
                definition = {"name": definition}
            elif not isinstance(definition, dict):
                definition = {}
            cname = definition.get("name") or cls.get("name") or "?"
            level = int(cls.get("level") or 1)
            total_level += level
            parts.append(f"{cname} {level}")
        role = " / ".join(parts) if parts else f"Level {max(total_level, 1)} Adventurer"
        if not total_level:
            total_level = 1

        # ability scores (ids: 1 STR, 2 DEX, 3 CON, 4 INT, 5 WIS, 6 CHA)
        dex_mod = con_mod = 0
        stats = character.get("stats")
        if isinstance(stats, dict):
            stats = list(stats.values())
        if isinstance(stats, list) and stats and isinstance(stats[0], dict):
            for stat in stats:
                s_id = int(stat.get("id") or 0)
                value = int(stat.get("value") or 10)
                if s_id == 2:
                    dex_mod = (value - 10) // 2
                elif s_id == 3:
                    con_mod = (value - 10) // 2
        elif isinstance(stats, list) and stats and isinstance(stats[0], int) and len(stats) >= 3:
            dex_mod = (int(stats[1]) - 10) // 2
            con_mod = (int(stats[2]) - 10) // 2

        # hit points: hit dice base + CON per level (+ any flat bonus)
        max_hp = None
        override = character.get("overrideHitPoints")
        if isinstance(override, dict):
            max_hp = int(override.get("value") or override.get("max"))
        if max_hp is None:
            base = int(character.get("baseHitPoints") or 0)
            bonus = int(character.get("bonusHitPoints") or 0)
            max_hp = base + bonus + con_mod * total_level
            if max_hp <= 0:
                max_hp = 10 + total_level * 5
        current = max(0, max_hp - int(character.get("removedHitPoints") or 0))

        # armor class: armor base + dex (capped by armor type) + shield + AC bonuses
        ac = 10
        dex_cap = None
        wearing_armor = False
        shield_bonus = 0
        inventory = character.get("inventory") or []
        if isinstance(inventory, list):
            for item in inventory:
                if not item.get("equipped"):
                    continue
                defn = item.get("definition")
                if not isinstance(defn, dict):
                    continue
                item_ac = defn.get("armorClass")
                atype = defn.get("armorTypeId")
                if atype in (1, 2, 3) and item_ac:
                    ac = int(item_ac)
                    dex_cap = {1: None, 2: 2, 3: 0}[atype]
                    wearing_armor = True
            for item in inventory:
                if not item.get("equipped"):
                    continue
                defn = item.get("definition")
                if not isinstance(defn, dict):
                    continue
                item_ac = defn.get("armorClass")
                atype = defn.get("armorTypeId")
                iname = (defn.get("name") or "").lower()
                if (atype == 4 or "shield" in iname) and item_ac:
                    shield_bonus += int(item_ac)
        ac += shield_bonus
        for mod in _iter_modifiers(character):
            if mod.get("type") == "bonus" and mod.get("subType") in ("armor-class", "armored-armor-class"):
                value = mod.get("fixedValue")
                if value is None:
                    value = mod.get("value")
                if value:
                    ac += int(value)
        ac += dex_mod if not wearing_armor else (dex_mod if dex_cap is None else min(dex_mod, dex_cap))

        race = ""
        race_obj = character.get("race")
        if isinstance(race_obj, str):
            race = f"{race_obj} "
        elif isinstance(race_obj, dict):
            rname = race_obj.get("fullName") or race_obj.get("baseRaceName")
            if rname:
                race = f"{rname} "

        ability_names = ABILITY_NAMES
        stat_values = {}
        if isinstance(stats, list) and stats and isinstance(stats[0], dict):
            for stat in stats:
                stat_values[int(stat.get("id") or 0)] = int(stat.get("value") or 0)
        elif isinstance(stats, list) and stats and isinstance(stats[0], int):
            for i, value in enumerate(stats[:6]):
                stat_values[i + 1] = int(value)
        stats_text = ", ".join(
            f"{ability_names[i]} {stat_values.get(i + 1, '?')}" for i in range(6)
        )
        note = f"{race}{role} — {stats_text}. Imported from D&D Beyond."

        def _stat_mod(aid: int) -> int:
            return (int(stat_values.get(aid, 10)) - 10) // 2

        prof = character.get("proficiencyBonus")
        prof = int(prof) if isinstance(prof, int) else 2 + (total_level - 1) // 4

        saves: set[int] = set()
        for cls in classes:
            definition = cls.get("definition")
            if not isinstance(definition, dict):
                continue
            st = definition.get("savingThrows")
            if isinstance(st, list):
                for s in st:
                    aid = _ABILITY_NAME_TO_ID.get(str(s).lower())
                    if aid:
                        saves.add(aid)
            elif isinstance(st, dict):
                for k, v in st.items():
                    if v and _ABILITY_NAME_TO_ID.get(str(k).lower()):
                        saves.add(_ABILITY_NAME_TO_ID[str(k).lower()])

        skill_ranks: dict[str, int] = {}
        for mod in _iter_modifiers(character):
            mtype = mod.get("type")
            if mtype not in ("proficiency", "expertise"):
                continue
            sub = (mod.get("subType") or "").strip().lower()
            if sub in _SKILL_ABILITY:
                skill_ranks[sub] = 2 if mtype == "expertise" else 1
        skills = {
            name: _stat_mod(_SKILL_ABILITY[name]) + prof * rank
            for name, rank in skill_ranks.items()
        }
        perception = skills.get("perception")
        passive_perception = 10 + (perception if perception is not None else _stat_mod(5))

        speed = character.get("speed")
        if isinstance(speed, dict):
            speed = speed.get("walk")
        speed = int(speed) if isinstance(speed, (int, float)) else None

        hd = character.get("hitPointDice")
        if isinstance(hd, dict):
            hd = "".join(f"{v}d{k}" for k, v in hd.items())
        hit_dice = hd if isinstance(hd, str) else ""

        attacks: list[str] = []
        str_mod = _stat_mod(1)
        if isinstance(inventory, list):
            for item in inventory:
                if not item.get("equipped") or len(attacks) >= 4:
                    continue
                defn = item.get("definition")
                if not isinstance(defn, dict):
                    continue
                dmg = defn.get("damage")
                if not dmg:
                    continue
                if defn.get("attackType") is None and not defn.get("weaponDefinition") \
                        and not defn.get("range") and not defn.get("damageType"):
                    continue
                stat_mod = dex_mod if defn.get("range") else str_mod
                dmg_bonus = int(defn.get("damageBonus") or 0)
                dtype = str(defn.get("damageType") or "")
                attacks.append(
                    f"{(defn.get('name') or '?')} +{stat_mod + prof + dmg_bonus} · {dmg}{stat_mod + dmg_bonus:+d} {dtype[:3].lower()}"
                )

        traits: list[str] = []
        if race:
            traits.append(f"{race.strip()} racial traits")
        features = character.get("classFeatures") or []
        if isinstance(features, list):
            for f in features[:2]:
                if isinstance(f, dict) and f.get("name"):
                    traits.append(f["name"])

        return Combatant(
            name=name,
            kind="PC",
            hp=current,
            max_hp=max_hp,
            ac=ac,
            init=None,
            init_mod=dex_mod,
            role=role,
            note=note,
            stats={aid: stat_values.get(aid, 10) for aid in range(1, 7)},
            saves=saves,
            speed=speed,
            proficiency=prof,
            hit_dice=hit_dice,
            skills=skills,
            passive_perception=passive_perception,
            attacks=attacks,
            traits=traits,
        )

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
        tmpl = MONSTERS[picked]
        count = sum(1 for c in self.combatants if c.name == picked or c.name.startswith(picked + " ")) + 1
        name = picked if count == 1 else f"{picked} {count}"
        x, y = find_free_spot(self.combatants, MAP_COLS, MAP_ROWS)
        mob = Combatant(name=name, kind="monster", hp=tmpl["max_hp"], max_hp=tmpl["max_hp"],
                        ac=tmpl["ac"], init=None, init_mod=tmpl["init"],
                        role=tmpl["role"], note=tmpl["note"], x=x, y=y,
                        stats=dict(tmpl.get("stats", {})), saves=set(tmpl.get("saves", set())),
                        speed=tmpl.get("speed"), proficiency=tmpl.get("proficiency"),
                        skills=dict(tmpl.get("skills", {})),
                        passive_perception=tmpl.get("passive_perception"),
                        attacks=list(tmpl.get("attacks", [])), traits=list(tmpl.get("traits", [])),
                        spells=list(tmpl.get("spells", [])))
        self._push_undo()
        self.combatants.append(mob)
        self._sort_combatants()
        self._log(f"{name} joins the fight at {coord_name(x, y)} — press [bold]o[/] to roll its initiative.", kind="monster")

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
        else:
            self._sel = None
        self._rebuild_rows()

    # -- misc ---------------------------------------------------------------

    def action_reset(self) -> None:
        self._push_undo()
        self._reset_encounter()
        self._log("Encounter reset to round 1.")

    async def action_help(self) -> None:
        self.run_worker(self._help_flow())

    async def _help_flow(self) -> None:
        await self.push_screen(HelpModal(), wait_for_dismiss=True)


def main() -> None:
    BattleApp().run()


if __name__ == "__main__":
    main()