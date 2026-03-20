"""
Astar Island — Konfigurasjon
"""
BASE_URL = "https://api.ainm.no/astar-island"

# Hent fra browser cookies etter innlogging på app.ainm.no
# DevTools → Application → Cookies → access_token
TOKEN = "PASTE_JWT_HER"

HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# Hyperparameter 1: Beskytter mot KL-divergens = inf
PROBABILITY_FLOOR = 0.01

# Hyperparameter 2: Bayesiansk prior pseudo-count
PRIOR_WEIGHT_BASE = 2.0
PRIOR_WEIGHT_MAX = 5.0
