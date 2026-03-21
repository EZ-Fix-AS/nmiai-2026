# NM i AI 2026 — EZ-Fix AS

## Prosjektstatus (oppdatert 2026-03-21 01:30)

**Rank: #213 av 320 lag | Overall: 35.3 | Deadline: Søndag 22. mars kl 15:00**

### Scores
| Oppgave | Score | Detaljer |
|---------|-------|----------|
| NorgesGruppen | 70.4 | YOLO mAP50=0.758, submission.zip klar |
| Tripletex | 26.0 | 15-16/30 oppgavetyper, best 100% (8/8) |
| Astar Island | 9.6 | Runde 10, kun priors (0 queries brukt) |

### Credentials (i .env)
- **Tripletex sandbox:** https://kkpqfuj-amager.tripletex.dev/v2
- **Tripletex token:** i .env
- **Astar JWT:** i .env + astar-island/main.py (utløper snart, hent ny fra browser cookies)
- **Anthropic API:** Delt med Huginn & Muninn
- **GitHub:** https://github.com/EZ-Fix-AS/nmiai-2026 (public, MIT)

### Deployment
- **Tripletex agent:** https://nmiai.ez-ai.no → Data-API server (95.217.15.99:8090)
  - systemd: `tripletex-agent.service`
  - Kode: `/opt/nmiai-tripletex/main.py`
  - Deploy: `scp tripletex/main.py root@95.217.15.99:/opt/nmiai-tripletex/ && ssh root@95.217.15.99 "systemctl restart tripletex-agent"`
- **YOLO trening:** kit-gpu-server (136.243.6.74), ferdig
  - Modell: `/srv/nmiai-2026/norgesgruppen/runs/detect/phase2_1280/weights/best.pt`
  - ONNX: eksportert, 262 MB

### Tripletex — Hva fungerer
- **100% oppgavetyper:** Opprett kunde, leverandør, ansatt, prosjekt, avdeling, produkt
- **Søk-først mønster:** Alle handlers søker eksisterende entiteter FØR opprettelse
- **Kreditnota:** `PUT /invoice/{id}/:createCreditNote?date=YYYY-MM-DD` — VERIFISERT
- **Send faktura:** `PUT /invoice/{id}/:send?sendType=EMAIL` — VERIFISERT
- **LLM fallback:** Komplekse oppgaver → Claude Sonnet med Tripletex API-docs i prompt

### Tripletex — Hva feiler (FIKS DISSE)
- **Reverser betaling:** createPayment FINNES IKKE i sandbox. Trenger annen metode.
- **Salary/lønn:** /salary/payslip gir 500-feil i sandbox
- **Dimensjoner:** /ledger/dimension finnes ikke
- **Timer + prosjektfaktura:** Kompleks flyt, LLM fallback klarer ~50%
- **Reiseregning med dagpenger:** ~25%, trenger bedre handler
- **Multi-create (3 avdelinger):** Sendes til LLM fallback, bør forbedres

### Tripletex — API-kunnskap lært fra sandbox
- Employee krever: `userType` (STANDARD/NO_ACCESS) + `department.id`
- STANDARD krever email, NO_ACCESS trenger det ikke
- Project krever: `projectManager.id` + `startDate`
- Invoice krever: bankkonto på konto 1920 (settes automatisk)
- Adresse: oppdater via `PUT /address/{id}`, IKKE som felt på customer
- MVA-typer: id=3 (25%), id=31 (15%), id=32 (12%), id=5 (0% innenfor), id=6 (0% utenfor)

### NorgesGruppen
- **Trening ferdig:** YOLOv8x (ultralytics 8.4.24), 2-fase progressive resizing
- **VIKTIG:** Sandbox har ultralytics 8.1.0 — bruk ONNX-eksport (opset=17)
- **submission_v2.zip:** `/Users/markus/PROSJEKTER/nmiai-2026/norgesgruppen/submission_v2.zip` (213 MB)
- **run.py:** Sandbox-safe (ingen os/sys import). Bruker ONNX-modell.
- **Scoring:** 0.7 × detection_mAP + 0.3 × classification_mAP
- **Sandbox-begrensninger:** os, sys, subprocess, yaml BLOKKERT. Bruk pathlib + json.
- **5 submissions igjen i dag**

### Astar Island
- **Script:** astar-island/main.py (Monte Carlo + priors)
- **Problem:** Runde 10 brukte 0 queries (budget var oppbrukt) → kun prior-basert → lav score
- **Temporal learning bug:** `learn_from_analysis` feilet med "len() of unsized object"
- **Neste runde:** Bruk 50 queries AKTIVT, 10 per seed
- **Probability floor 0.01** — KRITISK for å unngå KL-divergens = ∞
- **Round weight:** 1.05^round_number — sene runder er verdt mer
- **JWT utløper:** Sjekk og forny fra browser cookies på app.ainm.no

### Viktige regler
- **Best-ever score per oppgave teller** — dårlige forsøk skader aldri
- **Tripletex submissions:** 180/dag (resetter midnatt UTC)
- **NorgesGruppen:** 6 submissions/dag, max 420 MB zip
- **Astar:** 50 queries per runde, 5 seeds
- **GitHub repo MÅ være public FØR søndag 15:00**
- **.env ALDRI committes** (i .gitignore)
