"""
Tripletex AI Accounting Agent — V5.3
EFFICIENCY OPTIMIZED: GET is FREE, only writes (POST/PUT/DELETE) count.
Zero 4xx errors + minimum writes = maximum efficiency bonus (2x score).
NM i AI 2026 — EZ-Fix AS
"""
import base64, io, json, logging, time, os, re, random
from typing import Any, Optional
import anthropic, requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("agent")
app = FastAPI()
claude = anthropic.Anthropic()

# ============================================================
# PER-REQUEST CACHE — each submission has its OWN sandbox!
# Global cache is POISONOUS — different sandboxes have different IDs
# ============================================================
class RequestCache:
    def __init__(self):
        self.dept_id = None
        self.bank_setup_done = False
        self.pay_type_id = None
        self.account_ids = {}
        self.cost_categories = None

# Thread-local-ish: set per request
_rc = None

def get_cache():
    global _rc
    if _rc is None: _rc = RequestCache()
    return _rc

def reset_cache():
    global _rc
    _rc = RequestCache()

VAT_MAP = {25: 3, 15: 31, 12: 33, 0: 5}

def vat_id_from_rate(rate):
    try: r = float(str(rate).replace("%", ""))
    except: return 3
    if r >= 24: return 3
    elif r >= 14: return 31
    elif r >= 11: return 33
    elif r > 0: return 33
    else: return 5

# ============================================================
# TRIPLETEX CLIENT — interceptor + write counter
# ============================================================
ACTION_ENDPOINTS = {
    "/:payment": ["paymentDate", "paymentTypeId", "paidAmount", "paidAmountCurrency"],
    "/:send": ["sendType"],
    "/:createCreditNote": ["date"],
    "/:deliver": ["deliveryDate"],
    "/:approve": [], "/:reject": [],
}

class TX:
    def __init__(self, base_url, token):
        self.base = base_url.rstrip("/")
        self.auth = ("0", token)
        self.calls = 0
        self.writes = 0
        self.errors = 0
        self.log_entries = []
        self.start_time = time.time()

    def _intercept(self, method, ep, body):
        if method not in ("PUT", "POST") or not body or not isinstance(body, dict):
            return ep, body
        for action, params in ACTION_ENDPOINTS.items():
            if action in ep:
                moved, rest = {}, {}
                for k, v in body.items():
                    if k in params or k in ("paymentDate","paymentTypeId","paidAmount","paidAmountCurrency","sendType","date","deliveryDate"):
                        moved[k] = v
                    else:
                        rest[k] = v
                if moved:
                    sep = "&" if "?" in ep else "?"
                    ep = f"{ep}{sep}" + "&".join(f"{k}={v}" for k, v in moved.items())
                return ep, rest or {}
        return ep, body

    def _fix_endpoint(self, ep):
        """Fix common LLM endpoint mistakes."""
        ep = ep.lstrip("/")  # Remove leading slash
        # Fix wrong paths
        if ep == "voucher" or ep.startswith("voucher/"):
            ep = "ledger/" + ep
        if ep == "ledger" or ep == "ledger/":
            ep = "ledger/voucher"
        return ep

    def _req(self, method, ep, params=None, body=None):
        if getattr(self, '_dead', False):
            return {"_error": True, "_status": 403, "_body": "Proxy token expired"}
        ep = self._fix_endpoint(ep)
        if body is not None:
            ep, body = self._intercept(method, ep, body)
        url = f"{self.base}/{ep.lstrip('/')}"
        self.calls += 1
        if method in ("POST", "PUT", "DELETE", "PATCH"):
            self.writes += 1
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
            if resp.status_code == 403 and "proxy token" in resp.text.lower():
                self._dead = True
        else:
            log.info(f"✓ {method} {ep} → {resp.status_code} ({dt:.2f}s)")
        self.log_entries.append(entry)
        if resp.status_code >= 400:
            return {"_error": True, "_status": resp.status_code, "_body": resp.text[:500]}
        return resp.json() if resp.text else {}

    def get(self, ep, params=None): return self._req("GET", ep, params=params)
    def post(self, ep, body): return self._req("POST", ep, body=body)
    def put(self, ep, body=None): return self._req("PUT", ep, body=body or {})
    def delete(self, ep): return self._req("DELETE", ep)
    def elapsed(self): return time.time() - self.start_time

    def summary(self):
        return {"total_calls": self.calls, "writes": self.writes, "errors": self.errors,
                "elapsed": f"{self.elapsed():.1f}s",
                "failed": [e for e in self.log_entries if not e["success"]]}

# ============================================================
# CACHED LOOKUPS — GET is FREE, cache aggressively
# ============================================================
async def get_account_id(tx, number):
    rc = get_cache()
    number = int(number)
    if number in rc.account_ids:
        return rc.account_ids[number]
    acct = tx.get("ledger/account", params={"number": number, "fields": "id"})
    if not acct.get("_error") and acct.get("values"):
        rc.account_ids[number] = acct["values"][0]["id"]
        return acct["values"][0]["id"]
    return None

async def get_default_dept(tx):
    rc = get_cache()
    if rc.dept_id: return rc.dept_id
    dept = tx.get("department", params={"fields": "id", "count": 1})
    if not dept.get("_error") and dept.get("values"):
        rc.dept_id = dept["values"][0]["id"]
    else:
        r = tx.post("department", {"name": "Hovedavdeling", "departmentNumber": 1})
        if not r.get("_error"): rc.dept_id = r["value"]["id"]
    return rc.dept_id

async def ensure_bank_account(tx):
    rc = get_cache()
    if rc.bank_setup_done: return rc.account_ids.get(1920)
    acct = tx.get("ledger/account", params={"number": 1920, "fields": "id,bankAccountNumber"})
    if acct.get("_error") or not acct.get("values"):
        rc.bank_setup_done = True
        return None
    bank = acct["values"][0]
    rc.account_ids[1920] = bank["id"]
    if not bank.get("bankAccountNumber"):
        tx.put("ledger/account/list", [{"id": bank["id"], "number": 1920, "name": "Bankinnskudd", "bankAccountNumber": "12345678903"}])
    rc.bank_setup_done = True
    return bank["id"]

async def get_payment_type(tx):
    rc = get_cache()
    if rc.pay_type_id: return rc.pay_type_id
    pts = tx.get("invoice/paymentType", params={"fields": "id,description"})
    if not pts.get("_error") and pts.get("values"):
        for pt in pts["values"]:
            if "bank" in pt.get("description", "").lower():
                rc.pay_type_id = pt["id"]; return pt["id"]
        rc.pay_type_id = pts["values"][0]["id"]
        return rc.pay_type_id
    return None

async def get_cost_categories(tx):
    rc = get_cache()
    if rc.cost_categories: return rc.cost_categories
    cats = tx.get("travelExpense/costCategory", params={"fields": "id,description", "count": 40})
    if not cats.get("_error") and cats.get("values"):
        rc.cost_categories = {c.get("description","").lower(): c["id"] for c in cats["values"]}
    return rc.cost_categories or {}

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
# HAIKU FIELD EXTRACTOR
# ============================================================
def extract_fields(prompt, tool_name, schema, system_msg="Extract fields from the prompt. Return JSON only."):
    resp = claude.messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=512, temperature=0,
        system=system_msg,
        tools=[{"name": tool_name, "description": f"Extracted {tool_name}", "input_schema": schema}],
        tool_choice={"type": "tool", "name": tool_name},
        messages=[{"role": "user", "content": prompt}]
    )
    for block in resp.content:
        if block.type == "tool_use": return block.input
    return {}

# ============================================================
# DETERMINISTIC HANDLERS — MINIMUM WRITES
# ============================================================

# --- EMPLOYEE: Target 1 write (POST employee) ---
async def handle_create_employee(prompt, tx):
    fields = extract_fields(prompt, "emp", {
        "type": "object",
        "properties": {
            "firstName": {"type": "string"}, "lastName": {"type": "string"},
            "email": {"type": "string"}, "dateOfBirth": {"type": "string"},
            "departmentName": {"type": "string"}, "startDate": {"type": "string"},
            "annualSalary": {"type": "number"}, "nationalIdentityNumber": {"type": "string"},
            "bankAccountNumber": {"type": "string"}, "workingPercentage": {"type": "number"}
        }, "required": ["firstName", "lastName"]
    })
    first, last = fields.get("firstName", ""), fields.get("lastName", "")
    if not first or not last: return False

    # GET is free — search existing
    s = tx.get("employee", params={"firstName": first, "fields": "id,firstName,lastName"})
    if not s.get("_error") and s.get("values"):
        for emp in s["values"]:
            if emp.get("lastName", "").lower() == last.lower():
                return True  # Already exists — 0 writes!

    # Department — use cache, only create if named AND not found
    dept_id = None
    dn = fields.get("departmentName", "")
    if dn:
        ds = tx.get("department", params={"name": dn, "fields": "id,name"})
        if not ds.get("_error") and ds.get("values"):
            dept_id = ds["values"][0]["id"]
        else:
            # 1 write: create department
            dr = tx.post("department", {"name": dn, "departmentNumber": random.randint(300, 9999)})
            if not dr.get("_error"): dept_id = dr["value"]["id"]
    if not dept_id:
        dept_id = await get_default_dept(tx)
    if not dept_id: return False

    has_email = bool(fields.get("email"))
    body = {"firstName": first, "lastName": last,
            "userType": "STANDARD" if has_email else "NO_ACCESS",
            "department": {"id": dept_id}}
    if has_email: body["email"] = fields["email"]
    if fields.get("dateOfBirth"): body["dateOfBirth"] = fields["dateOfBirth"]
    if fields.get("nationalIdentityNumber"): body["nationalIdentityNumber"] = str(fields["nationalIdentityNumber"])
    if fields.get("bankAccountNumber"): body["bankAccountNumber"] = str(fields["bankAccountNumber"])

    # 1 write: POST employee
    result = tx.post("employee", body)
    if result.get("_error"): return False
    emp_id = result["value"]["id"]

    # Only create employment if explicitly requested — 1 extra write
    if fields.get("startDate") or fields.get("annualSalary") or fields.get("workingPercentage"):
        start = fields.get("startDate", "2026-03-21")
        details = {"date": start, "employmentType": "ORDINARY"}
        if fields.get("annualSalary"): details["annualSalary"] = float(fields["annualSalary"])
        if fields.get("workingPercentage"): details["percentageOfFullTimeEquivalent"] = float(fields["workingPercentage"])
        tx.post("employee/employment", {"employee": {"id": emp_id}, "startDate": start,
                "isMainEmployer": True, "employmentDetails": [details]})
    return True

# --- CUSTOMER: Target 1 write (POST customer with ALL fields) ---
async def handle_create_customer(prompt, tx):
    fields = extract_fields(prompt, "cust", {
        "type": "object",
        "properties": {
            "name": {"type": "string"}, "email": {"type": "string"},
            "phoneNumber": {"type": "string"}, "organizationNumber": {"type": "string"},
            "address": {"type": "string"}, "postalCode": {"type": "string"},
            "city": {"type": "string"}, "isSupplier": {"type": "boolean"},
            "invoiceEmail": {"type": "string"}, "language": {"type": "string"}
        }, "required": ["name"]
    }, "Extract customer/supplier fields. If supplier/leverandør/fournisseur/Lieferant/proveedor/fornecedor → isSupplier=true.")
    name = fields.get("name", "")
    if not name: return False
    is_supp = fields.get("isSupplier", False)

    # GET free — check existing
    s = tx.get("customer", params={"name": name, "fields": "id,name"})
    if not s.get("_error") and s.get("values"):
        cust_id = s["values"][0]["id"]
        # Only PUT if we have extra fields to add — 1 write
        update = {"id": cust_id}
        if is_supp: update["isSupplier"] = True
        for k in ["email", "invoiceEmail", "phoneNumber", "language"]:
            if fields.get(k): update[k] = fields[k]
        if fields.get("organizationNumber"): update["organizationNumber"] = str(fields["organizationNumber"])
        if len(update) > 1:
            tx.put(f"customer/{cust_id}", update)
        # Address — only if provided, 1 extra write
        if any(fields.get(k) for k in ["address", "postalCode", "city"]):
            cd = tx.get(f"customer/{cust_id}", params={"fields": "id,postalAddress"})
            if not cd.get("_error") and cd.get("value", {}).get("postalAddress"):
                aid = cd["value"]["postalAddress"]["id"]
                addr = {"id": aid}
                if fields.get("address"): addr["addressLine1"] = fields["address"]
                if fields.get("postalCode"): addr["postalCode"] = str(fields["postalCode"])
                if fields.get("city"): addr["city"] = fields["city"]
                tx.put(f"address/{aid}", addr)
        return True

    # Not found — create with ALL fields in one POST (1 write!)
    body = {"name": name, "isCustomer": not is_supp, "isSupplier": is_supp}
    if fields.get("email"): body["email"] = fields["email"]
    if fields.get("invoiceEmail"): body["invoiceEmail"] = fields["invoiceEmail"]
    if fields.get("phoneNumber"): body["phoneNumber"] = fields["phoneNumber"]
    if fields.get("organizationNumber"): body["organizationNumber"] = str(fields["organizationNumber"])
    # language must be valid Tripletex enum — skip if uncertain
    lang = fields.get("language", "")
    if lang and lang.upper() in ("NO", "EN", "SV", "DA", "FI", "DE", "FR", "ES", "PT", "NL", "PL"):
        body["language"] = lang.upper()

    result = tx.post("customer", body)
    if result.get("_error"): return False
    cust_id = result["value"]["id"]

    # Address only if provided — separate call required by API
    if any(fields.get(k) for k in ["address", "postalCode", "city"]):
        cd = tx.get(f"customer/{cust_id}", params={"fields": "id,postalAddress"})
        if not cd.get("_error") and cd.get("value", {}).get("postalAddress"):
            aid = cd["value"]["postalAddress"]["id"]
            addr = {"id": aid}
            if fields.get("address"): addr["addressLine1"] = fields["address"]
            if fields.get("postalCode"): addr["postalCode"] = str(fields["postalCode"])
            if fields.get("city"): addr["city"] = fields["city"]
            tx.put(f"address/{aid}", addr)
    return True

# --- SUPPLIER: 1 write ---
async def handle_create_supplier(prompt, tx):
    return await handle_create_customer(f"(This is a SUPPLIER/leverandør) {prompt}", tx)

# --- DEPARTMENT: 1 write ---
async def handle_create_department(prompt, tx):
    fields = extract_fields(prompt, "dept", {
        "type": "object",
        "properties": {"name": {"type": "string"}, "departmentNumber": {"type": "integer"}},
        "required": ["name"]
    }, "Extract department name and optional number. Return JSON only.")
    name = fields.get("name", "Avdeling")
    s = tx.get("department", params={"name": name, "fields": "id,name"})
    if not s.get("_error") and s.get("values"): return True  # 0 writes!
    body = {"name": name, "departmentNumber": fields.get("departmentNumber", random.randint(300, 9999))}
    r = tx.post("department", body)
    if r.get("_error") and "Nummeret er i bruk" in r.get("_body", ""):
        body["departmentNumber"] = random.randint(1000, 99999)
        r = tx.post("department", body)
    return not r.get("_error")

# --- MULTI-DEPARTMENT: N writes ---
async def handle_multi_department(prompt, tx):
    fields = extract_fields(prompt, "mdept", {
        "type": "object",
        "properties": {"departments": {"type": "array", "items": {"type": "string"}}},
        "required": ["departments"]
    }, "Extract ALL department names from the prompt as a list of strings.")
    depts = fields.get("departments", [])
    if not depts: return False
    for d in depts:
        s = tx.get("department", params={"name": d, "fields": "id"})
        if not s.get("_error") and s.get("values"): continue
        r = tx.post("department", {"name": d, "departmentNumber": random.randint(300, 99999)})
        if r.get("_error") and "Nummeret er i bruk" in r.get("_body", ""):
            tx.post("department", {"name": d, "departmentNumber": random.randint(10000, 99999)})
    return True

# --- PROJECT: find/create customer + employee + project ---
async def handle_create_project(prompt, tx):
    fields = extract_fields(prompt, "proj", {
        "type": "object",
        "properties": {
            "name": {"type": "string"}, "customerName": {"type": "string"},
            "customerOrgNumber": {"type": "string"},
            "projectManagerName": {"type": "string"}, "projectManagerEmail": {"type": "string"},
            "startDate": {"type": "string"}, "budget": {"type": "number"},
            "isFixedPrice": {"type": "boolean"}
        }, "required": ["name"]
    }, "Extract project fields. Include customer and project manager details.")
    pname = fields.get("name", "")
    if not pname: return False

    # Search existing project
    ps = tx.get("project", params={"name": pname, "fields": "id,name"})
    if not ps.get("_error") and ps.get("values"): return True

    # Find/create customer
    cust_id = None
    cn = fields.get("customerName", "")
    if cn:
        cs = tx.get("customer", params={"name": cn, "fields": "id"})
        if not cs.get("_error") and cs.get("values"):
            cust_id = cs["values"][0]["id"]
        else:
            body = {"name": cn, "isCustomer": True}
            if fields.get("customerOrgNumber"): body["organizationNumber"] = str(fields["customerOrgNumber"])
            cr = tx.post("customer", body)
            if not cr.get("_error"): cust_id = cr["value"]["id"]

    # Find/create project manager
    pm_id = None
    pmn = fields.get("projectManagerName", "")
    if pmn and " " in pmn:
        parts = pmn.split(None, 1)
        emps = tx.get("employee", params={"firstName": parts[0], "fields": "id,firstName,lastName"})
        if not emps.get("_error") and emps.get("values"):
            pm_id = emps["values"][0]["id"]
        else:
            dept_id = await get_default_dept(tx)
            has_email = bool(fields.get("projectManagerEmail"))
            eb = {"firstName": parts[0], "lastName": parts[1],
                  "userType": "STANDARD" if has_email else "NO_ACCESS",
                  "department": {"id": dept_id}}
            if has_email: eb["email"] = fields["projectManagerEmail"]
            er = tx.post("employee", eb)
            if not er.get("_error"): pm_id = er["value"]["id"]

    if not pm_id:
        emps = tx.get("employee", params={"fields": "id", "count": 1})
        if not emps.get("_error") and emps.get("values"): pm_id = emps["values"][0]["id"]

    body = {"name": pname, "startDate": fields.get("startDate", "2026-03-22")}
    if pm_id: body["projectManager"] = {"id": pm_id}
    if cust_id: body["customer"] = {"id": cust_id}
    if fields.get("isFixedPrice"):
        body["isFixedPrice"] = True
        if fields.get("budget"): body["fixedprice"] = fields["budget"]

    r = tx.post("project", body)
    return not r.get("_error")

# --- PRODUCT: 1 write ---
async def handle_create_product(prompt, tx):
    fields = extract_fields(prompt, "prod", {
        "type": "object",
        "properties": {"name": {"type": "string"}, "number": {"type": "string"},
                       "unitPrice": {"type": "number"}, "vatRate": {"type": "number"}},
        "required": ["name"]
    }, "Extract product fields. vatRate is a number: 25, 15, 12, or 0.")
    name = fields.get("name", "")
    if not name: return False
    s = tx.get("product", params={"name": name, "fields": "id,name"})
    if not s.get("_error") and s.get("values"):
        pid = s["values"][0]["id"]
        u = {"id": pid, "name": name}
        if fields.get("number"): u["number"] = str(fields["number"])
        if fields.get("unitPrice"): u["priceExcludingVatCurrency"] = float(fields["unitPrice"])
        tx.put(f"product/{pid}", u)  # 1 write
        return True
    body = {"name": name}
    if fields.get("number"): body["number"] = str(fields["number"])
    if fields.get("unitPrice"): body["priceExcludingVatCurrency"] = float(fields["unitPrice"])
    # Skip vatType — sandbox IDs differ, causes 422
    r = tx.post("product", body)
    return not r.get("_error")  # 1 write

# --- REGISTER PAYMENT: 1 write ---
async def handle_register_payment(prompt, tx):
    fields = extract_fields(prompt, "pay", {
        "type": "object",
        "properties": {"customerName": {"type": "string"}, "amount": {"type": "number"}},
        "required": ["customerName"]
    }, "Extract payment fields. customerName required. amount optional (default=full).")
    cn = fields.get("customerName", "")
    if not cn: return False
    c = tx.get("customer", params={"name": cn, "fields": "id"})
    if c.get("_error") or not c.get("values"): return False
    cid = c["values"][0]["id"]
    invs = tx.get("invoice", params={"customerId": cid, "invoiceDateFrom": "2020-01-01",
                  "invoiceDateTo": "2030-01-01", "fields": "id,amount,amountOutstanding"})
    if invs.get("_error") or not invs.get("values"): return False
    inv = next((i for i in invs["values"] if i.get("amountOutstanding", 0) > 0), None)
    if not inv: return True  # 0 writes
    amt = fields.get("amount", inv["amountOutstanding"])
    ptid = await get_payment_type(tx)
    if not ptid: return False
    # 1 write
    r = tx.put(f"invoice/{inv['id']}/:payment?paymentDate=2026-03-21&paymentTypeId={ptid}&paidAmount={amt}", {})
    return not r.get("_error")

# --- INVOICE: Minimum writes = customer + product + order + orderline + invoice ---
# That's 5 writes minimum (if all new), but search existing to reduce
async def handle_create_invoice(prompt, tx):
    fields = extract_fields(prompt, "inv", {
        "type": "object",
        "properties": {
            "customerName": {"type": "string"},
            "lines": {"type": "array", "items": {"type": "object", "properties": {
                "productName": {"type": "string"}, "quantity": {"type": "number"},
                "unitPrice": {"type": "number"}, "vatRate": {"type": "number"},
                "productNumber": {"type": "string"}
            }}},
            "withPayment": {"type": "boolean"},
            "invoiceDate": {"type": "string"}, "dueDate": {"type": "string"},
            "organizationNumber": {"type": "string"},
            "sendInvoice": {"type": "boolean"}
        }, "required": ["customerName"]
    }, "Extract invoice fields. lines=products with quantity/price. withPayment=true if payment needed. sendInvoice defaults to true.")

    today = "2026-03-21"
    cust_name = fields.get("customerName", "Kunde")

    # GET free — find customer
    cs = tx.get("customer", params={"name": cust_name, "fields": "id"})
    if not cs.get("_error") and cs.get("values"):
        cust_id = cs["values"][0]["id"]  # 0 writes
    else:
        # 1 write
        body = {"name": cust_name, "isCustomer": True}
        if fields.get("organizationNumber"): body["organizationNumber"] = str(fields["organizationNumber"])
        cr = tx.post("customer", body)
        if cr.get("_error"): return False
        cust_id = cr["value"]["id"]

    lines = fields.get("lines", [{"productName": "Produkt", "quantity": 1, "unitPrice": 0}])

    # Find/create products — GET free
    for line in lines:
        pname = line.get("productName", "Produkt")
        ps = tx.get("product", params={"name": pname, "fields": "id"})
        if not ps.get("_error") and ps.get("values"):
            line["_pid"] = ps["values"][0]["id"]  # 0 writes
        else:
            # 1 write — DON'T set vatType (sandbox IDs differ!)
            pbody = {"name": pname}
            if line.get("productNumber"): pbody["number"] = str(line["productNumber"])
            if line.get("unitPrice"): pbody["priceExcludingVatCurrency"] = float(line["unitPrice"])
            pr = tx.post("product", pbody)
            line["_pid"] = pr["value"]["id"] if not pr.get("_error") else None

    # 1 write: order
    order = tx.post("order", {"customer": {"id": cust_id},
                              "deliveryDate": fields.get("invoiceDate", today),
                              "orderDate": fields.get("invoiceDate", today)})
    if order.get("_error"): return False
    oid = order["value"]["id"]

    # 1 write per line: orderlines
    for line in lines:
        if not line.get("_pid"): continue
        tx.post("order/orderline", {"order": {"id": oid}, "product": {"id": line["_pid"]},
                "count": line.get("quantity", 1),
                "unitPriceExcludingVatCurrency": line.get("unitPrice", 0)})

    # 1 write: invoice
    inv = tx.post("invoice", {"invoiceDate": fields.get("invoiceDate", today),
                               "invoiceDueDate": fields.get("dueDate", "2026-04-21"),
                               "orders": [{"id": oid}]})
    if inv.get("_error"): return False
    inv_id = inv["value"]["id"]

    # 1 write: send (only if needed — skip to save writes if not asked)
    should_send = fields.get("sendInvoice", True)
    if should_send:
        tx.put(f"invoice/{inv_id}/:send?sendType=EMAIL", {})

    # Payment if requested
    if fields.get("withPayment"):
        ptid = await get_payment_type(tx)
        if ptid:
            inv_data = tx.get(f"invoice/{inv_id}", params={"fields": "id,amount,amountOutstanding"})
            if not inv_data.get("_error"):
                amt = inv_data.get("value", {}).get("amountOutstanding",
                      inv_data.get("value", {}).get("amount", 0))
                if amt:
                    # 1 write: payment
                    tx.put(f"invoice/{inv_id}/:payment?paymentDate={today}&paymentTypeId={ptid}&paidAmount={amt}", {})
    return True

# --- VOUCHER: 1 write (POST voucher) ---
async def handle_create_voucher(prompt, tx):
    fields = extract_fields(prompt, "voucher", {
        "type": "object",
        "properties": {
            "description": {"type": "string"}, "amount": {"type": "number"},
            "amountInclVat": {"type": "boolean"}, "vatRate": {"type": "number"},
            "debitAccount": {"type": "integer"}, "creditAccount": {"type": "integer"},
            "departmentName": {"type": "string"},
            "customerName": {"type": "string"}, "supplierName": {"type": "string"},
            "date": {"type": "string"}
        }, "required": ["description", "amount"]
    }, """Extract voucher/bilag fields.
amountInclVat=true if amount includes VAT (inkl. mva/inkl. MVA/incl. VAT).
vatRate: 25(standard), 15(food), 12(transport), 0(exempt). Default 25 for Norwegian receipts.
Common debit: 6300=kontorrekvisita, 6590=annen driftskostnad, 6800=kontorkost, 6900=telefon, 7100=bil, 7140=reise, 4000=varekost
Common credit: 1920=bank, 2400=leverandørgjeld
If kvittering/receipt: debit=expense, credit=1920
If leverandørfaktura: credit=2400""")

    amount = float(fields.get("amount", 0))
    if not amount: return False
    date = fields.get("date", "2026-03-21")
    desc = fields.get("description", "Bilag")
    debit_num = fields.get("debitAccount", 6300)
    credit_num = fields.get("creditAccount", 1920)
    vat_rate = fields.get("vatRate", 25)
    incl_vat = fields.get("amountInclVat", False)

    # Hardcoded Norwegian MVA
    if vat_rate and vat_rate > 0:
        if incl_vat:
            netto = round(amount / (1 + vat_rate / 100), 2)
            mva = round(amount - netto, 2)
            total = amount
        else:
            netto = amount
            mva = round(amount * vat_rate / 100, 2)
            total = round(netto + mva, 2)
    else:
        netto, mva, total = amount, 0, amount

    # GET free — look up accounts
    debit_id = await get_account_id(tx, debit_num)
    credit_id = await get_account_id(tx, credit_num)
    if not debit_id or not credit_id: return False

    # Department — GET free
    dept_id = None
    dn = fields.get("departmentName", "")
    if dn:
        ds = tx.get("department", params={"name": dn, "fields": "id,name"})
        if not ds.get("_error") and ds.get("values"):
            dept_id = ds["values"][0]["id"]
        else:
            # 1 write only if dept doesn't exist
            dr = tx.post("department", {"name": dn, "departmentNumber": random.randint(300, 9999)})
            if not dr.get("_error"): dept_id = dr["value"]["id"]

    # Customer/supplier refs — GET free
    cust_id, supp_id = None, None
    if fields.get("customerName"):
        c = tx.get("customer", params={"name": fields["customerName"], "fields": "id"})
        if not c.get("_error") and c.get("values"): cust_id = c["values"][0]["id"]
    if fields.get("supplierName"):
        s = tx.get("customer", params={"name": fields["supplierName"], "fields": "id"})
        if not s.get("_error") and s.get("values"): supp_id = s["values"][0]["id"]

    def _p(row, acct_id, amt, cid=None, sid=None, did=None):
        p = {"row": row, "account": {"id": acct_id},
             "amount": amt, "amountCurrency": amt, "amountGross": amt, "amountGrossCurrency": amt,
             "currency": {"id": 1}}
        if cid: p["customer"] = {"id": cid}
        if sid: p["supplier"] = {"id": sid}
        if did: p["department"] = {"id": did}
        return p

    postings = []
    if mva > 0:
        mva_id = await get_account_id(tx, 2710)
        postings.append(_p(1, debit_id, netto,
                        cid=cust_id if debit_num == 1500 else None,
                        sid=supp_id if debit_num == 2400 else None, did=dept_id))
        if mva_id:
            postings.append(_p(2, mva_id, mva))
        postings.append(_p(len(postings)+1, credit_id, -total,
                        cid=cust_id if credit_num == 1500 else None,
                        sid=supp_id if credit_num == 2400 else None))
    else:
        postings.append(_p(1, debit_id, amount,
                        cid=cust_id if debit_num == 1500 else None,
                        sid=supp_id if debit_num == 2400 else None, did=dept_id))
        postings.append(_p(2, credit_id, -amount,
                        cid=cust_id if credit_num == 1500 else None,
                        sid=supp_id if credit_num == 2400 else None))

    # 1 write: POST voucher
    r = tx.post("ledger/voucher", {"date": date, "description": desc, "postings": postings})
    if r.get("_error") and ("mva-kode" in r.get("_body", "").lower() or "vatType" in r.get("_body", "")):
        for p in postings: p.pop("vatType", None)
        r = tx.post("ledger/voucher", {"date": date, "description": desc, "postings": postings})
    return not r.get("_error")

# --- SALARY: 1 write (POST voucher with 5 rows) ---
async def handle_create_salary(prompt, tx):
    fields = extract_fields(prompt, "sal", {
        "type": "object",
        "properties": {"employeeName": {"type": "string"}, "amount": {"type": "number"},
                       "taxRate": {"type": "number"}, "date": {"type": "string"}},
        "required": ["employeeName", "amount"]
    }, "Extract salary fields. amount=gross salary. taxRate default 33%.")
    name = fields.get("employeeName", "")
    amount = float(fields.get("amount", 0))
    if not name or not amount: return False
    tax_rate = fields.get("taxRate", 33) / 100
    date = fields.get("date", "2026-03-22")
    # Validate date format
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(date)):
        date = "2026-03-22"
    tax = round(amount * tax_rate, 2)
    net = round(amount - tax, 2)
    aga = round(amount * 0.141, 2)

    # GET free — all account lookups
    ids = {}
    for num in [5000, 2600, 1920, 5400, 2770]:
        ids[num] = await get_account_id(tx, num)
        if not ids[num]: return False

    def _p(row, acct, amt):
        return {"row": row, "account": {"id": ids[acct]},
                "amount": amt, "amountCurrency": amt, "amountGross": amt, "amountGrossCurrency": amt,
                "currency": {"id": 1}}

    # 1 write: POST voucher
    r = tx.post("ledger/voucher", {
        "date": date, "description": f"Lønn {name}",
        "postings": [_p(1,5000,amount), _p(2,2600,-tax), _p(3,1920,-net), _p(4,5400,aga), _p(5,2770,-aga)]
    })
    return not r.get("_error")

# --- CREDIT NOTE: 1 write ---
async def handle_credit_note(prompt, tx):
    fields = extract_fields(prompt, "cn", {
        "type": "object",
        "properties": {"customerName": {"type": "string"}},
        "required": ["customerName"]
    }, "Extract customer name for credit note.")
    cn = fields.get("customerName", "")
    if not cn: return False
    c = tx.get("customer", params={"name": cn, "fields": "id"})
    if c.get("_error") or not c.get("values"): return False
    cid = c["values"][0]["id"]
    invs = tx.get("invoice", params={"customerId": cid, "invoiceDateFrom": "2020-01-01",
                  "invoiceDateTo": "2030-01-01", "fields": "id,isCreditNote"})
    if invs.get("_error") or not invs.get("values"): return False
    inv = next((i for i in invs["values"] if not i.get("isCreditNote", False)), None)
    if not inv: return False
    # 1 write
    r = tx.put(f"invoice/{inv['id']}/:createCreditNote?date=2026-03-21", {})
    return not r.get("_error")

# --- SEND INVOICE: 1 write ---
async def handle_send_invoice(prompt, tx):
    fields = extract_fields(prompt, "send", {
        "type": "object",
        "properties": {"customerName": {"type": "string"}, "sendType": {"type": "string"}},
        "required": ["customerName"]
    }, "Extract customer name and sendType (EMAIL/EHF). Default EMAIL.")
    cn = fields.get("customerName", "")
    if not cn: return False
    st = fields.get("sendType", "EMAIL").upper()
    c = tx.get("customer", params={"name": cn, "fields": "id"})
    if c.get("_error") or not c.get("values"): return False
    invs = tx.get("invoice", params={"customerId": c["values"][0]["id"],
                  "invoiceDateFrom": "2020-01-01", "invoiceDateTo": "2030-01-01", "fields": "id"})
    if invs.get("_error") or not invs.get("values"): return False
    # 1 write
    return not tx.put(f"invoice/{invs['values'][-1]['id']}/:send?sendType={st}", {}).get("_error")

# --- TRAVEL EXPENSE: 1 write (travelExpense) + N writes (costs) ---
async def handle_travel_expense(prompt, tx):
    fields = extract_fields(prompt, "travel", {
        "type": "object",
        "properties": {
            "employeeName": {"type": "string"}, "title": {"type": "string"},
            "costs": {"type": "array", "items": {"type": "object", "properties": {
                "description": {"type": "string"}, "amount": {"type": "number"}
            }}},
            "perDiem": {"type": "boolean"}, "days": {"type": "number"},
            "dailyRate": {"type": "number"}, "date": {"type": "string"}
        }, "required": ["employeeName"]
    }, "Extract travel expense. costs=array of {description, amount}. perDiem=true if daily allowance.")
    ename = fields.get("employeeName", "")
    if not ename: return False

    # GET free — find employee
    first = ename.split()[0]
    emps = tx.get("employee", params={"firstName": first, "fields": "id,firstName,lastName"})
    emp_id = None
    if not emps.get("_error") and emps.get("values"):
        emp_id = emps["values"][0]["id"]
    if not emp_id and " " in ename:
        parts = ename.split(None, 1)
        dept_id = await get_default_dept(tx)
        if dept_id:
            r = tx.post("employee", {"firstName": parts[0], "lastName": parts[1],
                        "userType": "NO_ACCESS", "department": {"id": dept_id}})
            if not r.get("_error"): emp_id = r["value"]["id"]
    if not emp_id: return False

    # 1 write: create travel expense
    te = tx.post("travelExpense", {"employee": {"id": emp_id},
                 "title": fields.get("title", "Reise"), "date": fields.get("date", "2026-03-21")})
    if te.get("_error"): return False
    te_id = te["value"]["id"]

    # GET free — cost categories (cached)
    cat_map = await get_cost_categories(tx)

    def find_cat(desc):
        dl = desc.lower()
        mappings = {"fly": "fly", "flight": "fly", "taxi": "annen kontorkostnad",
                    "hotel": "hotell", "hotell": "hotell", "buss": "buss",
                    "tog": "kollektivtransport", "train": "kollektivtransport",
                    "parkering": "parkering", "mat": "mat", "food": "mat"}
        for kw, target in mappings.items():
            if kw in dl:
                for cd, cid in cat_map.items():
                    if target in cd: return cid
        return cat_map.get("annen kontorkostnad", list(cat_map.values())[0] if cat_map else 35915266)

    costs = fields.get("costs", [])
    if not costs and fields.get("perDiem"):
        days = fields.get("days", 1)
        rate = fields.get("dailyRate", 800)
        costs.append({"description": "Dagpenger", "amount": float(days) * float(rate)})

    for cost in costs:
        amt = float(cost.get("amount", 0))
        if not amt: continue
        cat_id = find_cat(cost.get("description", ""))
        # 1 write per cost
        tx.post("travelExpense/cost", {"travelExpense": {"id": te_id}, "currency": {"id": 1},
                "costCategory": {"id": cat_id}, "paymentType": {"id": 0},
                "rate": amt, "amountCurrencyIncVat": amt, "date": fields.get("date", "2026-03-21")})

    if fields.get("perDiem") and fields.get("costs"):
        days = fields.get("days", 1)
        rate = fields.get("dailyRate", 800)
        total = float(days) * float(rate)
        cat_id = cat_map.get("mat", find_cat("mat"))
        tx.post("travelExpense/cost", {"travelExpense": {"id": te_id}, "currency": {"id": 1},
                "costCategory": {"id": cat_id}, "paymentType": {"id": 0},
                "rate": total, "amountCurrencyIncVat": total, "date": fields.get("date", "2026-03-21")})
    return True

# --- DEPRECIATION: 1 write ---
async def handle_depreciation(prompt, tx):
    fields = extract_fields(prompt, "depr", {
        "type": "object",
        "properties": {"amount": {"type": "number"}, "description": {"type": "string"},
                       "expenseAccount": {"type": "integer"}, "assetAccount": {"type": "integer"},
                       "date": {"type": "string"}},
        "required": ["amount"]
    }, "Extract depreciation fields. expenseAccount default 6000, assetAccount default 1200.")
    amt = float(fields.get("amount", 0))
    if not amt: return False
    exp_id = await get_account_id(tx, fields.get("expenseAccount", 6000))
    ast_id = await get_account_id(tx, fields.get("assetAccount", 1200))
    if not exp_id or not ast_id: return False
    def _p(row, aid, a):
        return {"row": row, "account": {"id": aid}, "amount": a, "amountCurrency": a,
                "amountGross": a, "amountGrossCurrency": a, "currency": {"id": 1}}
    # 1 write
    r = tx.post("ledger/voucher", {"date": fields.get("date", "2026-03-21"),
                "description": fields.get("description", "Avskrivning"),
                "postings": [_p(1, exp_id, amt), _p(2, ast_id, -amt)]})
    return not r.get("_error")

# --- SUPPLIER PAYMENT: 1 write ---
async def handle_supplier_payment(prompt, tx):
    fields = extract_fields(prompt, "suppay", {
        "type": "object",
        "properties": {"supplierName": {"type": "string"}, "amount": {"type": "number"},
                       "date": {"type": "string"}},
        "required": ["supplierName"]
    }, "Extract supplier payment fields.")
    sn = fields.get("supplierName", "")
    if not sn: return False
    s = tx.get("customer", params={"name": sn, "fields": "id"})
    if s.get("_error") or not s.get("values"): return False
    sid = s["values"][0]["id"]
    amt = float(fields.get("amount", 10000))
    pay_id = await get_account_id(tx, 2400)
    bank_id = await get_account_id(tx, 1920)
    if not pay_id or not bank_id: return False
    def _p(row, aid, a, si=None):
        p = {"row": row, "account": {"id": aid}, "amount": a, "amountCurrency": a,
             "amountGross": a, "amountGrossCurrency": a, "currency": {"id": 1}}
        if si: p["supplier"] = {"id": si}
        return p
    # 1 write
    return not tx.post("ledger/voucher", {"date": fields.get("date", "2026-03-22"),
                "description": f"Leverandørbetaling {sn}",
                "postings": [_p(1, pay_id, amt, si=sid), _p(2, bank_id, -amt)]}).get("_error")

# --- REMINDER FEE / PURREGEBYR ---
async def handle_reminder_fee(prompt, tx):
    fields = extract_fields(prompt, "remind", {
        "type": "object",
        "properties": {
            "customerName": {"type": "string"}, "fee": {"type": "number"},
            "partialPayment": {"type": "number"}, "date": {"type": "string"}
        }, "required": []
    }, "Extract reminder fee fields. fee=reminder amount (default 35). partialPayment=partial payment amount if mentioned. customerName if mentioned.")
    fee = float(fields.get("fee", 35))
    date = fields.get("date", "2026-03-22")

    # Find customer with overdue invoice
    cust_id = None
    cn = fields.get("customerName", "")
    if cn:
        c = tx.get("customer", params={"name": cn, "fields": "id"})
        if not c.get("_error") and c.get("values"): cust_id = c["values"][0]["id"]

    if not cust_id:
        invs = tx.get("invoice", params={"invoiceDateFrom": "2020-01-01", "invoiceDateTo": "2030-01-01",
                       "fields": "id,amount,amountOutstanding,customer(id,name)", "count": 50})
        if not invs.get("_error") and invs.get("values"):
            for inv in invs["values"]:
                if inv.get("amountOutstanding", 0) > 0:
                    cust_id = inv.get("customer", {}).get("id")
                    break
    if not cust_id: return False

    recv_id = await get_account_id(tx, 1500)
    fee_acct = await get_account_id(tx, 3400)
    if not recv_id or not fee_acct: return False

    def _p(row, aid, a, cid=None):
        p = {"row": row, "account": {"id": aid}, "amount": a, "amountCurrency": a,
             "amountGross": a, "amountGrossCurrency": a, "currency": {"id": 1}}
        if cid: p["customer"] = {"id": cid}
        return p

    # 1. Bokfør purregebyr
    tx.post("ledger/voucher", {"date": date, "description": "Purregebyr",
            "postings": [_p(1, recv_id, fee, cid=cust_id), _p(2, fee_acct, -fee)]})

    # 2. Faktura for purregebyret
    ps = tx.get("product", params={"name": "Purregebyr", "fields": "id"})
    if not ps.get("_error") and ps.get("values"):
        pid = ps["values"][0]["id"]
    else:
        pr = tx.post("product", {"name": "Purregebyr", "priceExcludingVatCurrency": fee, "vatType": {"id": 5}})
        pid = pr["value"]["id"] if not pr.get("_error") else None
    if pid:
        o = tx.post("order", {"customer": {"id": cust_id}, "deliveryDate": date, "orderDate": date})
        if not o.get("_error"):
            oid = o["value"]["id"]
            tx.post("order/orderline", {"order": {"id": oid}, "product": {"id": pid},
                    "count": 1, "unitPriceExcludingVatCurrency": fee})
            inv = tx.post("invoice", {"invoiceDate": date, "invoiceDueDate": "2026-04-22", "orders": [{"id": oid}]})
            if not inv.get("_error"):
                tx.put(f"invoice/{inv['value']['id']}/:send?sendType=EMAIL", {})

    # 3. Delbetaling på original faktura
    pp = fields.get("partialPayment", 0)
    if pp and float(pp) > 0:
        invs = tx.get("invoice", params={"customerId": cust_id, "invoiceDateFrom": "2020-01-01",
                      "invoiceDateTo": "2030-01-01", "fields": "id,amountOutstanding"})
        if not invs.get("_error") and invs.get("values"):
            target = next((i for i in invs["values"] if i.get("amountOutstanding", 0) > float(pp)), None)
            if target:
                ptid = await get_payment_type(tx)
                if ptid:
                    tx.put(f"invoice/{target['id']}/:payment?paymentDate={date}&paymentTypeId={ptid}&paidAmount={pp}", {})
    return True

# --- PAYMENT REVERSAL ---
async def handle_payment_reversal(prompt, tx):
    fields = extract_fields(prompt, "rev", {
        "type": "object",
        "properties": {"customerName": {"type": "string"}, "amount": {"type": "number"}, "date": {"type": "string"}},
        "required": ["customerName"]
    }, "Extract customer name and optional amount for payment reversal.")
    cn = fields.get("customerName", "")
    if not cn: return False
    c = tx.get("customer", params={"name": cn, "fields": "id"})
    if c.get("_error") or not c.get("values"): return False
    cust_id = c["values"][0]["id"]

    invs = tx.get("invoice", params={"customerId": cust_id, "invoiceDateFrom": "2020-01-01",
                  "invoiceDateTo": "2030-01-01", "fields": "id,amount,amountOutstanding"})
    if invs.get("_error") or not invs.get("values"): return False
    target = invs["values"][0]
    amt = float(fields.get("amount", target.get("amount", 0) - target.get("amountOutstanding", 0)))
    if not amt: amt = float(target.get("amount", 0))

    recv_id = await get_account_id(tx, 1500)
    bank_id = await get_account_id(tx, 1920)
    if not recv_id or not bank_id: return False

    def _p(row, aid, a, cid=None):
        p = {"row": row, "account": {"id": aid}, "amount": a, "amountCurrency": a,
             "amountGross": a, "amountGrossCurrency": a, "currency": {"id": 1}}
        if cid: p["customer"] = {"id": cid}
        return p

    r = tx.post("ledger/voucher", {"date": fields.get("date", "2026-03-22"),
                "description": f"Reversert betaling {cn}",
                "postings": [_p(1, recv_id, amt, cid=cust_id), _p(2, bank_id, -amt)]})
    return not r.get("_error")

# --- CURRENCY DIFFERENCE ---
async def handle_currency_diff(prompt, tx):
    fields = extract_fields(prompt, "fx", {
        "type": "object",
        "properties": {
            "customerName": {"type": "string"}, "invoiceAmountForeign": {"type": "number"},
            "oldRate": {"type": "number"}, "newRate": {"type": "number"}, "date": {"type": "string"}
        }, "required": ["customerName"]
    }, "Extract: customerName, invoiceAmountForeign (amount in EUR/foreign), oldRate (NOK per unit when invoiced), newRate (NOK per unit when paid).")
    cn = fields.get("customerName", "")
    if not cn: return False
    c = tx.get("customer", params={"name": cn, "fields": "id"})
    if c.get("_error") or not c.get("values"): return False
    cust_id = c["values"][0]["id"]

    foreign = float(fields.get("invoiceAmountForeign", 0))
    old_r = float(fields.get("oldRate", 0))
    new_r = float(fields.get("newRate", 0))
    if not foreign or not old_r or not new_r: return False

    inv_nok = round(foreign * old_r, 2)
    pay_nok = round(foreign * new_r, 2)
    diff = round(pay_nok - inv_nok, 2)

    # Register payment first
    invs = tx.get("invoice", params={"customerId": cust_id, "invoiceDateFrom": "2020-01-01",
                  "invoiceDateTo": "2030-01-01", "fields": "id,amount,amountOutstanding"})
    if not invs.get("_error") and invs.get("values"):
        target = next((i for i in invs["values"] if i.get("amountOutstanding", 0) > 0), None)
        if target:
            ptid = await get_payment_type(tx)
            if ptid:
                tx.put(f"invoice/{target['id']}/:payment?paymentDate=2026-03-22&paymentTypeId={ptid}&paidAmount={target['amountOutstanding']}", {})

    bank_id = await get_account_id(tx, 1920)
    fx_acct = 8060 if diff > 0 else 8160
    fx_id = await get_account_id(tx, fx_acct)
    if not bank_id or not fx_id: return False

    def _p(row, aid, a):
        return {"row": row, "account": {"id": aid}, "amount": a, "amountCurrency": a,
                "amountGross": a, "amountGrossCurrency": a, "currency": {"id": 1}}

    abs_diff = abs(diff)
    if diff > 0:  # Agio
        r = tx.post("ledger/voucher", {"date": "2026-03-22", "description": f"Agio {cn}",
                    "postings": [_p(1, bank_id, abs_diff), _p(2, fx_id, -abs_diff)]})
    else:  # Disagio
        r = tx.post("ledger/voucher", {"date": "2026-03-22", "description": f"Disagio {cn}",
                    "postings": [_p(1, fx_id, abs_diff), _p(2, bank_id, -abs_diff)]})
    return not r.get("_error")

# --- MONTHLY CLOSING ---
async def handle_monthly_closing(prompt, tx):
    fields = extract_fields(prompt, "close", {
        "type": "object",
        "properties": {
            "accrualAmount": {"type": "number"}, "accrualFromAccount": {"type": "integer"},
            "accrualToAccount": {"type": "integer"},
            "depreciationCost": {"type": "number"}, "depreciationLifeYears": {"type": "number"},
            "depreciationAccount": {"type": "integer"}, "assetAccount": {"type": "integer"},
            "date": {"type": "string"}
        }, "required": []
    }, """Extract monthly closing fields:
accrualAmount=monthly accrual amount, accrualFromAccount=prepaid account (1700 or 1720), accrualToAccount=expense account
depreciationCost=asset cost, depreciationLifeYears=useful life years, depreciationAccount=expense (6010/6020), assetAccount=asset (1200/1210)
date=closing date""")
    date = fields.get("date", "2026-03-31")
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(date)): date = "2026-03-31"

    def _p(row, aid, a):
        return {"row": row, "account": {"id": aid}, "amount": a, "amountCurrency": a,
                "amountGross": a, "amountGrossCurrency": a, "currency": {"id": 1}}

    acc_amt = fields.get("accrualAmount")
    if acc_amt:
        from_id = await get_account_id(tx, fields.get("accrualFromAccount", 1700))
        to_id = await get_account_id(tx, fields.get("accrualToAccount", 6800))
        if from_id and to_id:
            tx.post("ledger/voucher", {"date": date, "description": "Periodisering",
                    "postings": [_p(1, to_id, float(acc_amt)), _p(2, from_id, -float(acc_amt))]})

    dep_cost = fields.get("depreciationCost")
    dep_years = fields.get("depreciationLifeYears")
    if dep_cost and dep_years:
        monthly = round(float(dep_cost) / float(dep_years) / 12, 2)
        dep_id = await get_account_id(tx, fields.get("depreciationAccount", 6010))
        ast_id = await get_account_id(tx, fields.get("assetAccount", 1200))
        if dep_id and ast_id:
            tx.post("ledger/voucher", {"date": date, "description": "Månedlig avskrivning",
                    "postings": [_p(1, dep_id, monthly), _p(2, ast_id, -monthly)]})
    return True

# ============================================================
# KEYWORD ROUTER — route to minimum-write handlers
# ============================================================
def route_to_handler(prompt):
    p = prompt.lower().strip()

    # Multi-step: only when conjunction connects ACTIONS
    multi_match = re.search(r'\b(og|and|und)\b.{0,30}\b(opprett|create|registrer|bokfør|send|slett|lag)', p)
    if multi_match:
        # Exception: invoice+payment is ONE handler
        if re.search(r'(faktura|invoice).{0,120}(betal|payment)', p):
            return handle_create_invoice
        return None

    create_words = ["opprett", "create", "lag ", "registrer", "añadir", "criar", "crie ",
                    "erstellen", "créer", "créez", "add ", "nuevo", "nouveau", "new ",
                    "legg til", "registre", "legen sie", "anlegen", "cadastr",
                    "crea ", "crée ", "registe "]
    is_create = any(w in p for w in create_words)

    # === EARLY CATCHES — check complex patterns BEFORE simple entity matching ===

    # BANK RECONCILIATION → LLM (too complex for deterministic)
    if any(w in p for w in ["avstem", "reconcil", "kontoauszug", "relevé bancaire",
                             "extracto bancario", "extrato bancário", "bankutskrift"]):
        return None

    # REMINDER FEE / PURREGEBYR — contains "faktura" but is NOT invoice creation
    if any(w in p for w in ["purregebyr", "reminder fee", "mahngebühr", "cargo por recordatorio",
                             "frais de rappel", "taxa de lembrete", "overdue",
                             "forfalt", "vencida", "vencido", "überfällig"]):
        return handle_reminder_fee

    # PAYMENT REVERSAL — only when payment was RETURNED BY BANK
    # NOT when "reverserer fakturaen" (that's credit note!)
    if any(w in p for w in ["returnert av bank", "zurückgebucht", "returned by",
                             "devuelto por el banco", "retourné par la banque",
                             "devolvido pelo banco", "was returned",
                             "vart returnert", "ble returnert"]):
        return handle_payment_reversal

    # CURRENCY DIFFERENCE — contains "faktura" but is NOT invoice creation
    if any(w in p for w in ["valutadifferanse", "valutakurs", "exchange rate", "wechselkurs",
                             "tipo de cambio", "taux de change", "taxa de câmbio",
                             "agio", "disagio", "diferença cambial", "diferencia de tipo",
                             "nok/eur", "eur/nok", "kursen var", "kursen er",
                             "wechselkurs", "taux était", "taxa era"]):
        return handle_currency_diff

    # MONTHLY CLOSING
    if any(w in p for w in ["månedsavslutning", "monthly closing", "monatsabschluss",
                             "cierre mensual", "clôture mensuelle", "encerramento mensal"]):
        return handle_monthly_closing

    # DIMENSION → LLM (department + voucher combo)
    if any(w in p for w in ["dimensjon", "dimension", "dimensão"]):
        return None

    # ERROR CORRECTION in ledger → LLM
    if any(w in p for w in ["feil i hovedbok", "oppdaget feil", "oppdaga feil",
                             "erreurs dans", "errores en", "erros no", "fehler im",
                             "feil konto", "duplisert bilag", "manglende mva",
                             "discovered errors", "descubierto errores", "découvert des erreurs"]):
        return None  # LLM

    # YEAR-END CLOSING with multiple assets → LLM (needs multi-asset depreciation)
    if any(w in p for w in ["jahresabschluss", "year-end", "årsavslutning", "cierre anual",
                             "clôture annuelle", "encerramento anual"]):
        return None  # LLM handles multi-asset better

    # LEVERANDØRFAKTURA — contains "leverandør" but is NOT supplier creation
    if any(w in p for w in ["leverandorfaktura", "leverandørfaktura", "lieferantenrechnung",
                             "supplier invoice", "factura del proveedor", "fatura do fornecedor",
                             "facture fournisseur", "vorsteuer", "inngående mva",
                             "inngaende mva", "fatura inv-", "rechnung inv-", "factura inv-",
                             "invoice inv-"]):
        return handle_create_voucher

    # ONBOARDING / employment contract → employee, NOT department
    if any(w in p for w in ["onboarding", "tilbudsbrev", "arbeidskontrakt", "employment contract",
                             "contrat de travail", "arbeitsvertrag", "contrato de trabajo",
                             "carta de oferta", "offer letter", "integracao", "incorporacion"]):
        return handle_create_employee

    # TRAVEL EXPENSE — check early (contains "cliente/client" which would match customer)
    if any(w in p for w in ["reise", "travel", "viaje", "viagem", "voyage", "reiseregning",
                             "reiserekning", "note de frais", "nota de gastos", "nota de despesas",
                             "Reisekosten"]):
        return handle_travel_expense

    # TIMESHEET / LOG HOURS — check early (contains "invoice" sometimes)
    if any(w in p for w in ["log hours", "registrer timer", "registre horas", "erfassen sie stunden",
                             "registe horas", "enregistrez les heures"]):
        return None  # LLM for timesheet+invoice combo

    # PROJECT — check early (contains "client/kunde" which would match customer)
    if any(w in p for w in ["prosjekt", "project", "proyecto", "projekt", "projet"]):
        if any(w in p for w in ["lifecycle", "livssyklus", "ciclo de vida", "lebenszyklus"]):
            return None  # LLM
        if any(w in p for w in ["fastpris", "fixedprice", "fixed price", "precio fijo", "preço fixo", "festpreis"]):
            return None  # LLM for fixed price projects
        if is_create:
            return handle_create_project

    # CREDIT NOTE — also catches "reverserer fakturaen" which is credit note, not payment reversal
    if any(w in p for w in ["kreditnota", "credit note", "nota de crédito", "gutschrift", "avoir",
                             "storniert", "stornér", "annuler", "cancel",
                             "reverserer heile", "reverserer hele", "reverses the entire",
                             "reklamert", "reklamation", "complained", "reclamado", "reclamou"]):
        return handle_credit_note

    # EMPLOYEE
    emp_words = ["ansatt", "employee", "empleado", "funcionário", "mitarbeiter", "employé",
                 "tilsett", "tilsatt", "onboarding"]
    if is_create and any(w in p for w in emp_words):
        if not any(w in p for w in ["lønn", "salary", "reise", "travel", "timer", "timesheet"]):
            return handle_create_employee

    # SUPPLIER (before customer)
    supp_words = ["leverandør", "supplier", "proveedor", "fornecedor", "lieferant", "fournisseur"]
    if any(w in p for w in supp_words):
        if any(w in p for w in ["betal", "payment", "pago", "zahlung"]):
            return handle_supplier_payment
        if not any(w in p for w in ["faktura", "invoice", "bilag", "voucher", "bokfør"]):
            return handle_create_supplier

    # CUSTOMER — exclude if task is really about invoice/order/payment
    if is_create and any(w in p for w in ["kunde", "customer", "cliente", "client"]):
        if not any(w in p for w in ["faktura", "factura", "fatura", "invoice", "rechnung", "facture",
                                     "ordre", "order", "pedido", "commande",
                                     "betal", "payment", "pago", "pagamento", "zahlung",
                                     "timer", "hours", "horas", "stunden"]):
            return handle_create_customer

    # PRODUCT — but NOT if it's a dimension ("Produktlinje" is a dimension name, not a product)
    if is_create and any(w in p for w in ["produkt", "product", "producto", "produto", "produit"]):
        if any(w in p for w in ["dimensjon", "dimension", "produktlinje"]):
            return None  # LLM for dimensions
        if not any(w in p for w in ["faktura", "invoice", "ordre", "order"]):
            return handle_create_product

    # DEPARTMENT — single or multi
    if any(w in p for w in ["avdeling", "department", "departamento", "abteilung", "département"]):
        if any(w in p for w in ["dimensjon", "dimension"]):
            return None  # LLM for dimension+voucher combos
        # Multi?
        if any(w in p for w in ["tre ", "three ", "tres ", "drei ", "trois ",
                                 "fire ", "four ", "fem ", "five ",
                                 '", "', '", "', "und ", " et "]):
            return handle_multi_department
        if is_create:
            return handle_create_department

    # (project already handled above)

    # SEND INVOICE
    if re.search(r'\b(send)\b.{0,30}(faktura|invoice|factura|rechnung)', p):
        return handle_send_invoice

    # PAYMENT — check BEFORE invoice! But NOT if task also requires creating invoice/order
    pay_phrases = ["registrer betaling", "register payment", "registrar pago",
                   "innbetaling", "betaling på faktura", "register full payment",
                   "registrer full betaling", "registe o pagamento",
                   "registrer delbetaling", "partial payment", "pagamento total"]
    if any(w in p for w in pay_phrases):
        # If also mentions order/invoice creation → use invoice handler (handles payment too)
        if any(w in p for w in ["opprett", "create", "erstell", "créer", "lag ", "crie",
                                "pedido", "ordre", "order", "converta", "fatura", "faktura"]):
            return handle_create_invoice
        return handle_register_payment

    # INVOICE / FAKTURA
    if any(w in p for w in ["faktura", "invoice", "factura", "fatura", "rechnung", "facture"]):
        if not any(w in p for w in ["kredit", "credit", "kreditnota", "slett", "delete"]):
            return handle_create_invoice

    # DEPRECIATION
    if any(w in p for w in ["avskriv", "depreci", "amortis", "abschreib"]):
        return handle_depreciation

    # SALARY
    if any(w in p for w in ["lønn", "salary", "salario", "gehalt", "salaire", "lønnsslipp", "payslip"]):
        return handle_create_salary

    # (travel already handled above)

    # VOUCHER / BILAG / KVITTERING — but NOT error correction ("feil i bilag")
    if any(w in p for w in ["kvittering", "receipt", "bokfør", "bokfor",
                             "kontorrekvisita", "driftskostnad"]):
        return handle_create_voucher
    # "bilag" only if it's about CREATING one, not finding errors
    if "bilag" in p and not any(w in p for w in ["feil", "error", "feilene", "duplisert"]):
        return handle_create_voucher

    return None

# ============================================================
# LLM AGENT — fallback with efficiency awareness
# ============================================================
LLM_SYSTEM = """Du er en Tripletex regnskapsagent. EFFICIENCY ER KRITISK.

=== SCORING ===
- GET er GRATIS — les alt du trenger!
- Kun POST/PUT/DELETE telles som "write calls"
- Færre writes + null feil = efficiency bonus som DOBLER scoren
- SØK ALLTID med GET først, opprett KUN hvis ikke funnet

=== REGLER ===
1. SØK FØR OPPRETTELSE (GET er gratis!)
2. Inkluder ALLE felt i POST direkte — unngå POST + PUT
3. Bruk ID fra POST-respons, aldri GET etter opprettelse
4. Action-params i URL: /:payment?paymentDate=X&paymentTypeId=Y&paidAmount=Z
5. Kall 'done' når ferdig

=== API ===
EMPLOYEE: POST /employee {"firstName","lastName","userType":"NO_ACCESS","department":{"id":X}}
CUSTOMER: POST /customer {"name","isCustomer":true,"email":"x","organizationNumber":"y"}
SUPPLIER: POST /customer {"name","isSupplier":true,"isCustomer":false}
PRODUCT: POST /product {"name","number":"X","priceExcludingVatCurrency":N,"vatType":{"id":3}}
  vatType: 3=25%, 31=15%, 33=12%, 5=0%
DEPARTMENT: POST /department {"name","departmentNumber":RANDOM_300+} SØK FØRST!
PROJECT: POST /project {"name","projectManager":{"id":X},"startDate":"2026-03-21"}
ORDER: POST /order {"customer":{"id":X},"deliveryDate":"2026-03-21","orderDate":"2026-03-21"}
ORDERLINE: POST /order/orderline {"order":{"id":X},"product":{"id":Y},"count":N,"unitPriceExcludingVatCurrency":P}
INVOICE: POST /invoice {"invoiceDate":"2026-03-21","invoiceDueDate":"2026-04-21","orders":[{"id":X}]}
SEND: PUT /invoice/{id}/:send?sendType=EMAIL
CREDITNOTE: PUT /invoice/{id}/:createCreditNote?date=2026-03-21
PAYMENT: GET /invoice/paymentType → PUT /invoice/{id}/:payment?paymentDate=2026-03-21&paymentTypeId=X&paidAmount=Y

VOUCHER: POST /ledger/voucher {"date":"2026-03-21","description":"X","postings":[...]}
  row starts at 1! Positive=debet, negative=kredit.
  1500 KREVER customer-ref, 2400 KREVER supplier-ref.
  Posting: {"row":N,"account":{"id":X},"amount":Y,"amountCurrency":Y,"amountGross":Y,"amountGrossCurrency":Y,"currency":{"id":1}}

KONTOPLAN: 1200=Driftsmidler, 1500=Kundefordringer, 1920=Bank, 2400=Leverandørgjeld,
2600=Skattetrekk, 2710=Inng.MVA, 2770=AGA skyldig, 3000=Salg,
4000=Varekost, 5000=Lønn, 5400=AGA, 6000=Avskrivning, 6300=Kontorrekvisita

LØNN: Voucher 5 poster: D5000(brutto), K2600(-skatt33%), K1920(-netto), D5400(AGA14.1%), K2770(-AGA)
AVSKRIVNING: D6000, K1200
LEVERANDØRBETALING: D2400(m/supplier), K1920

TRAVEL: POST /travelExpense {"employee":{"id":X},"title":"Y","date":"2026-03-21"} — bruk "date" IKKE "departureDate"!
GET /travelExpense/costCategory?fields=id,description&count=40
POST /travelExpense/cost {"travelExpense":{"id":X},"currency":{"id":1},"costCategory":{"id":Y},"paymentType":{"id":0},"rate":Z,"amountCurrencyIncVat":Z,"date":"2026-03-21"}

TIMESHEET: POST /timesheet/entry {"employee":{"id":X},"project":{"id":Y},"activity":{"id":Z},"date":"2026-03-21","hours":N}
ACTIVITY: GET /activity?isProjectActivity=true&fields=id,name

DIMENSJONER = department + project. /ledger/dimension FINNES IKKE! departmentNumber 300+!

FINNES IKKE: /:createPayment, /:reversePayment, /salary/payslip(403), /company(405)

=== GYLDIGE FELT (KRITISK — bruk KUN disse!) ===
InvoiceDTO gyldige felt: id, invoiceNumber, amount, amountOutstanding, amountExcludingVat, invoiceDate, invoiceDueDate, isCreditNote, customer(id,name)
  IKKE: payments, description, balance, state, amountIncludingVat, sumAmount, sumRemaining
AccountDTO gyldige felt: id, number, name, description, bankAccountNumber
  IKKE: balance, sumAmount, sumAmountCurrency, totalAmount
VoucherDTO gyldige felt: id, date, description, postings(id,account(id,number),amount,amountCurrency)
  VIKTIG: Bruk PARENTESER for nested felt! postings(account(number)) IKKE postings.account.number

=== PÅKREVDE QUERY-PARAMS ===
GET /invoice KREVER: invoiceDateFrom OG invoiceDateTo (bruk 2020-01-01 til 2030-01-01)
GET /ledger/voucher KREVER: dateFrom OG dateTo (bruk 2026-01-01 til 2026-12-31)
BRUK ALLTID "ledger/voucher" IKKE bare "voucher"!

=== VOUCHER BEGRENSNING ===
POST /ledger/voucher feiler ofte med 404 i sandbox. Hvis du får 404 på voucher-POST, STOPP og kall done. Ikke retry — det fungerer ikke. Spar API-kall!

=== DELPOENG-STRATEGI ===
Selv ufullstendige oppgaver gir delpoeng! Gjør ALLTID de første stegene:
- Bank reconciliation: Les CSV, finn kunder/leverandører, match mot fakturaer, registrer betalinger du finner
- Cost analysis: GET /ledger/posting med datofilter, analyser data, opprett prosjekter
- Project lifecycle: Opprett kunde, prosjekt, ansatt — selv uten timer/faktura scorer det delpoeng
- Error correction: Les eksisterende bilag, identifiser feil, korriger det du kan
VIKTIG: Partial score > 0. Gjør det du KAN, kall done, ikke spin på det som er umulig.

FLERSPRÅKLIG: nb,nn,en,es,pt,de,fr. Hvis 403 proxy expired → STOPP, kall done.
"""

LLM_TOOLS = [
    {"name": "tripletex_get", "description": "GET (FREE — no efficiency cost)",
     "input_schema": {"type": "object", "properties": {"endpoint": {"type": "string"}, "params": {"type": "object"}}, "required": ["endpoint"]}},
    {"name": "tripletex_post", "description": "POST (COSTS 1 write — minimize!)",
     "input_schema": {"type": "object", "properties": {"endpoint": {"type": "string"}, "body": {"type": "object"}}, "required": ["endpoint", "body"]}},
    {"name": "tripletex_put", "description": "PUT (COSTS 1 write — minimize! For actions: params in URL, body={})",
     "input_schema": {"type": "object", "properties": {"endpoint": {"type": "string"}, "body": {"type": "object"}, "params": {"type": "object"}}, "required": ["endpoint"]}},
    {"name": "tripletex_delete", "description": "DELETE (COSTS 1 write)",
     "input_schema": {"type": "object", "properties": {"endpoint": {"type": "string"}}, "required": ["endpoint"]}},
    {"name": "done", "description": "Task complete.",
     "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}}
]

async def handle_llm(prompt, files_text, tx):
    t0 = time.time()
    msg = prompt + (f"\n\nVEDLEGG:\n{files_text}" if files_text else "")
    messages = [{"role": "user", "content": msg}]
    for i in range(15):
        if time.time() - t0 > 90:
            log.warning(f"LLM TIMEOUT {time.time()-t0:.0f}s")
            break
        resp = claude.messages.create(model="claude-sonnet-4-20250514", max_tokens=4096, temperature=0,
                                      system=LLM_SYSTEM, tools=LLM_TOOLS, messages=messages)
        results, done = [], False
        for block in resp.content:
            if block.type == "tool_use":
                if block.name == "done":
                    done = True
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": "OK"})
                elif block.name.startswith("tripletex_"):
                    m = block.name.replace("tripletex_", "")
                    inp = block.input
                    if m == "get": r = tx.get(inp["endpoint"], params=inp.get("params"))
                    elif m == "post": r = tx.post(inp["endpoint"], inp.get("body", {}))
                    elif m == "put":
                        ep = inp["endpoint"]
                        pm = inp.get("params", {})
                        if pm:
                            ep = f"{ep}{'&' if '?' in ep else '?'}" + "&".join(f"{k}={v}" for k, v in pm.items())
                        r = tx.put(ep, inp.get("body", {}))
                    elif m == "delete": r = tx.delete(inp["endpoint"])
                    else: r = {"_error": True}
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                   "content": json.dumps(r, ensure_ascii=False)[:3000]})
        if done or not results: break
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": results})
    return True

# ============================================================
# ENDPOINTS
# ============================================================
@app.get("/health")
def health():
    return {"status": "ok", "version": "v5.5"}

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
    reset_cache()  # CRITICAL: each submission has its own sandbox!
    await ensure_bank_account(tx)
    try:
        handler = route_to_handler(prompt)
        if handler:
            hname = handler.__name__
            log.info(f"ROUTE: {hname}")
            success = await handler(prompt, tx)
            if not success:
                log.warning(f"{hname} feilet → LLM")
                await handle_llm(prompt, files_text, tx)
        else:
            log.info("ROUTE: LLM")
            await handle_llm(prompt, files_text, tx)
    except Exception as e:
        log.error(f"FATAL: {e}", exc_info=True)
    s = tx.summary()
    log.info(f"SUMMARY: calls={s['total_calls']} writes={s['writes']} errors={s['errors']} {s['elapsed']}")
    return JSONResponse({"status": "completed"})
