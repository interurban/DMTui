"""Curated, glanceable 5e reference content for the table-side DM Screen."""

DM_SCREEN_PANELS = {
    "actions": (
        "[bold #a8d0ff]COMMON ACTIONS[/]\n\n"
        "Attack       Action\n"
        "Dash         Action\n"
        "Disengage    Action\n"
        "Dodge        Action\n"
        "Help         Action\n"
        "Hide         Action\n"
        "Ready        Action\n"
        "Search       Action\n"
        "Use Object   Action\n\n"
        "Bonus action / reaction are available\n"
        "only when a feature gives you one."
    ),
    "conditions": (
        "[bold #a8d0ff]CONDITIONS[/]\n\n"
        "Blinded       attacks against adv; attacks out disadv\n"
        "Charmed       can't attack charmer; charmer adv social\n"
        "Frightened    disadv while source is visible; can't approach\n"
        "Grappled      speed 0; ends if grappler is incapacitated\n"
        "Incapacitated can't take actions or reactions\n"
        "Invisible     heavily obscured; attacks adv / disadv\n"
        "Paralyzed     incapacitated; auto-fail STR/DEX saves\n"
        "Poisoned      disadv attacks and ability checks\n"
        "Prone         attacks against melee adv, ranged disadv\n"
        "Restrained    speed 0; attacks disadv; DEX saves disadv\n"
        "Stunned       incapacitated; auto-fail STR/DEX saves\n"
        "Unconscious   incapacitated; prone; auto-fail STR/DEX saves"
    ),
    "combat": (
        "[bold #a8d0ff]COMBAT QUICK RULES[/]\n\n"
        "Cover\n"
        "  Half       +2 AC and DEX saves\n"
        "  Three-fourths +5 AC and DEX saves\n"
        "  Total      can't be targeted directly\n\n"
        "Opportunity attack\n"
        "  Trigger: a visible creature leaves reach.\n"
        "  Disengage prevents it; forced movement doesn't trigger it.\n\n"
        "Concentration\n"
        "  On damage: CON save, DC 10 or half damage, whichever is higher.\n\n"
        "Death saves\n"
        "  10+ success · 9− failure · nat 20 regain 1 HP\n"
        "  nat 1 counts as two failures · 3 successes stabilize"
    ),
    "rolls": (
        "[bold #a8d0ff]DCs / ROLLS[/]\n\n"
        "DC 5   Very easy\n"
        "DC 10  Easy\n"
        "DC 15  Medium\n"
        "DC 20  Hard\n"
        "DC 25  Very hard\n"
        "DC 30  Nearly impossible\n\n"
        "Advantage / disadvantage\n"
        "  Multiple sources do not stack. One of each cancels.\n\n"
        "Attack roll\n"
        "  d20 + attack bonus vs AC\n"
        "  Natural 20 hits and crits; natural 1 always misses\n\n"
        "Ability check / save\n"
        "  d20 + ability modifier (+ proficiency when applicable)"
    ),
}


def panel_text(name: str) -> str:
    """Return a known panel or a useful empty state for future modes."""
    return DM_SCREEN_PANELS.get(name, "[dim]No reference available.[/]")
