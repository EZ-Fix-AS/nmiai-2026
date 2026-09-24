# NM i AI 2026 — EZ-Fix AS

## Prosjektstatus (oppdatert 2026-03-22 — KONKURRANSEN AVSLUTTET)

**Sluttresultat: #133 av 401 lag | Overall: ~80 | Deadline: Sondag 22. mars kl 15:00 (passert)**

### Sluttscores
| Oppgave | Score | Detaljer |
|---------|-------|----------|
| NorgesGruppen | **89.95** | WBF ensemble 0.8995. 3-modell (phase1+phase2+v3), conf=0.001 |
| Tripletex | **~58** | V5.5: 19 deterministiske handlers, 587 submissions, 30/30 oppgavetyper forsokt |
| Astar Island | ~53 | #19 pa Astar-leaderboard. V6-loop med Monte Carlo + priors |

### Tripletex — Sluttresultat
- **Score:** 48.4 -> **~58.0** (V5.5 med forbedret routing)
- **Rank pa Tripletex:** #133/401
- **Submissions brukt:** 587 av tilgjengelige
- **Arkitektur:** Keyword routing -> deterministisk handler -> LLM fallback (Claude Sonnet)

### Tripletex — Hva fungerte (100% score)
- **Customer:** Opprett kunde med alle felt
- **Supplier:** Opprett leverandor
- **Employee:** Opprett ansatt (NO_ACCESS + STANDARD med email)
- **Product:** Opprett produkt med pris
- **Department:** Opprett avdeling med unikt nummer
- **Salary/Lonn:** Voucher med 5 poster (D5000, K2600, K1920, D5400, K2770)
- **Voucher:** Generell bilagsfoering med korrekt debet/kredit
- **Invoice:** Full flyt — ordre -> ordrelinje -> faktura -> send
- **Travel:** Reiseregning med kostnader
- **Depreciation:** Avskrivning (D6000, K1200)
- **Credit note:** Kreditnota via /:createCreditNote
- **Payment:** Registrer betaling via /:payment

### Tripletex — Hva var vanskelig (0-50% score)
- **Bank reconciliation:** Kompleks flyt, sandbox-begrensninger
- **Project lifecycle:** Opprett + timer + fakturering i en flyt
- **Cost analysis:** Utrekk og analyse av kostnader fra vouchers
- **Error correction:** Finn og rett feil i eksisterende bilag
- **Dimensjoner:** /ledger/dimension finnes ikke — matte bruke department/project

### Tripletex — Viktigste laerdommer
1. **Routing-prioritet er KRITISK** — spesifikke patterns for generelle. "Lonn" matte matche for "betaling for lonn"
2. **Per-sandbox cache** — ALDRI cache IDs mellom requests, hver sandbox har unike IDs
3. **GET er gratis** i scoring — kun writes (POST/PUT/DELETE) teller mot score
4. **Action-endepunkter** tar params i URL query string, ALDRI i body
5. **Deterministiske handlers >> LLM** for strukturerte oppgaver
6. **vatType IDs** er sandbox-spesifikke — sla opp dynamisk
7. **Spray-submit** er riktig strategi nar best-ever score teller

### Tripletex API-kunnskap (VIKTIG for TimeGate + TEK-Flow)
- Komplett verifisert API-referanse: `/Users/markus/Claude_Local/tripletex-api-kunnskap/`
- Voucher, employee, invoice, timesheet, dimensjoner — alt testet mot sandbox
- Direkte anvendbart for Tripletex-integrasjon i TimeGate og TEK-Flow

### Credentials (i .env)
- **Tripletex sandbox:** https://kkpqfuj-amager.tripletex.dev/v2
- **Tripletex token:** i .env
- **Astar JWT:** i .env + astar-island/main.py (utlopt)
- **Anthropic API:** Delt med Huginn & Muninn
- **GitHub:** https://github.com/EZ-Fix-AS/nmiai-2026 (public, MIT)

### Deployment
- **Tripletex agent:** https://nmiai.ez-ai.no -> Data-API server (95.217.15.99:8090)
  - systemd: `tripletex-agent.service`
  - Kode: `/opt/nmiai-tripletex/main.py`
  - Deploy: `scp tripletex/main.py root@95.217.15.99:/opt/nmiai-tripletex/ && ssh root@95.217.15.99 "systemctl restart tripletex-agent"`
  - **Versjon deployet:** V5.5 med 19 handlers + forbedret flerspraklig routing
- **YOLO modeller:** kit-gpu-server (136.243.6.74), alle ferdig trent
  - Phase1: `/srv/nmiai-2026/norgesgruppen/runs/detect/phase1_640/weights/best.pt` (mAP50=0.735)
  - Phase2: `/srv/nmiai-2026/norgesgruppen/runs/detect/phase2_1280/weights/best.pt` (mAP50=0.742)
  - V3: `/srv/nmiai-2026/norgesgruppen/runs/detect/v3_strong_aug/weights/best.pt` (mAP50=0.753)
  - Alle har FP16 ONNX (~131 MB) ved siden av .pt

### NorgesGruppen — ENSEMBLE BREAKTHROUGH
- **Best score: 0.8995** med 3-modell WBF ensemble (phase1_640 + phase2_1280 + v3_1280)
- **Gjennombrudd:** Enkeltmodell plata ved 0.667 → 2-modell 0.8951 (+34%) → 3-modell 0.8995
- **Best WBF-params:** conf=0.001, iou_nms=0.45, iou_wbf=0.5, weights=[1.0, 1.5, 1.5]
- **Scoring:** 0.7 x detection_mAP + 0.3 x classification_mAP
- **Parameter-tuning 22. mars:** 11 submissions totalt. Endring av iou_wbf, weights, conf_type ga <0.001 forskjell. Modellkvalitet er taket.
- **Viktigste laerdom:** Aldri endre mange params samtidig — isoler variabler. Guide-anbefalinger er generaliseringer, test alltid mot eget datasett.

### Astar Island
- **Script:** astar-island/main.py (Monte Carlo + priors)
- **Probability floor 0.01** — KRITISK for a unnga KL-divergens = inf
- **Round weight:** 1.05^round_number — sene runder er verdt mer

### Viktige regler
- **Best-ever score per oppgave teller** — darlige forsok skader aldri
- **.env ALDRI committes** (i .gitignore)
