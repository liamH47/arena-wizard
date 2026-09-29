"""Role labels for real SOS and HOB cards, assigned by reading each card's rules text.

Each label records a judgment about what the card does in a limited deck; the classifier
must agree. Borderline calls are noted: 1-damage pings and 7-mana activated removal count
as removal; -1/-1 effects, "draw a card" cantrips, and trample alone do not count.
"""

from __future__ import annotations

import pytest

from arena_wizard.catalog import load_packaged_card_table
from arena_wizard.engine.roles import Role, classify

C, L, R, A, F, E, T = (
    Role.CREATURE,
    Role.LAND,
    Role.REMOVAL,
    Role.CARD_ADVANTAGE,
    Role.FIXING,
    Role.EVASIVE,
    Role.COMBAT_TRICK,
)

LABELS = [
    ("SOS", "Last Gasp", {R}),  # target creature gets -3/-3
    ("SOS", "Erode", {R}),  # destroy target creature or planeswalker
    ("SOS", "Harsh Annotation", {R}),
    ("SOS", "Chelonian Tackle", {R}),  # fight, at sorcery speed: not a trick
    ("SOS", "Dissection Practice", {T}),  # the -1/-1 mode is too small to be removal
    ("SOS", "Glorious Decay", {R}),  # 4 damage to a flier; its draw is a cantrip
    ("SOS", "Tome Blast", {R}),
    ("SOS", "Quandrix Charm", set()),  # counter-unless, enchantment removal, base 5/5
    ("SOS", "Stormcarved Coast", {L, F}),
    ("SOS", "Social Snub", {R}),  # each player sacrifices a creature
    ("SOS", "Abigale, Poet Laureate", {C, E}),
    ("SOS", "Elite Interceptor", {C}),  # its prepared spell draws only one card
    ("SOS", "Rancorous Archaic", {C}),  # reach and trample are not evasion here
    ("SOS", "Stock Up", {A}),  # two of the top five into your hand
    ("SOS", "Mathemagics", {A}),  # draws 2^X cards
    ("SOS", "Duel Tactics", {R}),  # 1 damage: borderline, counted
    ("HOB", "Stone by Sunlight", {R}),
    ("HOB", "Pinecone Strike", {R}),
    ("HOB", "Front Porch Sentries", {C}),  # dies trigger is only -1/-1
    ("HOB", "Enchanted River's Grasp", {R}),  # doesn't untap, loses abilities
    ("HOB", "Warg Tactics", {R}),  # destroy target creature with flying
    ("HOB", "Giant's Boulder", {R, F}),  # any-color mana; 7-mana destroy counted
    ("HOB", "Troll Negotiations", {R}),
    ("HOB", "Bofur, Reliable Guardian", {C}),
    ("HOB", "The Lonely Mountain", {L}),  # taps for red only: not fixing
    ("HOB", "Crude Bent Blade", {R}),  # opponent sacrifices a creature
    ("HOB", "Smaug, the Great Calamity", {C, E, R}),  # its adventure deals 5
]


@pytest.mark.parametrize(("set_code", "name", "roles"), LABELS)
def test_the_classifier_agrees_with_the_hand_label(
    set_code: str, name: str, roles: set[Role]
) -> None:
    card = next(c for c in load_packaged_card_table(set_code).cards if c.front_name == name)
    assert classify(card) == roles
