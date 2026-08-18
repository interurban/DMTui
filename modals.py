"""Modal screens for Ward — a number prompt, a pick list, a
text prompt, and the help screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static, TextArea
from rich.markup import escape


def _menu_entry(key: str, label: str) -> ListItem:
    """Build a folio-style menu row with room for an optional detail line."""
    classes = ["menu-entry"]
    if "\n" in label:
        classes.append("menu-entry-two-line")
    if key in {"back", "cancel", "quit"}:
        classes.append("menu-entry-quiet")
    return ListItem(
        Label(label, classes="modal-item"),
        classes=" ".join(classes),
    )


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

    def __init__(
        self,
        title: str,
        options: list[tuple[str, str]],
        *,
        wide: bool = False,
        compact: bool = False,
    ) -> None:
        super().__init__()
        self._title = title
        self._options = options
        self._wide = wide
        self._compact = compact

    def compose(self) -> ComposeResult:
        classes = ["modal-box"]
        if self._wide:
            classes.append("wide-modal")
        if self._compact:
            classes.append("compact-modal")
        with Container(classes=" ".join(classes)):
            yield Static(f"[bold #e6ebf2]{self._title}[/]", classes="modal-title")
            yield ListView(
                *[_menu_entry(key, label) for key, label in self._options],
                id="modal-list",
            )
            yield Static(
                "↑↓ move   Enter choose   Esc back",
                classes="modal-hint",
            )

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


class StartModal(ModalScreen[str]):
    """A direct choice of how to begin or resume play."""

    BINDINGS = [("escape", "quit", "Quit")]

    def __init__(
        self,
        options: list[tuple[str, str]],
        subtitle: str,
        prompt: str = "Where do you want to begin?",
    ) -> None:
        super().__init__()
        self._options = options
        self._subtitle = subtitle
        self._prompt = prompt

    def compose(self) -> ComposeResult:
        with Container(classes="modal-box startup-box"):
            yield Static(
                "[bold #a8d0ff]WARD[/]  [#566172]╱[/]  [bold #c9d3e0]DM'S FOLIO[/]",
                classes="modal-title startup-title",
            )
            yield Static(
                f"[bold #e6ebf2]{self._prompt}[/]\n[#8a93a3]{self._subtitle}[/]",
                classes="startup-intro",
            )
            yield Static("CHOOSE A PATH", classes="menu-kicker")
            yield ListView(
                *[_menu_entry(key, label) for key, label in self._options],
                id="modal-list",
            )
            yield Static(
                "↑↓ move   Enter open   Esc quit",
                classes="modal-hint",
            )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        index = event.list_view.index
        if index is not None and 0 <= index < len(self._options):
            self.dismiss(self._options[index][0])

    def action_quit(self) -> None:
        self.dismiss("quit")


class PartyImportModal(ModalScreen[str | None]):
    """Edit a campaign roster using D&D Beyond references or plain names."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, campaign_name: str = "", initial: str = "", first_run: bool = False) -> None:
        super().__init__()
        self._campaign_name = campaign_name
        self._initial = initial
        self._first_run = first_run

    def compose(self) -> ComposeResult:
        title = "ADD YOUR PARTY" if self._first_run else "EDIT PARTY"
        if self._campaign_name:
            title += f" · {escape(self._campaign_name)}"
        with Container(classes="modal-box party-import-box"):
            yield Static(f"[bold #e6ebf2]{title}[/]", classes="modal-title")
            yield Static("[dim]One adventurer per line · D&D Beyond link, character ID, or name.[/]")
            yield TextArea(
                self._initial,
                id="party-import-input",
                placeholder="https://www.dndbeyond.com/characters/12345678\nMara Stonehand\nTovin Reed",
            )
            with Horizontal(classes="modal-buttons"):
                yield Button("Review party", variant="primary", id="import")
                yield Button("Cancel", id="cancel")
            yield Static("[dim][bold]Tab[/] moves to Review party · [bold]Esc[/] back[/]", classes="modal-hint")

    def on_mount(self) -> None:
        self.query_one("#party-import-input", TextArea).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "import":
            self.dismiss(self.query_one("#party-import-input", TextArea).text.strip() or None)
        elif event.button.id == "cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class PartyPreviewModal(ModalScreen[str]):
    """Review a campaign party before remembering it."""

    BINDINGS = [("enter", "remember", "Remember"), ("escape", "cancel", "Cancel")]

    def __init__(self, party_name: str, lines: list[str], has_failures: bool) -> None:
        super().__init__()
        self._party_name = party_name
        self._lines = lines
        self._has_failures = has_failures

    def compose(self) -> ComposeResult:
        status = " [dim]· some entries failed[/]" if self._has_failures else ""
        with Container(classes="modal-box party-import-box"):
            yield Static(f"[bold #e6ebf2]PARTY FOR {escape(self._party_name)}[/]{status}", classes="modal-title")
            yield Static("\n".join(self._lines))
            with Horizontal(classes="modal-buttons"):
                yield Button("Remember party", variant="primary", id="remember")
                yield Button("Back", id="cancel")
            yield Static("[dim][bold]Enter[/] remember · [bold]Esc[/] back[/]", classes="modal-hint")

    def action_remember(self) -> None:
        self.dismiss("remember")

    def action_cancel(self) -> None:
        self.dismiss("cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "remember":
            self.dismiss("remember")
        elif event.button.id == "cancel":
            self.dismiss("cancel")


class EncounterPreviewModal(ModalScreen[str]):
    """Preview an assisted suggestion before it changes the live encounter."""

    BINDINGS = [
        ("enter", "accept", "Add encounter"),
        ("r", "regenerate", "Regenerate"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, plan: dict, lines: list[str]) -> None:
        super().__init__()
        self._plan = plan
        self._lines = lines

    def compose(self) -> ComposeResult:
        title = str(self._plan.get("title") or "ENCOUNTER SUGGESTION").upper()
        theme = str(self._plan.get("theme") or "")
        pressure = str(self._plan.get("pressure") or self._plan.get("difficulty") or "Unknown")
        detail = (
            f"[dim]{theme}[/]\n[bold #a8d0ff]Rough pressure:[/] {pressure}  "
            "[dim]DM judgment, not balancing[/]\n\n" + "\n".join(self._lines)
        )
        with Container(classes="modal-box"):
            yield Static(f"[bold #e6ebf2]{title}[/]", classes="modal-title")
            yield Static(detail)
            yield Static(
                "[dim][bold]Enter[/] add · [bold]r[/] regenerate · [bold]Esc[/] cancel[/]",
                classes="modal-hint",
            )

    def action_accept(self) -> None:
        self.dismiss("add")

    def action_regenerate(self) -> None:
        self.dismiss("regenerate")

    def action_cancel(self) -> None:
        self.dismiss(None)


class GeneratingModal(ModalScreen[None]):
    """Block input while an encounter suggestion is being generated."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Container(classes="modal-box"):
            yield Static("[bold #a8d0ff]Building encounter…[/]", classes="modal-title")
            yield Static("[dim]Choosing existing monster statblocks — one moment.[/]")

    def action_cancel(self) -> None:
        self.dismiss(None)


class ScratchpadModal(ModalScreen[str | None]):
    """A deliberately small multiline campaign scratchpad."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._text = text

    def compose(self) -> ComposeResult:
        with Container(classes="modal-box scratchpad-box"):
            yield Static("[bold #e6ebf2]CAMPAIGN SCRATCHPAD[/]", classes="modal-title")
            yield TextArea(self._text, id="scratchpad-input", placeholder="Notes for the next session…")
            with Horizontal(classes="modal-buttons"):
                yield Button("Remember", variant="primary", id="remember")
                yield Button("Cancel", id="cancel")
            yield Static("[dim]Ctrl+Enter or Remember · Esc cancel[/]", classes="modal-hint")

    def on_mount(self) -> None:
        self.query_one("#scratchpad-input", TextArea).focus()

    def on_key(self, event) -> None:
        if event.key == "ctrl+enter":
            event.stop()
            self._save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "remember":
            self._save()
        else:
            self.dismiss(None)

    def _save(self) -> None:
        self.dismiss(self.query_one("#scratchpad-input", TextArea).text)

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
        with Container(classes="modal-box help-modal"):
            yield Static(
                "[bold #a8d0ff]WARD[/]  [#8a93a3]A PRIVATE, TABLE-SIDE TOOL FOR THE DM[/]\n"
                "[#8a93a3]Ward remembers volatile state and retrieves references.\n"
                "Your physical table and your rulings remain authoritative.[/]\n\n"
                "[bold #a8d0ff]RUN THE ENCOUNTER[/]\n"
                "  [bold]↑↓ / k j[/]: select   ·   [bold]←→[/]: adjust HP\n"
                "  [bold]n[/]: next turn   ·   [bold]shift+i[/]: initiative pass   ·   [bold]+[/]: duplicate monster\n"
                "  [bold]Enter / a[/]: attack   ·   [bold]d / h[/]: damage / heal; type amount, Enter applies\n"
                "  [bold]c[/]: condition   ·   [bold]r[/]: monster init   ·   [bold]t[/]: type init   ·   [bold]u / shift+u[/]: undo / redo\n\n"
                "[bold #a8d0ff]REFERENCE[/]\n"
                "  [bold]s[/]: cycle Combat / DM Screen / Party   ·   [bold]Ctrl+1/2/3[/]: choose directly\n"
                "  [bold]/[/]: quick lookup   ·   [bold]/roll 2d6+4[/]: local roll   ·   [bold]f[/]: find creature or map note\n\n"
                "[bold #a8d0ff]PREPARE AND ADJUST[/]\n"
                "  [bold]m[/]: quick monster   ·   [bold]ctrl+m[/]: library   ·   [bold]v[/]: spellbook\n"
                "  [bold]i[/]: import PC   ·   [bold]p[/]: add PC   ·   [bold]e[/]: edit   ·   [bold]x[/]: remove\n"
                "  [bold]shift+e[/]: encounter assistant (rough suggestion)   ·   [bold]ctrl+e[/]: monster setups\n"
                "  [bold]ctrl+n[/]: another encounter   ·   [bold]shift+r[/]: reset encounter\n\n"
                "[bold #a8d0ff]CAMPAIGN AND WARD DATA[/]\n"
                "  [bold]shift+c[/]: campaign folio, encounters, party, notes, backup and restore\n"
                "  [bold]shift+p[/]: soundtrack controls   ·   Ward remembers live encounters automatically.\n"
                "  [bold]?[/]: help   ·   [bold]q[/]: quit\n\n"
                "[dim]The map is a quick note that mirrors the physical table—not a virtual tabletop.\n"
                "Click to select; [bold]g[/] grabs and arrows place. Blue = PC · red = monster.[/]",
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
            yield Static("[bold #a8d0ff]IMPORTING PARTY[/]", classes="modal-title")
            yield Static("[dim]Reading characters from D&D Beyond…[/]", classes="modal-hint")
