"""
Astar Island — Unified Loop (V6)
Auto-learn from completed rounds + entropy-based queries + auto-submit
NM i AI 2026 — EZ-Fix AS
"""
import time
import json
import logging
import numpy as np
import requests
from collections import defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("astar")

# === CONFIG ===
BASE = "https://api.ainm.no/astar-island"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIyOTJlNDQzMi0wNDY4LTRhNjAtOTY3OS1jYWIzODY4ZDdhZjYiLCJlbWFpbCI6Im1hcmt1c0Blei1maXgubm8iLCJpc19hZG1pbiI6ZmFsc2UsImV4cCI6MTc3NDY0Nzg4M30.hEeMSjseq5Kstu9D1c2TprPNXW6vxC3w1DPq4X_Jzcs"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
FLOOR = 0.01
DIR = Path(__file__).parent
DIST_PRIORS_FILE = DIR / "astar_dist_priors.json"
CLUSTER_PRIORS_FILE = DIR / "astar_cluster_priors.json"
STATE_FILE = DIR / "astar_state.json"
POLL_INTERVAL = 12


def api(method, path, body=None, retries=3):
    for i in range(retries):
        try:
            r = requests.request(method, f"{BASE}/{path.lstrip('/')}", headers=HEADERS, json=body, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i < retries - 1:
                time.sleep(2)
            else:
                raise


def to_class(v):
    return {0: 0, 10: 0, 11: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}.get(v, 0)


# === STATE ===
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"analyzed_rounds": [], "submitted_rounds": []}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state))


# === LEARNING ===
def learn_from_all_completed():
    """Rebuild dist priors from ALL completed rounds with ground truth."""
    state = load_state()
    rounds = api("GET", "rounds")
    completed = [r for r in rounds if r["status"] == "completed"]

    # Check if we need to learn anything new
    completed_ids = {r["id"] for r in completed}
    already = set(state.get("analyzed_rounds", []))
    new_rounds = completed_ids - already

    if not new_rounds and DIST_PRIORS_FILE.exists():
        log.info(f"No new rounds to learn from ({len(already)} already analyzed)")
        return

    log.info(f"Learning from {len(completed)} completed rounds ({len(new_rounds)} new)...")

    dist_stats = defaultdict(lambda: {"total": np.zeros(6), "count": 0})
    cluster_stats = defaultdict(lambda: {"total": np.zeros(6), "count": 0})

    for rnd in completed:
        rid = rnd["id"]
        rn = rnd["round_number"]
        try:
            rnd_detail = api("GET", f"rounds/{rid}")
            time.sleep(0.15)
        except Exception:
            continue

        for si in range(5):
            try:
                data = api("GET", f"analysis/{rid}/{si}")
                time.sleep(0.15)
                truth = np.array(data["ground_truth"])
                init_grid = data.get("initial_grid")
                if init_grid is None:
                    continue
                init_grid = np.array(init_grid)
                h, w = truth.shape[:2]

                sett_positions = [(s["y"], s["x"]) for s in rnd_detail["initial_states"][si]["settlements"]]

                dist_map = _compute_dist_map(sett_positions, h, w)
                coast_map = _compute_coast_map(init_grid, h, w)
                cluster_map = _compute_cluster_size(sett_positions, h, w)

                entropy = -np.sum(truth * np.log(truth + 1e-10), axis=-1)
                dynamic = entropy > 0.1

                for y in range(h):
                    for x in range(w):
                        if not dynamic[y, x]:
                            continue
                        tv = int(init_grid[y, x])
                        d = min(int(dist_map[y, x]), 8)
                        nc = 1 if coast_map[y, x] else 0
                        cl = int(cluster_map[y, x])
                        dist_stats[(tv, d, nc)]["total"] += truth[y, x]
                        dist_stats[(tv, d, nc)]["count"] += 1
                        cluster_stats[(tv, d, nc, cl)]["total"] += truth[y, x]
                        cluster_stats[(tv, d, nc, cl)]["count"] += 1
            except Exception:
                pass

        log.info(f"  R{rn} done")

    # Save dist priors
    priors_db = {}
    for key, val in dist_stats.items():
        if val["count"] >= 3:
            priors_db[f"{key[0]}_{key[1]}_{key[2]}"] = {
                "probs": (val["total"] / val["count"]).tolist(),
                "count": val["count"],
            }
    DIST_PRIORS_FILE.write_text(json.dumps(priors_db))

    # Save cluster priors
    cluster_db = {}
    for key, val in cluster_stats.items():
        if val["count"] >= 5:
            cluster_db[f"{key[0]}_{key[1]}_{key[2]}_{key[3]}"] = {
                "probs": (val["total"] / val["count"]).tolist(),
                "count": val["count"],
            }
    CLUSTER_PRIORS_FILE.write_text(json.dumps(cluster_db))

    total_cells = sum(v["count"] for v in dist_stats.values())
    log.info(f"Saved {len(priors_db)} dist + {len(cluster_db)} cluster entries from {total_cells} cells")

    # Update state
    state["analyzed_rounds"] = list(completed_ids)
    save_state(state)


def _compute_dist_map(sett_positions, h, w):
    dist_map = np.full((h, w), 99)
    for sy, sx in sett_positions:
        for y in range(h):
            for x in range(w):
                d = max(abs(y - sy), abs(x - sx))
                dist_map[y, x] = min(dist_map[y, x], d)
    return dist_map


def _compute_cluster_size(sett_positions, h, w):
    """Count settlements within radius 5 of each cell."""
    cluster = np.zeros((h, w), dtype=int)
    for y in range(h):
        for x in range(w):
            count = sum(1 for sy, sx in sett_positions if max(abs(y - sy), abs(x - sx)) <= 5)
            cluster[y, x] = min(count, 5)
    return cluster


def _compute_coast_map(grid, h, w):
    coast = np.zeros((h, w), dtype=bool)
    for y in range(h):
        for x in range(w):
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and grid[ny, nx] == 10:
                        coast[y, x] = True
                        break
                if coast[y, x]:
                    break
    return coast


# === PRIORS ===
def compute_priors(grid, settlements, h, w):
    """Cluster-aware priors with dist fallback. Uses terrain + distance + coast + cluster size."""
    grid = np.array(grid)
    sett_positions = [(s["y"], s["x"]) for s in settlements]

    # Load priors (cluster → dist → hardcoded fallback)
    cluster_priors = {}
    if CLUSTER_PRIORS_FILE.exists():
        cluster_priors = json.loads(CLUSTER_PRIORS_FILE.read_text())
    dist_priors = {}
    if DIST_PRIORS_FILE.exists():
        dist_priors = json.loads(DIST_PRIORS_FILE.read_text())

    dist_map = _compute_dist_map(sett_positions, h, w)
    coast_map = _compute_coast_map(grid, h, w)
    cluster_map = _compute_cluster_size(sett_positions, h, w)

    P = np.full((h, w, 6), FLOOR)
    for y in range(h):
        for x in range(w):
            tv = int(grid[y, x])
            d = min(int(dist_map[y, x]), 8)
            nc = 1 if coast_map[y, x] else 0
            cl = int(cluster_map[y, x])
            ckey = f"{tv}_{d}_{nc}_{cl}"
            dkey = f"{tv}_{d}_{nc}"

            if ckey in cluster_priors:
                P[y, x] = np.array(cluster_priors[ckey]["probs"])
            elif dkey in dist_priors:
                P[y, x] = np.array(dist_priors[dkey]["probs"])
            elif tv == 10:
                P[y, x] = [0.97, 0.005, 0.005, 0.005, 0.005, 0.01]
            elif tv == 5:
                P[y, x] = [0.005, 0.005, 0.005, 0.005, 0.005, 0.975]
            else:
                P[y, x] = [0.60, 0.15, 0.01, 0.02, 0.20, 0.02]

    P = np.maximum(P, FLOOR)
    P /= P.sum(axis=-1, keepdims=True)
    P = np.maximum(P, FLOOR)
    P /= P.sum(axis=-1, keepdims=True)
    return P


# === ENTROPY-BASED VIEWPORT PLANNING ===
def plan_viewports(grid, priors, h, w, n_queries):
    """Focus queries where uncertainty (entropy) is highest."""
    grid = np.array(grid)

    # Entropy per cell from priors
    entropy = -np.sum(priors * np.log(priors + 1e-10), axis=-1)

    # Zero out static cells (ocean, mountain)
    for y in range(h):
        for x in range(w):
            if grid[y, x] in (10, 5):
                entropy[y, x] = 0

    vps = []
    covered = np.zeros((h, w), dtype=int)
    for _ in range(n_queries):
        best = (-1, None)
        for vy in range(0, h - 5, 2):
            for vx in range(0, w - 5, 2):
                vw = min(15, w - vx)
                vh = min(15, h - vy)
                region = entropy[vy:vy + vh, vx:vx + vw]
                cov = covered[vy:vy + vh, vx:vx + vw]
                score = np.sum(region / (cov + 1))
                if score > best[0]:
                    best = (score, (vx, vy, vw, vh))
        if best[1] is None:
            break
        vx, vy, vw, vh = best[1]
        covered[vy:vy + vh, vx:vx + vw] += 1
        vps.append(best[1])
    return vps


# === AGGREGATION ===
def aggregate(observations, priors, h, w):
    """Two-phase aggregation:
    1. Calibrate: detect this round's class distribution from ALL observations
    2. Update: apply calibrated priors + per-cell Bayesian update"""
    # Phase 1: Global calibration from observations
    # Detect how this round differs from average (e.g. high settlement round)
    global_counts = np.zeros(6)
    for obs_list in observations.values():
        for c in obs_list:
            global_counts[c] += 1

    pred = np.copy(priors)

    if global_counts.sum() >= 50:
        # Enough observations to calibrate
        obs_dist = global_counts / global_counts.sum()

        # Expected distribution from our priors (average over dynamic cells)
        # Use observed cells' priors as reference
        prior_avg = np.zeros(6)
        n_obs_cells = 0
        for (y, x) in observations:
            prior_avg += priors[y, x]
            n_obs_cells += 1
        if n_obs_cells > 0:
            prior_avg /= n_obs_cells

        # Calibration ratio: how much to scale each class
        # Blend: 60% calibration + 40% no-change to avoid over-correction
        cal_ratio = np.ones(6)
        for c in range(6):
            if prior_avg[c] > 0.005:
                raw_ratio = obs_dist[c] / prior_avg[c]
                cal_ratio[c] = 0.4 + 0.6 * np.clip(raw_ratio, 0.2, 5.0)

        log.info(f"Calibration: obs_dist=[{','.join(f'{v:.3f}' for v in obs_dist)}] "
                 f"ratio=[{','.join(f'{v:.2f}' for v in cal_ratio)}]")

        # Apply calibration to ALL cells (not just observed)
        for y in range(h):
            for x in range(w):
                pred[y, x] *= cal_ratio
        pred = np.maximum(pred, FLOOR)
        pred /= pred.sum(axis=-1, keepdims=True)

    # Phase 2: Per-cell Bayesian update for observed cells
    for (y, x), obs in observations.items():
        if not obs:
            continue
        counts = np.zeros(6)
        for c in obs:
            counts[c] += 1
        emp = counts / counts.sum()

        n = len(obs)
        pw = 10.0  # Trust calibrated priors but let observations refine
        pred[y, x] = (emp * n + pred[y, x] * pw) / (n + pw)

    pred = np.maximum(pred, FLOOR)
    pred /= pred.sum(axis=-1, keepdims=True)
    pred = np.maximum(pred, FLOOR)
    pred /= pred.sum(axis=-1, keepdims=True)
    return pred


# === RUN A ROUND ===
def run_round(rnd):
    rid = rnd["id"]
    rn = rnd["round_number"]
    log.info(f"=== RUNNING ROUND {rn} ===")

    details = api("GET", f"rounds/{rid}")
    h, w = details["map_height"], details["map_width"]
    states = details["initial_states"]
    n_seeds = len(states)

    budget = api("GET", "budget")
    remaining = budget["queries_max"] - budget["queries_used"]
    qps = remaining // n_seeds
    log.info(f"Budget: {remaining} queries, {qps} per seed")

    for si in range(n_seeds):
        log.info(f"--- SEED {si} ---")
        grid = states[si]["grid"]
        setts = states[si]["settlements"]

        priors = compute_priors(grid, setts, h, w)
        vps = plan_viewports(grid, priors, h, w, qps)
        log.info(f"{len(vps)} viewports (entropy-based)")

        obs = defaultdict(list)
        for qi, (vx, vy, vw, vh) in enumerate(vps):
            try:
                res = api("POST", "simulate", {
                    "round_id": rid, "seed_index": si,
                    "viewport_x": vx, "viewport_y": vy,
                    "viewport_w": vw, "viewport_h": vh,
                })
                vp = res["viewport"]
                g = res["grid"]
                for dy in range(len(g)):
                    for dx in range(len(g[dy])):
                        obs[(vp["y"] + dy, vp["x"] + dx)].append(to_class(g[dy][dx]))
                log.info(f"Q{qi + 1}/{len(vps)}: ({vx},{vy}) {res['queries_used']}/{res['queries_max']}")
                time.sleep(0.2)
            except Exception as e:
                log.error(f"Q{qi + 1} FAILED: {e}")
                break

        prediction = aggregate(obs, priors, h, w)

        assert prediction.shape == (h, w, 6)
        assert np.allclose(prediction.sum(axis=-1), 1.0, atol=0.02)
        assert prediction.min() >= FLOOR * 0.99

        try:
            result = api("POST", "submit", {
                "round_id": rid, "seed_index": si,
                "prediction": prediction.tolist(),
            })
            log.info(f"SUBMITTED seed {si}: {result}")
        except Exception as e:
            log.error(f"SUBMIT FAILED seed {si}: {e}")

    log.info(f"=== ROUND {rn} COMPLETE — ALL {n_seeds} SEEDS SUBMITTED ===")

    state = load_state()
    state["submitted_rounds"].append(rid)
    save_state(state)


# === MAIN LOOP ===
def main():
    log.info("=== ASTAR ISLAND V6 — AUTO FEEDBACK LOOP ===")

    # Initial learning from all completed rounds
    learn_from_all_completed()

    last_submitted = None
    while True:
        try:
            rounds = api("GET", "rounds")

            # 1. Learn from newly completed rounds
            completed = [r for r in rounds if r["status"] == "completed"]
            state = load_state()
            analyzed = set(state.get("analyzed_rounds", []))
            new_completed = [r for r in completed if r["id"] not in analyzed]
            if new_completed:
                log.info(f"{len(new_completed)} new completed round(s) — rebuilding priors...")
                learn_from_all_completed()

            # 2. Run active round if not yet submitted
            active = [r for r in rounds if r["status"] == "active"]
            if active:
                rnd = active[0]
                rid = rnd["id"]

                if rid == last_submitted:
                    pass  # Already handled
                else:
                    budget = api("GET", "budget")
                    if budget["queries_used"] > 5:
                        log.info(f"Round {rnd['round_number']}: {budget['queries_used']} queries already used — skipping")
                        last_submitted = rid
                    else:
                        run_round(rnd)
                        last_submitted = rid

        except Exception as e:
            log.error(f"Loop error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
