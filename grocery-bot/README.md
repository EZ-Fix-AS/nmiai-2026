# Grocery Bot — EZ-Fix

Training ground for NM i AI 2027. Grocery Bot (https://grocerybot.no) is run by Astar, who also host
NM i AI. You program a fleet of robots that fill online grocery orders; see `PROTOCOL.md` for the
exact protocol and https://grocerybot.no/how-to-play for the rules.

## Run it

```sh
curl -fsSL https://grocerybot.no/static/install.sh | sh   # installs the grocerybot CLI (Python ≥ 3.11)
grocerybot login                                          # opens a browser, once per machine
grocerybot doctor                                         # checks the bot without spending an attempt
grocerybot play --store easy                              # ranked game: counts towards the leaderboard
```

Ranked play: best score per difficulty counts, total = sum of all five. 50 games per day, one at a time.

## Measure before you change anything

```sh
PY=$(ls ~/.local/share/grocerybot/cli/*/bin/python)
$PY tools/evaluate.py '{}' 40                     # 40 offline seeds per store, prints averages
$PY tools/evaluate.py '{"row_penalty":1}' 20 expert,nightmare   # try a variant without editing code
grocerybot benchmark --suite standard-v1          # the CLI's own reproducible suite
python3 -m unittest test_bot                      # protocol smoke tests
```

The JSON argument is passed as `GB_TUNE`; every key is read near the top of `bot.py`. Change one
thing at a time — several changes at once hid both a win and a loss during development.
`GB_DEBUG=/some/prefix` writes one JSON line per round (positions, jobs, timing) for analysis.

## Results (local, average over 40 seeds per store)

| Store | Starter bot | v1.3.0 | Leaderboard #1 (14.10.2026, best-of-many) |
|---|---|---|---|
| Easy (1 bot) | 140 | 170 | 211 |
| Medium (3) | 153 | 223 | 320 |
| Hard (5) | 150 | 235 | 332 |
| Expert (10) | 112 | 256 | 375 |
| Nightmare (20) | 199 | 623 | 986 |
| **Sum** | **754** | **1507** | **2224** |

Worst round ≈ 20 ms, a whole game < 2 s of compute (limits: 2 s per round, 2–5 min per game).

## How it works

Every round the bot re-reads the full state; only a little memory carries over (jobs, which truck a
carried item is meant for, parking spots).

1. **Allocate.** Carried items keep the truck they were picked for, so bots do not flip between trucks.
2. **Assign pickups.**
   - 1–3 bots: *trip planner*. Every set of up to three open order units, across trucks, is scored as
     points per round, with a one-trip lookahead (this trip + the best follow-up).
   - 5+ bots: *min-makespan*. Each open unit goes to the bot that would finish it first; docked trucks
     get parallel fetches, trucks still away get consolidated trips.
   - Unstarted trips are re-planned only when the order picture changes (new order, truck state,
     a load). Re-planning every round made bots swap trips forever.
3. **Move.** Space-time A* with reservations that encode the engine's rule that moves resolve in bot-ID
   order (a lower ID can follow into a cell vacated the same round; a higher ID cannot). The 1-wide
   load row costs 1.5 per step except at your own truck. Stuck bots get top priority in random order.
4. **Park.** Idle bots spread over the open corridors so some bot is always near any shelf.

## Lessons (what did and did not work)

- Big wins: fixing deadlocks in the load row, event-based re-planning (+18 Easy, +16 Medium),
  row penalty 2 → 0.5 (+10–20 per store), makespan assignment for big fleets.
- Did not help: a speculative buffer (idle bots pre-picking popular items) — tried three ways, always
  worse; safety margins on route estimates; parking in the middle of the store.
- Shelves right below the load row can be picked from the load cell itself (pick → load without moving).
- Orders are ~uniform over item types, regardless of how many shelves a type has.

## Files

- `bot.py` — the bot (version in `__version__`).
- `bot_starter.py` — the CLI's starter bot, kept as a fallback.
- `tools/evaluate.py` — offline multi-seed evaluation.
- `test_bot.py` — protocol tests.
- `ROLLBACK.md` — how to go back to an earlier version.
