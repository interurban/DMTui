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


class MonsterLibrary(ModalScreen[None]):
    """Large, searchable monster picker — the DM's add-monster UI.

    Merges the hand-authored templates (tagged [built-in]) with the Open5e SRD
    library (tagged [SRD]). Type to filter; Enter/a on a row adds it and keeps
    the picker open so several monsters can be dropped in mid-fight without
    re-opening. `f` pulls the SRD library on demand (needs network, one-time)."""

    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("enter", "add_selected", "Add (stays open)"),
        ("a", "add_selected", "Add"),
        ("f", "fetch_srd", "Fetch SRD"),
    ]

    def __init__(self, builtins: dict, srd: list[dict] | None, add_fn, fetch_fn) -> None:
        super().__init__()
        self._builtins = builtins
        self._srd = list(srd or [])
        self._add_fn = add_fn
        self._fetch_fn = fetch_fn
        self._current: list[tuple[str, tuple[str, object]]] = []

    def compose(self) -> ComposeResult:
        with Container(classes="modal-box library-box"):
            yield Static("[bold #e6ebf2]MONSTER LIBRARY[/]  [dim]built-ins + SRD[/]", classes="modal-title")
            yield Input(placeholder="filter by name, type, or source…", id="lib-search")
            yield Static("", id="lib-status", classes="modal-hint")
            yield ListView(id="lib-list")
            yield Static(
                "[dim][bold]Enter[/]/[bold]a[/] add (stays open) · [bold]f[/] fetch SRD · [bold]Esc[/] close[/]",
                classes="modal-hint",
            )

    def on_mount(self) -> None:
        self.query_one("#lib-search", Input).focus()
        self._rebuild()

    def _entries(self) -> list[tuple[str, tuple[str, object]]]:
        q = self.query_one("#lib-search", Input).value.strip().lower()
        out: list[tuple[str, tuple[str, object]]] = []
        for name, m in sorted(self._builtins.items()):
            if not q or q in name.lower() or q in str(m.get("role", "")).lower():
                label = f"{name}   [dim][built-in] hp {m['max_hp']} · ac {m['ac']} · {m.get('role', '')}[/]"
                out.append((label, ("builtin", name)))
        for m in self._srd:
            nm = m.get("name", "?")
            hay = f"{nm} {m.get('role', '')} {m.get('note', '')}".lower()
            if not q or q in hay:
                label = f"{nm}   [dim][SRD] hp {m['max_hp']} · ac {m['ac']} · {m.get('role', '')}[/]"
                out.append((label, ("srd", m)))
        return out

    def _rebuild(self) -> None:
        entries = self._entries()
        self._current = entries
        lv = self.query_one("#lib-list", ListView)
        lv.clear()
        for label, _ in entries:
            lv.append(ListItem(Label(label, classes="modal-item")))
        lv.index = 0 if entries else None
        total = len(entries)
        src = "built-ins" + (f" + {len(self._srd)} SRD" if self._srd else " (SRD not loaded — press f)")
        self.query_one("#lib-status", Static).update(
            f"[dim]{total} match{'es' if total != 1 else ''} · {src}[/]"
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "lib-search":
            self._rebuild()

    def on_input_submitted(self, _: Input.Submitted) -> None:
        if not self._current:
            return
        if len(self._current) == 1:
            self._add(self._current[0][1])
        else:
            self.query_one("#lib-list", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is not None and 0 <= idx < len(self._current):
            self._add(self._current[idx][1])

    def action_add_selected(self) -> None:
        lv = self.query_one("#lib-list", ListView)
        idx = lv.index
        if idx is not None and 0 <= idx < len(self._current):
            self._add(self._current[idx][1])
        elif len(self._current) == 1:
            self._add(self._current[0][1])

    def _add(self, payload: tuple[str, object]) -> None:
        try:
            added = self._add_fn(payload)
        except Exception as exc:  # never let a bad add kill the picker
            self.query_one("#lib-status", Static).update(f"[dim #d95841]Add failed: {exc}[/]")
            return
        if added:
            self.query_one("#lib-status", Static).update(
                f"[dim #3fae6a]Added {added} — press [bold]Esc[/] when done[/]"
            )
            lv = self.query_one("#lib-list", ListView)
            if lv.index is None and self._current:
                lv.index = 0

    def action_fetch_srd(self) -> None:
        self.query_one("#lib-status", Static).update("[dim #a8d0ff]Fetching SRD monsters…[/]")
        try:
            self._fetch_fn()
        except Exception:
            pass

    def update_srd(self, data: list[dict]) -> None:
        """Swap in freshly fetched SRD data and refresh the list."""
        self._srd = list(data or [])
        self._rebuild()

    def action_cancel(self) -> None:
        self.dismiss(None)


class SpellBrowser(ModalScreen[None]):
    """Searchable SRD spellbook — adds an Open5e spell to the selected creature.

    Mirrors MonsterLibrary's large, keep-open UX: type to filter, Enter/a adds
    the spell to the selected combatant's `spells` list (where it becomes
    usable in the attack flow), `f` fetches the SRD spell list on demand."""

    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("enter", "add_selected", "Add (stays open)"),
        ("a", "add_selected", "Add"),
        ("f", "fetch_srd", "Fetch SRD"),
    ]

    def __init__(self, spells: list[dict] | None, add_fn, fetch_fn, warn_fn) -> None:
        super().__init__()
        self._spells = list(spells or [])
        self._add_fn = add_fn
        self._fetch_fn = fetch_fn
        self._warn_fn = warn_fn
        self._current: list[tuple[str, dict]] = []

    def compose(self) -> ComposeResult:
        with Container(classes="modal-box library-box"):
            yield Static("[bold #e6ebf2]SPELLBOOK[/]  [dim]Open5e SRD — adds to selected creature[/]", classes="modal-title")
            yield Input(placeholder="filter by name, school, or level…", id="lib-search")
            yield Static("", id="lib-status", classes="modal-hint")
            yield ListView(id="lib-list")
            yield Static(
                "[dim][bold]Enter[/]/[bold]a[/] add to selected (stays open) · [bold]f[/] fetch SRD · [bold]Esc[/] close[/]",
                classes="modal-hint",
            )

    def on_mount(self) -> None:
        self.query_one("#lib-search", Input).focus()
        self._rebuild()

    def _entries(self) -> list[tuple[str, dict]]:
        q = self.query_one("#lib-search", Input).value.strip().lower()
        out: list[tuple[str, dict]] = []
        for m in self._spells:
            nm = m.get("name", "?")
            hay = f"{nm} {m.get('school', '')} level {m.get('level', '')}".lower()
            if not q or q in hay:
                lvl = m.get("level", 0)
                label = f"{nm}   [dim]L{lvl} {m.get('school', '')}[/]"
                out.append((label, m))
        return out

    def _rebuild(self) -> None:
        entries = self._entries()
        self._current = entries
        lv = self.query_one("#lib-list", ListView)
        lv.clear()
        for label, _ in entries:
            lv.append(ListItem(Label(label, classes="modal-item")))
        lv.index = 0 if entries else None
        total = len(entries)
        src = f"{len(self._spells)} SRD spells" if self._spells else "SRD not loaded — press f"
        self.query_one("#lib-status", Static).update(
            f"[dim]{total} match{'es' if total != 1 else ''} · {src}[/]"
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "lib-search":
            self._rebuild()

    def on_input_submitted(self, _: Input.Submitted) -> None:
        if not self._current:
            return
        if len(self._current) == 1:
            self._add(self._current[0][1])
        else:
            self.query_one("#lib-list", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is not None and 0 <= idx < len(self._current):
            self._add(self._current[idx][1])

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        idx = event.list_view.index
        if idx is not None and 0 <= idx < len(self._current):
            m = self._current[idx][1]
            info = f"{m.get('name')} · L{m.get('level', 0)} {m.get('school', '')} · {m.get('casting_time', '')} · {m.get('range', '')}"
            self.query_one("#lib-status", Static).update(f"[dim]{info}[/]")

    def action_add_selected(self) -> None:
        lv = self.query_one("#lib-list", ListView)
        idx = lv.index
        if idx is not None and 0 <= idx < len(self._current):
            self._add(self._current[idx][1])
        elif len(self._current) == 1:
            self._add(self._current[0][1])

    def _add(self, fields: dict) -> None:
        try:
            added = self._add_fn(fields)
        except Exception as exc:
            self.query_one("#lib-status", Static).update(f"[dim #d95841]Add failed: {exc}[/]")
            return
        if added is None:
            # no creature selected — warn and stay open
            self._warn_fn()
            return
        self.query_one("#lib-status", Static).update(
            f"[dim #3fae6a]Added {added} — press [bold]Esc[/] when done[/]"
        )
        lv = self.query_one("#lib-list", ListView)
        if lv.index is None and self._current:
            lv.index = 0

    def action_fetch_srd(self) -> None:
        self.query_one("#lib-status", Static).update("[dim #a8d0ff]Fetching SRD spells…[/]")
        try:
            self._fetch_fn()
        except Exception:
            pass

    def update_srd(self, data: list[dict]) -> None:
        self._spells = list(data or [])
        self._rebuild()

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
                "  [bold]Enter[/]/[bold]a[/] attack   [bold]d[/]/[bold]h[/] type damage/heal\n"
                 "  [bold]c[/] condition   [bold]C[/] campaigns   [bold]m[/] monster   [bold]x[/] remove\n"
                 "  [bold]b[/] monster library   [bold]v[/] spellbook   [bold]r[/] roll init   [bold]t[/] set init   [bold]shift+r[/] reset\n"
                "  [bold]i[/] import PC   [bold]f[/] find   [bold]e[/] edit   [bold]p[/] add PC\n"
                "  [bold]ctrl+n[/] new encounter   [bold]?[/] help   [bold]q[/] quit   [bold]ctrl+p[/] palette\n"
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


class ImportingModal(ModalScreen[None]):
    """Shown while a D&D Beyond fetch is in flight so keystrokes don't leak
    through into the live encounter (the fetch runs on a background thread)."""

    def compose(self) -> ComposeResult:
        with Container(classes="modal-box"):
            yield Static("[bold #a8d0ff]Importing character…[/]", classes="modal-title")
            yield Static("[dim]Contacting D&D Beyond — one moment.[/]", classes="modal-hint")