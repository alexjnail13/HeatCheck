# HeatCheck — Product Roadmap & Build Prompt

*Next phase: from an NBA analytics app into a model-driven sports betting insights + odds-comparison product.*

---

## 1. Positioning (what HeatCheck is becoming)

HeatCheck is an **odds-comparison and betting-insights product**, not a sportsbook. It never takes a wager. Its edge is a transparent, explainable win-probability and advanced-stats engine that does one thing the big books don't advertise: **it tells you where the market's price disagrees with a model, and by how much.**

The loop for a user:

> See a live or upcoming game → HeatCheck shows both scores, the full box score (team + player stats), and live advanced stats (win probability, pace, efficiency) → it compares its model's implied probability to the **current market odds** pulled from real sportsbooks → it surfaces "value" picks (moneyline, player props) where the model sees an edge → the user taps through an **affiliate link** to a licensed book to place the bet there.

Revenue comes from affiliate referrals, not wagers — which is exactly why this scope avoids sportsbook licensing while still being a real business.

**What it is NOT (keep this framing in the product and the code):** not a sportsbook, not financial advice, not a guarantee. Every pick is a model estimate with a confidence and a disclaimer. This framing isn't just legal cover — "here's the math, here's the edge, decide for yourself" *is* the product.

---

## 2. Current state (as of this roadmap)

Already built and live on Render:

- FastAPI + React + PostgreSQL, deployed (backend web service, static frontend, managed Postgres).
- JWT auth (signup/login/protected routes), tokens in `localStorage`, axios interceptor.
- Games list, game detail with a **win-probability chart** (logistic-regression model, ~77% acc).
- Standings computed **from our own database** (no live NBA call).
- "Ask Heat Check" Gemini chatbot, grounded on DB standings.
- **Key pattern already proven:** "own your data" — cache third-party data in Postgres so `stats.nba.com` (which blocks datacenter IPs) is never on the request hot path. Win probability now reads from a seeded `play_by_play` table; standings compute from stored games.

**One known gap:** the live-scoreboard WebSocket still calls `nba_api`'s `scoreboard` live, which fails from Render. Phase A fixes this as a side effect of switching to a cloud-reachable live-data provider.

---

## 3. Guiding principles (carry these forward — they're hard-won)

1. **Own your data.** Anything on the request hot path reads from Postgres, not a live third-party call. External data comes in via ingestion/seeding jobs that run on a schedule, not per user request. (This is *why* standings and win probability work in production and the live feed doesn't — yet.)
2. **Derive facts from data structure, not positional assumptions.** (The NBA Cup neutral-site bug taught this: parse *who is home* from the data, don't assume the API's row order.)
3. **Decouple models from stored data.** Store raw inputs, compute features/predictions fresh, so retraining never requires re-seeding.
4. **Fail gracefully + degrade, never hang.** Every external dependency wrapped; a dead odds feed shows stale-but-labeled prices, not a spinner.
5. **Responsible by design** (see §7) — for a betting product this is a first-class feature, not an afterthought.

---

## 4. Data sources (researched, current)

**Odds / lines (the market side):**

- **[The Odds API](https://theoddsapi.com/)** — covers NBA, NFL, MLB, NHL, MLS, the 2026 World Cup, and European soccer. Tiers: **Free** ($0, NBA+MLB moneylines — enough to prototype), **Professional** ($29/mo, all ~25 sports with h2h/spreads/totals from US books), **Business** ($99/mo, 50+ books, **player props**, historical odds, futures). Start Free, move to Pro when the edge engine works, Business when you add player props.

**Live scores / box scores / player stats (the game side):**

- **[MySportsFeeds](https://www.mysportsfeeds.com/)** — **free for students & non-commercial use**; schedules, scores, box scores, play-by-play, lineups, injuries across NFL/MLB/NBA/NHL. Best first pick for a student build and it fixes the blocked live feed.
- **[BALLDONTLIE](https://www.balldontlie.io/)** — real-time scores, player stats, odds, and player props across NBA/NFL/MLB/NHL/soccer + 20 leagues; generous free tier, clean API. Strong multi-sport option.
- **[SportsDataIO](https://sportsdata.io/)** / **[Sportradar](https://sportradar.com/media-tech/data-content/sports-data-api/)** — enterprise-grade, paid; the upgrade path if HeatCheck ever needs guaranteed SLAs and sub-second data.

**Recommended starting stack:** The Odds API (Free→Pro) + MySportsFeeds (free student tier) + BALLDONTLIE for multi-sport reach. Keep the "own your data" rule: ingest all of it into Postgres on a schedule.

---

## 5. Phased roadmap

### Phase A — Complete the NBA live experience (foundation)

Goal: a live game view showing **both scores + full box score (team & player basic stats) + live advanced stats (win probability)**, plus the same box-score/advanced-stats depth for **completed** games. Also retires the broken `nba_api` live feed.

- Swap the live-scoreboard source from `nba_api.scoreboard` to a **cloud-reachable provider** (MySportsFeeds or BALLDONTLIE) — fixes the WebSocket-in-production gap.
- New tables: `player`, `player_game_stats` (points, reb, ast, min, FG, 3P, FT, +/- …), and a `team_game_stats` (or derive team totals from player rows).
- Ingestion job (scheduled) writes live/final box scores into Postgres; the API reads from there.
- Frontend: box-score tables (team + per-player), live-updating during games via the existing WebSocket, now fed from your DB.
- Extend the win-probability model with the richer live inputs you now have (pace, possession, timeouts — already in your feature vision).

### Phase B — Betting insights & odds comparison (the differentiator)

- **Odds ingestion service** — pull lines from The Odds API on a schedule, store in an `odds` table (game, book, market, price, timestamp). Same "own your data" pattern.
- **Edge engine** — convert both the model's win probability and the market's odds into implied probabilities, compute **expected value / edge %**, and flag "value" bets where the model disagrees with the price. This is the heart of the product.
- **Suggested bets UI** ("HeatCheck Picks") — moneyline pick from the win-prob model, each with an edge %, a confidence level, a plain-English rationale, a **responsible-gambling disclaimer**, and an **affiliate deep-link** to a licensed book.
- Affiliate link management + click tracking (this is the revenue path).

### Phase C — Player prop models

- Build per-stat **player projection models** (points / rebounds / assists / etc.) from the `player_game_stats` history you started collecting in Phase A.
- Compare projections to the market's player-prop lines (The Odds API Business tier) → prop value picks. This requires the Business tier and is the most technically ambitious modeling work.

### Phase D — Multi-sport expansion (NFL, MLB, NHL, MLS, World Cup)

- **Abstract the sport-specific pieces** behind a common interface *before* adding the second sport: a data-adapter per sport (ingestion), a features module per sport, a win-prob model per sport, and a shared schema for games/teams/players/odds. Resist copy-pasting the NBA code five times.
- Add one sport at a time. Football and hockey have different win-probability dynamics (drives/possessions, low-scoring variance) — each needs its own trained model and feature engineering, but the *architecture* (own-your-data ingestion → model → edge engine → picks) is identical.
- The Odds API and BALLDONTLIE both already cover all target sports, so the market + stats data is available on day one.

### Phase E — Product, trust, and monetization polish

- User features on top of existing auth: pick history, watchlists, bankroll/bet tracking, notifications on line moves.
- Responsible-gambling features (§7) as real, visible product surfaces.
- SEO + content (model recaps, "biggest edges tonight") to drive affiliate traffic.
- Performance: caching, cold-start mitigation, and an odds-refresh cadence that balances freshness against API quota.

---

## 6. Architecture decisions to make (before Phase D, ideally before A)

- **Multi-sport schema:** one generic `games`/`players`/`stats` set of tables with a `sport` column, vs. per-sport tables. (Generic-with-sport-column is usually the right call, but stat shapes differ wildly by sport — decide deliberately.)
- **Real-time delivery:** keep WebSockets, or move to SSE/polling? Whatever you choose, the data behind it must come from your DB, refreshed by a job.
- **Odds refresh cadence & quota:** how often to poll The Odds API without blowing the tier's request budget; cache aggressively, refresh hot games faster.
- **Model registry:** one model per (sport, market). Keep the "retrain at build, store raw inputs" pattern so models stay swappable.

---

## 7. Responsible gambling & legal (first-class for a "premier" betting product)

Building these *well* is part of being premier, and part of qualifying for reputable affiliate programs:

- **Informational framing everywhere:** "model estimate, not financial advice, no guarantees." No language that promises winnings.
- **Age gating (21+)** and, for affiliate compliance, **geolocation** so you only surface books legal in the user's state.
- **Responsible-gambling resources** visible in the UI: the National Problem Gambling Helpline (1-800-GAMBLER) and self-exclusion/limit information. Offer optional user-set limits and a self-exclusion toggle.
- **FTC affiliate disclosure** on any page with referral links.
- **Never present a pick as a sure thing** — always show the edge/confidence and that it can lose. This is honest *and* it's the product's credibility.

---

## 8. Reusable build-prompt (paste this at the start of a future session)

> I'm continuing HeatCheck, my sports-analytics web app (FastAPI + React + PostgreSQL + scikit-learn, deployed on Render). It's evolving from an NBA app into a **model-driven sports betting *insights* and odds-comparison product** (odds-comparison + affiliate model — no wagers taken). Keep using the mentor teaching style: guide me with questions and let me propose a solution before you write code; boilerplate is fine to hand over directly.
>
> Core principles I want enforced: (1) **own your data** — cache third-party data in Postgres via scheduled jobs, never call a live third-party API on the request hot path; (2) derive facts from data structure, not positional assumptions; (3) decouple models from stored data (store raw inputs, compute features fresh); (4) responsible-gambling framing is a first-class feature, not an afterthought.
>
> Data stack: The Odds API (odds), MySportsFeeds + BALLDONTLIE (scores/box scores/player stats). The differentiator is an **edge engine**: convert my model's win probability and the market's odds to implied probabilities, compute expected value, and surface value picks with a confidence and a disclaimer, linking out to licensed books via affiliate.
>
> Read my ROADMAP.md for the full phase plan and current state. Then ask me which phase to tackle, and start by having me reason through the design before we build.

---

## 9. Open questions for you (Alex)

1. **Phase A data provider** — MySportsFeeds (free student tier) or BALLDONTLIE (multi-sport now, easier expansion later)? This choice shapes your ingestion layer.
2. **Do you want to build the multi-sport abstraction early** (slower now, much easier expansion) or ship NBA betting insights fully first, then refactor for Phase D?
3. **How live is "live"?** Sub-second (expensive, enterprise APIs) or 5–15s (fine for a betting-insights product, cheap tiers)? This drives cost and architecture.
4. **Affiliate programs** — worth researching which sportsbook affiliate programs accept a product like this and in which states, since that gates the revenue model and the geolocation work.

---

*Sources: [The Odds API](https://theoddsapi.com/), [SportsDataIO](https://sportsdata.io/), [BALLDONTLIE](https://www.balldontlie.io/), [MySportsFeeds](https://www.mysportsfeeds.com/), [Sportradar](https://sportradar.com/media-tech/data-content/sports-data-api/).*
