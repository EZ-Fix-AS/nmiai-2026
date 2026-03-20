# CLAUDE CODE PROMPT — AGENT 3: ASTAR ISLAND NORSE WORLD PREDICTION (V3)
# NM i AI 2026 | Dream Team: Hinton, Karpathy, Musk, Hotz
# V3-forbedringer: Temporal priors, dynamisk PRIOR_WEIGHT, start fredag kveld

---

## V3-ENDRINGER FRA V2

1. **Temporal priors** — bruk `/analysis` fra forrige runde til å oppdatere priors for neste
2. **Dynamisk PRIOR_WEIGHT** — `max(2.0, 5.0 - n_obs)`: mer prior-vekt ved få observasjoner
3. **Start fredag kveld** (ikke lørdag morgen) — scriptet er <200 linjer, skrives på 1-2 timer
4. **Viewport: behold greedy** — koster millisekunder, gir bedre dekning enn uniform grid

---

## OPERATIVE REGLER (uendret fra V2)

**Hinton:** Statistisk fysikk. Probability floor 0.01. Maks 2 hyperparametre. Enkelhet.
**Karpathy:** Inspiser data. Verifiser hvert steg. Test på MNIST først.
**Musk:** Slett statiske soner. First principles priors.
**Hotz:** Én fil. Under 200 linjer. Fungerer det? Ship det.

---

## IMPLEMENTASJON — ÉN FIL (V3)

```python
"""
Astar Island — Monte Carlo Prediction (V3)
V3: Temporal priors, dynamisk prior-weight, error recovery
"""
import time
import json
import numpy as np
import requests
from collections import Counter, defaultdict

# === CONFIG ===
BASE = "https://api.ainm.no/astar-island"
TOKEN = "PASTE_JWT_HER"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
FLOOR = 0.01

def api(method, path, body=None):
    r = requests.request(method, f"{BASE}/{path.lstrip('/')}", headers=HEADERS, json=body)
    r.raise_for_status()
    return r.json()

def to_class(v):
    return {0:0, 10:0, 11:0, 1:1, 2:2, 3:3, 4:4, 5:5}.get(v, 0)

# === PRIORS (Hinton: knowledge distillation) ===
def compute_priors(grid, settlements, h, w, prev_truth=None):
    """
    V3: Hvis prev_truth finnes (fra forrige runde), bruk det som sterkere prior.
    Hinton: "Overføring av kunnskap fra en stor modell til en liten modell."
    """
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
            
            # V3: Hvis vi har ground truth fra forrige runde, bruk det
            # (kartene er forskjellige, men mekanikkene er like — 
            #  settlement-overlevelse, ruin-sannsynlighet etc. er overførbare som priors)
            
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

    P = np.maximum(P, FLOOR)
    P /= P.sum(axis=-1, keepdims=True)
    return P

# === VIEWPORT-PLANLEGGING (behold greedy — koster millisekunder) ===
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

# === AGGREGERING MED DYNAMISK PRIOR_WEIGHT (V3) ===
def aggregate(observations, priors, h, w):
    """
    V3: Dynamisk prior_weight = max(2.0, 5.0 - n_obs)
    Celler med 1-2 obs → stol mer på priors
    Celler med 5+ obs → stol mer på empiri
    """
    pred = np.copy(priors)
    for (y,x), obs in observations.items():
        if not obs: continue
        counts = np.zeros(6)
        for c in obs: counts[c] += 1
        emp = counts / counts.sum()
        
        n = len(obs)
        pw = max(2.0, 5.0 - n)  # V3: dynamisk
        pred[y,x] = (emp * n + priors[y,x] * pw) / (n + pw)
    
    pred = np.maximum(pred, FLOOR)
    pred /= pred.sum(axis=-1, keepdims=True)
    return pred

# === MAIN ===
def main():
    # 1. Finn aktiv runde
    rounds = api("GET", "rounds")
    active = [r for r in rounds if r["status"] == "active"]
    if not active:
        print("Ingen aktiv runde.")
        # V3: Sjekk om det finnes completed runder vi kan analysere
        completed = [r for r in rounds if r["status"] == "completed"]
        if completed:
            print(f"Fant {len(completed)} ferdige runder — kjør analyse.")
            analyze_last_round(completed[-1])
        return

    rnd = active[0]
    rid = rnd["id"]
    print(f"Runde #{rnd['round_number']}: {rid}")

    details = api("GET", f"rounds/{rid}")
    h, w = details["map_height"], details["map_width"]
    states = details["initial_states"]
    n_seeds = len(states)

    budget = api("GET", "budget")
    remaining = budget["queries_max"] - budget["queries_used"]
    qps = remaining // n_seeds
    print(f"Budget: {remaining} queries, {qps} per seed")

    for si in range(n_seeds):
        print(f"\n{'='*40} SEED {si} {'='*40}")
        grid = states[si]["grid"]
        setts = states[si]["settlements"]

        priors = compute_priors(grid, setts, h, w)
        vps = plan_viewports(grid, setts, h, w, qps)
        print(f"  {len(vps)} viewports planlagt")

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
                print(f"  Q{qi+1}/{len(vps)}: ({vx},{vy}) — {res['queries_used']}/{res['queries_max']}")
                time.sleep(0.25)
            except Exception as e:
                print(f"  Q{qi+1} FEIL: {e}")
                break

        prediction = aggregate(obs, priors, h, w)
        
        # Karpathy: verifiser format
        assert prediction.shape == (h, w, 6)
        assert np.allclose(prediction.sum(axis=-1), 1.0, atol=0.02)
        assert prediction.min() >= FLOOR * 0.99

        try:
            result = api("POST", "submit", {
                "round_id": rid, "seed_index": si,
                "prediction": prediction.tolist()
            })
            print(f"  SUBMITTED: {result}")
        except Exception as e:
            print(f"  SUBMIT FEIL: {e}")

    print(f"\n{'='*40}\nALLE SEEDS SUBMITTED")

# === V3: ANALYSE-FUNKSJON (temporal priors) ===
def analyze_last_round(round_info):
    """
    Hent ground truth fra forrige runde og analyser feilmønstre.
    Hinton: "Forstå HVORFOR modellen feiler."
    """
    rid = round_info["id"]
    print(f"\nAnalyserer runde #{round_info['round_number']}...")
    
    for si in range(5):
        try:
            data = api("GET", f"analysis/{rid}/{si}")
            if data.get("score") is not None:
                pred = np.array(data["prediction"])
                truth = np.array(data["ground_truth"])
                
                print(f"\n  Seed {si}: score={data['score']:.1f}")
                
                # Systematiske feil per klasse
                for cls, name in enumerate(["Empty","Settlement","Port","Ruin","Forest","Mountain"]):
                    p_avg = pred[:,:,cls].mean()
                    t_avg = truth[:,:,cls].mean()
                    diff = p_avg - t_avg
                    if abs(diff) > 0.01:
                        direction = "OVERPREDIKERER" if diff > 0 else "UNDERPREDIKERER"
                        print(f"    {name}: {direction} med {abs(diff):.3f}")
        except:
            pass

if __name__ == "__main__":
    main()
```

---

## TIDSPLAN (V3: start fredag kveld)

| Tid | Hva |
|-----|-----|
| **Fre kveld** | Skriv scriptet (1-2 timer mens YOLO trener) |
| **Lør morgen** | Hent JWT, kjør på aktiv runde, submit alle 5 seeds |
| **Lør ettermiddag** | Analyser resultater, juster priors |
| **Lør kveld** | Kjør neste runde med forbedrede priors |
| **Søn morgen** | Siste runder + V3 temporal priors fra analyse |

## SUKSESSKRITERIER (V3)

- [ ] Alle 5 seeds submitted per runde
- [ ] Probability floor 0.01 på alle celler
- [ ] Dynamisk PRIOR_WEIGHT implementert
- [ ] Post-runde analyse utført (Karpathy + Hinton)
- [ ] Temporal priors brukt mellom runder (V3)
- [ ] Under 200 linjer kode
