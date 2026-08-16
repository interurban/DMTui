"""Battle-tracker widgets: the initiative row, the clickable token map, and
the scroll containers that deliberately ignore the arrow keys."""

from __future__ import annotations

from textual import events
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static
from rich.text import Text

from battle import CONDITIONS, Combatant

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


def _abbrev(name: str) -> str:
    return COND_SHORT.get(name, name[:6])


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
        t.append(hp.ljust(8), self._style(hcol, c.alive and c.bloodied))
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


class MapGrid(Static):
    def __init__(self, content: str = "", *, id: str | None = None) -> None:
        super().__init__(content, id=id)
        self.cell_w = CELL_W

    def on_click(self, event: events.Click) -> None:
        cx = (event.x - LEFT_W) // self.cell_w
        cy = event.y - 1
        if hasattr(self.app, "select_at"):
            self.app.select_at(cx, cy)
        event.stop()

    def on_resize(self, event: events.Resize) -> None:
        self.cell_w = 4 if event.size.width >= 20 else 3
        if hasattr(self.app, "_refresh_map"):
            self.app._refresh_map()


class InitiativeList(VerticalScroll, inherit_bindings=False):
    """Initiative list that never eats the arrow keys (arrows drive the app)."""

    BINDINGS: list[Binding] = []


class LogView(VerticalScroll, inherit_bindings=False):
    """Scrolling battle log that never eats the arrow keys."""

    BINDINGS: list[Binding] = []
