"""Curated, glanceable 5e reference content for the table-side DM Screen."""

# Content deliberately omits panel titles: the four panel chrome headers are
# the titles, so repeating them here wastes the first line of every reference.
DM_SCREEN_PANELS = {
    "numbers": (
        "[bold #c678dd]FALLING[/]\n"
        "  [bold #e0c04c]1d6 / 10 ft[/] · max 20d6\n"
        "  Land prone unless no damage taken\n\n"
        "[bold #c678dd]CONCENTRATION[/]\n"
        "  CON save: [bold #e0c04c]DC 10 or ½ damage[/], higher wins\n"
        "  Separate save for each source of damage\n\n"
        "[bold #c678dd]HEALING POTIONS[/]\n"
        "  Healing       [bold #e0c04c]2d4 + 2[/]\n"
        "  Greater       [bold #e0c04c]4d4 + 4[/]\n"
        "  Superior      [bold #e0c04c]8d4 + 8[/]\n"
        "  Supreme       [bold #e0c04c]10d4 + 20[/]\n\n"
        "[bold #c678dd]PASSIVE CHECKS[/]\n"
        "  Passive = [bold #e0c04c]10 + modifier[/]\n"
        "  Advantage [bold #3fae6a]+5[/] · Disadvantage [bold #d95841]−5[/]\n\n"
        "[bold #c678dd]OBJECT AC[/]\n"
        "  Cloth/paper [bold #e0c04c]11[/]  ·  Wood/bone [bold #e0c04c]15[/]\n"
        "  Stone [bold #e0c04c]17[/]        ·  Iron/steel [bold #e0c04c]19[/]\n\n"
        "[bold #c678dd]IMPROVISED DAMAGE[/]\n"
        "  Minor [bold #e0c04c]1d10[/] · Dangerous [bold #e0c04c]2d10[/] · Deadly [bold #e0c04c]4d10+[/]"
    ),
    "conditions": (
        "[bold #e0c04c]BLINDED[/]       Against: [bold]ADV[/] · yours: [bold]DISADV[/]\n"
        "[bold #e0c04c]CHARMED[/]       Can't harm charmer · social [bold]ADV[/]\n"
        "[bold #e0c04c]FRIGHTENED[/]    Source visible: [bold]DISADV[/] · can't approach\n"
        "[bold #e0c04c]GRAPPLED[/]      Speed [bold]0[/] · ends if grappler incapacitated\n"
        "[bold #e0c04c]INCAPACITATED[/] Can't take actions or reactions\n"
        "[bold #e0c04c]INVISIBLE[/]     Heavily obscured · attacks [bold]ADV[/]/[bold]DISADV[/]\n"
        "[bold #e0c04c]PARALYZED[/]     Incapacitated · auto-fail STR/DEX saves\n"
        "[bold #e0c04c]POISONED[/]      Attacks and checks [bold]DISADV[/]\n"
        "[bold #e0c04c]PRONE[/]         Melee against: [bold]ADV[/] · ranged: [bold]DISADV[/]\n"
        "[bold #e0c04c]RESTRAINED[/]    Speed [bold]0[/] · attacks/DEX saves [bold]DISADV[/]\n"
        "[bold #e0c04c]STUNNED[/]       Incap. · auto-fail STR/DEX saves\n"
        "[bold #e0c04c]UNCONSCIOUS[/]   Incap. · prone · auto-fail STR/DEX saves"
    ),
    "combat": (
        "[bold #c678dd]COVER[/]\n"
        "  [bold #e0c04c]½[/]             +2 AC / DEX saves\n"
        "  [bold #e0c04c]¾[/]             +5 AC / DEX saves\n"
        "  [bold #e0c04c]TOTAL[/]         Can't be targeted directly\n\n"
        "[bold #c678dd]OPPORTUNITY ATTACK[/]\n"
        "  Trigger: visible creature leaves reach.\n"
        "  Disengage prevents it; forced movement doesn't.\n\n"
        "[bold #c678dd]DEATH SAVES[/]\n"
        "  [bold #3fae6a]10+[/] success · [bold #d95841]9−[/] failure · nat 20: regain 1 HP\n"
        "  nat 1: two failures · [bold #3fae6a]3 successes[/] stabilize"
    ),
    "rolls": (
        "[bold #c678dd]DIFFICULTY CLASS[/]\n"
        "  [bold #e0c04c]DC 5[/]   Very easy\n"
        "  [bold #e0c04c]DC 10[/]  Easy\n"
        "  [bold #e0c04c]DC 15[/]  Medium\n"
        "  [bold #e0c04c]DC 20[/]  Hard\n"
        "  [bold #e0c04c]DC 25[/]  Very hard\n"
        "  [bold #e0c04c]DC 30[/]  Nearly impossible\n\n"
        "[bold #c678dd]ADVANTAGE / DISADVANTAGE[/]\n"
        "  Sources don't stack; one of each cancels.\n\n"
        "[bold #c678dd]ATTACK ROLL[/]\n"
        "  d20 + attack bonus vs AC\n"
        "  nat 20 hits and crits · nat 1 always misses\n\n"
        "[bold #c678dd]CHECK / SAVE[/]\n"
        "  d20 + ability modifier (+ proficiency if applicable)"
    ),
}


def panel_text(name: str) -> str:
    """Return a known panel or a useful empty state for future modes."""
    return DM_SCREEN_PANELS.get(name, "[dim]No reference available.[/]")
