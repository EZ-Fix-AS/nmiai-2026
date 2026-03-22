# Lessons Learned — NM i AI 2026

## Tripletex Agent

### Global state + concurrent requests = race condition
**Problem:** `_bank_checked` global var delte state mellom samtidige uvicorn workers. En request satte cache med sitt token, neste request brukte cachet og fikk 403 "expired proxy token".
**Fix:** Fjern ALL global state. Hver request ma vaere helt selvstendig med sin egen TX-instans.
**Regel:** Aldri bruk globale variabler i FastAPI med multiple workers.

### Tripletex action-endpoints: params i URL, IKKE body
**Problem:** LLM-en la /:payment, /:send, /:createCreditNote params i request body -> 422 "kan ikke vaere null".
**Fix:** Eksplisitte FEIL/RIKTIG-eksempler i LLM system prompt. Gjentas 3+ ganger fordi LLM "glemmer".
**Regel:** For LLM-instruksjoner: vis FEIL-eksempel + RIKTIG-eksempel, ikke bare si "gjor X".

### Voucher row starter pa 1, ikke 0
**Problem:** Row 0 er "systemgenerert" i Tripletex -> feil. Tok lang tid a finne.
**Fix:** Alltid start row=1.
**Regel:** Test ALLTID API-format mot sandbox FOR du skriver handler.

### Classifier misrouting
**Problem:** "Tilbudsbrev for ny ansatt" -> create_voucher. "Payment reversal" -> create_salary.
**Leksjon:** Classifier-eksempler MA dekke edge cases. Legg til negative eksempler.

### MVA-laste kontoer
**Problem:** Konto 6000 (avskrivning) er last til MVA 0. Satte vatType=3 -> 422.
**Fix:** Retry uten vatType ved MVA-feil.
**Regel:** Bygg retry-logikk for forutsigbare API-feil.

### Best-ever scoring = gratis forsok
**Leksjon:** Darlige runs skader aldri. Spray-submit er riktig strategi nar agenten er stabil.

### LLM "glemmer" instruksjoner
**Problem:** Tross detaljerte instruksjoner gjor LLM-en samme feil (body vs URL params) gjentatte ganger.
**Leksjon:** Repeter kritiske regler 3+ ganger i system prompt. Bruk GENERELL REGEL-seksjoner som dekker alle tilfeller.

### Keyword-routing med flerspraklig stotte krever PRIORITERT rekkefolge
**Problem:** "Registrer betaling for lonn" matchet "betaling" (payment handler) i stedet for "lonn" (salary handler). Flerspraklige varianter (norsk+engelsk) skapte falske positive.
**Fix:** Spesifikke patterns (f.eks. "lonn", "salary") ma sjekkes FOR generelle patterns (f.eks. "betaling", "payment"). Implementer prioritert keyword-matching med eksplisitt rekkefolge.
**Regel:** I keyword routing: ALLTID sjekk spesifikke/sammensatte patterns for generelle. Test med flerspraklige inputs.

### Sandbox-IDs er unike per request — ALDRI cache mellom requests
**Problem:** Konto-IDer, avdelings-IDer, vatType-IDer etc. cachet fra en sandbox-token ble brukt med en annen -> 403/404.
**Fix:** Hver request har sin egen isolerte TripletexClient med tom cache. Ingen global state.
**Regel:** I sandbox/multi-tenant miljoer: ALDRI cache IDer pa tvers av sessions/tokens.

### GET er gratis i scoring — optimaliser for faerest mulige writes
**Problem:** Unodvendige POST/PUT/DELETE kall som feilet ga negativ score-impact.
**Fix:** Gjor sa mange GET-oppslag som nodvendig for a sikre at writes er korrekte. Soek for du oppretter.
**Regel:** Nar scoring baseres pa write-operasjoner: bruk GET liberalt, vaer konservativ med writes.

### Action-endepunkter i Tripletex: lag interceptor
**Problem:** /:payment, /:send, /:createCreditNote tok params i URL query string. LLM og manuell kode glemte dette gjentatte ganger.
**Fix:** Lag en TX interceptor-klasse som automatisk flytter kjente action-params til URL query string, uavhengig av hvor kalleren legger dem.
**Regel:** Nar et API har inkonsistent parameter-plassering: bygg et abstraksjonslaag som haandterer det transparent.

### Partial score > 0 — gjor det du kan
**Problem:** Brukte tid pa a perfeksjonere vanskelige oppgaver (bank reconciliation, dimensjoner) mens enkle oppgaver ga 100%.
**Fix:** Prioriter oppgaver med hoy sannsynlighet for full score. Bruk LLM fallback for de vanskelige — partial score er bedre enn 0.
**Regel:** I konkurranser: 80/20-regelen. Gjor de enkle oppgavene perfekt for, deretter bruk tid pa de vanskelige.

### vatType IDs er sandbox-spesifikke
**Problem:** Hardkodet vatType id=3 for 25% MVA -> fungerte i en sandbox, feilet i neste.
**Fix:** Dynamisk oppslag via GET /ledger/vatType, match pa prosentverdi.
**Regel:** Aldri hardkod ID-verdier som kan variere mellom miljoer.

### Nested fields i Tripletex bruker parenteser
**Problem:** `fields=postings.account.number` returnerte ikke data. Tripletex bruker parenteser.
**Fix:** `fields=postings(account(number))` — parenteser for nested selection.
**Regel:** Les API-docs for field selection syntax — den er IKKE alltid punktum-basert.

## NorgesGruppen (Object Detection)

### Ensemble > enkeltmodell
**Leksjon:** Enkeltmodell plata ved 0.667. WBF ensemble av 2 modeller ga 0.8951 (+34%). Alltid prov ensemble for deteksjonsoppgaver.

### Lav confidence threshold for ensemble
**Leksjon:** conf=0.01 med WBF gir bedre resultater enn hoyere threshold. WBF haandterer overlappende bokser elegant.

## Astar Island (Monte Carlo)

### Probability floor for KL-divergens
**Leksjon:** Null-sannsynligheter gir KL-divergens = uendelig. Alltid bruk floor (0.01) pa predictions.
