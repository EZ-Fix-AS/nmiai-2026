"""
NM i AI 2026 — Live Dashboard
Read-only. Henter data fra journalctl + Astar API.
Deployed separat fra Tripletex-agenten.
"""
import json, re, subprocess, time
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import requests

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ASTAR_BASE = "https://api.ainm.no/astar-island"
ASTAR_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIyOTJlNDQzMi0wNDY4LTRhNjAtOTY3OS1jYWIzODY4ZDdhZjYiLCJlbWFpbCI6Im1hcmt1c0Blei1maXgubm8iLCJpc19hZG1pbiI6ZmFsc2UsImV4cCI6MTc3NDY0Nzg4M30.hEeMSjseq5Kstu9D1c2TprPNXW6vxC3w1DPq4X_Jzcs"
ASTAR_HEADERS = {"Authorization": f"Bearer {ASTAR_TOKEN}"}

# Cache for Astar data (don't spam the API)
_cache = {"astar": None, "astar_ts": 0, "tripletex": None, "tripletex_ts": 0}
CACHE_TTL = 30  # seconds for tripletex
ASTAR_CACHE_TTL = 120  # seconds for astar (avoid API spam)


def get_tripletex_data():
    """Parse journalctl logs from tripletex-agent."""
    now = time.time()
    if _cache["tripletex"] and now - _cache["tripletex_ts"] < CACHE_TTL:
        return _cache["tripletex"]

    try:
        result = subprocess.run(
            ["journalctl", "-u", "tripletex-agent", "--since", "6 hours ago", "--no-pager", "-o", "short-iso"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().split("\n") if result.stdout else []
    except Exception:
        lines = []

    tasks = []
    current_task = None
    handler_stats = {}  # handler → {total, success, total_calls, total_errors}

    for line in lines:
        # Parse OPPGAVE
        m = re.search(r'(\d{2}:\d{2}:\d{2}).*OPPGAVE: (.+)', line)
        if m:
            if current_task:
                tasks.append(current_task)
            current_task = {
                "time": m.group(1),
                "prompt": m.group(2)[:120],
                "intent": None,
                "api_calls": None,
                "errors": None,
                "error_rate": None,
                "status": "running"
            }
            continue

        # Parse INTENT (kan komme fra annen worker enn OPPGAVE)
        m = re.search(r'INTENT: (\w+)', line)
        if m:
            if current_task and not current_task["intent"]:
                current_task["intent"] = m.group(1)
            elif current_task:
                current_task["intent"] = m.group(1)
            continue

        # Parse SUMMARY
        m = re.search(r'SUMMARY: ({.+})', line)
        if m and current_task:
            try:
                s = json.loads(m.group(1))
                current_task["api_calls"] = s.get("total_calls", 0)
                current_task["errors"] = s.get("errors", 0)
                current_task["error_rate"] = s.get("error_rate", "?")
                current_task["status"] = "ok" if s.get("errors", 0) == 0 else "error"

                intent = current_task["intent"] or "unknown"
                if intent not in handler_stats:
                    handler_stats[intent] = {"total": 0, "success": 0, "total_calls": 0, "total_errors": 0}
                handler_stats[intent]["total"] += 1
                handler_stats[intent]["total_calls"] += s.get("total_calls", 0)
                handler_stats[intent]["total_errors"] += s.get("errors", 0)
                if s.get("errors", 0) == 0:
                    handler_stats[intent]["success"] += 1
            except json.JSONDecodeError:
                pass
            continue

    if current_task:
        tasks.append(current_task)

    data = {
        "tasks": tasks[-50:],  # Last 50
        "handler_stats": handler_stats,
        "total_tasks": len(tasks),
        "total_ok": sum(1 for t in tasks if t["status"] == "ok"),
        "total_error": sum(1 for t in tasks if t["status"] == "error"),
    }
    _cache["tripletex"] = data
    _cache["tripletex_ts"] = now
    return data


def get_astar_data():
    """Fetch Astar Island round data."""
    now = time.time()
    if _cache["astar"] and now - _cache["astar_ts"] < ASTAR_CACHE_TTL:
        return _cache["astar"]

    try:
        rounds = requests.get(f"{ASTAR_BASE}/rounds", headers=ASTAR_HEADERS, timeout=10).json()
        budget = requests.get(f"{ASTAR_BASE}/budget", headers=ASTAR_HEADERS, timeout=10).json()

        active = [r for r in rounds if r["status"] == "active"]
        completed = sorted([r for r in rounds if r["status"] == "completed"],
                           key=lambda r: r["round_number"])

        # Get scores from completed rounds where we submitted
        round_scores = []
        for rnd in completed[-5:]:  # Last 5
            seeds = []
            for si in range(5):
                try:
                    analysis = requests.get(
                        f"{ASTAR_BASE}/analysis/{rnd['id']}/{si}",
                        headers=ASTAR_HEADERS, timeout=10
                    ).json()
                    seeds.append(analysis.get("score"))
                except Exception:
                    seeds.append(None)

            submitted = any(s is not None for s in seeds)
            avg_score = None
            if submitted and any(s is not None for s in seeds):
                valid = [s for s in seeds if s is not None]
                avg_score = sum(valid) / len(valid) if valid else None

            round_scores.append({
                "round": rnd["round_number"],
                "submitted": submitted,
                "seeds": seeds,
                "avg_score": avg_score
            })

        data = {
            "active_round": active[0]["round_number"] if active else None,
            "latest_completed": completed[-1]["round_number"] if completed else None,
            "total_rounds": len(rounds),
            "budget_used": budget.get("queries_used", 0),
            "budget_max": budget.get("queries_max", 50),
            "round_scores": round_scores
        }
    except Exception as e:
        data = {"error": str(e), "active_round": None, "round_scores": []}

    _cache["astar"] = data
    _cache["astar_ts"] = now
    return data


@app.get("/api/tripletex")
def api_tripletex():
    return JSONResponse(get_tripletex_data())


@app.get("/api/astar")
def api_astar():
    return JSONResponse(get_astar_data())


def get_norgesgruppen_data():
    """NorgesGruppen static + submission info."""
    now = time.time()
    if _cache.get("norges") and now - _cache.get("norges_ts", 0) < CACHE_TTL:
        return _cache["norges"]

    data = {
        "score": 0.8951,
        "normalized_score": 96.7,
        "rank": "#? / 265",
        "submissions_scored": 6,
        "submissions_remaining": 0,
        "model": "YOLOv8x (ultralytics 8.4)",
        "training": "2-fase progressive resizing (640→1280)",
        "mAP50": 0.8951,
        "format": "ONNX (242 MB)",
        "categories": 356,
        "gpu": "kit-gpu-server (RTX 4000 SFF Ada 20GB)",
        "submission_file": "submission (242.1 MB)",
        "history": [
            {"time": "14:47", "score": 0.8951, "size": "242.1 MB"},
            {"time": "10:54", "score": 0.6599, "size": "212.6 MB"},
            {"time": "10:48", "score": 0.6670, "size": "212.6 MB"},
            {"time": "10:42", "score": 0.6666, "size": "212.6 MB"},
            {"time": "10:37", "score": 0.6571, "size": "212.6 MB"},
            {"time": "01:22", "score": 0.6517, "size": "212.6 MB"},
        ]
    }

    # Check if submission file exists on local or note size
    try:
        import os
        sub_path = "/opt/nmiai-tripletex/../norgesgruppen/submission_v2.zip"
        if os.path.exists(sub_path):
            size_mb = os.path.getsize(sub_path) / (1024*1024)
            data["submission_size_mb"] = round(size_mb, 1)
    except Exception:
        pass

    _cache["norges"] = data
    _cache["norges_ts"] = now
    return data


def get_leaderboard_data():
    """Fetch live leaderboard positions from competition API."""
    now = time.time()
    if _cache.get("leaderboard") and now - _cache.get("leaderboard_ts", 0) < ASTAR_CACHE_TTL:
        return _cache["leaderboard"]

    AINM_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIyOTJlNDQzMi0wNDY4LTRhNjAtOTY3OS1jYWIzODY4ZDdhZjYiLCJlbWFpbCI6Im1hcmt1c0Blei1maXgubm8iLCJpc19hZG1pbiI6ZmFsc2UsImV4cCI6MTc3NDY0Nzg4M30.hEeMSjseq5Kstu9D1c2TprPNXW6vxC3w1DPq4X_Jzcs"
    headers = {"Authorization": f"Bearer {AINM_TOKEN}"}

    data = {"tripletex": None, "astar": None, "norgesgruppen": None}

    # Tripletex leaderboard
    try:
        r = requests.get("https://api.ainm.no/tripletex/leaderboard", headers=headers, timeout=10)
        teams = r.json()
        total = len(teams)
        for t in teams:
            if t.get("team_slug") == "ez-fix":
                data["tripletex"] = {
                    "rank": t["rank"],
                    "total_teams": total,
                    "score": t["total_score"],
                    "submissions": t["total_submissions"],
                    "tasks_touched": t["tasks_touched"],
                    "tier1": t.get("tier1_score"),
                    "tier2": t.get("tier2_score"),
                    "tier3": t.get("tier3_score"),
                }
                break
        # Top 5
        data["tripletex_top5"] = [
            {"rank": t["rank"], "name": t["team_name"], "score": t["total_score"]}
            for t in teams[:5]
        ]
    except Exception as e:
        data["tripletex_error"] = str(e)

    # Astar leaderboard
    try:
        r = requests.get("https://api.ainm.no/astar-island/leaderboard", headers=headers, timeout=10)
        teams = r.json()
        total = len(teams)
        for t in teams:
            if t.get("team_slug") == "ez-fix":
                data["astar"] = {
                    "rank": t["rank"],
                    "total_teams": total,
                    "score": t.get("weighted_score"),
                    "rounds_participated": t.get("rounds_participated"),
                    "hot_streak": t.get("hot_streak_score"),
                }
                break
        data["astar_top5"] = [
            {"rank": t["rank"], "name": t["team_name"], "score": t.get("weighted_score")}
            for t in teams[:5]
        ]
    except Exception as e:
        data["astar_error"] = str(e)

    # NorgesGruppen — no leaderboard API, update manually when known
    data["norgesgruppen"] = {
        "rank": 72,
        "total_teams": 265,
        "score": 96.7,
    }

    # Overall — compute from live scores
    scores = []
    if data.get("tripletex") and data["tripletex"].get("score"):
        scores.append(data["tripletex"]["score"])
    if data.get("norgesgruppen") and data["norgesgruppen"].get("score"):
        scores.append(data["norgesgruppen"]["score"])
    if data.get("astar") and data["astar"].get("score"):
        # Astar weighted_score is different from normalized challenge score
        # Use the challenge score from the competition (91.1 last known)
        pass

    # Overall rank: approximate from individual ranks
    ranks = []
    if data.get("tripletex"): ranks.append(data["tripletex"]["rank"])
    if data.get("astar"): ranks.append(data["astar"]["rank"])
    if data.get("norgesgruppen") and data["norgesgruppen"]["rank"]:
        ranks.append(data["norgesgruppen"]["rank"])

    data["overall"] = {
        "rank": round(sum(ranks) / len(ranks)) if ranks else None,
        "tripletex_score": data.get("tripletex", {}).get("score"),
        "astar_score": data.get("astar", {}).get("score"),
        "norgesgruppen_score": data.get("norgesgruppen", {}).get("score"),
    }

    _cache["leaderboard"] = data
    _cache["leaderboard_ts"] = now
    return data


@app.get("/api/leaderboard")
def api_leaderboard():
    return JSONResponse(get_leaderboard_data())


@app.get("/api/norgesgruppen")
def api_norgesgruppen():
    return JSONResponse(get_norgesgruppen_data())


@app.get("/api/all")
def api_all():
    tx = get_tripletex_data()
    ng = get_norgesgruppen_data()
    try:
        astar = get_astar_data()
    except Exception:
        astar = _cache.get("astar") or {"error": "timeout", "active_round": None, "round_scores": []}
    try:
        lb = get_leaderboard_data()
    except Exception:
        lb = _cache.get("leaderboard") or {}
    return JSONResponse({
        "tripletex": tx,
        "astar": astar,
        "norgesgruppen": ng,
        "leaderboard": lb,
        "timestamp": datetime.now(timezone(timedelta(hours=1))).isoformat(),
        "deadline": "2026-03-22T15:00:00+01:00"
    })


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return open("/opt/nmiai-dashboard/index.html").read()
