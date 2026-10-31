# Stomped design: "the ski edit"

Locked 2026-10-28 (Connor's picks, `../sendit-splash/BRAND-DECISIONS.md`). Mock: "FINAL picks" page of
https://claude.ai/artifact/6fy5qomGP5Kx13kcqoHRu2. Replaces "Gloss + Edge" (dark, shields, metal ranks).
Every screen follows this file. If something here is wrong, change this file first.

## Feel
A friend's ski edit on a phone: cool snow, a camcorder REC corner, one orange stamp. Chill park rat, not a game HUD.

## Color
| Token | Hex | Use |
|---|---|---|
| snow | #edf1f4 | page background, with faint film grain over everything (opacity .08) |
| paper | #f7f9fa | tab bar, sheets, inputs' surroundings |
| ink | #111316 | text, dark screens (feed, judge, camera) |
| mute | #5b6168 | secondary text (5.5:1 on snow) |
| line | #cfd6dc | hairline rules between rows |
| hot | #ff5a1f | the ONE accent: Film it, Landed, Collect, the STOMPED stamp, active tab underline |
| rec | #ff3b1f | the REC dot only |

Tier colors live only on season passes and their trail marks (see below). Never a second accent.

## Type
- Display: **Archivo** at width 125%, weight 800-900, lowercase ("land it. prove it.", "landed or bailed?", "your bag").
- Wordmark: **STOMPED**, all caps, Archivo 900 wide.
- UI/body: **Figtree** 400-700.
- **JetBrains Mono 700** only for the REC timecode and numbers on passes (840 / 1,000 PTS, NO. 0042). Not for labels.

## Film bits
- REC dot + timecode (`REC 00:00:07`) top-left on clips, the camera and the reward.
- Camcorder corner brackets on clips and photos (the `brk` element).
- The **STOMPED stamp**: rough orange ink box, rotated about -7°, on landed clips, the reward, the contact sheet and
  shared exports. Bails get a grey BAILED stamp.

## Season pass (the rank)
A modern RFID-style card (340 × 214): tier gradient, faint topo lines + two ridge silhouettes, a light sheen,
STOMPED + season (26/27) on top, the tier's trail mark, the tier name, @handle, an ID photo the rider picks
(REC dot + brackets on it, blank until they pick one), a progress bar, points to the next tier, "NO. 0042 · ELDORA".

| Tier | Points | Mark | Card | Foil edge |
|---|---|---|---|---|
| green | 0 | ● | #34b36c → #155e38 | none |
| blue | 100 | ■ | #4386ea → #173f94 | none |
| black | 300 | ◆ | #363c43 → #131518 | none |
| double black | 600 | ◆◆ | #2c3137 → #0d0f11 | silver |
| triple black | 1000 | ◆◆◆ | #25292e → #070809 + holo sheen | gold |
| park rat | 1500 | orange park-sign oval | #1d2024 → #060708 + holo sheen, orange topo + name | orange |

- No divisions (no I/II/III). Names are just the color, never "green circle".
- Old ranks map 1:1 on the same thresholds: Bronze→green, Silver→blue, Gold→black, Platinum→double black,
  Diamond→triple black, Legend→park rat.
- **Season reset (soft):** on opening day everyone drops about one tier (`start_season()` in supabase/024) and last
  season's pass stays on the profile as a trophy.
- **Rank-up:** dark screen. The pass lifts and taps the TAP PASS reader, the light turns green with a flash, the gate beep
  (placeholder until Connor records the real one, to-do #10: drop it in `app/sounds/gate.mp3`) and a vibration (only with
  sounds on), then a scan line sweeps across and the SAME pass becomes the next tier, and RANK UP slams on. No new card.
  About 5s; a tap skips to the end. The reward before it shows the rank you're leaving.
- No real brands (Ikon, Red Bull...) anywhere.

## Layout
Tabs: **base / feed / record / crew / me** (record = orange dot in a ring, in the middle).
- **Base:** your pass big at the top → today's trick as one line + Film it → "N clips need your call" → your week in
  3 numbers (landed, bailed, #rank at your mountain). No clip replays on Base.
- **Feed:** full screen, one clip at a time, REC + brackets, tabs = your mountain / crew / CU. A clip that still needs
  calls shows Bailed / Landed right on it; the rider's name stays hidden until you call it (judging stays fair).
- **Judge:** video on top, a thin progress line, then "@rider · trick · mountain", "landed or bailed?", two 64px
  buttons, "Your call is anonymous." + Skip.
- **Reward:** your clip, the STOMPED stamp slams on, +points huge, the bar to your next pass, Collect (60px).
- **Crew:** "eldora, this week", tabs mountain / CU / friends (+ crews), a podium of the top-3 passes, then the list.
  Below: friends / your crew / duels.
- **Me:** your pass, 6 stats, "your bag" (landed tricks solid, next ones dashed), then your clips as a contact sheet
  with STOMPED / BAILED stamps. Settings live behind the gear.
- **Landing:** Connor's backflip full-bleed with REC + the stamp, "land it. prove it.", Make an account.
- **First run:** ski or snowboard → home mountain (picked at signup from the short list) → call 3 clips → green pass.

## Glove-proof
Main moves are **at least 56px tall with real gaps** (12px+): Film it, Landed / Bailed (64 on Judge), Collect (60),
Post / Retake, Keep it, the shutter (80). Everything else that's tappable is at least 44px.

## Shapes + motion
- Flat. Hairline rules between rows, not cards everywhere. 4px corners on buttons, 6px on the few cards.
- Stamps slam in (scale 2.2 → 1), the pass scans, the reward shakes once. Respect prefers-reduced-motion.

## Voice
Chill park rat: short, lowercase, like texting your crew ("stomped. +140 pts", "needs your call. what's yours?").
No hype words, no emoji spam.

## Never (no AI tells)
No glow, no floating particles, no confetti, no little code-font labels, no gradient text, no second accent,
no cartoon rider, no shields.

## App icon
Connor's ski-run S (2026-10-28 pick), recolored: safety-orange S + frame, ink mountains, snow background.
Every size in `app/icons/` was recolored from the same art (not redrawn). `og.png` = the landing photo + "land it. prove it.".
