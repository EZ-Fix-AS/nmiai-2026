"""
Astar Island — Monte Carlo Prediction (V5)
Distance-aware priors from 13 rounds of ground truth data
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
DIST_PRIORS_FILE = Path(__file__).parent / "astar_dist_priors.json"
SIMPLE_PRIORS_FILE = Path(__file__).parent / "astar_learned_priors_v2.json"

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

# === PRIORS ===
def compute_priors(grid, settlements, h, w):
    """Distance-aware priors from 68k+ ground truth cells across 13 rounds."""
    grid = np.array(grid)
    sett_positions = [(s["y"], s["x"]) for s in settlements]

    # Load distance-aware priors
    dist_priors = {}
    if DIST_PRIORS_FILE.exists():
        dist_priors = json.loads(DIST_PRIORS_FILE.read_text())

    # Load simple terrain priors as fallback
    simple_priors = {}
    if SIMPLE_PRIORS_FILE.exists():
        data = json.loads(SIMPLE_PRIORS_FILE.read_text())
        simple_priors = data.get("terrain_to_outcome", {})

    # Compute distance to nearest settlement (Chebyshev)
    dist_map = np.full((h, w), 99)
    for sy, sx in sett_positions:
        for y in range(h):
            for x in range(w):
                d = max(abs(y - sy), abs(x - sx))
                dist_map[y, x] = min(dist_map[y, x], d)

    # Compute coast proximity (within radius 2)
    coast_map = np.zeros((h, w), dtype=bool)
    for y in range(h):
        for x in range(w):
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and grid[ny, nx] == 10:
                        coast_map[y, x] = True
                        break
                if coast_map[y, x]:
                    break

    P = np.full((h, w, 6), FLOOR)
    for y in range(h):
        for x in range(w):
            tv = int(grid[y, x])
            d = min(int(dist_map[y, x]), 8)
            nc = 1 if coast_map[y, x] else 0
            key = f"{tv}_{d}_{nc}"

            if key in dist_priors:
                P[y, x] = np.array(dist_priors[key]["probs"])
            elif str(tv) in simple_priors:
                P[y, x] = np.array(simple_priors[str(tv)])
            elif tv == 10:
                P[y, x] = [0.97, 0.005, 0.005, 0.005, 0.005, 0.01]
            elif tv == 5:
                P[y, x] = [0.005, 0.005, 0.005, 0.005, 0.005, 0.975]

    P = np.maximum(P, FLOOR)
    P /= P.sum(axis=-1, keepdims=True)
    P = np.maximum(P, FLOOR)
    P /= P.sum(axis=-1, keepdims=True)
    return P

# === VIEWPORT PLANNING ===
def plan_viewports(grid, settlements, h, w, n_queries):
    """Plan viewports focusing on dynamic zones near settlements."""
    grid = np.array(grid)
    dynamic = np.zeros((h, w), dtype=bool)
    for s in settlements:
        for dy in range(-7, 8):
            for dx in range(-7, 8):
                ny, nx = s["y"] + dy, s["x"] + dx
                if 0 <= ny < h and 0 <= nx < w:
                    dynamic[ny, nx] = True

    vps = []
    covered = np.zeros((h, w), dtype=int)
    for _ in range(n_queries):
        best = (-1, None)
        for vy in range(0, h - 5, 2):
            for vx in range(0, w - 5, 2):
                vw, vh = min(15, w - vx), min(15, h - vy)
                region = dynamic[vy:vy + vh, vx:vx + vw]
                cov = covered[vy:vy + vh, vx:vx + vw]
                score = np.sum(region * (1.0 / (cov + 1)))
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
    """Bayesian update: combine observations with priors."""
    pred = np.copy(priors)
    for (y, x), obs in observations.items():
        if not obs:
            continue
        counts = np.zeros(6)
        for c in obs:
            counts[c] += 1
        emp = counts / counts.sum()

        n = len(obs)
        pw = max(2.0, 5.0 - n)
        pred[y, x] = (emp * n + priors[y, x] * pw) / (n + pw)

    pred = np.maximum(pred, FLOOR)
    pred /= pred.sum(axis=-1, keepdims=True)
    pred = np.maximum(pred, FLOOR)
    pred /= pred.sum(axis=-1, keepdims=True)
    return pred

# === MAIN ===
def main():
    log.info("=== ASTAR ISLAND V5 — Distance-Aware ===")

    rounds = api("GET", "rounds")
    active = [r for r in rounds if r["status"] == "active"]
    if not active:
        log.info("Ingen aktiv runde.")
        return

    rnd = active[0]
    rid = rnd["id"]
    log.info(f"Runde #{rnd['round_number']}: {rid}")

    details = api("GET", f"rounds/{rid}")
    h, w = details["map_height"], details["map_width"]
    states = details["initial_states"]
    n_seeds = len(states)

    budget = api("GET", "budget")
    remaining = budget["queries_max"] - budget["queries_used"]
    qps = remaining // n_seeds
    log.info(f"Budget: {remaining} queries, {qps} per seed")

    for si in range(n_seeds):
        log.info(f"{'=' * 40} SEED {si} {'=' * 40}")
        grid = states[si]["grid"]
        setts = states[si]["settlements"]

        priors = compute_priors(grid, setts, h, w)
        vps = plan_viewports(grid, setts, h, w, qps)
        log.info(f"{len(vps)} viewports planlagt")

        obs = defaultdict(list)
        for qi, (vx, vy, vw, vh) in enumerate(vps):
            try:
                res = api("POST", "simulate", {
                    "round_id": rid, "seed_index": si,
                    "viewport_x": vx, "viewport_y": vy,
                    "viewport_w": vw, "viewport_h": vh
                })
                vp = res["viewport"]
                g = res["grid"]
                for dy in range(len(g)):
                    for dx in range(len(g[dy])):
                        obs[(vp["y"] + dy, vp["x"] + dx)].append(to_class(g[dy][dx]))
                log.info(f"Q{qi + 1}/{len(vps)}: ({vx},{vy}) — {res['queries_used']}/{res['queries_max']}")
                time.sleep(0.2)
            except Exception as e:
                log.error(f"Q{qi + 1} FEIL: {e}")
                break

        prediction = aggregate(obs, priors, h, w)

        assert prediction.shape == (h, w, 6)
        assert np.allclose(prediction.sum(axis=-1), 1.0, atol=0.02)
        assert prediction.min() >= FLOOR * 0.99

        try:
            result = api("POST", "submit", {
                "round_id": rid, "seed_index": si,
                "prediction": prediction.tolist()
            })
            log.info(f"SUBMITTED: {result}")
        except Exception as e:
            log.error(f"SUBMIT FEIL: {e}")

    log.info("ALLE SEEDS SUBMITTED")

if __name__ == "__main__":
    main()
