"""Protocol smoke tests: python3 -m unittest test_bot (from the grocery-bot folder)."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

BOT = Path(__file__).resolve().parent / "bot.py"

# A tiny store: walls round the edge, two shelves, one truck with three load cells.
STATE = {
    "type": "game_state", "round": 0, "max_rounds": 300, "action_status": "ok",
    "grid": {"width": 8, "height": 6, "walls": [[x, 0] for x in range(8)] + [[x, 5] for x in range(8)]
             + [[0, y] for y in range(1, 5)] + [[7, y] for y in range(1, 5)]},
    "bots": [{"id": 0, "position": [6, 4], "inventory": []}, {"id": 1, "position": [6, 4], "inventory": []}],
    "items": [{"id": "item_0", "type": "milk", "position": [2, 3], "department": "dairy", "fixture": "fridge"},
              {"id": "item_1", "type": "bread", "position": [4, 3], "department": "bakery", "fixture": "rack"}],
    "trucks": [{"id": 0, "bay": [3, 0], "load_cells": [[2, 1], [3, 1], [4, 1]], "state": "docked",
                "rounds_until_back": 0,
                "order": {"id": "order_0", "items_required": ["milk", "bread"], "items_delivered": [],
                          "complete": False}},
               {"id": 1, "bay": [6, 0], "load_cells": [[5, 1], [6, 1]], "state": "away",
                "rounds_until_back": 5, "order": None}],
    "score": 0, "orders_completed": 0, "total_orders": 1,
}
ACTIONS = {"move_up", "move_down", "move_left", "move_right", "pick_up", "load", "drop_off", "wait"}


def run(messages: list[dict]) -> list[dict]:
    out = subprocess.run([sys.executable, str(BOT)], input="".join(json.dumps(m) + "\n" for m in messages),
                         capture_output=True, text=True, timeout=30, check=True)
    return [json.loads(line) for line in out.stdout.splitlines()]


class ProtocolTest(unittest.TestCase):
    def test_handshake_and_rounds(self):
        later = json.loads(json.dumps(STATE))
        later["round"] = 1
        replies = run([{"type": "hello", "protocol_version": 1}, STATE, later,
                       {"type": "game_over", "score": 0, "rounds_used": 2}])
        self.assertEqual(replies[0], {"type": "ready", "protocol_version": 1})
        self.assertEqual(len(replies), 3, "one reply per hello/game_state, none after game_over")
        for reply, rnd in zip(replies[1:], (0, 1)):
            self.assertEqual(reply["round"], rnd)
            bots = [a["bot"] for a in reply["actions"]]
            self.assertEqual(len(bots), len(set(bots)), "at most one action per bot")
            for action in reply["actions"]:
                self.assertIn(action["action"], ACTIONS)

    def test_unpickable_order_type_does_not_freeze_fleet(self):
        state = json.loads(json.dumps(STATE))
        state["trucks"][0]["order"]["items_required"].append("caviar")  # on no shelf
        replies = run([{"type": "hello", "protocol_version": 1}, state])
        moves = [a for a in replies[1]["actions"] if a["action"] != "wait"]
        self.assertTrue(moves, "bots still work on the pickable part of the order")

    def test_ignores_blank_and_garbage_lines(self):
        out = subprocess.run([sys.executable, str(BOT)], capture_output=True, text=True, timeout=30, check=True,
                             input=json.dumps({"type": "hello", "protocol_version": 1}) + "\n\nnot json\n[1]\n"
                             + json.dumps(STATE) + "\n")
        self.assertEqual(len(out.stdout.splitlines()), 2)

    def test_survives_eof_without_game_over(self):
        replies = run([{"type": "hello", "protocol_version": 1}, STATE])
        self.assertEqual(len(replies), 2)


if __name__ == "__main__":
    unittest.main()
