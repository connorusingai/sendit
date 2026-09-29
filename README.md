# Sendit

A social app for skiers. Film a trick, post it, and get it verified. Verified tricks earn
points that rank you up, and you can challenge other skiers to duels.

> Working name. The trick-detection AI is a separate project: [`../sendit-ai`](../sendit-ai/README.md).

## The core loop

1. **Film** a trick (a friend films you, or you use a GoPro or 360 camera).
2. **Pick the trick** from a list, e.g. "Cork 720, Safety grab".
3. **Post.**
4. **Get verified** and earn points. The skier just gets a notification: "✅ Verified, +84 pts".

Keep the skier's side this simple. All the checking happens in the background.

## Status

| Piece | State |
|---|---|
| Clickable prototype | ✅ [`prototype/index.html`](prototype/index.html), fake users, saves in your browser only · [live link](https://claude.ai/artifact/R2RN1gjaBDJzi2VtuPRERC) |
| Real accounts + shared database | ⬜ Not started (plan: Supabase) |
| Mobile app | ⬜ Not started |
| AI verification | 🔨 Separate project, [`sendit-ai`](../sendit-ai/README.md) |

To run the prototype locally, double-click `prototype/index.html` to open it in a browser.

## Roadmap

1. **Prototype** (done): test whether the idea feels fun.
2. **Real backend**: sign-in, video uploads, shared leaderboard, so friends can use it together.
3. **Plug in the AI**: clips that `sendit-ai` is confident about get verified instantly, and only unsure ones go to people.
4. **Launch small**: CU ski club and the Eldora park crew first, not everyone.

See [FEATURES.md](FEATURES.md) for every feature and the reasoning behind it.
