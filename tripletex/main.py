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
                        "create_employee", "create_customer", "create_supplier",
                        "create_product", "create_invoice", "create_order",
                        "register_payment", "create_project", "create_department",
                        "create_travel_expense", "create_voucher",
                        "delete_entity", "update_entity", "unknown"
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

"Registe o fornecedor Luz do Sol Lda com número de organização 962006930"
→ intent=create_supplier, fields={name:"Luz do Sol Lda", organizationNumber:"962006930"}

"Créez le produit Stockage cloud avec numéro 8912 à 26850 NOK avec 25% TVA"
→ intent=create_product, fields={name:"Stockage cloud", number:"8912", unitPrice:26850, vatRate:"25"}

"Register full payment on the invoice for Blueshore Ltd"
→ intent=register_payment, fields={customerName:"Blueshore Ltd", paymentType:"full"}
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

async def find_or_create_employee(fields, tx):
    """Søk etter eksisterende ansatt, opprett kun hvis ikke funnet."""
    first = fields.get("firstName", "")
    last = fields.get("lastName", "")

    if first:
        search = tx.get("employee", params={"firstName": first, "fields": "id,firstName,lastName,email"})
        if not search.get("_error") and search.get("values"):
            # Sjekk om etternavn matcher
            for emp in search["values"]:
                if not last or emp.get("lastName", "").lower() == last.lower():
                    log.info(f"Fant eksisterende ansatt: {first} {last} → ID={emp['id']}")
                    return emp["id"]

    # Ikke funnet — opprett
    if not first or not last:
        log.error("Mangler firstName eller lastName for employee")
        return None

    dept = tx.get("department", params={"fields": "id", "count": 1})
    if dept.get("_error") or not dept.get("values"):
        dept_result = tx.post("department", {"name": "Hovedavdeling", "departmentNumber": 1})
        if dept_result.get("_error"): return None
        dept_id = dept_result["value"]["id"]
    else:
        dept_id = dept["values"][0]["id"]

    has_email = bool(fields.get("email"))
    body = {
        "firstName": first,
        "lastName": last,
        "userType": "STANDARD" if has_email else "NO_ACCESS",
        "department": {"id": dept_id}
    }
    if has_email: body["email"] = fields["email"]

    result = tx.post("employee", body)
    if result.get("_error"): return None
    return result["value"]["id"]

async def handle_create_employee(fields, tx):
    emp_id = await find_or_create_employee(fields, tx)
    if emp_id:
        log.info(f"Ansatt klar ID={emp_id}")
        return True
    return False

async def handle_create_customer(fields, tx):
    name = fields.get("name", "")
    if not name:
        log.error("Mangler name for customer")
        return False

    cust_id = await find_or_create_customer(name, tx, is_supplier=False)
    if not cust_id: return False

    # Oppdater med ekstra felt
    update_body = {"id": cust_id, "name": name}
    if "email" in fields: update_body["email"] = fields["email"]
    if "phone" in fields: update_body["phoneNumber"] = fields["phone"]
    if "organizationNumber" in fields: update_body["organizationNumber"] = str(fields["organizationNumber"])

    # Oppdater kunde-felt (uten adresse)
    if len(update_body) > 2:  # More than just id+name
        tx.put(f"customer/{cust_id}", update_body)

    # Adresse — oppdater via separat PUT på address-objektet
    has_address = any(k in fields for k in ["address", "postalCode", "city"])
    if has_address:
        cust_data = tx.get(f"customer/{cust_id}", params={"fields": "id,postalAddress"})
        if not cust_data.get("_error") and cust_data.get("value", {}).get("postalAddress"):
            addr_id = cust_data["value"]["postalAddress"]["id"]
            addr_body = {"id": addr_id}
            if "address" in fields: addr_body["addressLine1"] = fields["address"]
            if "postalCode" in fields: addr_body["postalCode"] = str(fields["postalCode"])
            if "city" in fields: addr_body["city"] = fields["city"]
            tx.put(f"address/{addr_id}", addr_body)

    return True

async def handle_create_supplier(fields, tx):
    name = fields.get("name", "")
    if not name:
        log.error("Mangler name for supplier")
        return False

    cust_id = await find_or_create_customer(name, tx, is_supplier=True)
    if not cust_id: return False

    # Oppdater med ekstra felt
    update_body = {"id": cust_id, "name": name, "isSupplier": True}
    if "email" in fields: update_body["email"] = fields["email"]
    if "organizationNumber" in fields: update_body["organizationNumber"] = str(fields["organizationNumber"])
    tx.put(f"customer/{cust_id}", update_body)

    return True

async def handle_create_product(fields, tx):
    name = fields.get("name", "")
    if not name:
        log.error("Mangler name for product")
        return False

    # Søk først
    search = tx.get("product", params={"name": name, "fields": "id,name"})
    if not search.get("_error") and search.get("values"):
        log.info(f"Fant eksisterende produkt: {name} → ID={search['values'][0]['id']}")
        # Oppdater med nye felt hvis nødvendig
        prod_id = search["values"][0]["id"]
        update = {"id": prod_id, "name": name}
        if "number" in fields: update["number"] = str(fields["number"])
        if "unitPrice" in fields:
            try: update["priceExcludingVatCurrency"] = float(fields["unitPrice"])
            except: pass
        if "vatRate" in fields:
            vat_id = _vat_rate_to_id(fields["vatRate"])
            if vat_id: update["vatType"] = {"id": vat_id}
        tx.put(f"product/{prod_id}", update)
        return True

    body = {"name": name}
    if "number" in fields: body["number"] = str(fields["number"])
    if "unitPrice" in fields:
        try: body["priceExcludingVatCurrency"] = float(fields["unitPrice"])
        except: pass
    if "vatRate" in fields:
        vat_id = _vat_rate_to_id(fields["vatRate"])
        if vat_id: body["vatType"] = {"id": vat_id}

    result = tx.post("product", body)
    return not result.get("_error")

def _vat_rate_to_id(rate):
    """Konverter MVA-sats til Tripletex vatType ID."""
    try:
        r = float(str(rate).replace("%", ""))
    except: return 3
    if r >= 24: return 3    # 25% standard
    elif r >= 14: return 31  # 15% mat
    elif r >= 11: return 32  # 12% transport
    elif r > 0: return 32
    else: return 5           # 0% fritatt

async def ensure_bank_account(tx):
    """Tripletex krever bankkonto for fakturering. Sett opp hvis mangler."""
    acct = tx.get("ledger/account", params={"number": 1920, "fields": "id,bankAccountNumber"})
    if acct.get("_error") or not acct.get("values"):
        return
    bank = acct["values"][0]
    if not bank.get("bankAccountNumber"):
        tx.put("ledger/account/list", [{"id": bank["id"], "number": 1920, "name": "Bankinnskudd", "bankAccountNumber": "12345678903"}])

async def find_or_create_customer(name, tx, is_supplier=False):
    """Søk etter eksisterende kunde/leverandør, opprett kun hvis ikke funnet."""
    search = tx.get("customer", params={"name": name, "fields": "id,name"})
    if not search.get("_error") and search.get("values"):
        cust_id = search["values"][0]["id"]
        log.info(f"Fant eksisterende kunde/leverandør: {name} → ID={cust_id}")
        return cust_id
    # Ikke funnet — opprett
    body = {"name": name, "isCustomer": not is_supplier, "isSupplier": is_supplier}
    result = tx.post("customer", body)
    if result.get("_error"): return None
    return result["value"]["id"]

async def find_or_create_product(name, tx):
    """Søk etter eksisterende produkt, opprett kun hvis ikke funnet."""
    search = tx.get("product", params={"name": name, "fields": "id,name"})
    if not search.get("_error") and search.get("values"):
        return search["values"][0]["id"]
    result = tx.post("product", {"name": name})
    if result.get("_error"): return None
    return result["value"]["id"]

async def handle_create_invoice(fields, tx):
    today = "2026-03-21"
    due = "2026-04-21"

    # Sørg for bankkonto
    await ensure_bank_account(tx)

    # 1. Kunde — SØK FØRST
    cust_name = fields.get("customerName", fields.get("name", "Kunde"))
    cust_id = await find_or_create_customer(cust_name, tx)
    if not cust_id: return False

    # 2. Produkt — SØK FØRST
    prod_name = fields.get("productName", fields.get("description", "Produkt"))
    prod_id = await find_or_create_product(prod_name, tx)
    if not prod_id: return False

    # 3. Ordre
    order = tx.post("order", {
        "customer": {"id": cust_id},
        "deliveryDate": fields.get("date", today),
        "orderDate": fields.get("date", today)
    })
    if order.get("_error"): return False
    order_id = order["value"]["id"]

    # 4. Ordrelinje(r) — støtter flere linjer
    lines = fields.get("lines", [])
    if not lines:
        # Enkelt-linje fra flat fields
        lines = [{"productName": prod_name, "productId": prod_id,
                   "quantity": fields.get("quantity", 1),
                   "unitPrice": fields.get("unitPrice", 0)}]

    for line in lines:
        line_prod_id = line.get("productId", prod_id)
        if "productName" in line and "productId" not in line:
            p = tx.post("product", {"name": line["productName"]})
            if not p.get("_error"):
                line_prod_id = p["value"]["id"]

        tx.post("order/orderline", {
            "order": {"id": order_id},
            "product": {"id": line_prod_id},
            "count": line.get("quantity", 1),
            "unitPriceExcludingVatCurrency": line.get("unitPrice", 0)
        })

    # 5. Faktura
    invoice = tx.post("invoice", {
        "invoiceDate": fields.get("invoiceDate", today),
        "invoiceDueDate": fields.get("dueDate", due),
        "orders": [{"id": order_id}]
    })
    return not invoice.get("_error")

async def handle_create_order(fields, tx):
    """Opprett ordre uten faktura."""
    today = "2026-03-20"

    # Kunde — søk eller opprett
    cust_name = fields.get("customerName", fields.get("name", "Kunde"))
    cust = tx.post("customer", {"name": cust_name, "isCustomer": True})
    if cust.get("_error"): return False
    cust_id = cust["value"]["id"]

    order = tx.post("order", {
        "customer": {"id": cust_id},
        "deliveryDate": fields.get("date", today),
        "orderDate": fields.get("date", today)
    })
    if order.get("_error"): return False
    order_id = order["value"]["id"]

    # Ordrelinjer
    prod_name = fields.get("productName", "Produkt")
    prod = tx.post("product", {"name": prod_name})
    if not prod.get("_error"):
        tx.post("order/orderline", {
            "order": {"id": order_id},
            "product": {"id": prod["value"]["id"]},
            "count": fields.get("quantity", 1),
            "unitPriceExcludingVatCurrency": fields.get("unitPrice", 0)
        })

    log.info(f"Opprettet ordre ID={order_id}")
    return True

async def handle_create_project(fields, tx):
    today = "2026-03-21"
    name = fields.get("name", "")

    # SØK FØRST etter eksisterende prosjekt
    if name:
        search = tx.get("project", params={"name": name, "fields": "id,name"})
        if not search.get("_error") and search.get("values"):
            log.info(f"Fant eksisterende prosjekt: {name} → ID={search['values'][0]['id']}")
            return True

    body = {"startDate": fields.get("startDate", today)}
    if name: body["name"] = name
    if "number" in fields: body["number"] = str(fields["number"])

    # Finn prosjektleder — søk etter navngitt person eller bruk første ansatt
    if fields.get("projectManagerName"):
        pm_fields = {"firstName": fields["projectManagerName"].split()[0]}
        if " " in fields["projectManagerName"]:
            pm_fields["lastName"] = fields["projectManagerName"].split()[-1]
        pm_id = await find_or_create_employee(pm_fields, tx)
        if pm_id:
            body["projectManager"] = {"id": pm_id}

    if "projectManager" not in body:
        emps = tx.get("employee", params={"fields": "id", "count": 1})
        if not emps.get("_error") and emps.get("values"):
            body["projectManager"] = {"id": emps["values"][0]["id"]}

    result = tx.post("project", body)
    return not result.get("_error")

async def handle_create_travel_expense(fields, tx):
    """Opprett reiseregning."""
    today = "2026-03-20"

    # Finn ansatt
    emp_name = fields.get("employeeName", "")
    emp_id = None
    if emp_name:
        first = emp_name.split()[0] if " " in emp_name else emp_name
        emps = tx.get("employee", params={"firstName": first, "fields": "id"})
        if not emps.get("_error") and emps.get("values"):
            emp_id = emps["values"][0]["id"]

    if not emp_id:
        # Bruk første ansatt
        emps = tx.get("employee", params={"fields": "id", "count": 1})
        if emps.get("_error") or not emps.get("values"): return False
        emp_id = emps["values"][0]["id"]

    body = {
        "employee": {"id": emp_id},
        "title": fields.get("title", fields.get("description", "Reise")),
        "departureDate": fields.get("departureDate", today),
        "returnDate": fields.get("returnDate", today),
    }

    result = tx.post("travelExpense", body)
    if result.get("_error"): return False

    # Legg til kostnader hvis spesifisert
    te_id = result["value"]["id"]
    if fields.get("amount"):
        tx.post("travelExpense/cost", {
            "travelExpense": {"id": te_id},
            "description": fields.get("costDescription", "Reisekostnad"),
            "amount": fields["amount"],
            "date": fields.get("date", today),
            "paymentType": {"id": 1}
        })

    log.info(f"Opprettet reiseregning ID={te_id}")
    return True

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

KRITISK: Kontoen er IKKE tom — den er PRE-POPULERT med data. SØK ALLTID FØRST etter eksisterende entiteter før du oppretter nye.

REGLER:
1. SØK FØRST med GET, OPPRETT KUN HVIS IKKE FUNNET
2. Bruk MINIMALT antall API-kall
3. Etter POST, bruk ID fra responsen
4. Kall 'done' når du er ferdig

VANLIGE OPPSLAG (bruk disse FØR du oppretter):
- GET /customer?name=X&fields=id,name,isCustomer,isSupplier — finn kunde/leverandør
- GET /employee?firstName=X&fields=id,firstName,lastName — finn ansatt
- GET /invoice?customerId=X&invoiceDateFrom=2020-01-01&invoiceDateTo=2030-01-01&fields=id,amount,balance — finn faktura
- GET /product?name=X&fields=id,name — finn produkt
- GET /project?name=X&fields=id,name — finn prosjekt

VANLIGE OPERASJONER:
- Opprett kunde: POST /customer {"name":"X", "isCustomer":true}
- Opprett leverandør: POST /customer {"name":"X", "isSupplier":true, "isCustomer":false}
- Opprett ansatt: POST /employee {"firstName":"X", "lastName":"Y", "userType":"NO_ACCESS", "department":{"id":DEPT_ID}}
- Registrer betaling: POST /ledger/voucher med debet/kredit posteringer, ELLER bruk PUT /invoice/{id} for å markere betalt
- Opprett faktura: Krever kunde + produkt + ordre + ordrelinje + faktura (5 steg)

PÅKREVDE FELT:
- POST /employee: firstName, lastName, userType (NO_ACCESS eller STANDARD), department.id
- POST /customer: name, isCustomer ELLER isSupplier
- POST /product: name
- POST /order: customer.id, deliveryDate (YYYY-MM-DD), orderDate (YYYY-MM-DD)
- POST /order/orderline: order.id, product.id, count
- POST /invoice: invoiceDate, invoiceDueDate, orders[].id
- POST /project: name, projectManager.id, startDate (YYYY-MM-DD)
- POST /department: name, departmentNumber (unik int)

SPRÅK: Oppgaver kan komme på nb, nn, en, es, pt, de, fr. Parse alle.
- "fornecedor" / "leverandør" / "supplier" / "Lieferant" = isSupplier:true
- "cliente" / "kunde" / "customer" / "Kunde" = isCustomer:true

KOMPLETTE FLYTER (følg disse nøyaktig):

=== ORDRE → FAKTURA → BETALING ===
1. GET /customer?name=X → finn eksisterende kunde-ID
2. Hvis ikke funnet: POST /customer {"name":"X", "isCustomer":true} → cust_id
3. For hvert produkt: GET /product?name=X → finn eller POST /product {"name":"X", "number":"NUM"}
4. POST /order {"customer":{"id":cust_id}, "deliveryDate":"2026-03-21", "orderDate":"2026-03-21"}
5. For hver ordrelinje: POST /order/orderline {"order":{"id":order_id}, "product":{"id":prod_id}, "count":QTY, "unitPriceExcludingVatCurrency":PRIS}
6. POST /invoice {"invoiceDate":"2026-03-21", "invoiceDueDate":"2026-04-21", "orders":[{"id":order_id}]}
7. For betaling: POST /invoice/{invoice_id}/:createPayment {"paymentDate":"2026-03-21", "paymentTypeId":0, "paidAmount":BELØP_INKL_MVA}
   VIKTIG: paidAmount MÅ inkludere MVA (25% standard). Hvis beløp er 22000 eks MVA → paidAmount = 27500.

=== REISEREGNING (travelExpense) ===
1. GET /employee?firstName=X → finn ansatt-ID
2. POST /travelExpense {"employee":{"id":emp_id}, "title":"Tittel", "departureDate":"2026-03-21", "returnDate":"2026-03-23"}
3. For dagpenger: POST /travelExpense/perDiemCompensation {"travelExpense":{"id":te_id}, "rateTypeId":1, "countDays":DAGER, "amount":DAGSATS*DAGER}
   Eller: POST /travelExpense/cost {"travelExpense":{"id":te_id}, "description":"Dagpenger", "amount":TOTAL, "date":"2026-03-21", "paymentType":{"id":0}, "category":"per_diem"}
4. For kostnader (fly, taxi): POST /travelExpense/cost {"travelExpense":{"id":te_id}, "description":"Flybillett", "amount":BELØP, "date":"2026-03-21", "paymentType":{"id":0}}

=== OPPRETT PRODUKT MED MVA ===
POST /product {"name":"X", "number":"NUM", "priceExcludingVatCurrency":PRIS, "vatType":{"id":3}}
MVA-typer: id=3 (25% standard/utgående høy), id=31 (15% mat/utgående middels), id=5 (0% fritatt innenfor), id=6 (0% utenfor)

=== LØNN / SALARY ===
1. GET /employee?firstName=X → finn ansatt
2. GET /salary/type?fields=id,description → finn lønnsart
3. POST /salary/payslip {"employee":{"id":EMP_ID}, "date":"2026-03-21", "year":2026, "month":3, "specifications":[{"salaryType":{"id":TYPE_ID}, "rate":BELØP, "count":1}]}

=== KREDITNOTA (credit note / avoir / Gutschrift) ===
1. GET /customer?name=X → finn kunde
2. GET /invoice?customerId=CUST_ID&invoiceDateFrom=2020-01-01&invoiceDateTo=2030-01-01&fields=id,amount,amountOutstanding → finn faktura
3. PUT /invoice/{invoice_id}/:createCreditNote?date=2026-03-21
Det er alt! Tripletex oppretter automatisk kreditnota som annulerer fakturaen.

=== SEND FAKTURA ===
Etter å ha opprettet faktura:
PUT /invoice/{invoice_id}/:send?sendType=EMAIL
sendType kan være: EMAIL, EHF, EFAKTURA, AVTALEGIRO, VIPPS

=== OPPRETT OG SEND FAKTURA (komplett flyt) ===
1. GET /customer?name=X → finn eller POST /customer
2. POST /product {"name":"X"} → finn eller opprett
3. POST /order {"customer":{"id":CUST_ID}, "deliveryDate":"2026-03-21", "orderDate":"2026-03-21"}
4. POST /order/orderline {"order":{"id":ORDER_ID}, "product":{"id":PROD_ID}, "count":1, "unitPriceExcludingVatCurrency":PRIS}
5. POST /invoice {"invoiceDate":"2026-03-21", "invoiceDueDate":"2026-04-21", "orders":[{"id":ORDER_ID}]}
6. PUT /invoice/{invoice_id}/:send?sendType=EMAIL

=== KJENTE BEGRENSNINGER (IKKE prøv disse) ===
- /invoice/:createPayment EKSISTERER IKKE i sandbox
- /ledger/dimension eksisterer IKKE
- /salary/transaction bruker "employee":{"id":X}, IKKE "employeeId"
- /salary/payslip gir 500-feil i sandbox
- /company gir 405 Method Not Allowed
- For betaling: registrer via bilag (POST /ledger/voucher) eller ignorer betalingsdelen
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
    "create_supplier": handle_create_supplier,
    "create_product": handle_create_product,
    "create_invoice": handle_create_invoice,
    "create_order": handle_create_order,
    "create_project": handle_create_project,
    "create_department": handle_create_department,
    "create_travel_expense": handle_create_travel_expense,
    "delete_entity": handle_delete_entity,
}

# ============================================================
# ENDPOINTS
# ============================================================
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/solve")
@app.post("/")
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

        # Komplekse oppgaver → direkte til LLM (bedre enn deterministisk for multi-steg)
        complex_intents = {"register_payment", "create_voucher", "update_entity", "unknown"}

        # Sjekk om oppgaven er multi-steg eller multi-create
        multi_step_keywords = ["konverter", "betaling", "payment", "pago",
                               "registra el pago", "registrer betaling",
                               "pago completo", "full payment", "dagpenger", "indemnités",
                               "note de frais", "reiseregning", "travel expense", "nota de despesas",
                               "kreditnota", "avoir", "credit note", "gutschrift", "nota de crédito",
                               "reverser", "reverse", "annuler", "stornieren",
                               "lønnsslipp", "salário", "salary", "gehalt", "salaire",
                               "dimensjon", "dimension"]

        # Multi-create: oppgaver som ber om å opprette flere entiteter
        prompt_lower = prompt.lower()
        multi_create_keywords = ["tre avdeling", "drei abteilung", "three department",
                                  "tres departamento", "trois département"]
        is_multi_create = any(kw in prompt_lower for kw in multi_create_keywords)
        is_multi_step = any(kw in prompt_lower for kw in multi_step_keywords)

        if intent in complex_intents or is_multi_create or (is_multi_step and intent not in {"create_employee", "create_customer", "create_supplier", "create_department", "create_product"}):
            log.info(f"Kompleks oppgave → LLM fallback (intent={intent}, multi_step={is_multi_step}, multi_create={is_multi_create})")
            await handle_unknown(prompt, files_text, tx)
        elif intent in HANDLERS:
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
