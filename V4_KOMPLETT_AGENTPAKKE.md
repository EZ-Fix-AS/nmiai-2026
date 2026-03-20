# NM I AI 2026 — V4 KOMPLETT AGENTPAKKE
# Alle forbedringer fra V3-review implementert
# 4 prompts i ett dokument — klipp ut og paste i separate Claude Code-agenter

---
---
---

# ═══════════════════════════════════════════════════════════
# AGENT 0: PROSJEKTLEDER & SETUP (V4)
# ═══════════════════════════════════════════════════════════

## DIN ROLLE

Sett opp alt som KAN automatiseres. Stopp med eksplisitt BLOCKED-status på manuelle steg. Rapporter ALDRI "setup komplett" før blockers er løst.

## AUTOMATISERTE STEG (gjør disse selv)

1. Opprett mappestruktur:
```
nmiai-2026/
├── README.md (MIT-lisens, kort beskrivelse)
├── LICENSE (MIT, Copyright 2026 EZ-Fix AS)
├── .gitignore (pycache, .env, .pt, runs/, .zip)
├── .env.example (ANTHROPIC_API_KEY, AINM_JWT_TOKEN, TRIPLETEX_*)
├── SCOREBOARD.md (V4: felles score-tracking)
├── tripletex/
│   ├── main.py (placeholder — Agent 1 bygger denne)
│   ├── handlers.py (placeholder — Agent 1 bygger denne)
│   ├── requirements.txt
│   ├── Dockerfile
│   └── deploy.sh
├── norgesgruppen/
│   ├── inspect_data.py (placeholder)
│   ├── train.py (placeholder)
│   ├── run.py (placeholder)
│   └── requirements.txt
└── astar-island/
    ├── main.py (placeholder)
    ├── config.py
    └── requirements.txt
```

2. Init git, opprett .gitignore, commit initial structure
3. Opprett SCOREBOARD.md:

```markdown
# SCOREBOARD — NM i AI 2026

| Tid | Oppgave | Commit | Endring | Score | Hypotese | Neste |
|-----|---------|--------|---------|-------|----------|-------|
| | | | | | | |
```

4. Opprett alle requirements.txt, Dockerfile, deploy.sh (innhold fra V3)
5. Installer MCP: `claude mcp add --transport http nmiai https://mcp-docs.ainm.no/mcp`

## MANUELLE BLOCKERS — MÅ LØSES AV MENNESKE

Rapporter denne listen eksplisitt:

```
⛔ BLOCKERS (krever manuell handling):

1. [ ] GitHub repo: Opprett public repo og push
       → github.com → New → "nmiai-2026" → Public → Create
       → git remote add origin ... && git push

2. [ ] NorgesGruppen data: Last ned fra app.ainm.no → Tasks → NorgesGruppen → Submit
       → NM_NGD_coco_dataset.zip (~864 MB)
       → Pakk ut i norgesgruppen/dataset/

3. [ ] Tripletex sandbox: Gå til app.ainm.no → Tasks → Tripletex → Submit → "Get Sandbox Account"
       → Kopier URL + token → legg i .env

4. [ ] Astar JWT token: Logg inn app.ainm.no → DevTools → Cookies → access_token
       → Oppdater astar-island/config.py

5. [ ] ANTHROPIC_API_KEY: export ANTHROPIC_API_KEY=sk-ant-...

STATUS: ❌ IKKE KLAR — løs blockers ovenfor, deretter start Agent 1-3
```

**Rapporter ALDRI "setup komplett" uten at blockers er merket som løst.**

---
---
---

# ═══════════════════════════════════════════════════════════
# AGENT 1: TRIPLETEX AI ACCOUNTING AGENT (V4)
# ═══════════════════════════════════════════════════════════

## V4-ENDRING: DETERMINISTISK MELLOMLAG

V3 lot Claude velge rå endpoints/bodies fritt via tools. V4 innfører:

```
Prompt → Intent Classifier (LLM) → Deterministic Handler (kode) → Tripletex API
```

LLM sin jobb: Forstå HVEM, HVA, HVILKE FELT.
Kode sin jobb: Eie API-formen, endpoint-valg, felt-validering.

## ARKITEKTUR

```
POST /solve
  ├── extract_files() → tekst fra PDF/vedlegg
  ├── classify_intent(prompt) → {"intent": "create_employee", "fields": {...}}
  │   └── Claude tool-use med INTENT-tools (ikke API-tools)
  ├── handlers[intent](fields, tx_client)
  │   └── Deterministisk kode som kaller riktige endpoints
  └── return {"status": "completed"}
```

## KOMPLETT main.py (V4)

```python
"""
Tripletex AI Accounting Agent — V4
Deterministisk mellomlag: LLM forstår → Kode handler
"""
import base64, io, json, logging, time, os
from typing import Any, Optional
import anthropic, requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("agent")
app = FastAPI()
claude = anthropic.Anthropic()

# ============================================================
# TRIPLETEX CLIENT (Burns: logg alt)
# ============================================================
class TX:
    def __init__(self, base_url, token):
        self.base = base_url.rstrip("/")
        self.auth = ("0", token)
        self.calls = 0
        self.errors = 0
        self.log_entries = []  # V4: intern sannhetsstatus

    def _req(self, method, ep, params=None, body=None):
        url = f"{self.base}/{ep.lstrip('/')}"
        self.calls += 1
        t0 = time.time()
        kwargs = {"auth": self.auth}
        if params: kwargs["params"] = params
        if body is not None: kwargs["json"] = body
        resp = requests.request(method, url, **kwargs)
        dt = time.time() - t0
        
        entry = {"method": method, "endpoint": ep, "status": resp.status_code, 
                 "time": round(dt, 2), "success": resp.status_code < 400}
        
        if resp.status_code >= 400:
            self.errors += 1
            entry["error"] = resp.text[:500]
            log.warning(f"✗ {method} {ep} → {resp.status_code} ({dt:.2f}s): {resp.text[:300]}")
        else:
            log.info(f"✓ {method} {ep} → {resp.status_code} ({dt:.2f}s)")
        
        self.log_entries.append(entry)
        
        if resp.status_code >= 400:
            return {"_error": True, "_status": resp.status_code, "_body": resp.text[:500]}
        return resp.json() if resp.text else {}

    def get(self, ep, params=None): return self._req("GET", ep, params=params)
    def post(self, ep, body): return self._req("POST", ep, body=body)
    def put(self, ep, body): return self._req("PUT", ep, body=body)
    def delete(self, ep): return self._req("DELETE", ep)
    
    def summary(self):
        """V4: Intern sannhetsstatus for debugging"""
        return {
            "total_calls": self.calls,
            "errors": self.errors,
            "error_rate": f"{self.errors/max(self.calls,1)*100:.0f}%",
            "failed_calls": [e for e in self.log_entries if not e["success"]]
        }

# ============================================================
# FILE HANDLER
# ============================================================
def extract_files(files):
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

# ============================================================
# V4: INTENT CLASSIFIER (LLM forstår, kode handler)
# ============================================================
CLASSIFY_TOOLS = [
    {
        "name": "classify_task",
        "description": "Klassifiser oppgaven og ekstraher alle relevante felt.",
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": [
                        "create_employee", "create_customer", "create_product",
                        "create_invoice", "create_order", "register_payment",
                        "create_project", "create_department", "create_travel_expense",
                        "create_voucher", "delete_entity", "update_entity",
                        "unknown"
                    ],
                    "description": "Oppgavetypen"
                },
                "fields": {
                    "type": "object",
                    "description": "Alle relevante felt fra oppgaven. Bruk feltnavn som matcher Tripletex API."
                },
                "reasoning": {
                    "type": "string",
                    "description": "Kort forklaring av hva oppgaven ber om"
                }
            },
            "required": ["intent", "fields", "reasoning"]
        }
    }
]

CLASSIFY_SYSTEM = """Du er en intent-classifier for Tripletex regnskapsoppgaver.

Din ENESTE jobb er å:
1. Forstå hva oppgaven ber om
2. Klassifisere den som én intent
3. Ekstrahere ALLE relevante felt

Du utfører INGEN API-kall. Du bare forstår og ekstraherer.

SPRÅK: Oppgaver kan komme på nb, nn, en, es, pt, de, fr. Parse alle.

FELT-KONVENSJONER:
- Personnavn: firstName, lastName
- Firmanavn: name
- Epost: email
- Beløp: amount, unitPrice
- Dato: bruk YYYY-MM-DD format. Hvis ingen dato oppgitt, bruk 2026-03-20.
- Roller: isAdministrator, userType
- Referanser: customerName, employeeName, productName (for oppslag)

EKSEMPLER:

"Opprett en ansatt med navn Ola Nordmann, ola@test.no, administrator"
→ intent=create_employee, fields={firstName:"Ola", lastName:"Nordmann", email:"ola@test.no", isAdministrator:true}

"Lag en faktura til Acme AS for 10 konsulenttimer à 1500 kr"  
→ intent=create_invoice, fields={customerName:"Acme AS", productName:"Konsulenttimer", quantity:10, unitPrice:1500}

"Slett reiseregningen til Kari Hansen"
→ intent=delete_entity, fields={entityType:"travelExpense", employeeName:"Kari Hansen"}

"Opprett prosjekt 'Nettside redesign' med Ola som prosjektleder"
→ intent=create_project, fields={name:"Nettside redesign", projectManagerName:"Ola"}
"""

async def classify_intent(prompt, files_text):
    msg = prompt + (f"\n\nVEDLEGG:\n{files_text}" if files_text else "")
    
    resp = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        temperature=0,
        system=CLASSIFY_SYSTEM,
        tools=CLASSIFY_TOOLS,
        tool_choice={"type": "tool", "name": "classify_task"},
        messages=[{"role": "user", "content": msg}]
    )
    
    for block in resp.content:
        if block.type == "tool_use" and block.name == "classify_task":
            return block.input
    
    return {"intent": "unknown", "fields": {}, "reasoning": "Kunne ikke klassifisere"}

# ============================================================
# V4: DETERMINISTISKE HANDLERS (kode eier API-formen)
# ============================================================

async def handle_create_employee(fields, tx):
    """Opprett ansatt — deterministisk."""
    body = {}
    if "firstName" in fields: body["firstName"] = fields["firstName"]
    if "lastName" in fields: body["lastName"] = fields["lastName"]
    if "email" in fields: body["email"] = fields["email"]
    
    # Validering
    if "firstName" not in body or "lastName" not in body:
        log.error("Mangler firstName eller lastName for employee")
        return False
    
    result = tx.post("employee", body)
    if result.get("_error"): return False
    
    emp_id = result["value"]["id"]
    log.info(f"Opprettet ansatt ID={emp_id}")
    
    # Sett administrator-rolle hvis påkrevd
    if fields.get("isAdministrator"):
        # Hent full employee for å oppdatere
        tx.put(f"employee/{emp_id}", {"id": emp_id, "firstName": body["firstName"], 
                "lastName": body["lastName"], "email": body.get("email", "")})
    
    return True

async def handle_create_customer(fields, tx):
    """Opprett kunde — deterministisk."""
    body = {"isCustomer": True}
    if "name" in fields: body["name"] = fields["name"]
    if "email" in fields: body["email"] = fields["email"]
    if "phone" in fields: body["phoneNumber"] = fields["phone"]
    
    if "name" not in body:
        log.error("Mangler name for customer")
        return False
    
    result = tx.post("customer", body)
    return not result.get("_error")

async def handle_create_product(fields, tx):
    """Opprett produkt — deterministisk."""
    body = {}
    if "name" in fields: body["name"] = fields["name"]
    if "number" in fields: body["number"] = fields["number"]
    if "unitPrice" in fields: body["priceExcludingVatCurrency"] = fields["unitPrice"]
    
    result = tx.post("product", body)
    return not result.get("_error")

async def handle_create_invoice(fields, tx):
    """Opprett faktura — multi-steg, deterministisk."""
    today = "2026-03-20"
    due = "2026-04-20"
    
    # 1. Opprett eller finn kunde
    cust_name = fields.get("customerName", "Kunde")
    cust = tx.post("customer", {"name": cust_name, "isCustomer": True})
    if cust.get("_error"): return False
    cust_id = cust["value"]["id"]
    
    # 2. Opprett produkt hvis spesifisert
    prod_name = fields.get("productName", "Produkt")
    prod = tx.post("product", {"name": prod_name})
    if prod.get("_error"): return False
    prod_id = prod["value"]["id"]
    
    # 3. Opprett ordre
    order = tx.post("order", {
        "customer": {"id": cust_id},
        "deliveryDate": fields.get("date", today),
        "orderDate": fields.get("date", today)
    })
    if order.get("_error"): return False
    order_id = order["value"]["id"]
    
    # 4. Opprett ordrelinje
    qty = fields.get("quantity", 1)
    price = fields.get("unitPrice", 0)
    orderline = tx.post("order/orderline", {
        "order": {"id": order_id},
        "product": {"id": prod_id},
        "count": qty,
        "unitPriceExcludingVatCurrency": price
    })
    if orderline.get("_error"): return False
    
    # 5. Opprett faktura
    invoice = tx.post("invoice", {
        "invoiceDate": fields.get("invoiceDate", today),
        "invoiceDueDate": fields.get("dueDate", due),
        "orders": [{"id": order_id}]
    })
    return not invoice.get("_error")

async def handle_create_project(fields, tx):
    """Opprett prosjekt — deterministisk."""
    body = {}
    if "name" in fields: body["name"] = fields["name"]
    if "number" in fields: body["number"] = fields["number"]
    
    # Finn prosjektleder
    if fields.get("projectManagerName"):
        name = fields["projectManagerName"]
        emps = tx.get("employee", params={"firstName": name.split()[0] if " " in name else name, "fields": "id,firstName,lastName"})
        if not emps.get("_error") and emps.get("values"):
            body["projectManager"] = {"id": emps["values"][0]["id"]}
    
    result = tx.post("project", body)
    return not result.get("_error")

async def handle_create_department(fields, tx):
    body = {}
    if "name" in fields: body["name"] = fields["name"]
    if "number" in fields: body["departmentNumber"] = fields["number"]
    result = tx.post("department", body)
    return not result.get("_error")

async def handle_delete_entity(fields, tx):
    entity_type = fields.get("entityType", "")
    endpoint_map = {
        "employee": "employee", "customer": "customer", "product": "product",
        "invoice": "invoice", "travelExpense": "travelExpense", "project": "project",
        "department": "department", "voucher": "ledger/voucher"
    }
    ep = endpoint_map.get(entity_type, entity_type)
    
    # Søk etter entiteten
    search_params = {"fields": "id", "count": 10}
    if "employeeName" in fields:
        name = fields["employeeName"]
        if " " in name:
            parts = name.split(None, 1)
            search_params["employeeFirstName"] = parts[0]
        else:
            search_params["employeeFirstName"] = name
    
    results = tx.get(ep, params=search_params)
    if results.get("_error") or not results.get("values"): return False
    
    entity_id = results["values"][0]["id"]
    result = tx.delete(f"{ep}/{entity_id}")
    return not result.get("_error")

# V4: Fallback — bruk full LLM agent-loop for ukjente oppgavetyper
async def handle_unknown(prompt, files_text, tx):
    """Fallback til V3 tool-use for oppgaver vi ikke har hardkodet handler for."""
    log.warning("UNKNOWN intent — bruker LLM fallback")
    
    # V3 tool-use kode her (forkortet for plass)
    TOOLS = [
        {"name": "tripletex_get", "description": "GET Tripletex API", 
         "input_schema": {"type": "object", "properties": {"endpoint": {"type": "string"}, "params": {"type": "object"}}, "required": ["endpoint"]}},
        {"name": "tripletex_post", "description": "POST Tripletex API",
         "input_schema": {"type": "object", "properties": {"endpoint": {"type": "string"}, "body": {"type": "object"}}, "required": ["endpoint", "body"]}},
        {"name": "tripletex_put", "description": "PUT Tripletex API",
         "input_schema": {"type": "object", "properties": {"endpoint": {"type": "string"}, "body": {"type": "object"}}, "required": ["endpoint", "body"]}},
        {"name": "tripletex_delete", "description": "DELETE Tripletex API",
         "input_schema": {"type": "object", "properties": {"endpoint": {"type": "string"}}, "required": ["endpoint"]}},
        {"name": "done", "description": "Oppgaven er ferdig", 
         "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}}
    ]
    
    SYSTEM = """Du er en Tripletex regnskapsagent. Utfør oppgaven med minimale API-kall.
Kontoen starter TOM. Opprett prerequisites FØR hovedoppgaven.
Etter POST, bruk ID fra responsen — aldri GET for å finne noe du nettopp opprettet.
Kall 'done' når du er ferdig."""
    
    messages = [{"role": "user", "content": prompt + (f"\n\nVEDLEGG:\n{files_text}" if files_text else "")}]
    
    for _ in range(10):  # Maks 10 runder
        resp = claude.messages.create(
            model="claude-sonnet-4-20250514", max_tokens=4096, temperature=0,
            system=SYSTEM, tools=TOOLS, messages=messages
        )
        
        results = []
        done = False
        for block in resp.content:
            if block.type == "tool_use":
                if block.name == "done":
                    done = True
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": "OK"})
                elif block.name.startswith("tripletex_"):
                    method = block.name.split("_")[1]
                    inp = block.input
                    if method == "get":
                        r = tx.get(inp["endpoint"], params=inp.get("params"))
                    elif method == "post":
                        r = tx.post(inp["endpoint"], inp["body"])
                    elif method == "put":
                        r = tx.put(inp["endpoint"], inp["body"])
                    elif method == "delete":
                        r = tx.delete(inp["endpoint"])
                    else: r = {}
                    results.append({"type": "tool_result", "tool_use_id": block.id, 
                                   "content": json.dumps(r, ensure_ascii=False)[:3000]})
        
        if done or not results: break
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": results})
    
    return True

# ============================================================
# HANDLER REGISTRY
# ============================================================
HANDLERS = {
    "create_employee": handle_create_employee,
    "create_customer": handle_create_customer,
    "create_product": handle_create_product,
    "create_invoice": handle_create_invoice,
    "create_project": handle_create_project,
    "create_department": handle_create_department,
    "delete_entity": handle_delete_entity,
}

# ============================================================
# ENDPOINTS
# ============================================================
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
        # V4: Intent classification → deterministic handler
        classification = await classify_intent(prompt, files_text)
        intent = classification.get("intent", "unknown")
        fields = classification.get("fields", {})
        reasoning = classification.get("reasoning", "")
        
        log.info(f"INTENT: {intent}")
        log.info(f"FIELDS: {json.dumps(fields, ensure_ascii=False)[:300]}")
        log.info(f"REASONING: {reasoning}")
        
        if intent in HANDLERS:
            success = await HANDLERS[intent](fields, tx)
            if not success:
                log.warning(f"Handler feilet — prøver LLM fallback")
                await handle_unknown(prompt, files_text, tx)
        else:
            await handle_unknown(prompt, files_text, tx)
        
    except Exception as e:
        log.error(f"FATAL: {e}")
    
    # V4: Logg intern sannhetsstatus (for debugging mellom submissions)
    summary = tx.summary()
    log.info(f"SUMMARY: {json.dumps(summary)}")
    
    return JSONResponse({"status": "completed"})
```

## ITERASJONSSTRATEGI

1. Deploy med bare create_employee handler → submit → verifiser 100% correctness
2. Legg til create_customer → submit → verifiser
3. Legg til create_invoice (multi-steg) → submit → verifiser
4. Fortsett med alle handlers i HANDLERS-registeret
5. For oppgavetyper uten handler: LLM fallback dekker dem
6. Etter correctness er OK: optimaliser efficiency (fjern unødvendige kall)

## LOGG TIL SCOREBOARD.md ETTER HVER SUBMISSION

```markdown
| Fre 22:30 | Tripletex | abc123 | Lagt til create_employee handler | 1.0 (Tier 1) | Efficiency bonus? | Test Tier 2 |
```

---
---
---

# ═══════════════════════════════════════════════════════════
# AGENT 2: NORGESGRUPPEN (V4) — endringer markert
# ═══════════════════════════════════════════════════════════

## V4-ENDRINGER

Alt fra V3 er beholdt. Nytt:

### Feilanalyse-loop mellom submissions

Etter submit 1, KJØR DENNE ANALYSEN FØR submit 2:

```python
"""
V4: Feilanalyse mellom submissions
Kjør dette etter du ser scoren fra submit 1
"""
from ultralytics import YOLO
from collections import Counter
import json

model = YOLO('runs/detect/phase2_1280/weights/best.pt')
metrics = model.val(data='dataset.yaml', imgsz=1280)

# 1. Hvilke klasser har null recall?
per_class = metrics.box.ap  # Per-class AP
zero_recall = [i for i, ap in enumerate(per_class) if ap < 0.01]
print(f"Klasser med ~0 AP: {len(zero_recall)} av {len(per_class)}")

# 2. Box-size distribusjon
with open('annotations.json') as f:
    coco = json.load(f)

areas = [a['bbox'][2] * a['bbox'][3] for a in coco['annotations']]
small = sum(1 for a in areas if a < 32*32)
medium = sum(1 for a in areas if 32*32 <= a < 96*96)
large = sum(1 for a in areas if a >= 96*96)
print(f"Small: {small}, Medium: {medium}, Large: {large}")

# 3. Klasser som kolliderer mest (lavest AP men høy frekvens)
cat_counts = Counter(a['category_id'] for a in coco['annotations'])
confused = [(i, ap, cat_counts.get(i, 0)) for i, ap in enumerate(per_class) 
            if ap < 0.3 and cat_counts.get(i, 0) > 20]
confused.sort(key=lambda x: x[1])
print(f"\nKonfuse klasser (lav AP, høy frekvens):")
for cat_id, ap, count in confused[:10]:
    print(f"  [{cat_id}] AP={ap:.3f} count={count}")

# 4. Bør vi bytte til v8l?
# Sjekk inference-hastighet
import time
t0 = time.time()
model.predict(source='dataset/images/val', imgsz=1280, conf=0.15, save=False, verbose=False)
dt = time.time() - t0
print(f"\nInference-tid: {dt:.1f}s for val-sett")
print(f"Estimert per bilde: {dt/len(list(Path('dataset/images/val').glob('*.jpg'))):.2f}s")
```

### Submission-strategi basert på analyse

Submit 1: Fase 2 modell, conf=0.15 → se baseline score
Submit 2: Basert på feilanalyse:
- Hvis mange small objects misses → tren med imgsz=1600
- Hvis mange klasser har 0 recall → senk conf til 0.10
- Hvis inference er for treg → bytt til v8l
Submit 3: Beste kombinasjon

**Alt annet er uendret fra V3** — 2-fase trening, submission-validering, TTA.

---
---
---

# ═══════════════════════════════════════════════════════════
# AGENT 3: ASTAR ISLAND (V4) — endringer markert
# ═══════════════════════════════════════════════════════════

## V4-ENDRING: EKTE TEMPORAL PRIORS

Erstatt den kosmetiske temporal priors-koden med faktisk læring:

```python
# V4: Lagre og bruk analyse-data mellom runder
import json
from pathlib import Path

LEARNING_FILE = "astar_learned_priors.json"

def load_learned_priors():
    """Last lærte priorer fra forrige runde."""
    p = Path(LEARNING_FILE)
    if p.exists():
        return json.loads(p.read_text())
    return None

def save_learned_priors(data):
    """Lagre lærte priorer for neste runde."""
    Path(LEARNING_FILE).write_text(json.dumps(data))

def learn_from_analysis(round_id):
    """
    V4: Ekte temporal learning.
    Hent ground truth, beregn:
    - Global klassefrekvens (over alle dynamiske celler)
    - Over-/underprediksjon per klasse
    - Overlevelsesrate per terrengtype
    - Sannsynlighetstabeller for nærhet til coast/forest/settlement
    """
    learned = {
        "class_freq": [0]*6,           # Global klassefrekvens
        "pred_bias": [0]*6,            # Over-/underprediksjon
        "survival_by_terrain": {},     # Initial terrain → sluttfordeling
        "n_cells_analyzed": 0
    }
    
    terrain_stats = {}  # initial_value → Counter of final classes
    
    for si in range(5):
        try:
            data = api("GET", f"analysis/{round_id}/{si}")
            truth = np.array(data["ground_truth"])
            pred = np.array(data.get("prediction", []))
            init_grid = data.get("initial_grid")
            
            h, w = truth.shape[:2]
            
            for y in range(h):
                for x in range(w):
                    t = truth[y, x]
                    entropy = -np.sum(t * np.log(t + 1e-10))
                    
                    if entropy > 0.1:  # Dynamisk celle
                        # Global klassefrekvens
                        for c in range(6):
                            learned["class_freq"][c] += t[c]
                        
                        # Bias-korreksjon
                        if len(pred) > 0:
                            for c in range(6):
                                learned["pred_bias"][c] += (pred[y,x,c] - t[c])
                        
                        # Terrain → outcome mapping
                        if init_grid:
                            iv = init_grid[y][x]
                            if iv not in terrain_stats:
                                terrain_stats[iv] = np.zeros(6)
                            terrain_stats[iv] += t
                        
                        learned["n_cells_analyzed"] += 1
                        
        except Exception as e:
            log.warning(f"Analyse seed {si} feilet: {e}")
    
    # Normaliser
    n = max(learned["n_cells_analyzed"], 1)
    learned["class_freq"] = [f/n for f in learned["class_freq"]]
    learned["pred_bias"] = [b/n for b in learned["pred_bias"]]
    
    # Terrain → outcome (normalisert)
    learned["terrain_to_outcome"] = {}
    for iv, counts in terrain_stats.items():
        total = counts.sum()
        if total > 0:
            learned["terrain_to_outcome"][str(iv)] = (counts / total).tolist()
    
    save_learned_priors(learned)
    
    print(f"\nLÆRT FRA {n} dynamiske celler:")
    for c, name in enumerate(["Empty","Settlement","Port","Ruin","Forest","Mountain"]):
        freq = learned["class_freq"][c]
        bias = learned["pred_bias"][c]
        print(f"  {name}: freq={freq:.3f}, bias={bias:+.3f}")
    
    if learned["terrain_to_outcome"]:
        print(f"\nTerrain → outcome:")
        for iv, probs in learned["terrain_to_outcome"].items():
            print(f"  Initial {iv}: {[round(p,3) for p in probs]}")
    
    return learned
```

### Bruk lærte priors i compute_priors:

```python
def compute_priors(grid, settlements, h, w):
    """V4: Bruk lærte priors fra forrige runde hvis tilgjengelig."""
    learned = load_learned_priors()
    
    P = np.full((h, w, 6), FLOOR)
    sett_pos = {(s["y"], s["x"]) for s in settlements}
    
    # ... (same near/near_val functions as V3) ...
    
    for y in range(h):
        for x in range(w):
            v = grid[y][x]
            
            # V4: Hvis vi har lært fra forrige runde, bruk terrain→outcome mapping
            if learned and str(v) in learned.get("terrain_to_outcome", {}):
                base = np.array(learned["terrain_to_outcome"][str(v)])
                # Juster basert på nabolag (coast, forest, settlement)
                # ... (nabolag-kode som før, men med lærte base-sannsynligheter)
                P[y, x] = base
            else:
                # Fallback til hardkodede priors (V3-kode)
                # ... (uendret V3-logikk) ...
                pass
    
    # Bias-korreksjon fra forrige runde
    if learned and learned.get("pred_bias"):
        bias = np.array(learned["pred_bias"])
        for y in range(h):
            for x in range(w):
                P[y, x] -= bias * 0.5  # Halv korreksjon — ikke overkompeniser
    
    P = np.maximum(P, FLOOR)
    P /= P.sum(axis=-1, keepdims=True)
    return P
```

### Oppdatert main-loop:

```python
def main():
    # ... (uendret fra V3 for aktiv runde) ...
    
    # ETTER runden er scored:
    # Kjør learn_from_analysis for å oppdatere priors
    completed = [r for r in api("GET", "rounds") if r["status"] == "completed"]
    if completed:
        latest = max(completed, key=lambda r: r["round_number"])
        print(f"\nKjører V4 temporal learning fra runde #{latest['round_number']}...")
        learn_from_analysis(latest["id"])
```

**Alt annet er uendret fra V3** — viewport-planlegging, aggregering, dynamisk PRIOR_WEIGHT, probability floor.
