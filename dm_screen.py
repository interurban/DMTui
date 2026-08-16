"""Curated, glanceable 5e reference content for the table-side DM Screen."""

# Content deliberately omits panel titles: the four panel chrome headers are
# the titles, so repeating them here wastes the first line of every reference.
DM_SCREEN_PANELS = {
    "timing": (
        "[bold #c678dd]REACTION[/]      One per round; refreshes at turn start.\n"
        "[bold #c678dd]READY[/]         Declare trigger + action; uses reaction.\n"
        "[bold #c678dd]READIED SPELL[/] Requires concentration; cast when trigger fires.\n"
        "[bold #c678dd]BONUS ACTION[/]  Only one; a feature must grant it.\n"
        "[bold #c678dd]OBJECT[/]        One simple interaction is usually free.\n\n"
        "[bold #c678dd]MOVEMENT[/]\n"
        "  Split movement around actions; difficult terrain costs 2/1.\n"
        "  Stand from prone: half your speed.\n\n"
        "[bold #c678dd]HIDING / SIGHT[/]\n"
        "  Heavy obscurement blocks sight; unseen attacks have [bold]ADV[/].\n"
        "  An attack usually reveals the attacker's position.\n\n"
        "[bold #c678dd]TRIGGERS[/]     Resolve the trigger before the reaction."
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
        "[bold #e0c04c]STUNNED[/]       Incapacitated · auto-fail STR/DEX saves\n"
        "[bold #e0c04c]UNCONSCIOUS[/]   Incapacitated · prone · auto-fail STR/DEX saves"
    ),
    "combat": (
        "[bold #c678dd]COVER[/]\n"
        "  [bold #e0c04c]½[/]             +2 AC / DEX saves\n"
        "  [bold #e0c04c]¾[/]             +5 AC / DEX saves\n"
        "  [bold #e0c04c]TOTAL[/]         Can't be targeted directly\n\n"
        "[bold #c678dd]OPPORTUNITY ATTACK[/]\n"
        "  Trigger: visible creature leaves reach.\n"
        "  Disengage prevents it; forced movement doesn't.\n\n"
        "[bold #c678dd]CONCENTRATION[/]\n"
        "  Damage: CON save, [bold #e0c04c]DC 10 or half damage[/], higher wins.\n\n"
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
