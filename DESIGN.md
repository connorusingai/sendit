# Stomped design: "Gloss + Edge"

Locked 2026-10-24 (Connor: "yes thats better"). Reference mockup: style E in `prototype/style-compare.html`
(https://claude.ai/artifact/Jf6t6ZCAGFWCmTcwowZ3yU). Inspiration: Liftoff's glossy rank badges, made edgier.
Do not copy Liftoff's layout or features. Every screen gets built to this file; if something here is wrong, change this file first.

## Feel
A polished game with a ski-edit attitude. Glossy rewards on a dark, gritty base. Not cartoon, not a website.

## Color
| Token | Hex | Use |
|---|---|---|
| bg | #0a0b10 | page, near-black with a cool tint |
| panel | #15161d | flat panels |
| line | #1d1f28 | dividers |
| ink | #eef1f7 | main text |
| mute | #80849a | secondary text |
| hot | #ff5a1f | the one accent: DROP IN, stamps, 2x, trick of the day edge |
| bail | #5d6070 | bailed stamp, disabled |

Tier colors live only on rank badges and rank glows:
Bronze #c8793a · Silver #aab4c2 · Gold #f2b81f · Platinum #2fc4ac · Diamond #7d70ff · Legend #e96ae0.

## Type
- Display: **Big Shoulders Display 900**, uppercase, italic for rank names and trick names.
- UI/body: **Figtree 400–700** (what the app has used since day 1).
- Labels and numbers: **JetBrains Mono 700**, 10–11px, letter-spacing .12em, uppercase ("CREW / LAST 24H").

## Shapes
- Cut corners, not round ones: clip-path bevels on panels and buttons. Radius only on avatars.
- Angled (skewed -20°) progress bars with a glow in the tier color.
- Accent edge: a 3px `hot` left border marks the featured panel (trick of the day).
- Light film grain over the whole screen (opacity ~.14).

## Badges (the main art)
- A shield with blade wings and a dark rim, glossy facets (light top, mid, dark bottom), and a white core.
- A glow drop-shadow in the tier color on large badges.
- The code version is `#blade` in the mockup. For the real app, make polished PNG/SVG files per tier (6 tiers × large/small).

## Motion (where the game feel lives)
- Rank badge pops in (scale .4 → 1, overshoot).
- Progress bar fills on load (1.2s ease-out).
- STOMPED stamp slams onto the newest crew trick (scale 2.4 → 1, rotated -6°).
- Buttons press down on tap. Respect prefers-reduced-motion.

## Home (Base) layout
1. Top bar: logo, streak, points.
2. Rank hero: big badge + rank name + angled bar + "N pts to next".
3. Trick of the day panel (hot edge, 2x).
4. Crew / last 24h: each row = small rank badge, @name, trick + place, STOMPED/BAILED stamp.
5. DROP IN button (hot, bevelled) above the tab bar.

## Never
- No cartoon rider in the middle, no drawn scenery, no looped video background.
- No rounded "card everywhere" look, no emoji as icons, no second accent color.
