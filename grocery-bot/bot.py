"""EZ-Fix Grocery Bot: order assignment with pre-staging + cooperative space-time A*.

Each round:
  1. Allocate what bots carry to the trucks that need it, drop pickups nobody needs any more.
  2. Hand out new pickups: a trip planner for small fleets (best points per round, may mix
     trucks), a min-makespan split for big fleets (parallel fetch for docked trucks).
  3. Plan moves with space-time A* and reservations that encode the engine's bot-ID move order.

Stdout carries protocol JSON only; diagnostics go to stderr.
"""

import heapq
import itertools
import json
import os
import random
import sys
import time
from collections import Counter

__version__ = "1.1.0"

CAP = 3
WINDOW = 16  # space-time planning horizon (rounds)
ROUND_BUDGET = 0.35  # seconds of planning before remaining bots just wait
INF = 10**6
DIRS = ((0, -1, "move_up"), (0, 1, "move_down"), (-1, 0, "move_left"), (1, 0, "move_right"))

TUNE = json.loads(os.environ.get("GB_TUNE", "{}"))  # local experiments only
STUCK_ROUNDS = TUNE.get("stuck_rounds", 3)

# Fleet-size dependent; set by configure() on the first state.
ASSIGN = "trip"
MAX_BOTS_PER_TRUCK = 3
LOAD_ROW_PENALTY = 2
TRIP_UNITS = TUNE.get("trip_units", 14)  # cap on open units the trip planner enumerates
TRIP_ITEM_BONUS = TUNE.get("trip_item_bonus", 2.0)  # favour fuller trips: travel dominates
TRIP_REPLAN = TUNE.get("trip_replan", 1)  # reconsider a trip each round until its first pickup
TRIP_HYSTERESIS = TUNE.get("trip_hyst", 0.0)  # how much better a new trip must be to switch
MAKESPAN_REPLAN = TUNE.get("makespan_replan", 1)  # same re-planning for big fleets


def configure(n_bots: int):
    global ASSIGN, MAX_BOTS_PER_TRUCK, LOAD_ROW_PENALTY
    ASSIGN = TUNE.get("assign", "makespan" if n_bots >= 5 else "trip")
    MAX_BOTS_PER_TRUCK = TUNE.get("max_bots", 5 if n_bots >= 10 else 3)
    LOAD_ROW_PENALTY = TUNE.get("row_penalty", 0 if n_bots == 1 else 2)


class World:
    """Static store geometry: fixed for the whole game."""

    def __init__(self, state: dict):
        self.w, self.h = state["grid"]["width"], state["grid"]["height"]
        walls = {tuple(c) for c in state["grid"]["walls"]}
        shelf = {tuple(it["position"]): (it["id"], it["type"]) for it in state["items"]}
        blocked = walls | set(shelf)
        self.cells = [(x, y) for y in range(self.h) for x in range(self.w) if (x, y) not in blocked]
        self.idx = {c: i for i, c in enumerate(self.cells)}
        n = len(self.cells)
        self.nbr = []
        self.move_name = {}
        for i, (x, y) in enumerate(self.cells):
            out = []
            for dx, dy, name in DIRS:
                j = self.idx.get((x + dx, y + dy))
                if j is not None:
                    out.append(j)
                    self.move_name[(i, j)] = name
            self.nbr.append(out)

        # Shelves a bot standing on cell i can pick from.
        self.adj_shelf = [[] for _ in range(n)]
        pick: dict[str, set[int]] = {}
        for (sx, sy), (item_id, typ) in shelf.items():
            for dx, dy, _ in DIRS:
                j = self.idx.get((sx + dx, sy + dy))
                if j is not None:
                    self.adj_shelf[j].append((item_id, typ))
                    pick.setdefault(typ, set()).add(j)
        self.pick = pick

        self.load = {tr["id"]: [self.idx[tuple(c)] for c in tr["load_cells"]] for tr in state["trucks"]}
        self.load_set = {k: set(v) for k, v in self.load.items()}
        rows = {self.cells[c][1] for v in self.load.values() for c in v}
        self.load_row = {i for i, (x, y) in enumerate(self.cells) if y in rows}
        # The load row is a 1-wide corridor: only drive along it near your own truck.
        self.cost = [1 + (LOAD_ROW_PENALTY if i in self.load_row else 0) for i in range(n)]
        self.type_dist, self.type_near = {}, {}
        for t, src in self.pick.items():
            self.type_dist[t], self.type_near[t] = self._dijkstra(src, self.cost)
        self.truck_cost, self.truck_dist = {}, {}
        for k, v in self.load.items():
            cost = list(self.cost)
            for c in v:
                cost[c] = 1
            self.truck_cost[k] = cost
            self.truck_dist[k] = self._dijkstra(v, cost)[0]

        self.spawn = self.idx.get((self.w - 2, self.h - 2), -1)
        # Idle bots park in the bottom corridor or on the stackable spawn tile.
        self.park = {i for i, (x, y) in enumerate(self.cells) if y == self.h - 2} | ({self.spawn} - {-1})
        self.park_dist = self._dijkstra(self.park, self.cost)[0]

    def _dijkstra(self, sources, cost):
        """Cost-to-go towards sources, where entering cell c costs cost[c]."""
        dist = [INF] * len(self.cells)
        near = [-1] * len(self.cells)
        heap = []
        for s in sources:
            dist[s], near[s] = 0, s
            heap.append((0, s))
        heapq.heapify(heap)
        while heap:
            d, c = heapq.heappop(heap)
            if d > dist[c]:
                continue
            for nb in self.nbr[c]:
                nd = d + cost[c]  # reversed search: stepping from nb into c costs cost[c]
                if nd < dist[nb]:
                    dist[nb], near[nb] = nd, near[c]
                    heapq.heappush(heap, (nd, nb))
        return dist, near


world: World | None = None
jobs: dict[int, Counter] = {}  # bot id -> pending pickups {(truck, type): count}
deliver: dict[int, Counter] = {}  # bot id -> carried items bound to trucks {(truck, type): count}
previous: dict[int, Counter] = {}  # trip released for re-planning this round
last_pos: dict[int, int] = {}
stuck: dict[int, int] = {}
DEBUG = open(f"{os.environ['GB_DEBUG']}.{os.getpid()}", "w") if os.environ.get("GB_DEBUG") else None


def truck_need(truck: dict) -> Counter | None:
    order = truck["order"]
    if truck["state"] == "leaving" or not order or order["complete"]:
        return None
    need = Counter(order["items_required"])
    need.subtract(order["items_delivered"])
    return +need


def route_cost(start: int, types: list[str], truck: int) -> int:
    """Nearest-neighbour route through pickups of `types`, then to the truck."""
    w = world
    left = list(types)
    p, travel = start, 0
    while left:
        typ = min(left, key=lambda t: w.type_dist[t][p])
        travel += w.type_dist[typ][p]
        p = w.type_near[typ][p]
        left.remove(typ)
    return travel + w.truck_dist[truck][p]


# ---------------------------------------------------------------- assignment

def allocate(pos, inv, need, eta):
    """Match carried items to trucks (preferring the bot's own job) and trim stale pickups."""
    w = world
    carry = {b: Counter() for b in pos}
    # Items keep the truck they were picked for, so bots do not flip between trucks.
    for b in sorted(pos, key=lambda b: (b not in deliver, b)):
        bound = Counter(deliver.get(b, ()))
        mine = {t for t, _ in jobs.get(b, ())}
        alloc = Counter()
        for item in inv[b]:
            t = next((t for (t, ty), k in bound.items() if ty == item and k > 0 and t in need
                      and need[t][item] > 0), None)
            if t is None:
                cands = [t for t in need if need[t][item] > 0]
                if not cands:
                    continue
                t = min(cands, key=lambda t: (t not in mine, eta[t], w.truck_dist[t][pos[b]]))
            else:
                bound[(t, item)] -= 1
            need[t][item] -= 1
            carry[b][t] += 1
            alloc[(t, item)] += 1
        deliver[b] = alloc

    for b in list(jobs):
        kept = Counter()
        if b in pos:
            for (t, typ), k in jobs[b].items():
                take = min(k, need[t][typ]) if t in need else 0
                if take > 0:
                    kept[(t, typ)] = take
                    need[t][typ] -= take
        if kept:
            jobs[b] = kept
        else:
            del jobs[b]
    return carry


def assign_makespan(pos, inv, need, eta, carry):
    """Give each open unit to the bot that would finish it earliest.

    Docked trucks spread their units over many bots (parallel fetch); trucks still
    away consolidate units, since finishing before they dock gains nothing.
    """
    owner, plan, assigned = {}, {}, Counter()
    for b in pos:
        trucks = {t for t, _ in jobs.get(b, ())} | set(carry[b])
        if len(trucks) == 1:
            owner[b] = next(iter(trucks))
        elif trucks:
            owner[b] = None  # busy with several trucks: leave alone
        plan[b] = [typ for (t, typ), k in jobs.get(b, Counter()).items() for _ in range(k)]
        for t in trucks:
            assigned[t] += 1
    slots = {b: CAP - len(inv[b]) - len(plan[b]) for b in pos}

    for t in sorted(need, key=lambda t: (eta[t], t)):
        units = list((+need[t]).elements())
        while units:
            best = None
            for b in pos:
                if slots[b] <= 0 or owner.get(b, t) != t:
                    continue
                if b not in owner and assigned[t] >= MAX_BOTS_PER_TRUCK:
                    continue
                base = route_cost(pos[b], plan[b], t) if b in owner else 0
                for typ in set(units):
                    cost = route_cost(pos[b], plan[b] + [typ], t)
                    key = (max(cost, eta[t]), cost - base, b)
                    if best is None or key < best[0]:
                        best = (key, b, typ)
            if best is None:
                break
            _, b, typ = best
            if b not in owner:
                owner[b] = t
                assigned[t] += 1
            plan[b].append(typ)
            slots[b] -= 1
            units.remove(typ)
            need[t][typ] -= 1
            jobs.setdefault(b, Counter())[(t, typ)] += 1


def trip_time(start: int, units: tuple, eta: dict) -> int:
    """Rounds to pick `units` (best order) and deliver them, the soonest truck first."""
    w = world
    trucks = sorted({t for t, _ in units}, key=lambda t: eta[t])
    best = INF
    for perm in set(itertools.permutations(units)):
        p, rounds = start, 0
        for _, typ in perm:
            rounds += w.type_dist[typ][p] + 1
            p = w.type_near[typ][p]
        for t in trucks:
            rounds = max(rounds + w.truck_dist[t][p], eta[t]) + 1
            p = min(w.load[t], key=lambda c: abs(w.cells[c][0] - w.cells[p][0]))
        best = min(best, rounds)
    return best


def trip_score(start, combo, remaining, eta):
    per_truck = Counter(t for t, _ in combo)
    value = len(combo) * (1 + TRIP_ITEM_BONUS) + sum(5 for t, n in per_truck.items() if n == remaining[t])
    rounds = trip_time(start, combo, eta)
    return (value / max(rounds, 1), -rounds)


def assign_trips(pos, inv, need, eta, carry):
    """Small fleets: each free bot takes the pickup set with the most points per round."""
    for b in sorted(pos):
        if b in jobs or carry[b]:
            continue
        slots = CAP - len(inv[b])
        open_units = [(t, typ) for t in sorted(need, key=lambda t: eta[t]) for typ in (+need[t]).elements()]
        if slots <= 0 or not open_units:
            continue
        open_units = open_units[:TRIP_UNITS]
        remaining = {t: sum((+need[t]).values()) for t in need}
        best, seen = None, set()
        for k in range(1, min(slots, len(open_units)) + 1):
            for combo in itertools.combinations(open_units, k):
                if combo in seen:
                    continue
                seen.add(combo)
                score = trip_score(pos[b], combo, remaining, eta)
                if best is None or score > best[0]:
                    best = (score, combo)
        if best is None:
            continue
        # Hysteresis: keep the previous trip unless the new one is clearly better.
        prev = previous.pop(b, None)
        if prev is not None:
            combo = tuple(sorted(prev.elements()))
            if all(need.get(t, Counter())[typ] >= k for (t, typ), k in prev.items()):
                score = trip_score(pos[b], combo, remaining, eta)
                if best[0][0] <= score[0] * (1 + TRIP_HYSTERESIS):
                    best = (score, combo)
        jobs[b] = Counter(best[1])
        for t, typ in best[1]:
            need[t][typ] -= 1


def assign(pos, inv, need, eta):
    previous.clear()
    if TRIP_REPLAN and (ASSIGN == "trip" or MAKESPAN_REPLAN):
        # Until a bot has picked something, its trip stays open to better offers.
        for b in [b for b in jobs if not deliver.get(b)]:
            previous[b] = jobs.pop(b)
    carry = allocate(pos, inv, need, eta)
    if ASSIGN == "makespan":
        assign_makespan(pos, inv, need, eta, carry)
    else:
        assign_trips(pos, inv, need, eta, carry)
    return carry


# ---------------------------------------------------------------- movement

class Reservations:
    """Space-time occupancy encoding the engine's bot-ID move order."""

    def __init__(self, spawn: int):
        self.occ = [dict() for _ in range(WINDOW + 3)]
        self.last = {}
        self.spawn = spawn

    def add(self, bot: int, path: list[int], persist: bool):
        horizon = WINDOW + 2 if persist else len(path) - 1
        for t in range(horizon + 1):
            c = path[min(t, len(path) - 1)]
            self.occ[t].setdefault(c, []).append(bot)
            self.last[c] = max(self.last.get(c, -1), INF if persist else t + 1)

    def conflict(self, c: int, t: int, bot: int) -> bool:
        if c == self.spawn:
            return False
        if self.occ[t].get(c):
            return True
        # A lower ID moves first: it must not find us still standing where it goes next.
        for j in self.occ[t + 1].get(c, ()):
            if j < bot:
                return True
        # A higher ID moves after us: its old cell is still occupied when we move.
        for j in self.occ[t - 1].get(c, ()):
            if j > bot:
                return True
        return False

    def safe(self, c: int, t: int) -> bool:
        return c == self.spawn or self.last.get(c, -1) <= t


def astar(bot, start, res, goal, h, blocked_now, cost):
    w = world
    tick = 0
    frontier = [(h(start), 0, tick, start, 0, 0)]
    parent = {(start, 0): None}
    while frontier:
        _, _, _, c, t, g = heapq.heappop(frontier)
        if (goal(c) and res.safe(c, t)) or t == WINDOW:
            path, node = [], (c, t)
            while node is not None:
                path.append(node[0])
                node = parent[node]
            return path[::-1]
        nt = t + 1
        for n in w.nbr[c] + [c]:
            if (n, nt) in parent or res.conflict(n, nt, bot):
                continue
            # A higher ID has not moved yet when we do, so its cell is still taken.
            if nt == 1 and n != c and blocked_now.get(n, -1) > bot:
                continue
            parent[(n, nt)] = (c, t)
            tick += 1
            ng = g + cost[n]
            heapq.heappush(frontier, (ng + h(n), -nt, tick, n, nt, ng))
    return None


def decide_actions(state: dict) -> list[dict]:
    global world
    started = time.monotonic()
    if world is None:
        configure(len(state["bots"]))
        world = World(state)
    w = world

    pos = {b["id"]: w.idx[tuple(b["position"])] for b in state["bots"]}
    inv = {b["id"]: list(b["inventory"]) for b in state["bots"]}
    trucks = {t["id"]: t for t in state["trucks"]}
    raw_need = {}
    for t in state["trucks"]:
        n = truck_need(t)
        if n is not None:
            raw_need[t["id"]] = n
    need = {t: Counter(n) for t, n in raw_need.items()}
    eta = {t: trucks[t]["rounds_until_back"] for t in need}
    docked = {t for t in need if trucks[t]["state"] == "docked"}

    carry = assign(pos, inv, need, eta)

    # Movement goal per bot: next pickup, a truck's load cells, or a parking spot.
    spec = {}
    for b, p in pos.items():
        types = tuple(sorted({typ for (_, typ) in jobs.get(b, ())}))
        if types:
            spec[b] = (lambda c, types=types: any(c in w.pick[t] for t in types),
                       lambda c, types=types: min(w.type_dist[t][c] for t in types),
                       w.cost)
        elif carry[b]:
            t = min(carry[b], key=lambda t: (t not in docked, eta[t], w.truck_dist[t][p]))
            spec[b] = (lambda c, t=t: c in w.load_set[t], lambda c, t=t: w.truck_dist[t][c], w.truck_cost[t])
        else:
            spec[b] = (lambda c: c in w.park, lambda c: w.park_dist[c], w.cost)

    # Stuck = a busy bot that has not moved for a while.
    for b, p in pos.items():
        busy = b in jobs or bool(carry[b])
        stuck[b] = stuck.get(b, 0) + 1 if busy and last_pos.get(b) == p else 0
        last_pos[b] = p

    # Who plans first: stuck bots in random order, then bots that can score soonest.
    rng = random.Random(state["round"])
    shuffle = {b: rng.random() for b in pos}

    def rank(b):
        if stuck[b] >= STUCK_ROUNDS:
            return (-1, shuffle[b])
        job_trucks = {t for t, _ in jobs.get(b, ())}
        if not job_trucks and any(t in docked for t in carry[b]):
            return (0, b)
        if job_trucks & docked:
            return (1, b)
        if carry[b] and not job_trucks:
            return (2, b)
        if job_trucks:
            return (3, b)
        return (4, b)

    res = Reservations(w.spawn)
    actions = {}
    unplanned = set(pos)

    for b in sorted(pos, key=rank):
        unplanned.discard(b)
        p = pos[b]

        # Load if standing at a docked truck that wants something we hold.
        here = next((t for t in docked if p in w.load_set[t]), None)
        if here is not None and any(raw_need[here][i] > 0 for i in inv[b]):
            actions[b] = {"bot": b, "action": "load"}
            res.add(b, [p, p, p], persist=False)
            continue

        job = jobs.get(b)
        if job and len(inv[b]) < CAP:
            shelf = next(((iid, typ) for iid, typ in w.adj_shelf[p]
                          if any(k > 0 and ty == typ for (_, ty), k in job.items())), None)
            if shelf is not None:
                actions[b] = {"bot": b, "action": "pick_up", "item_id": shelf[0]}
                key = min((k for k in job if k[1] == shelf[1] and job[k] > 0),
                          key=lambda k: (k[0] not in docked, eta.get(k[0], INF)))
                job[key] -= 1
                deliver.setdefault(b, Counter())[key] += 1
                res.add(b, [p, p, p], persist=False)
                continue

        if time.monotonic() - started > ROUND_BUDGET:
            actions[b] = {"bot": b, "action": "wait"}
            res.add(b, [p], persist=True)
            continue

        goal, h, cost = spec[b]
        path = astar(b, p, res, goal, h, {pos[o]: o for o in unplanned}, cost)
        if not path:
            actions[b] = {"bot": b, "action": "wait"}
            res.add(b, [p], persist=True)
            continue
        res.add(b, path, persist=True)
        if len(path) > 1 and path[1] != p:
            actions[b] = {"bot": b, "action": w.move_name[(p, path[1])]}
        else:
            actions[b] = {"bot": b, "action": "wait"}

    for b in [b for b, j in jobs.items() if not +j]:
        del jobs[b]

    if DEBUG:
        DEBUG.write(json.dumps({
            "r": state["round"], "score": state["score"], "st": state["action_status"],
            "trucks": [(t["id"], t["state"], t["rounds_until_back"], dict(raw_need.get(t["id"], {})))
                       for t in state["trucks"]],
            "bots": [(b, w.cells[pos[b]], inv[b], {str(k): v for k, v in carry[b].items()},
                      sorted({t for t, _ in jobs.get(b, ())}) or None,
                      {f"{t}:{ty}": k for (t, ty), k in jobs.get(b, Counter()).items()} or None,
                      actions[b]["action"]) for b in sorted(pos)]}) + "\n")
    elapsed = time.monotonic() - started
    if elapsed > 0.2:
        print(f"round {state['round']}: {elapsed:.3f}s", file=sys.stderr)
    return [actions[b] for b in sorted(actions)]


def main():
    for line in sys.stdin:
        message = json.loads(line)
        kind = message.get("type")
        if kind == "hello":
            print(json.dumps({"type": "ready", "protocol_version": 1}), flush=True)
        elif kind == "game_state":
            try:
                acts = decide_actions(message)
            except Exception as exc:  # never lose a round to a bug
                print(f"error round {message.get('round')}: {exc!r}", file=sys.stderr)
                acts = []
            print(json.dumps({"round": message["round"], "actions": acts}), flush=True)
        elif kind in ("game_over", "game_end"):
            print(line.strip(), file=sys.stderr)
            break


if __name__ == "__main__":
    main()
