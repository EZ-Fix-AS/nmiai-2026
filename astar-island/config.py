"""
Astar Island — Konfigurasjon
"""
BASE_URL = "https://api.ainm.no/astar-island"

# Hent fra browser cookies etter innlogging på app.ainm.no
# DevTools → Application → Cookies → access_token
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIyOTJlNDQzMi0wNDY4LTRhNjAtOTY3OS1jYWIzODY4ZDdhZjYiLCJlbWFpbCI6Im1hcmt1c0Blei1maXgubm8iLCJpc19hZG1pbiI6ZmFsc2UsImV4cCI6MTc3NDY0Nzg4M30.hEeMSjseq5Kstu9D1c2TprPNXW6vxC3w1DPq4X_Jzcs"

HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# Hyperparameter 1: Beskytter mot KL-divergens = inf
PROBABILITY_FLOOR = 0.01

# Hyperparameter 2: Bayesiansk prior pseudo-count
PRIOR_WEIGHT_BASE = 2.0
PRIOR_WEIGHT_MAX = 5.0
