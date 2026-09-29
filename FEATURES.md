# Sendit features

What's decided, and why. ✅ = in the prototype.

## Points and ranks

There are **two separate ranks**, and both use the same medals:
**Bronze → Silver → Gold → Platinum → Diamond → Legend**

### Trick rank ✅
Every verified trick adds points. Reach a points total and you rank up.

| Rank | Points needed | Gap |
|---|---|---|
| Bronze | 0 | |
| Silver | 100 | +100 |
| Gold | 250 | +150 |
| Platinum | 450 | +200 |
| Diamond | 700 | +250 |
| Legend | 1,000 | +300 |

Easy to climb at first, harder at the top: each gap is 50 points bigger than the last. With one-and-done
points, every ski trick with a grab totals about 1,070, so Legend means landing nearly the whole Trick Book.

- Each trick has a base value, e.g. 180 = 10, 540 = 35, Cork 720 = 70, Double Cork 1080 = 120.
- A grab adds 20%.
- Categories: Park, Rails, Pipe, Moguls, Backcountry.
- **One and done:** a trick pays only the first time it's verified, so nobody can farm 180s. Landing it later with a
  *new grab* pays just the grab (20% of the trick). Exact repeats still show in the feed but pay 0. Exception: a repeat of the Trick of the Day pays normal points once that day.
- **Trick Book:** a checklist of every trick (ski and snowboard) showing which ones you've landed.

### Duel rank ✅
Based on your duel wins and losses, using the chess rating system (ELO).
Winning moves you up, and losing moves you down. Beating someone ranked above you earns more.

| Rank | Rating |
|---|---|
| Bronze | under 1,000 |
| Silver | 1,000 |
| Gold | 1,200 |
| Platinum | 1,400 |
| Diamond | 1,600 |
| Legend | 1,800 |

**Why two ranks:** they measure different things. Trick rank is *what you can land*, and duel
rank is *how you do head-to-head*. Someone with no one to duel can still rank up with tricks.

## Duels: Game of S.K.I. ✅
It works like the skateboarding game S.K.A.T.E.
- You land a trick, and your opponent has to match it.
- Miss a match and you take a letter. Spell **S-K-I** and you lose.
- Turns are async (72 hours each), so you can duel someone at a different mountain.
- Each attempt is a clip, verified the same way as normal posts.

## Verification
The skier's side stays simple: **film → pick trick → post → notification**.

Behind the scenes:
1. **AI checks first** ([`sendit-ai`](../sendit-ai/README.md)). If it's confident, the clip is verified instantly.
2. **Unsure clips go to people.** Community voting ✅ is in the prototype now:
   - Judges see the clip without the skier's name, and never get clips from rivals.
   - Hidden test clips catch judges who always vote no, and their votes stop counting.
   - "Not landed" asks for a quick reason: *fell / wrong trick / can't see*.
   - "Wrong trick" can still give credit for the easier trick.
3. **Sensor data backs it up** when there is some (phone in pocket, or GoPro/Insta360 telemetry).
   Clips with sensor data get a "sensor-verified" badge.

## Anti-cheat
- Clips are recorded in the app, with time and GPS stamps, so nobody can upload old or downloaded clips.
- Two phones at the same place and time (you plus your filmer) are hard to fake.
- The sensors should roughly match the claimed trick.

## Filming setups
| Setup | Video | Sensors |
|---|---|---|
| Friend films, your phone in pocket | ✅ | ✅ (matched by timestamp) |
| GoPro / Insta360 on a selfie stick | ✅ | ✅ (built into the video file) |
| Smartwatch plus a friend filming | ✅ | ⚠️ less accurate (arms flail) |
| Skiing alone, phone in pocket | ❌ | ✅ personal stats only, no rank points |

## Ideas for later
- **Trick tips:** a short "how to land it" guide on each trick in the Trick Book, for riders who keep bailing it.
- **Trick of the Day**: a daily challenge trick for bonus points.
- **Feed** with likes and comments ✅ (basic feed is in).
- **Skill brackets** so beginners compete with beginners, which also means fewer people getting hurt chasing points.
- **Off-season league** with trampoline, water ramp and dryslope clips (the season runs roughly Nov–Apr).
- **Season resets** for duel rank.
- Leaderboards by resort.
