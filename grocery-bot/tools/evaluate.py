"""Score bot.py on many local seeds in parallel with the CLI's offline engine.

Run with the Python that ships with the grocerybot CLI, from the grocery-bot folder:

    ~/.local/share/grocerybot/cli/*/bin/python tools/evaluate.py '{}' 40
    ~/.local/share/grocerybot/cli/*/bin/python tools/evaluate.py '{"row_penalty":1}' 20 expert,nightmare

The JSON argument is passed to the bot as GB_TUNE (see the TUNE keys in bot.py), so variants
can be compared without editing code. Seeds 100.. are separate from the CLI benchmark suites.
"""

import asyncio
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent.parent
STORES = "easy,medium,hard,expert,nightmare"


def play(args):
    store, seed, tune = args
    os.environ["GB_TUNE"] = tune
    os.environ.pop("GB_DEBUG", None)
    from grocerybot.config import load_project
    from grocerybot.local import play_local

    result = asyncio.run(play_local(load_project(BOT_DIR), store, seed, 5000 + seed, record=False))
    return store, seed, result.get("score", 0)


def main():
    tune = sys.argv[1] if len(sys.argv) > 1 else "{}"
    seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    stores = (sys.argv[3] if len(sys.argv) > 3 else STORES).split(",")
    cases = [(store, seed, tune) for store in stores for seed in range(100, 100 + seeds)]
    scores: dict[str, list[int]] = {}
    with ProcessPoolExecutor(int(os.environ.get("JOBS", os.cpu_count() or 2))) as pool:
        for store, _, score in pool.map(play, cases):
            scores.setdefault(store, []).append(score)
    parts = [f"{s}={sum(v) / len(v):.1f} (min {min(v)})" for s, v in scores.items()]
    total = sum(sum(v) / len(v) for v in scores.values())
    print(f"{tune}  " + "  ".join(parts) + f"  SUM={total:.1f}")


if __name__ == "__main__":
    main()
