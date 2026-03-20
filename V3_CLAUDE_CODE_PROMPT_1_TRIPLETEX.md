# CLAUDE CODE PROMPT — AGENT 1: TRIPLETEX AI ACCOUNTING AGENT (V3)
# NM i AI 2026 | Dream Team: Karpathy, Altman, Hotz, Burns
# V3-forbedringer: Tool-use API, error recovery, few-shot, feltvalidering

---

## DIN ROLLE

Bygg og deploy en Tripletex AI Accounting Agent. Følg beslutningsreglene bokstavelig.

---

## KRITISKE V3-FORBEDRINGER (implementer disse)

### 1. TOOL-USE istedenfor JSON-parsing
Bruk Anthropics tool-use API. Definer Tripletex-operasjoner som tools. Da slipper du all JSON-parsing og feilhåndtering rundt det. Claude returnerer strukturerte tool_use-blokker som du parser direkte.

### 2. ERROR RECOVERY med retry til Claude
Hvis et API-kall feiler med 4xx, send feilmeldingen TILBAKE til Claude med kontekst ("Steg 3 av 5 feilet med 422: 'firstName is required'"). La Claude generere korrigert steg. Maks 2 retries per OPPGAVE (ikke per steg).

### 3. FEW-SHOT eksempler i system-prompten
Inkluder 2-3 komplette eksempler: prompt → tool-calls → resultat. Dette øker Tier 1 correctness dramatisk.

### 4. FELTVALIDERING før API-kall
Valider at påkrevde felt finnes FØR du sender til Tripletex. Forhindrer 422-feil. Direkte mapping til efficiency bonus.

---

## OPERATIVE BESLUTNINGSREGLER

**Karpathy:** Start enkelt → overfit på én oppgave → generaliser gradvis → verifiser hvert steg
**Altman:** Ship 80% → iterer med real scoring → perfeksjon på få > middelmådighet på mange
**Hotz:** Fungerer det? Ship det. 30 min uten fremgang? Bytt tilnærming. Under 500 linjer.
**Burns:** Én container, deklarativ deploy, logg alt, ha rollback-plan.

---

## SCORING (uendret fra V2 — les dette)

- 30 oppgavetyper, 3 tiers (×1, ×2, ×3)
- Correctness: felt-for-felt verifisering → 0-1
- **Efficiency bonus:** KUN ved perfekt correctness. Færre API-kall + null 4xx = dobbel score.
- Best-ever per oppgave — dårlige forsøk teller aldri
- 56 varianter (7 språk × 8 datasett)
- Rate limits (verifisert): 3 concurrent, 5 per task per dag

---

## IMPLEMENTASJON — main.py MED TOOL-USE

```python
"""
Tripletex AI Accounting Agent — NM i AI 2026 (V3)
Forbedringer: Tool-use API, error recovery, few-shot, feltvalidering
"""
import base64
import io
import json
import logging
import time
from typing import Any

import anthropic
import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("agent")

app = FastAPI()
claude = anthropic.Anthropic()

# === TRIPLETEX CLIENT (Burns: logg alt) ===
class TX:
    def __init__(self, base_url: str, token: str):
        self.base = base_url.rstrip("/")
        self.auth = ("0", token)
        self.calls = 0
        self.errors = 0

    def _req(self, method, endpoint, params=None, body=None):
        url = f"{self.base}/{endpoint.lstrip('/')}"
        self.calls += 1
        t0 = time.time()
        kwargs = {"auth": self.auth}
        if params:
            kwargs["params"] = params
        if body is not None:
            kwargs["json"] = body
        resp = requests.request(method, url, **kwargs)
        dt = time.time() - t0
        status = resp.status_code
        if status >= 400:
            self.errors += 1
            log.warning(f"✗ {method} {endpoint} → {status} ({dt:.2f}s): {resp.text[:500]}")
            return {"_error": True, "_status": status, "_body": resp.text[:500]}
        log.info(f"✓ {method} {endpoint} → {status} ({dt:.2f}s)")
        return resp.json() if resp.text else {}

    def get(self, ep, params=None): return self._req("GET", ep, params=params)
    def post(self, ep, body): return self._req("POST", ep, body=body)
    def put(self, ep, body): return self._req("PUT", ep, body=body)
    def delete(self, ep): return self._req("DELETE", ep)

# === FILE HANDLER ===
def extract_files(files: list) -> str:
    if not files: return ""
    texts = []
    for f in files:
        try:
            raw = base64.b64decode(f.get("content_base64", ""))
            if "pdf" in f.get("mime_type", ""):
                try:
                    import pdfplumber
                    pdf = pdfplumber.open(io.BytesIO(raw))
                    text = "\n".join(p.extract_text() or "" for p in pdf.pages)
                    pdf.close()
                    texts.append(f"[{f['filename']}]\n{text}")
                except: texts.append(f"[{f['filename']}] (PDF feilet)")
            else:
                texts.append(f"[{f['filename']}]\n{raw.decode('utf-8', errors='replace')[:5000]}")
        except Exception as e:
            log.error(f"Fil-feil: {e}")
    return "\n\n".join(texts)

# === TOOL-DEFINISJONER FOR CLAUDE (V3: tool-use istedenfor JSON) ===
TOOLS = [
    {
        "name": "tripletex_get",
        "description": "GET request til Tripletex API. Bruk for å hente/søke etter entiteter.",
        "input_schema": {
            "type": "object",
            "properties": {
                "endpoint": {"type": "string", "description": "API endpoint, f.eks. '/employee' eller '/customer'"},
                "params": {"type": "object", "description": "Query parameters, f.eks. {'fields': 'id,firstName', 'name': 'Ola'}"}
            },
            "required": ["endpoint"]
        }
    },
    {
        "name": "tripletex_post",
        "description": "POST request til Tripletex API. Bruk for å opprette nye entiteter. Returnerer opprettet entitet med ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "endpoint": {"type": "string", "description": "API endpoint, f.eks. '/employee'"},
                "body": {"type": "object", "description": "JSON body med felt for den nye entiteten"}
            },
            "required": ["endpoint", "body"]
        }
    },
    {
        "name": "tripletex_put",
        "description": "PUT request til Tripletex API. Bruk for å oppdatere eksisterende entiteter.",
        "input_schema": {
            "type": "object",
            "properties": {
                "endpoint": {"type": "string", "description": "API endpoint med ID, f.eks. '/employee/123'"},
                "body": {"type": "object", "description": "JSON body med oppdaterte felt"}
            },
            "required": ["endpoint", "body"]
        }
    },
    {
        "name": "tripletex_delete",
        "description": "DELETE request til Tripletex API. Bruk for å slette entiteter.",
        "input_schema": {
            "type": "object",
            "properties": {
                "endpoint": {"type": "string", "description": "API endpoint med ID, f.eks. '/travelExpense/456'"}
            },
            "required": ["endpoint"]
        }
    },
    {
        "name": "task_complete",
        "description": "Kall dette NÅR oppgaven er fullført. Kall det alltid til slutt.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Kort oppsummering av hva som ble gjort"}
            },
            "required": ["summary"]
        }
    }
]

# === SYSTEM PROMPT MED FEW-SHOT (V3) ===
SYSTEM = """Du er en Tripletex regnskapsagent. Du utfører regnskapsoppgaver mot Tripletex API.

REGLER FOR EFFICIENCY (dette påvirker scoren direkte):
1. TENK GJENNOM hele oppgaven FØR du gjør noe. Planlegg alle steg mentalt.
2. Bruk MINIMALT antall API-kall. Hvert ekstra kall senker efficiency-bonusen.
3. Etter POST, bruk ID-en fra responsen. ALDRI gjør GET for å finne noe du nettopp opprettet.
4. ALDRI send et kall du vet vil feile. Sjekk at alle påkrevde felt er med.
5. Null 4xx-feil er målet. Hver feil reduserer bonusen.

SPRÅK: Oppgaver kan komme på norsk bokmål, nynorsk, engelsk, spansk, portugisisk, tysk eller fransk. Parse alle.

KONTOEN STARTER TOM: Du må opprette prerequisites (kunde, produkt) FØR du lager faktura/ordre.

VANLIGE PÅKREVDE FELT:
- POST /employee: firstName (str), lastName (str) — email er valgfri men ofte etterspurt
- POST /customer: name (str), isCustomer (bool: true)
- POST /product: name (str)
- POST /order: customer.id (int), deliveryDate (str YYYY-MM-DD), orderDate (str YYYY-MM-DD)
- POST /order/orderline: order.id (int), product.id (int) ELLER description (str), count (num)
- POST /invoice: invoiceDate (str), invoiceDueDate (str), orders[].id (int)
- POST /project: name (str), number (str/int), projectManager.id (int)
- POST /department: name (str), departmentNumber (int)

KALL task_complete NÅR DU ER FERDIG.

=== EKSEMPEL 1: Opprett ansatt ===
Oppgave: "Opprett en ansatt med navn Ola Nordmann, epost ola@test.no. Han skal være administrator."

Steg:
1. tripletex_post("/employee", {"firstName": "Ola", "lastName": "Nordmann", "email": "ola@test.no"})
   → Får tilbake {"value": {"id": 42, ...}}
2. Sjekk om administratorrolle krever PUT — i Tripletex settes dette ofte via userType eller tilgangsgrupper.
3. task_complete("Opprettet ansatt Ola Nordmann (ID 42) med epost ola@test.no")

=== EKSEMPEL 2: Opprett faktura ===
Oppgave: "Opprett en faktura til kunde Acme AS for produkt 'Konsulenttimer' med 10 timer à 1500 kr."

Steg:
1. tripletex_post("/customer", {"name": "Acme AS", "isCustomer": true})
   → {"value": {"id": 100}}
2. tripletex_post("/product", {"name": "Konsulenttimer"})
   → {"value": {"id": 200}}
3. tripletex_post("/order", {"customer": {"id": 100}, "deliveryDate": "2026-03-20", "orderDate": "2026-03-20"})
   → {"value": {"id": 300}}
4. tripletex_post("/order/orderline", {"order": {"id": 300}, "product": {"id": 200}, "count": 10, "unitPriceExcludingVatCurrency": 1500})
   → {"value": {"id": 400}}
5. tripletex_post("/invoice", {"invoiceDate": "2026-03-20", "invoiceDueDate": "2026-04-20", "orders": [{"id": 300}]})
   → {"value": {"id": 500}}
6. task_complete("Opprettet faktura 500 til Acme AS for 10x Konsulenttimer à 1500kr")

=== EKSEMPEL 3: Slett reiseregning ===
Oppgave: "Slett reiseregningen til Kari Hansen"

Steg:
1. tripletex_get("/travelExpense", {"employeeFirstName": "Kari", "fields": "id,employee"})
   → Finn riktig ID
2. tripletex_delete("/travelExpense/{id}")
3. task_complete("Slettet reiseregning {id}")
"""

# === AGENT LOOP MED ERROR RECOVERY (V3) ===
async def run_agent(prompt: str, files_text: str, tx: TX):
    """
    Kjør Claude med tool-use. Utfør tool-calls sekvensielt.
    Ved feil: send feilmelding tilbake til Claude for korrigering. Maks 2 retries.
    """
    messages = [{"role": "user", "content": prompt + (f"\n\nVEDLEGG:\n{files_text}" if files_text else "")}]
    
    retries = 0
    max_retries = 2
    
    while retries <= max_retries:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            temperature=0,
            system=SYSTEM,
            tools=TOOLS,
            messages=messages
        )
        
        # Prosesser response
        tool_results = []
        task_done = False
        had_error = False
        
        for block in response.content:
            if block.type == "tool_use":
                name = block.name
                inp = block.input
                tool_id = block.id
                
                log.info(f"Tool: {name}({json.dumps(inp, ensure_ascii=False)[:200]})")
                
                if name == "task_complete":
                    log.info(f"FERDIG: {inp.get('summary', '')}")
                    task_done = True
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": "OK"
                    })
                    
                elif name == "tripletex_get":
                    result = tx.get(inp["endpoint"], params=inp.get("params"))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": json.dumps(result, ensure_ascii=False)[:3000]
                    })
                    if result.get("_error"):
                        had_error = True
                    
                elif name == "tripletex_post":
                    result = tx.post(inp["endpoint"], inp["body"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": json.dumps(result, ensure_ascii=False)[:3000]
                    })
                    if result.get("_error"):
                        had_error = True
                    
                elif name == "tripletex_put":
                    result = tx.put(inp["endpoint"], inp["body"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": json.dumps(result, ensure_ascii=False)[:3000]
                    })
                    if result.get("_error"):
                        had_error = True
                    
                elif name == "tripletex_delete":
                    result = tx.delete(inp["endpoint"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": json.dumps(result, ensure_ascii=False)[:3000]
                    })
                    if result.get("_error"):
                        had_error = True
        
        if task_done:
            break
        
        if not tool_results:
            # Claude svarte med tekst uten tool-calls — oppgaven er kanskje allerede ferdig
            log.info("Ingen tool-calls — antar ferdig")
            break
        
        # Legg til assistant-response og tool-results i samtalen
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})
        
        if had_error:
            retries += 1
            log.warning(f"Feil i tool-call — retry {retries}/{max_retries}")
        
        # Sikkerhet: maks 15 tool-call-runder (unngå uendelig loop)
        if len(messages) > 30:
            log.warning("Maks meldinger nådd — stopper")
            break
    
    log.info(f"Agent ferdig: {tx.calls} API-kall, {tx.errors} feil, {retries} retries")

# === ENDPOINTS ===
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/solve")
async def solve(request: Request):
    body = await request.json()
    prompt = body["prompt"]
    files = body.get("files", [])
    creds = body["tripletex_credentials"]
    
    log.info(f"{'='*60}")
    log.info(f"OPPGAVE: {prompt[:300]}")
    
    files_text = extract_files(files)
    tx = TX(creds["base_url"], creds["session_token"])
    
    try:
        await run_agent(prompt, files_text, tx)
    except Exception as e:
        log.error(f"FATAL: {e}")
        # Altman: ship uansett — returnerer completed
    
    # ALLTID returner completed (loggen har feilinfo for debugging)
    return JSONResponse({"status": "completed"})
```

---

## DEPLOY

Uendret fra V2 — bruk deploy.sh eller:
```bash
# Cloud Run
gcloud run deploy tripletex-agent --source . --region europe-north1 --allow-unauthenticated --memory 1Gi --cpu 2 --timeout 300 --min-instances 1 --set-env-vars "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}"

# Eller lokal Docker + Caddy
docker build -t tripletex-agent . && docker run -d -p 8080:8080 -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" --name tripletex tripletex-agent
```

---

## KARPATHYS OPPSKRIFT — ITERASJONSSTRATEGI

1. **Deploy baseline** → submit → se score
2. **Overfit på "Opprett ansatt"** til 100% correctness
3. **Legg til oppgavetyper én om gangen**, submit etter hver
4. **Tier 2** (fredag morgen): utvid few-shot med faktura/betaling-eksempler
5. **Tier 3** (lørdag morgen): legg til komplekse eksempler
6. **Efficiency-optimalisering** etter correctness er 100%
7. **Lørdag 20:00: FEATURE FREEZE** — kun bugfix

## HOTZ FALLBACK

| Problem | Løsning | Tid |
|---------|---------|-----|
| Tool-use feiler | Fall tilbake til JSON-parsing (V2-metoden) | 15 min |
| Claude timeout | Forenkle system-prompt, fjern few-shot | 5 min |
| Spesifikk oppgavetype feiler | Hardcode API-kall for den ene typen | 20 min |
| Alt feiler | Returner {"status": "completed"} — dårlig score > timeout | 0 min |
