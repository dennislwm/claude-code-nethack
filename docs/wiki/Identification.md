Source: https://nethackwiki.com/wiki/Identification

# Identification

## Overview

In *NetHack*, **identification** refers to the process of determining an item's properties and characteristics. The mechanic is considered "one of the game's most core aspects" since players must distinguish useful items from dangerous ones.

## Mechanics of Identification

Items can be identified by qualities such as type, beatitude, and enchantment. Multiple methods exist—both formal (directly stated by the game) and informal (requiring player knowledge). Many items feature randomized appearances that differ between playthroughs.

## Straightforward Identification

These methods are universal, don't require naming, and result in formal identification:

### Initial Knowledge
Starting items are automatically identified. Wizards begin with identified spellbooks, scrolls, rings, and wands. Role-based weapon and armor knowledge may also apply.

### Scroll of Identify
Reading this scroll identifies items based on its beatitude:

| Beatitude | 1 Item | 2 Items | 3 Items | 4 Items | Everything |
|-----------|--------|---------|---------|---------|------------|
| Blessed | 1/5* | 1/5 | 1/5 | 1/5 | 1/5 |
| Uncursed | 21/25 | 1/25 | 1/25 | 1/25 | 1/25 |
| Cursed | Always | Never | Never | Never | Never |

*With positive Luck, identifies two items instead of one.

### Spell of Identify
Casting this divination spell equals reading an uncursed scroll (Unskilled/Basic) or blessed scroll (Skilled/Expert).

### Sitting on a Throne
One possible throne effect mimics reading a blessed scroll of identify.

### Touchstone
A blessed touchstone formally identifies gems, glass, and gray stones. Gnomes and archaeologists may use uncursed touchstones. This method doesn't reveal BUC status.

### Selling in Shops
Shopkeepers reveal item appearance. Items with unique, non-randomized appearances (most armor and weapons) become formally identified.

### Type Identification

**Formal type identification** (auto-identification) displays items by proper names, overriding their appearance.

**Informal with prompt**: Sometimes players are prompted to name item types after use, such as when potions are thrown by monsters or rings dropped in sinks.

**Informal without prompt**: Some effects unambiguously identify items to experienced players without auto-identification, like engraving with wands or price-based identification.

### Individual Object Identification
Each object has properties: BUC status (except gold), erodeproofness (weapons/armor), and enchantment/charges (weapons, armor, wands, some rings/tools).

Stackable items with different identification statuses won't merge, even if their BUC/enchantment matches.

## Indirect Identification

These methods require external knowledge and may not result in formal identification:

### Price Identification
Shopkeeper prices vary by charisma and randomization. Selling prices prove most helpful for categorizing rings, potions, and wands. The "cheapest of the scrolls" identifies scroll of identify.

### Weight Identification
While less useful than price, weight provides clues. Examples include levitation boots (unique within price groups) and loadstones in large boxes.

Weight testing: Carry rocks and gold to near-burden, add the object, then count items dropped to relieve burden.

### Behavior Identification

**Passive identification**: Discovering item properties without auto-identifying them. For example, zapping an unidentified wand of cancellation at a dragon reveals its identity through the dragon's cough, but the randomized appearance persists.

**Identification by using**:
- Some items auto-identify when worn, quaffed, or used (boots of speed, elven cloak)
- Others require time to notice (ring of slow digestion)
- Some identify when special events occur (resistance rings, amulet of reflection)

**Safety precautions**: Check beatitude with pets or altars. Test potions using unicorn horns. Avoid reading unidentified scrolls when confused or wearing precious armor.

**Easily identifiable items**:
- **Cloaks**: Most magical cloaks auto-ID when worn (except magic resistance and invisibility cloaks for invisible characters)
- **Boots**: Fumble boots and levitation boots are usually cursed; elven and speed boots auto-ID; jumping boots are trivial to identify
- **Whistles**: Blowing identifies them; magic whistles auto-ID when affecting pets

**Identification by monster use**: Humanoids use certain items. Amulets of life saving auto-identify when resurrecting them. Monsters quaff beneficial potions and throw harmful ones. They read certain scrolls and zap attack wands or use polymorph/speed/invisibility/teleportation wands on themselves.

### Wand Engrave Identification
Engrave something in dust, then engrave again with the wand on the same square. Nine wands are unambiguously identified this way; others give ambiguous results. Charges aren't revealed except that one was spent. Zero-charge wands show no effect.

### Dropping Rings in Sinks
This method unambiguously identifies most rings but destroys them. Useful for duplicate rings or when desperately seeking ring of slow digestion (which survives the sink).

### Monster Inventory Identification
Certain monsters possess specific items. Nymphs often have potion of object detection; elves carry elven cloaks and boots.

## Related Topics

- **Curse testing**: Determines BUC status of individual items

## External Resources

- The NetHack Object Identification Spoiler (version 3.4.3, largely accurate for current versions)

---

**Status**: Updated for NetHack 3.6.0; may need updates for current versions.
