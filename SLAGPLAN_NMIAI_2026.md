# SLAGPLAN: NM I AI 2026 — FØRSTEPLASS
## AI & Technology Dream Team Analyse

**Dato:** 20. mars 2026 (fredag kveld)
**Deadline:** 22. mars kl. 15:00 CET
**Gjenstående tid:** ~45 timer
**Mål:** 1. plass — 400 000 NOK
**Totalscoring:** Gjennomsnitt av tre normaliserte oppgavescorer (33.3% hver)

---

## AKTIVERTE PROFILER

| Profil | Avdeling | Rolle i denne planen |
|--------|----------|---------------------|
| **Andrej Karpathy** | Avd 02 | Tripletex-agentens LLM-pipeline, treningsoppskrift for NorgesGruppen |
| **Sam Altman** | Avd 07 | Agent-arkitekturvalg, Plan-and-Execute mønster, ship-og-iterer |
| **Jeremy Howard** | Avd 02 | Transfer learning-strategi NorgesGruppen, effektiv trening |
| **Fei-Fei Li** | Avd 01 | Datasett-analyse NorgesGruppen, COCO-format ekspertise |
| **Geoffrey Hinton** | Avd 01 | Probabilistisk resonnering for Astar Island |
| **Elon Musk** | Avd 07 | First principles tidsallokering, slett-først, iterasjonshastighet |
| **Brendan Burns** | Avd 03 | Container-deploy, Cloud Run, deklarativ infrastruktur |
| **George Hotz** | Avd 02 | Rask hacking der systematikk tar for lang tid |

**Ikke aktivert:** Avd 04 (Hardware), Avd 05 (Robotics), Avd 08 (Ethics) — irrelevant for 45-timers hackathon.

---

## MUSKS FIRST PRINCIPLES-ANALYSE

> **IF noen sier "det er umulig å vinne med 45 timer mot lag som startet torsdag" → KREV at de forklarer hvilken fysisk lov som forhindrer det.**

Hva er det faktisk som avgjør seieren? Ikke tid — men *kvalitet på løsningene multiplisert med bredde*. Totalscoren er normalisert: `din_score / beste_score × 100` per oppgave. Det betyr:

- Hvis topplaget scorer 80% på Tripletex og du scorer 80%, får du 100/100 normalisert
- Hvis topplaget scorer 0.7 mAP på NorgesGruppen og du scorer 0.6, får du 85.7/100
- En null på én oppgave gir 0/100 for den oppgaven — og dreper totalen

**Musks slett-først-regel:** *"If you do not end up adding back at least 10% of what you deleted, then you didn't delete enough."*

Det vi sletter:
- ~~Perfeksjon på NorgesGruppen~~ → Solid baseline er nok
- ~~Manuell Tripletex API-utforskning~~ → La LLM-agenten løse det
- ~~Søvn~~ → To korte blokker, ikke åtte timer

Det vi beholder:
- Tripletex som primærfokus (høyest ROI)
- Astar Island som sekundært (lavt arbeid, middels score)
- NorgesGruppen som baseline (tren over natten, submit morgen)

---

## OPPGAVE 1: TRIPLETEX AI ACCOUNTING AGENT

### Arkitekturvalg — Altman + Karpathy

**Altmans IF/THEN:** *IF du vurderer om en kapabilitet skal lanseres som produkt eller API → START med API.*
**Altmans IF/THEN:** *IF produktet er 80% ferdig → LANSER det. De siste 20% perfeksjoneringen gir mindre innsikt enn faktisk brukerinteraksjon.*

Fra **SKILL_TECH_agent_architecture.md** (Steg 1): Vi velger **Plan-and-Execute med ReAct** for hvert steg.

**Begrunnelse:** Tripletex-oppgavene er flertrinnsoppgaver der rekkefølge er viktig (opprett kunde FØR faktura). Plan-and-Execute lar agenten lage en plan basert på promptet, deretter utføre hvert steg sekvensielt. ReAct innenfor hvert steg gir selvkorrektur.

### Verktøydesign — SKILL_TECH_agent_architecture.md Steg 2

> *"Design verktøyene atomisk — ett verktøy gjør én ting godt."*

Agentens verktøy mot Tripletex API:

```
tripletex_get(endpoint, params)    → GET med auth og fields-parameter
tripletex_post(endpoint, body)     → POST med auth og JSON body
tripletex_put(endpoint, id, body)  → PUT med auth
tripletex_delete(endpoint, id)     → DELETE med auth
parse_pdf(base64_content)          → Extraher data fra vedlagt PDF
```

Hvert verktøy logger input/output/tidsstempel (audit trail per SKILL krav).

### Karpathys treningsoppskrift tilpasset agentbygging

> **Karpathys Start-enkel-regelen:** *IF du vurderer en kompleks arkitektur → implementer en enkel baseline først.*

**Steg 1: Bli ett med dataene.**
Før du skriver agenten — forstå Tripletex API manuelt. Kjør 5-10 API-kall mot sandbox-kontoen for hånd. Forstå respons-formater, feilmeldinger, og hvilke felt som kreves.

**Steg 2: Sett opp et komplett skjelett og oppnå en triviell baseline.**
Bygg FastAPI `/solve` som mottar prompt, kaller Claude med en enkel system-prompt, og returnerer `{"status": "completed"}`. Deploy til Cloud Run. Submit én gang. Se at pipelinen fungerer ende-til-ende.

**Steg 3: Overfit på én oppgavetype.**
Ta "Opprett ansatt" — den enkleste Tier 1-oppgaven. Gjør agenten perfekt på denne ene oppgaven. Perfekt betyr: 100% correctness OG efficiency bonus (minimalt antall API-kall, null 4xx-feil).

**Steg 4: Generaliser gradvis.**
Legg til én oppgavetype om gangen. Verifiser hvert steg.

### Efficiency bonus — der seieren avgjøres

Scoring-systemet belønner perfeksjon dramatisk:

| Scenario (Tier 2) | Score |
|---|---|
| 80% correctness | 1.6 |
| Perfekt, men slurvete | ~2.1 |
| Perfekt og effektiv | 4.0 |

**Karpathys IF/THEN:** *IF treningen ikke konvergerer → sjekk learning rate først.* Oversatt til agenter: IF agenten feiler → sjekk prompten først, ikke arkitekturen.

For maks efficiency bonus:
1. **Planlegg ALLE API-kall FØR du starter** — agenten må resonnere over hele oppgaven først
2. **Null trial-and-error** — valider input i kode før du sender til API
3. **Bruk POST-response direkte** — ikke gjør GET etter POST for å sjekke ID
4. **Forstå Tripletex' feilmeldinger** — 422 sier eksakt hva som mangler

### System-prompt for Tripletex-agenten

Agentens LLM (Claude Sonnet) mottar:

```
Du er en regnskapsagent. Du mottar en oppgave på norsk (eller annet språk) og 
Tripletex API-credentials.

REGLER:
1. PLANLEGG først. List alle API-operasjoner som trengs FØR du utfører noe.
2. Utfør operasjonene i riktig rekkefølge.
3. ALDRI gjør en GET for å sjekke noe du nettopp POSTet — du har allerede ID fra responsen.
4. ALDRI send en request du vet vil feile — valider input først.
5. Hvis en POST feiler med 422, les feilmeldingen og fiks i ÉN retry.

TILGJENGELIGE VERKTØY: [verktøyliste]

VANLIGE MØNSTRE:
- Opprett ansatt: POST /employee med firstName, lastName, email
- Opprett kunde: POST /customer med name, isCustomer=true
- Opprett faktura: Krever kunde-ID + ordre-ID → opprett begge først
- Registrer betaling: Krever faktura-ID → opprett faktura først
...
```

### Deploy — Burns' deklarative tilnærming

> **Burns IF/THEN:** *IF du starter et nytt prosjekt med et lite team → begynn med en monolitt i én container.*

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

Deploy til Google Cloud Run:
```bash
gcloud run deploy tripletex-agent \
  --source . \
  --region europe-north1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --timeout 300
```

> **Burns' rollback-krav:** *IF en deployment ikke har en definert rollback-strategi → den er ikke produksjonsklar.*

Cloud Run gir automatisk rollback via revisions — hver deploy er en ny revision, og du kan route tilbake til forrige på sekunder.

**Alternativ (raskere for EZ-Fix):** Deploy på egen server med Caddy for automatisk HTTPS. Dere har allerede Docker-infrastruktur på 5 servere.

### Tidslinje Tripletex

| Tid | Hva | Karpathy-steg |
|-----|-----|---------------|
| Fre 18-20 | Registrering + sandbox-utforskning | Steg 1: Bli ett med dataene |
| Fre 20-23 | FastAPI skeleton + Claude-integrasjon + deploy | Steg 2: Triviell baseline |
| Fre 23-01 | Perfeksjonér "Opprett ansatt" og 3-4 Tier 1-oppgaver | Steg 3: Overfit på én oppgavetype |
| Lør 08-14 | Utvid til alle Tier 1 + Tier 2 (åpner fredag morgen) | Steg 4: Generaliser |
| Lør 14-20 | Tier 3 (åpner lørdag morgen) + efficiency-optimalisering | Steg 5: Tune |
| Søn 08-13 | Siste polish, kjør alle 30 oppgavetyper | Steg 6: Squeeze |

---

## OPPGAVE 2: ASTAR ISLAND — NORRØN VERDENSPREDSJON

### Hintons probabilistiske rammeverk

> **Hintons prinsipp:** *"Statistisk fysikk er det riktige rammeverket."* Boltzmann-maskiner, energilandskaper, stokastiske systemer — dette ER Astar Island.

Simuleringen er et stokastisk system med kjente mekanikker (vekst, konflikt, handel, vinter, miljø). Ground truth er sannsynlighetsfordelingen fra hundrevis av simuleringer. Vårt mål er å estimere denne fordelingen med 50 observasjoner per runde.

> **Hintons IF/THEN:** *IF en idé ikke fungerer på et lite datasett → ikke kast mer compute på den. Test på MNIST først.*

Oversatt: Test strategien på de enkleste cellene først (statiske), deretter dynamiske.

### Monte Carlo-strategi

**Steg 1: Kartlegg det statiske kartet (gratis)**

`GET /rounds/{round_id}` gir hele startkartet med alle celler. Identifiser:
- **Ocean (10)** → Klasse 0 med ~0.98 sannsynlighet. Havet endrer seg aldri.
- **Mountain (5)** → Klasse 5 med ~0.98 sannsynlighet. Fjell er permanente.
- **Indre skog (4)** → Klasse 4 med høy sannsynlighet, men kan bli ruin-reclaimert
- **Dynamiske soner** → Alt innen 5 celler fra en settlement er potensielt dynamisk

**Steg 2: Allokér queries strategisk (50 per runde, 5 seeds)**

> **Musks first principles:** Hva gir mest informasjon per query?

10 queries per seed. Viewport er maks 15×15 = 225 celler. Kartet er 40×40 = 1600 celler. Med 10 viewports à 15×15 kan vi dekke 2250 celler — mer enn hele kartet.

MEN: Vi trenger ikke dekke havområder. Fokusér viewports på dynamiske soner:
- Plasser viewports slik at de dekker alle initielle settlements + 5-cellers radius
- Overlap mellom viewports er OK — det gir flere observasjoner per celle
- Statiske celler i viewport er "gratis" bekreftelse

**Steg 3: Aggregér observasjoner til sannsynligheter**

Hver query kjører en ny stokastisk simulering. For celle (x,y):
```python
observations[(x,y)] = [klasse_i_query_1, klasse_i_query_2, ...]

# Empirisk fordeling
counts = Counter(observations[(x,y)])
probs = {k: v/total for k, v in counts.items()}
```

**Steg 4: Probability floor — KRITISK**

> **Hintons enkelhet-testen:** *IF en modell har mer enn 3 hyperparametre du ikke kan forklare intuisjonen bak → forenkle.*

Én hyperparameter: `floor = 0.01`

```python
prediction = np.maximum(prediction, 0.01)
prediction = prediction / prediction.sum(axis=-1, keepdims=True)
```

KL-divergens med `q=0.0` → uendelig. Én null i prediksjonen kan ødelegge hele scoren. Floor 0.01 koster nesten ingenting men beskytter mot katastrofe.

**Steg 5: Bruk domeneforståelse som prior**

Fra simuleringens mekanikker:
- Settlements nær skog har bedre food → høyere overlevelsessannsynlighet
- Kystceller nær settlements → høyere port-sannsynlighet
- Settlements uten skog-naboer → høyere ruin-sannsynlighet (sult)
- Ruiner nær aktive settlements → kan reclaimes til nye settlements
- Ruiner uten naboer → skog overtar gradvis

Disse priors forbedrer prediksjonen for celler med få observasjoner.

### Tidslinje Astar Island

| Tid | Hva |
|-----|-----|
| Lør 08-12 | Skriv Python-script: hent initial state, planlegg viewports, kjør queries, aggregér, submit |
| Lør 12-14 | Kjør på aktiv runde, analyser resultater via `/analysis/{round_id}/{seed}` |
| Lør 14-18 | Forbedre viewport-strategi basert på analyse |
| Søn 08-12 | Kjør siste runder med forbedret strategi |

---

## OPPGAVE 3: NORGESGRUPPEN DATA — OBJEKTDETEKSJON

### Howards transfer learning-tilnærming

> **Howards IF/THEN:** *IF du har lite merkede data (< 1000 eksempler) → bruk transfer learning FØR du vurderer å samle mer data.*

248 bilder med 22 700 annotasjoner er et lite-middels datasett. Transfer learning er obligatorisk.

> **Howards progressive resizing:** *IF du trener på bilder → start med lav oppløsning og øk gradvis. Raskere trening OG bedre generalisering.*

### Lis datasett-analyse — ImageNet-metoden tilpasset

> **Lis IF/THEN:** *IF du starter et nytt AI-prosjekt → invester i datakvalitet FØR du velger modellarkitektur.*

**Steg 1: Forstå dataene (Karpathy + Li)**

Før du trener noe — inspiser dataene:
```python
# Last COCO annotations
with open('annotations.json') as f:
    coco = json.load(f)

# Sjekk klasse-distribusjon
category_counts = Counter(a['category_id'] for a in coco['annotations'])
# Sjekk bildestørrelser
# Visualiser 20 bilder med bounding boxes
# Se etter annotasjonsfeil, overlappende bokser, etc.
```

356 produktkategorier med 22 700 annotasjoner betyr gjennomsnittlig ~64 annotasjoner per kategori — men sannsynligvis svært ujevnt fordelt. Noen kategorier har kanskje 500+ annotasjoner, andre 5.

> **Lis anti-pattern:** *Aldri tren på data som ikke reflekterer den virkelige verden.*

Test-settet kan ha produkter fra andre butikkseksjoner enn treningsdataene (Egg, Frokost, Knekkebrod, Varmedrikker). Generalisering er viktigere enn overfitting.

### Treningsstrategi — Howard + Karpathy

**Modellvalg: YOLOv8x med pretrenede COCO-vekter**

> **Karpathys start-enkel-regel:** Start med den enkleste tingen som kan fungere.

`ultralytics==8.1.0` er forhåndsinstallert i sandbox. Bruk det.

```python
from ultralytics import YOLO

# Last pretrent modell (transfer learning per Howard)
model = YOLO('yolov8x.pt')

# Tren med standard augmentering
model.train(
    data='dataset.yaml',
    epochs=150,           # Over natten på RTX 6000 Ada 48GB
    imgsz=1280,           # Høy oppløsning for hyllebilder
    batch=4,              # Tilpass til 48GB VRAM
    augment=True,         # Mosaic, flipping, etc.
    mosaic=1.0,
    mixup=0.15,           # Howards mixup-regularisering
    close_mosaic=20,      # Slå av mosaic siste 20 epochs for fintuning
    patience=30,          # Early stopping
)
```

> **Howards effektive trening:** Learning rate finder → One-cycle policy → Progressive resizing → Mixup → Mixed precision. ultralytics implementerer flere av disse automatisk.

### Scoring-optimalisering

Scoring: `0.7 × detection_mAP + 0.3 × classification_mAP`

**Detection-only baseline:** Sett `category_id: 0` for alt → maks 0.70 score.
**Med klassifisering:** Selv 50% riktig klassifisering gir 0.70 + 0.15 = 0.85.

> **Karpathys overfitting-sjekk:** *IF modellen din ikke kan overfitte ett enkelt batch → du har en kode-bug.*

Første test: Tren 50 epochs på 10 bilder. Hvis mAP ikke nærmer seg 1.0 → bug i datapipeline.

### Productimage-boost (valgfritt, lørdag)

60 MB med produktreferansebilder (multi-angle per produkt). Disse kan brukes til:
- Data augmentation: Legg til cropped produktbilder med random backgrounds
- Klassifiserings-forbedring: Tren en separat klassifiserer som matcher detekterte regioner mot referansebilder

### Tidslinje NorgesGruppen

| Tid | Hva | Profil |
|-----|-----|--------|
| Fre 20-21 | Last ned data, inspiser (Karpathys steg 1) | Karpathy + Li |
| Fre 21-22 | Sett opp treningsscript, start trening | Howard |
| Fre 22 → Lør 08 | Trening kjører over natten på GEX130 | (automatisk) |
| Lør 08-09 | Evaluer, pakk zip, **første submission** | Karpathy |
| Lør 18-19 | Juster hyperparametre, **andre submission** | Howard |
| Søn 10-11 | Beste modell, **tredje submission** | — |

---

## PARALLELL EKSEKVERINGSPLAN

### Musks iterasjonsfrekvens-prinsipp

> *"Mål tiden fra beslutning til implementert endring. Visualiser iterasjonsfrekvensen over tid."*

Med to personer (Markus + Alec) er parallelisering nøkkelen:

| Tid | Markus (Tripletex-eier) | Alec/Claude Code (Data + Infra) |
|-----|-------------------------|--------------------------------|
| **Fre 18:00** | Registrer lag + Vipps-verifisering | `claude mcp add` NMiAI docs server |
| **Fre 18:30** | Opprett sandbox-konto, utforsk API manuelt | Last ned NorgesGruppen data + inspiser |
| **Fre 20:00** | Start bygge Tripletex-agent (FastAPI + Claude) | Sett opp YOLOv8 treningsscript, start trening |
| **Fre 23:00** | Agent deployed, tester Tier 1-oppgaver | Trening kjører. Sov. |
| **Lør 08:00** | Tripletex: utvid til flere Tier 1-oppgaver | NorgesGruppen: evaluer + submit #1. Start Astar Island script |
| **Lør 12:00** | Tripletex: Tier 2 oppgaver | Astar: kjør på aktiv runde |
| **Lør 16:00** | Tripletex: Tier 3 oppgaver | NorgesGruppen submit #2 + Astar-forbedring |
| **Lør 22:00** | Efficiency-optimalisering | Sov |
| **Søn 08:00** | Siste Tripletex-polish | NorgesGruppen submit #3 + Astar siste runder |
| **Søn 12:00** | Alle tre oppgaver submittet, repo public | Final check |
| **Søn 13:00** | FERDIG | |

---

## HOTZ' HACKING-REGLER — NÅR SYSTEMATIKK TAR FOR LANG TID

> George Hotz anti-pattern: *"Perfeksjon er fienden av shipping."*

Det er 45 timer. For hvert problem du støter på:

1. **Fungerer det?** → Ship det
2. **Fungerer det ikke etter 30 min?** → Hotz-hack: bruk den enkleste workarounden som gir resultat
3. **Tripletex API gir 422?** → Les feilmeldingen, fiks i kode, ikke i LLM-prompten
4. **YOLOv8 trener for sakte?** → Reduser `imgsz` til 640, øk `batch`
5. **Astar query brukt opp?** → Submit med priors + de queries du har. Noe > ingenting

---

## RISIKOMATRISE OG BESLUTNINGSREGLER

| Risiko | Sannsynlighet | Konsekvens | Tiltak (IF/THEN) |
|--------|--------------|------------|-------------------|
| Tripletex sandbox nede | Lav | Kritisk | IF sandbox nede > 30 min → bytt til Astar/NorgesGruppen, monitorer Slack |
| Cloud Run deploy feiler | Medium | Middels | IF Cloud Run feiler → deploy på egen server med Caddy (Burns: ha rollback-plan) |
| YOLO trening krasjer over natten | Medium | Lav | IF trening krasjer → restart med lavere imgsz. 3 submissions per dag gir rom |
| Astar runde utløper uten submit | Lav | Middels | IF < 5 min igjen → submit uniform distribution med probability floor. 0 > null |
| 7-språk-prompts feiler | Medium | Høy | IF ikke-norsk prompt → Claude håndterer alle 7 språk nativt. Ikke prøv regex |
| NorgesGruppen zip > 420 MB | Lav | Middels | IF > 420 MB → kvantiser til FP16 eller bruk YOLOv8l istedenfor v8x |

---

## KVALITETSKRITERIER FRA DREAM TEAM

### Karpathys oppskrift-sjekkliste
- [ ] Datasett inspisert visuelt FØR trening startet
- [ ] Enkel baseline fungerer ende-til-ende FØR kompleksitet legges til
- [ ] Overfit-test bestått på minste datasett
- [ ] Én ting endret om gangen

### Altmans agent-sjekkliste (SKILL_TECH_agent_architecture.md)
- [ ] Oppgaveløsningsrate > 80% på Tier 1
- [ ] Alle Tripletex API-kall logges med input/output/tidsstempel
- [ ] Maks 20 iterasjoner per oppgave (unngå uendelige looper)
- [ ] 5 minutters timeout respektert

### Burns' deploy-sjekkliste
- [ ] Container har definerte resource limits
- [ ] HTTPS fungerer
- [ ] Rollback-strategi definert (Cloud Run revision)
- [ ] Helsesjekk-endpoint (`/health`)

### Lis datakvalitet-sjekkliste
- [ ] Klasse-distribusjon i NorgesGruppen-data analysert
- [ ] Annotasjonskvalitet visuelt inspisert (10+ bilder)
- [ ] Train/val split respekterer original distribusjon

---

## KODE-REPOSITORY (krav for premieutbetaling)

Opprett `github.com/ez-fix-as/nmiai-2026` med:

```
/tripletex/        → FastAPI agent + Dockerfile + deploy script
/norgesgruppen/    → YOLOv8 treningsscript + run.py + model
/astar-island/     → Monte Carlo prediksjonsscript
/README.md         → Kort beskrivelse av tilnærming
```

Repo MÅ være public FØR kl. 15:00 søndag. MIT-lisens.

---

## OPPSUMMERING — DEN KRITISKE INNSIKTEN

**Altmans ship-og-iterer:** Ikke bygg den perfekte agenten. Bygg den som fungerer, deploy, submit, se scoren, forbedre, submit igjen. Best-ever score per oppgave betyr at dårlige forsøk aldri straffer deg.

**Karpathys start-enkelt:** Tier 1 først, perfekt. Deretter Tier 2. Deretter Tier 3. Ikke prøv alle 30 oppgaver parallelt.

**Howards gjør-mer-med-mindre:** Transfer learning på NorgesGruppen. Pretrent YOLOv8 + 150 epochs er bedre enn noe du trener fra scratch på 45 timer.

**Hintons usikkerhet:** Aldri probability 0.0 på Astar Island. Probability floor 0.01 overalt.

**Musks first principles:** Dere trenger ikke vinne alle tre oppgaver. Dere trenger å score bedre enn alle andre *i gjennomsnitt*. Én dominant oppgave + to solide = førsteplass.

**Burns' deklarativ deploy:** Docker + Cloud Run. Ingen manuell SSH-deploy. Alt reproduserbart.

---

*Slagplan generert av AI & Technology Dream Team — 8 profiler aktivert av 34 tilgjengelige*
*SKILL-filer brukt: SKILL_TECH_agent_architecture.md, SKILL_TECH_infrastructure.md*
