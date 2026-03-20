"""
Astar Island — Monte Carlo Prediction (V4)
Temporal priors, dynamisk prior-weight, error recovery
NM i AI 2026 — EZ-Fix AS
"""
import time
import json
import logging
import numpy as np
import requests
from collections import Counter, defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("astar")

# === CONFIG ===
BASE = "https://api.ainm.no/astar-island"
TOKEN = "PASTE_JWT_HER"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
FLOOR = 0.01
LEARNING_FILE = "astar_learned_priors.json"

def api(method, path, body=None):
    r = requests.request(method, f"{BASE}/{path.lstrip('/')}", headers=HEADERS, json=body)
    r.raise_for_status()
    return r.json()

def to_class(v):
    return {0:0, 10:0, 11:0, 1:1, 2:2, 3:3, 4:4, 5:5}.get(v, 0)

# === LEARNED PRIORS ===
def load_learned_priors():
    p = Path(LEARNING_FILE)
    if p.exists():
        return json.loads(p.read_text())
    return None

def save_learned_priors(data):
    Path(LEARNING_FILE).write_text(json.dumps(data))

# === PRIORS ===
def compute_priors(grid, settlements, h, w):
    learned = load_learned_priors()
    P = np.full((h, w, 6), FLOOR)
    sett_pos = {(s["y"], s["x"]) for s in settlements}

    def near(y, x, positions, r=3):
        return any(abs(y-py)<=r and abs(x-px)<=r for py,px in positions)

    def near_val(y, x, val, r=2):
        for dy in range(-r, r+1):
            for dx in range(-r, r+1):
                ny, nx = y+dy, x+dx
                if 0<=ny<h and 0<=nx<w and grid[ny][nx]==val:
                    return True
        return False

    for y in range(h):
        for x in range(w):
            v = grid[y][x]

            # Use learned terrain→outcome if available
            if learned and str(v) in learned.get("terrain_to_outcome", {}):
                base = np.array(learned["terrain_to_outcome"][str(v)])
                P[y, x] = base
                continue

            if v == 10:
                P[y,x] = [0.97, 0.005, 0.005, 0.005, 0.005, 0.01]
            elif v == 5:
                P[y,x] = [0.005, 0.005, 0.005, 0.005, 0.01, 0.97]
            elif v == 4:
                if near(y,x,sett_pos,3):
                    P[y,x] = [0.08, 0.15, 0.05, 0.05, 0.62, 0.05]
                else:
                    P[y,x] = [0.04, 0.02, 0.01, 0.03, 0.87, 0.03]
            elif v == 1:
                coast = near_val(y,x,10,2)
                forest = near_val(y,x,4,2)
                if coast and forest:
                    P[y,x] = [0.04, 0.28, 0.28, 0.15, 0.20, 0.05]
                elif coast:
                    P[y,x] = [0.05, 0.22, 0.33, 0.20, 0.10, 0.10]
                elif forest:
                    P[y,x] = [0.05, 0.42, 0.05, 0.18, 0.25, 0.05]
                else:
                    P[y,x] = [0.10, 0.18, 0.04, 0.43, 0.15, 0.10]
            elif v == 2:
                P[y,x] = [0.04, 0.13, 0.43, 0.20, 0.10, 0.10]
            elif v == 3:
                if near(y,x,sett_pos,4):
                    P[y,x] = [0.10, 0.22, 0.10, 0.28, 0.25, 0.05]
                else:
                    P[y,x] = [0.13, 0.04, 0.02, 0.26, 0.50, 0.05]
            else:
                if near(y,x,sett_pos,5):
                    if near_val(y,x,10,2):
                        P[y,x] = [0.28, 0.22, 0.15, 0.10, 0.15, 0.10]
                    else:
                        P[y,x] = [0.38, 0.27, 0.04, 0.10, 0.16, 0.05]
                else:
                    P[y,x] = [0.68, 0.04, 0.02, 0.05, 0.16, 0.05]

    # Bias correction from previous round
    if learned and learned.get("pred_bias"):
        bias = np.array(learned["pred_bias"])
        for y in range(h):
            for x in range(w):
                P[y, x] -= bias * 0.5

    P = np.maximum(P, FLOOR)
    P /= P.sum(axis=-1, keepdims=True)
    return P

# === VIEWPORT PLANNING ===
def plan_viewports(grid, settlements, h, w, n_queries):
    dynamic = np.zeros((h,w), dtype=bool)
    for s in settlements:
        for dy in range(-7,8):
            for dx in range(-7,8):
                ny, nx = s["y"]+dy, s["x"]+dx
                if 0<=ny<h and 0<=nx<w:
                    dynamic[ny,nx] = True

    vps = []
    covered = np.zeros((h,w), dtype=int)
    for _ in range(n_queries):
        best = (-1, None)
        for vy in range(0, h-5, 2):
            for vx in range(0, w-5, 2):
                vw, vh = min(15, w-vx), min(15, h-vy)
                region = dynamic[vy:vy+vh, vx:vx+vw]
                cov = covered[vy:vy+vh, vx:vx+vw]
                score = np.sum(region * (1.0/(cov+1)))
                if score > best[0]:
                    best = (score, (vx,vy,vw,vh))
        if best[1] is None: break
        vx,vy,vw,vh = best[1]
        covered[vy:vy+vh, vx:vx+vw] += 1
        vps.append(best[1])
    return vps

# === AGGREGATION ===
def aggregate(observations, priors, h, w):
    pred = np.copy(priors)
    for (y,x), obs in observations.items():
        if not obs: continue
        counts = np.zeros(6)
        for c in obs: counts[c] += 1
        emp = counts / counts.sum()

        n = len(obs)
        pw = max(2.0, 5.0 - n)  # Dynamic prior weight
        pred[y,x] = (emp * n + priors[y,x] * pw) / (n + pw)

    pred = np.maximum(pred, FLOOR)
    pred /= pred.sum(axis=-1, keepdims=True)
    return pred

# === TEMPORAL LEARNING ===
def learn_from_analysis(round_id):
    learned = {
        "class_freq": [0]*6,
        "pred_bias": [0]*6,
        "n_cells_analyzed": 0,
        "terrain_to_outcome": {}
    }

    terrain_stats = {}

    for si in range(5):
        try:
            data = api("GET", f"analysis/{round_id}/{si}")
            truth = np.array(data["ground_truth"])
            pred = np.array(data.get("prediction", []))
            init_grid = data.get("initial_grid")

            h, w = truth.shape[:2]

            for y in range(h):
                for x in range(w):
                    t = truth[y, x]
                    entropy = -np.sum(t * np.log(t + 1e-10))

                    if entropy > 0.1:
                        for c in range(6):
                            learned["class_freq"][c] += t[c]

                        if len(pred) > 0:
                            for c in range(6):
                                learned["pred_bias"][c] += (pred[y,x,c] - t[c])

                        if init_grid:
                            iv = init_grid[y][x]
                            if iv not in terrain_stats:
                                terrain_stats[iv] = np.zeros(6)
                            terrain_stats[iv] += t

                        learned["n_cells_analyzed"] += 1

        except Exception as e:
            log.warning(f"Analyse seed {si} feilet: {e}")

    n = max(learned["n_cells_analyzed"], 1)
    learned["class_freq"] = [f/n for f in learned["class_freq"]]
    learned["pred_bias"] = [b/n for b in learned["pred_bias"]]

    for iv, counts in terrain_stats.items():
        total = counts.sum()
        if total > 0:
            learned["terrain_to_outcome"][str(iv)] = (counts / total).tolist()

    save_learned_priors(learned)

    log.info(f"Lært fra {n} dynamiske celler:")
    for c, name in enumerate(["Empty","Settlement","Port","Ruin","Forest","Mountain"]):
        freq = learned["class_freq"][c]
        bias = learned["pred_bias"][c]
        log.info(f"  {name}: freq={freq:.3f}, bias={bias:+.3f}")

    return learned

# === ANALYSIS ===
def analyze_last_round(round_info):
    rid = round_info["id"]
    log.info(f"Analyserer runde #{round_info['round_number']}...")

    for si in range(5):
        try:
            data = api("GET", f"analysis/{rid}/{si}")
            if data.get("score") is not None:
                pred = np.array(data["prediction"])
                truth = np.array(data["ground_truth"])

                log.info(f"Seed {si}: score={data['score']:.1f}")

                for cls, name in enumerate(["Empty","Settlement","Port","Ruin","Forest","Mountain"]):
                    p_avg = pred[:,:,cls].mean()
                    t_avg = truth[:,:,cls].mean()
                    diff = p_avg - t_avg
                    if abs(diff) > 0.01:
                        direction = "OVER" if diff > 0 else "UNDER"
                        log.info(f"  {name}: {direction} med {abs(diff):.3f}")
        except:
            pass

    # V4: Learn from this round
    learn_from_analysis(rid)

# === MAIN ===
def main():
    log.info("=== ASTAR ISLAND V4 ===")

    rounds = api("GET", "rounds")
    active = [r for r in rounds if r["status"] == "active"]
    if not active:
        log.info("Ingen aktiv runde.")
        completed = [r for r in rounds if r["status"] == "completed"]
        if completed:
            latest = max(completed, key=lambda r: r["round_number"])
            analyze_last_round(latest)
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
        log.info(f"{'='*40} SEED {si} {'='*40}")
        grid = states[si]["grid"]
        setts = states[si]["settlements"]

        priors = compute_priors(grid, setts, h, w)
        vps = plan_viewports(grid, setts, h, w, qps)
        log.info(f"{len(vps)} viewports planlagt")

        obs = defaultdict(list)
        for qi, (vx,vy,vw,vh) in enumerate(vps):
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
                        obs[(vp["y"]+dy, vp["x"]+dx)].append(to_class(g[dy][dx]))
                log.info(f"Q{qi+1}/{len(vps)}: ({vx},{vy}) — {res['queries_used']}/{res['queries_max']}")
                time.sleep(0.25)
            except Exception as e:
                log.error(f"Q{qi+1} FEIL: {e}")
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

    # Learn from completed rounds
    completed = [r for r in rounds if r["status"] == "completed"]
    if completed:
        latest = max(completed, key=lambda r: r["round_number"])
        log.info(f"Kjører V4 temporal learning fra runde #{latest['round_number']}...")
        learn_from_analysis(latest["id"])

if __name__ == "__main__":
    main()
