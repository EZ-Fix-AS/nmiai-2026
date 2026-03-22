"""
Poll for active Astar Island round and run immediately.
Usage: python3 poll_and_run.py
"""
import time
import subprocess
import requests
import sys

BASE = "https://api.ainm.no/astar-island"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIyOTJlNDQzMi0wNDY4LTRhNjAtOTY3OS1jYWIzODY4ZDdhZjYiLCJlbWFpbCI6Im1hcmt1c0Blei1maXgubm8iLCJpc19hZG1pbiI6ZmFsc2UsImV4cCI6MTc3NDY0Nzg4M30.hEeMSjseq5Kstu9D1c2TprPNXW6vxC3w1DPq4X_Jzcs"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

last_round = 14
poll_interval = 15  # seconds

print(f"Polling for round > {last_round}... (every {poll_interval}s)")

while True:
    try:
        r = requests.get(f"{BASE}/rounds", headers=HEADERS, timeout=10)
        rounds = r.json()
        active = [rd for rd in rounds if rd["status"] == "active" and rd["round_number"] > last_round]

        if active:
            rnd = active[0]
            print(f"\n{'='*60}")
            print(f"ROUND {rnd['round_number']} IS ACTIVE! Running main.py...")
            print(f"{'='*60}")

            # Check budget
            b = requests.get(f"{BASE}/budget", headers=HEADERS).json()
            remaining = b["queries_max"] - b["queries_used"]
            print(f"Budget: {remaining} queries remaining")

            if remaining > 0:
                result = subprocess.run(
                    [sys.executable, "main.py"],
                    capture_output=True, text=True, timeout=120
                )
                print(result.stdout[-2000:] if result.stdout else "")
                if result.stderr:
                    print(result.stderr[-1000:])

                last_round = rnd["round_number"]
                print(f"\nDone! Waiting for round > {last_round}...")
            else:
                print(f"No budget! Waiting...")
                last_round = rnd["round_number"]
        else:
            # Check newest completed round
            completed = [rd for rd in rounds if rd["status"] == "completed"]
            if completed:
                newest = max(completed, key=lambda r: r["round_number"])
                if newest["round_number"] > last_round:
                    last_round = newest["round_number"]
                    print(f"Round {newest['round_number']} completed (missed). Now polling for > {last_round}")

            sys.stdout.write(".")
            sys.stdout.flush()

    except Exception as e:
        print(f"\nError: {e}")

    time.sleep(poll_interval)
