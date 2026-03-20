# CLAUDE CODE PROMPT — AGENT 0: PROSJEKTLEDER & SETUP
# NM i AI 2026 — Norwegian AI Championship
# Denne agenten kjøres FØRST — setter opp alt de tre andre agentene trenger

---

## DIN ROLLE

Du er prosjektleder og setup-agent for NM i AI 2026. Din jobb er å:
1. Opprette hele prosjektstrukturen
2. Sette opp GitHub-repo (public, MIT-lisens — krav for premie)
3. Installere MCP-server for NMiAI docs
4. Lage alle config-filer, Dockerfiles og deploy-scripts
5. Verifisere at alt er klart for de tre oppgave-agentene

Du gjør ALT selv. Ingenting manuelt. Når du er ferdig skal de tre andre agentene bare kunne starte i sin mappe og begynne å kode.

---

## KONTEKST

- **Konkurranse:** NM i AI 2026 (app.ainm.no)
- **Deadline:** Søndag 22. mars 2026 kl. 15:00 CET (~43 timer igjen)
- **Team:** EZ-Fix AS
- **Tre oppgaver:** Tripletex (33%), NorgesGruppen (33%), Astar Island (33%)
- **Premiepott:** 1 MNOK — 400k til vinner
- **Krav for premie:** Public GitHub repo med MIT-lisens + Vipps-verifisering for alle teammedlemmer
- **Submission deadline for oss:** Lørdag kl. 20:00 (ingen nye features etter dette, kun bugfix)

---

## STEG 1: OPPRETT PROSJEKTSTRUKTUR

Opprett denne mappestrukturen:

```
nmiai-2026/
├── README.md
├── LICENSE                    # MIT (krav for premie)
├── .gitignore
├── tripletex/
│   ├── main.py               # FastAPI agent (Agent 1 bygger denne)
│   ├── requirements.txt
│   ├── Dockerfile
│   └── deploy.sh
├── norgesgruppen/
│   ├── inspect_data.py        # Datainspeksjon (Karpathy steg 1)
│   ├── convert_coco.py        # COCO → YOLO konvertering
│   ├── overfit_test.py        # Overfitting-sjekk (Karpathy steg 3)
│   ├── train.py               # Full treningsscript med progressive resizing
│   ├── run.py                 # Submission entry point
│   └── requirements.txt
├── astar-island/
│   ├── main.py                # Monte Carlo prediksjonssystem
│   ├── config.py              # Token og hyperparametre
│   └── requirements.txt
└── .env.example               # Template for environment variables
```

## STEG 2: OPPRETT ALLE FILER

### README.md
```markdown
# NM i AI 2026 — EZ-Fix AS

Norges mesterskap i kunstig intelligens 2026.
Konkurranse: 19.-22. mars 2026 | app.ainm.no

## Oppgaver

### 1. Tripletex — AI Accounting Agent (33%)
FastAPI-agent som parser norskspråklige regnskapsoppgaver og utfører dem mot Tripletex API via Claude tool-use.

### 2. NorgesGruppen Data — Object Detection (33%)
YOLOv8x med transfer learning og progressive resizing for deteksjon av dagligvarer i hyllebilder.

### 3. Astar Island — Norse World Prediction (33%)
Monte Carlo-sampling med Bayesianske priors basert på simuleringens mekanikker.

## Kjøring

Se README i hver undermappe for instruksjoner.

## Lisens
MIT
```

### LICENSE
Standard MIT-lisens med "Copyright (c) 2026 EZ-Fix AS"

### .gitignore
```
__pycache__/
*.pyc
.env
*.pt
*.onnx
*.safetensors
runs/
wandb/
.DS_Store
*.zip
venv/
dist/
build/
*.egg-info/
```

### .env.example
```
ANTHROPIC_API_KEY=sk-ant-...
AINM_JWT_TOKEN=eyJ...
TRIPLETEX_SANDBOX_URL=https://kkpqfuj-amager.tripletex.dev/v2
TRIPLETEX_SANDBOX_TOKEN=your-sandbox-token
```

### tripletex/requirements.txt
```
fastapi==0.115.0
uvicorn[standard]==0.30.0
requests==2.31.0
anthropic>=0.40.0
pdfplumber==0.11.0
```

### tripletex/Dockerfile
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
```

### tripletex/deploy.sh
```bash
#!/bin/bash
set -e

echo "=== DEPLOY TRIPLETEX AGENT ==="

# Sjekk at ANTHROPIC_API_KEY er satt
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "FEIL: ANTHROPIC_API_KEY er ikke satt"
    echo "Kjør: export ANTHROPIC_API_KEY=sk-ant-..."
    exit 1
fi

# ALTERNATIV 1: Google Cloud Run
if command -v gcloud &> /dev/null; then
    echo "Deployer til Google Cloud Run..."
    gcloud run deploy tripletex-agent \
        --source . \
        --region europe-north1 \
        --allow-unauthenticated \
        --memory 1Gi \
        --cpu 2 \
        --timeout 300 \
        --min-instances 1 \
        --set-env-vars "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}"
    echo "Cloud Run deploy ferdig!"

# ALTERNATIV 2: Lokal Docker + Caddy
else
    echo "gcloud ikke funnet — deployer lokalt med Docker..."
    docker build -t tripletex-agent .
    docker stop tripletex-agent 2>/dev/null || true
    docker rm tripletex-agent 2>/dev/null || true
    docker run -d \
        --name tripletex-agent \
        --restart unless-stopped \
        -p 8080:8080 \
        -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
        tripletex-agent
    echo "Lokal deploy ferdig på port 8080"
    echo "Husk: Sett opp Caddy/nginx for HTTPS!"
fi
```

### norgesgruppen/requirements.txt
```
# For TRENING (lokalt på GEX130)
ultralytics==8.1.0
# torch installeres med CUDA: pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cu124
```

### astar-island/requirements.txt
```
requests
numpy
```

### astar-island/config.py
```python
"""
Astar Island — Konfigurasjon
Hinton: Maks 2 hyperparametre med klar intuisjon
"""
BASE_URL = "https://api.ainm.no/astar-island"

# Hent fra browser cookies etter innlogging på app.ainm.no
# DevTools → Application → Cookies → access_token
TOKEN = "PASTE_JWT_HER"

HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# Hyperparameter 1: Beskytter mot KL-divergens = ∞
PROBABILITY_FLOOR = 0.01

# Hyperparameter 2: Bayesiansk prior pseudo-count
# Dynamisk: max(2.0, 5.0 - n_obs) — mer prior-vekt ved få observasjoner
PRIOR_WEIGHT_BASE = 2.0
PRIOR_WEIGHT_MAX = 5.0
```

## STEG 3: INIT GIT + PUSH TIL GITHUB

```bash
cd nmiai-2026
git init
git add .
git commit -m "Initial project structure — NM i AI 2026"

# Opprett public repo på GitHub
# Alternativ 1: Med gh CLI
gh repo create ez-fix-as/nmiai-2026 --public --source=. --push

# Alternativ 2: Manuelt
# 1. Gå til github.com → New repository → "nmiai-2026" → Public → Create
# 2. git remote add origin git@github.com:BRUKERNAVN/nmiai-2026.git
# 3. git push -u origin main
```

## STEG 4: INSTALLER NMIAI MCP-SERVER

```bash
claude mcp add --transport http nmiai https://mcp-docs.ainm.no/mcp
```

Verifiser at den fungerer ved å spørre Claude Code om Tripletex-dokumentasjonen.

## STEG 5: LAST NED NORGESGRUPPEN DATA

```bash
# Logg inn på app.ainm.no og gå til NorgesGruppen submit-siden
# Last ned:
# 1. NM_NGD_coco_dataset.zip (~864 MB) — treningsdata
# 2. NM_NGD_product_images.zip (~60 MB) — produktreferansebilder

# Pakk ut i norgesgruppen-mappen
cd norgesgruppen/
unzip ~/Downloads/NM_NGD_coco_dataset.zip -d dataset/
unzip ~/Downloads/NM_NGD_product_images.zip -d product_images/
```

## STEG 6: HENT TRIPLETEX SANDBOX-KONTO

```
1. Gå til app.ainm.no → Tasks → Tripletex → Submit
2. Trykk "Get Sandbox Account"
3. Kopier:
   - Sandbox URL
   - Session token
4. Legg inn i .env:
   TRIPLETEX_SANDBOX_URL=https://kkpqfuj-amager.tripletex.dev/v2
   TRIPLETEX_SANDBOX_TOKEN=din-token-her
```

## STEG 7: HENT ASTAR ISLAND JWT TOKEN

```
1. Logg inn på app.ainm.no i nettleseren
2. Åpne DevTools (F12) → Application → Cookies
3. Finn "access_token" — kopier verdien
4. Oppdater astar-island/config.py med tokenet
```

## STEG 8: VERIFISER ALT

Kjør denne sjekklisten:

```bash
echo "=== NMIAI 2026 SETUP SJEKKLISTE ==="

# Repo eksisterer
[ -d ".git" ] && echo "✓ Git repo" || echo "✗ Git repo mangler"

# Mappestruktur
[ -f "tripletex/Dockerfile" ] && echo "✓ Tripletex Dockerfile" || echo "✗ Tripletex Dockerfile"
[ -f "norgesgruppen/run.py" ] && echo "✓ NorgesGruppen run.py" || echo "✗ NorgesGruppen run.py"  
[ -f "astar-island/config.py" ] && echo "✓ Astar config" || echo "✗ Astar config"

# Env vars
[ -n "$ANTHROPIC_API_KEY" ] && echo "✓ ANTHROPIC_API_KEY" || echo "✗ ANTHROPIC_API_KEY mangler"

# Python deps
python3 -c "import fastapi" 2>/dev/null && echo "✓ FastAPI" || echo "✗ FastAPI"
python3 -c "import anthropic" 2>/dev/null && echo "✓ Anthropic" || echo "✗ Anthropic"

# Data
[ -d "norgesgruppen/dataset" ] && echo "✓ NorgesGruppen data" || echo "✗ NorgesGruppen data mangler"

echo "=== FERDIG ==="
```

## STEG 9: RAPPORTER TIL TEAMET

Når alt er klart, skriv en kort status:

```
SETUP KOMPLETT:
- [x] Repo: github.com/ez-fix-as/nmiai-2026 (public)
- [x] Mappestruktur for alle 3 oppgaver
- [x] Dockerfile + deploy.sh for Tripletex
- [x] MCP-server installert
- [ ] NorgesGruppen data lastet ned (manuelt steg)
- [ ] Tripletex sandbox-konto hentet (manuelt steg)
- [ ] Astar JWT token hentet (manuelt steg)

NESTE STEG:
1. Agent 1: Start i tripletex/ — bygg main.py
2. Agent 2: Start i norgesgruppen/ — kjør inspect_data.py → train.py
3. Agent 3: Start i astar-island/ — bygg main.py

TIDSPLAN:
- Fre kveld: Tripletex MVP + YOLOv8 trening starter + Astar script ferdig
- Lør morgen: Første submissions på alle 3 oppgaver
- Lør kveld 20:00: FEATURE FREEZE — kun bugfix etter dette
- Søn 13:00: Alt submittet, repo public, ferdig
```

---

## VIKTIGE REGLER

1. **GitHub repo MÅ være public FØR søndag kl. 15:00** — ellers ingen premieutbetaling
2. **Alle teammedlemmer MÅ Vipps-verifisere** — ellers ingen premie
3. **Submission deadline for oss: lørdag kl. 20:00** — kun bugfix etter dette
4. **.env skal ALDRI committes** — den er i .gitignore. Sjekk dette.
5. **Model-vekter (.pt) skal IKKE committes** — for store for git. Bruk .gitignore.
