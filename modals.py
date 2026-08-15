"""Modal screens for the battle tracker — a number prompt, a pick list, a
text prompt, and the help screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static


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


class MonsterBrowser(ModalScreen[str]):
    """Searchable monster-library picker: type to filter, Enter to add."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, monsters: dict) -> None:
        super().__init__()
        self._monsters = monsters

    def compose(self) -> ComposeResult:
        with Container(classes="modal-box"):
            yield Static("[bold #e6ebf2]MONSTER LIBRARY[/]", classes="modal-title")
            yield Input(placeholder="type to filter…", id="browser-search")
            yield ListView(id="modal-list")
            yield Static("[dim][bold]Enter[/] add · [bold]Esc[/] cancel[/]", classes="modal-hint")

    def _visible(self) -> list[str]:
        q = self.query_one("#browser-search", Input).value.strip().lower()
        names = [
            name
            for name in self._monsters
            if not q
            or q in name.lower()
            or q in str(self._monsters[name].get("role", "")).lower()
        ]
        return sorted(names)

    def on_mount(self) -> None:
        self.query_one("#browser-search").focus()
        self._rebuild()

    def on_input_changed(self, _: Input.Changed) -> None:
        self._rebuild()

    def on_input_submitted(self, _: Input.Submitted) -> None:
        names = self._visible()
        if len(names) == 1:
            self.dismiss(names[0])
        elif names:
            self.query_one("#modal-list", ListView).focus()

    def _rebuild(self) -> None:
        names = self._visible()
        self.query_one("#modal-list", ListView).clear()
        for name in names:
            m = self._monsters[name]
            label = f"{name}   [dim]hp {m['max_hp']} · ac {m['ac']} · init {m['init']:+d}[/]"
            self.query_one("#modal-list", ListView).append(ListItem(Label(label, classes="modal-item")))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is not None and 0 <= idx < len(self._visible()):
            self.dismiss(self._visible()[idx])

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
                "  [bold]b[/] monster library   [bold]o[/] roll monster init   [bold]t[/] set init\n"
                "  [bold]i[/] import PC   [bold]f[/] find   [bold]e[/] edit\n"
                "  [bold]p[/] add PC   [bold]ctrl+n[/] new encounter\n"
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