"""
Tripletex AI Accounting Agent — V4
Deterministisk mellomlag: LLM forstår → Kode handler
NM i AI 2026 — EZ-Fix AS
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
# TRIPLETEX CLIENT
# ============================================================
class TX:
    def __init__(self, base_url, token):
        self.base = base_url.rstrip("/")
        self.auth = ("0", token)
        self.calls = 0
        self.errors = 0
        self.log_entries = []

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
# INTENT CLASSIFIER
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
# DETERMINISTISKE HANDLERS
# ============================================================

async def handle_create_employee(fields, tx):
    body = {}
    if "firstName" in fields: body["firstName"] = fields["firstName"]
    if "lastName" in fields: body["lastName"] = fields["lastName"]
    if "email" in fields: body["email"] = fields["email"]

    if "firstName" not in body or "lastName" not in body:
        log.error("Mangler firstName eller lastName for employee")
        return False

    result = tx.post("employee", body)
    if result.get("_error"): return False

    emp_id = result["value"]["id"]
    log.info(f"Opprettet ansatt ID={emp_id}")
    return True

async def handle_create_customer(fields, tx):
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
    body = {}
    if "name" in fields: body["name"] = fields["name"]
    if "number" in fields: body["number"] = fields["number"]
    if "unitPrice" in fields: body["priceExcludingVatCurrency"] = fields["unitPrice"]

    result = tx.post("product", body)
    return not result.get("_error")

async def handle_create_invoice(fields, tx):
    today = "2026-03-20"
    due = "2026-04-20"

    cust_name = fields.get("customerName", "Kunde")
    cust = tx.post("customer", {"name": cust_name, "isCustomer": True})
    if cust.get("_error"): return False
    cust_id = cust["value"]["id"]

    prod_name = fields.get("productName", "Produkt")
    prod = tx.post("product", {"name": prod_name})
    if prod.get("_error"): return False
    prod_id = prod["value"]["id"]

    order = tx.post("order", {
        "customer": {"id": cust_id},
        "deliveryDate": fields.get("date", today),
        "orderDate": fields.get("date", today)
    })
    if order.get("_error"): return False
    order_id = order["value"]["id"]

    qty = fields.get("quantity", 1)
    price = fields.get("unitPrice", 0)
    orderline = tx.post("order/orderline", {
        "order": {"id": order_id},
        "product": {"id": prod_id},
        "count": qty,
        "unitPriceExcludingVatCurrency": price
    })
    if orderline.get("_error"): return False

    invoice = tx.post("invoice", {
        "invoiceDate": fields.get("invoiceDate", today),
        "invoiceDueDate": fields.get("dueDate", due),
        "orders": [{"id": order_id}]
    })
    return not invoice.get("_error")

async def handle_create_project(fields, tx):
    body = {}
    if "name" in fields: body["name"] = fields["name"]
    if "number" in fields: body["number"] = fields["number"]

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

# Fallback — full LLM agent-loop for unknown intents
async def handle_unknown(prompt, files_text, tx):
    log.warning("UNKNOWN intent — bruker LLM fallback")

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
Kall 'done' når du er ferdig.

VANLIGE PÅKREVDE FELT:
- POST /employee: firstName (str), lastName (str) — email er valgfri
- POST /customer: name (str), isCustomer (bool: true)
- POST /product: name (str)
- POST /order: customer.id (int), deliveryDate (str YYYY-MM-DD), orderDate (str YYYY-MM-DD)
- POST /order/orderline: order.id (int), product.id (int), count (num)
- POST /invoice: invoiceDate (str), invoiceDueDate (str), orders[].id (int)
- POST /project: name (str), number (str/int), projectManager.id (int)
- POST /department: name (str), departmentNumber (int)
"""

    messages = [{"role": "user", "content": prompt + (f"\n\nVEDLEGG:\n{files_text}" if files_text else "")}]

    for _ in range(10):
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

    summary = tx.summary()
    log.info(f"SUMMARY: {json.dumps(summary)}")

    return JSONResponse({"status": "completed"})
