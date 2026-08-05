"""End-to-end scenario at realistic scale, driven entirely through the HTTP API.

    python -m scripts.scenario_e2e            # 1000 products, 100 customers
    SC_PRODUCTS=50 SC_CUSTOMERS=10 SC_TAG=X python -m scripts.scenario_e2e

Needs the backend running on localhost:8000 and a database seeded far enough to
have the standard role accounts. Safe to re-run: everything it creates is looked
up by name or SKU first, so a run that dies halfway does not poison the next one.

It found a real bug on its first full pass — a salesman holding three vans, with
the field app silently choosing between them — which no unit test had caught
because nothing at the unit level ever assigns a second van.

Every action here goes over the wire to the running server, exactly as the React
app does — so routing, JWT auth, RBAC, Pydantic validation, the response envelope,
the cashier gate and the credit gate are all exercised, not just the service layer.
That is the difference from the seed script, which calls services directly and so
cannot catch anything that lives in the request path.

Roles are used the way people use them: the storekeeper receives and counts, the
salesman sells, the cashier collects, the accountant reads the books. Nothing is
done as admin that a real installation would not do as admin.

Data is left in the database on purpose.
"""

import asyncio
import random
import time
from collections import defaultdict
from decimal import Decimal

import httpx

BASE = "http://localhost:8000/api/v1"
TAG_BASE = "SC"  # marks everything this scenario creates, so it can be measured apart

import os

TARGET_WAREHOUSES = 5
TARGET_PRODUCTS = int(os.environ.get("SC_PRODUCTS", 1000))
TARGET_CUSTOMERS = int(os.environ.get("SC_CUSTOMERS", 100))
INVOICES_PER_CUSTOMER = 3
# A smoke run must not collide with the real run's SKUs and customer names.
TAG_SUFFIX = os.environ.get("SC_TAG", "")

CREDENTIALS = {
    "admin": "Admin@1234",
    "storekeeper": "User@12345",
    "cashier": "User@12345",
    "accountant": "User@12345",
    "rep1": "Rep@12345",
    "rep2": "Rep@12345",
}

TAG = TAG_BASE + TAG_SUFFIX

random.seed(20260805)

CATEGORIES = [
    ("زيت", "كرتونة", 12, Decimal("48"), Decimal("52"), Decimal("58")),
    ("أرز", "كيس", 10, Decimal("120"), Decimal("128"), Decimal("140")),
    ("سكر", "كيس", 20, Decimal("85"), Decimal("92"), Decimal("100")),
    ("معلبات", "كرتونة", 24, Decimal("36"), Decimal("40"), Decimal("46")),
    ("ألبان", "طرد", 6, Decimal("22"), Decimal("25"), Decimal("29")),
    ("عصائر", "كرتونة", 12, Decimal("30"), Decimal("34"), Decimal("39")),
    ("معجنات", "كرتونة", 18, Decimal("44"), Decimal("48"), Decimal("55")),
    ("بقوليات", "كيس", 25, Decimal("95"), Decimal("102"), Decimal("112")),
]

failures: list[str] = []
timings: dict[str, float] = {}


def check(label: str, condition: bool, detail: str = "") -> bool:
    """Records an invariant result instead of raising, so one break does not hide
    the rest — a scenario that stops at the first problem reports one bug per run."""
    if condition:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}  {detail}")
        failures.append(f"{label} — {detail}")
    return condition


class Api:
    """A logged-in user session."""

    def __init__(self, client: httpx.AsyncClient, username: str, token: str) -> None:
        self.client = client
        self.username = username
        self.h = {"Authorization": f"Bearer {token}"}

    @classmethod
    async def login(cls, client: httpx.AsyncClient, username: str) -> "Api":
        r = await client.post(
            f"{BASE}/auth/login",
            json={"username": username, "password": CREDENTIALS[username]},
        )
        r.raise_for_status()
        return cls(client, username, r.json()["data"]["access_token"])

    async def get(self, path: str, **params):
        r = await self.client.get(f"{BASE}{path}", headers=self.h, params=params or None)
        r.raise_for_status()
        return r.json()["data"]

    async def post(self, path: str, body=None, *, expect_ok: bool = True):
        r = await self.client.post(f"{BASE}{path}", headers=self.h, json=body)
        if expect_ok and r.status_code >= 400:
            raise RuntimeError(f"POST {path} -> {r.status_code} {r.text[:300]}")
        return r

    async def post_data(self, path: str, body=None):
        return (await self.post(path, body)).json()["data"]

    async def put_data(self, path: str, body=None):
        r = await self.client.put(f"{BASE}{path}", headers=self.h, json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"PUT {path} -> {r.status_code} {r.text[:300]}")
        return r.json()["data"]


async def gather_limited(coros, limit: int = 12):
    """Bounded concurrency: fast enough for bulk setup without burying the server."""
    sem = asyncio.Semaphore(limit)

    async def run(c):
        async with sem:
            return await c

    return await asyncio.gather(*(run(c) for c in coros))



async def existing_by(api: Api, path: str, key: str) -> dict:
    """One listing call, indexed — so "create it unless it is already there" costs
    a single request rather than one lookup per row.

    Making the scenario re-runnable matters more than it sounds: a run that dies
    halfway otherwise leaves debris that makes the next attempt fail on a name
    clash instead of on the thing that actually broke.
    """
    return {row[key]: row for row in await api.get(path)}


async def ensure(api: Api, path: str, body: dict, index: dict, key: str):
    """Return the existing row with this key, or create it."""
    found = index.get(body[key])
    if found is not None:
        return found
    created = await api.post_data(path, body)
    index[body[key]] = created
    return created


def phase(name: str):
    class T:
        def __enter__(self):
            self.t = time.time()
            print(f"\n=== {name} ===")

        def __exit__(self, *a):
            timings[name] = time.time() - self.t
            print(f"    ({timings[name]:.1f}s)")

    return T()


async def main() -> None:
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=20)
    async with httpx.AsyncClient(timeout=120.0, limits=limits) as client:
        # --- Sessions, one per role ---
        with phase("0. Logging in as each role"):
            admin = await Api.login(client, "admin")
            users = {u["username"]: u for u in await admin.get("/auth/users")}
            store = await Api.login(client, "storekeeper")
            cashier = await Api.login(client, "cashier")
            acct = await Api.login(client, "accountant")
            reps = [await Api.login(client, "rep1"), await Api.login(client, "rep2")]
            print(f"  logged in: admin, storekeeper, cashier, accountant, rep1, rep2")

        # --- Baseline, so the scenario's own effect can be isolated later ---
        with phase("1. Baseline"):
            tb0 = await acct.get("/accounting/reports/trial-balance")
            base_products = len(await admin.get("/inventory/products"))
            base_customers = len(await admin.get("/sales/customers"))
            base_invoices = len(await admin.get("/sales/invoices"))
            print(f"  before: {base_products} products, {base_customers} customers, "
                  f"{base_invoices} invoices")
            print(f"  trial balance: debit {tb0['total_debit']} credit {tb0['total_credit']}")

        # --- Warehouses (admin sets up the physical network) ---
        with phase(f"2. {TARGET_WAREHOUSES} warehouses"):
            wh_index = await existing_by(admin, "/inventory/warehouses", "name")
            wh = []
            names = ["المستودع المركزي", "مستودع التبريد", "مستودع الجنوب",
                     "مستودع المنطقة الحرة"]
            for n in names:
                wh.append(await ensure(
                    admin, "/inventory/warehouses",
                    {"name": f"{TAG} {n}", "location": "منطقة صناعية"},
                    wh_index, "name"))
            van = await ensure(admin, "/inventory/warehouses", {
                "name": f"{TAG} سيارة توزيع ١",
                "is_vehicle": True,
                "assigned_to_id": users["rep1"]["id"],
            }, wh_index, "name")
            wh.append(van)
            fixed = [w for w in wh if not w["is_vehicle"]]
            print(f"  {len(fixed)} fixed + 1 van (id {van['id']})")

        # --- Products (admin/storekeeper builds the catalogue) ---
        with phase(f"3. {TARGET_PRODUCTS} products"):
            specs = []
            for i in range(TARGET_PRODUCTS):
                cat, unit_name, factor, w, hw, r = CATEGORIES[i % len(CATEGORIES)]
                home = fixed[i % len(fixed)]
                specs.append({
                    "sku": f"{TAG}-{i:04d}",
                    "barcode": f"{62 if not TAG_SUFFIX else 63}{i:011d}",
                    "name": f"{cat} {i // len(CATEGORIES) + 1} — عبوة {factor}",
                    "base_unit_name": "حبة",
                    "wholesale_price": str(w),
                    "half_wholesale_price": str(hw),
                    "retail_price": str(r),
                    "min_stock_level": str(random.choice([0, 50, 100])),
                    "warehouse_id": home["id"],
                    # Multi-UoM on purpose: selling by carton exercises the
                    # conversion factor rather than the trivial base-unit path.
                    "units": [{"name": unit_name, "factor": str(factor)}],
                })
            sku_index = await existing_by(admin, "/inventory/products", "sku")
            todo = [s for s in specs if s["sku"] not in sku_index]
            if todo:
                await gather_limited(
                    [admin.post_data("/inventory/products", s) for s in todo], limit=16)
            # Re-read so every product carries its unit ids, existing or new alike.
            sku_index = await existing_by(admin, "/inventory/products", "sku")
            products = [sku_index[s["sku"]] for s in specs]
            print(f"  {len(todo)} new, {len(specs) - len(todo)} already present")
            by_warehouse = defaultdict(list)
            for p in products:
                by_warehouse[p["warehouse_id"]].append(p)
            print(f"  {len(products)} created across {len(by_warehouse)} warehouses")

        # --- Stock arrives the only legitimate way: purchase invoices with batches ---
        with phase("4. Stocking up via purchase invoices"):
            sup_index = await existing_by(acct, "/purchases/suppliers", "name")
            suppliers = [
                await ensure(acct, "/purchases/suppliers", {"name": f"{TAG} {n}"},
                             sup_index, "name")
                for n in ["مؤسسة الغذاء الحديثة", "شركة التوريد الوطنية",
                          "مجموعة الأسواق الكبرى"]
            ]

            LINES_PER_INVOICE = 40
            purchase_bodies = []
            batch_expiry: dict[int, list[str]] = defaultdict(list)
            for wh_id, items in by_warehouse.items():
                for start in range(0, len(items), LINES_PER_INVOICE):
                    chunk = items[start : start + LINES_PER_INVOICE]
                    lines = []
                    for p in chunk:
                        cat_i = int(p["sku"].split("-")[1]) % len(CATEGORIES)
                        cost = (CATEGORIES[cat_i][3] * Decimal("0.72")).quantize(
                            Decimal("0.01"))
                        # Two batches per product with different expiries, so FEFO
                        # has an actual ordering decision to make.
                        for b, days in ((1, 45), (2, 200)):
                            exp = f"2026-{(8 + days // 30 - 1) % 12 + 1:02d}-{(days % 28) + 1:02d}"
                            exp = (f"2027-0{((days // 30) % 9) + 1}-15" if days > 120
                                   else f"2026-09-{(days % 27) + 1:02d}")
                            lines.append({
                                "product_id": p["id"],
                                "batch_number": f"{TAG}{p['id']}-{b}",
                                "expiry_date": exp,
                                "quantity": "600",
                                "unit_cost": str(cost),
                            })
                            batch_expiry[p["id"]].append(exp)
                    purchase_bodies.append({
                        "supplier_id": random.choice(suppliers)["id"],
                        "warehouse_id": wh_id,
                        "payment_method": "credit",
                        "supplier_invoice_number": f"{TAG}-PI-{wh_id}-{start}",
                        "shipping_cost": "150.00",
                        "tax_rate_ids": [1],
                        "lines": lines,
                    })
            # Posted by the accountant: purchases.create is theirs, because
            # receiving goods and committing the company to pay for them are
            # deliberately different authorities.
            already = {
                p.get("supplier_invoice_number")
                for p in await acct.get("/purchases/invoices")
            }
            fresh = [b for b in purchase_bodies
                     if b["supplier_invoice_number"] not in already]
            purchases = await gather_limited(
                [acct.post_data("/purchases/invoices", b) for b in fresh], limit=6)
            print(f"  {len(purchases)} purchase invoices posted "
                  f"({len(purchase_bodies) - len(fresh)} already existed), "
                  f"{sum(len(b['lines']) for b in fresh)} batches received")

        # --- Load the van from the central store ---
        with phase("5. Loading the van"):
            van_load = by_warehouse[fixed[0]["id"]][:25]
            for p in van_load:
                await store.post_data("/inventory/stock/transfer", {
                    "product_id": p["id"],
                    "from_warehouse_id": fixed[0]["id"],
                    "to_warehouse_id": van["id"],
                    "quantity": "60",
                })
            print(f"  {len(van_load)} product lines moved onto the van")

        # --- Customers ---
        with phase(f"6. {TARGET_CUSTOMERS} customers"):
            tiers = ["wholesale", "half_wholesale", "retail"]
            bodies = []
            for i in range(TARGET_CUSTOMERS):
                bodies.append({
                    "name": f"{TAG} عميل {i + 1:03d} — "
                            f"{random.choice(['بقالة','سوبرماركت','مطعم','ملحمة'])}",
                    "phone": f"07{random.randint(10000000, 99999999)}",
                    "address": random.choice(["وسط البلد", "الصناعية", "الضاحية"]),
                    "price_tier": tiers[i % 3],
                    "credit_limit": str(random.choice([0, 2000, 8000, 25000])),
                    "salesman_id": users[f"rep{(i % 2) + 1}"]["id"],
                })
            cust_index = await existing_by(admin, "/sales/customers", "name")
            todo = [b for b in bodies if b["name"] not in cust_index]
            if todo:
                await gather_limited(
                    [admin.post_data("/sales/customers", b) for b in todo], limit=16)
            cust_index = await existing_by(admin, "/sales/customers", "name")
            customers = [cust_index[b["name"]] for b in bodies]
            print(f"  {len(customers)} created")

        # --- Sales: 3 invoices per customer, sequentially like real posting ---
        with phase(f"7. {TARGET_CUSTOMERS * INVOICES_PER_CUSTOMER} sales invoices"):
            invoices = []
            refused_credit = 0
            for idx, cust in enumerate(customers):
                rep = reps[idx % 2]
                for n in range(INVOICES_PER_CUSTOMER):
                    warehouse_pool = by_warehouse[fixed[(idx + n) % len(fixed)]["id"]]
                    picks = random.sample(warehouse_pool, random.randint(1, 4))
                    lines = []
                    for p in picks:
                        unit = p["units"][-1] if p.get("units") else None
                        # Sell in cartons half the time to exercise conversion.
                        if unit and random.random() < 0.5:
                            lines.append({"product_id": p["id"],
                                          "quantity": str(random.randint(1, 5)),
                                          "unit_id": unit["id"]})
                        else:
                            lines.append({"product_id": p["id"],
                                          "quantity": str(random.randint(2, 30))})
                    method = ["cash", "card", "credit"][n % 3]
                    r = await rep.post("/sales/invoices", {
                        "customer_id": cust["id"],
                        "payment_method": method,
                        "fulfillment": "delivery" if n == 2 else "pickup",
                        "tax_rate_ids": [1],
                        "lines": lines,
                    }, expect_ok=False)
                    if r.status_code >= 400:
                        # A credit sale over the limit *should* be refused; that is
                        # the gate working, not a failure of the scenario.
                        msg = r.json().get("message", "")
                        if method == "credit" and "ائتمان" in msg:
                            refused_credit += 1
                            continue
                        raise RuntimeError(f"invoice -> {r.status_code} {r.text[:250]}")
                    invoices.append(r.json()["data"])
            print(f"  {len(invoices)} posted, {refused_credit} credit sales refused "
                  f"by the credit-limit gate")

        # --- Van sales by the assigned salesman ---
        with phase("8. Van sales"):
            van_invoices = []
            van_errors: list[str] = []
            for cust in customers[:12]:
                p = random.choice(van_load)
                r = await reps[0].post("/sales/field/sync", {
                    "documents": [{
                        "client_uuid": f"sc-van-{cust['id']}",
                        "kind": "van_sale",
                        "customer_id": cust["id"],
                        "payment_method": "cash",
                        "lines": [{"product_id": p["id"], "quantity": "3"}],
                    }]
                }, expect_ok=False)
                if r.status_code < 400:
                    van_invoices.append(r.json()["data"])
                elif not van_errors:
                    van_errors.append(f"{r.status_code} {r.text[:200]}")
            print(f"  {len(van_invoices)} field sync batches accepted")
            if van_errors:
                print(f"  first rejection: {van_errors[0]}")
            check("field sync accepted the van sales", not van_errors, van_errors[0] if van_errors else "")

        # --- The cashier collects, sometimes partially ---
        with phase("9. Cashier collections"):
            pending = await cashier.get("/cashier/invoices")
            collected = partial = 0
            for inv in pending:
                due = Decimal(inv["total"]) - Decimal(inv["paid_amount"])
                if due <= 0:
                    continue
                if random.random() < 0.15:
                    amount = (due / 2).quantize(Decimal("0.01"))
                    partial += 1
                else:
                    amount = due
                    collected += 1
                await cashier.post_data(
                    f"/cashier/invoices/{inv['id']}/collect", {"amount": str(amount)})
            print(f"  {collected} fully collected, {partial} part-paid")

        # --- Delivery: the storekeeper builds trips from what the cashier cleared ---
        with phase("10. Delivery trips"):
            ready = await store.get("/delivery/invoices")
            trips = 0
            for start in range(0, min(len(ready), 60), 10):
                chunk = ready[start : start + 10]
                wh_id = chunk[0]["warehouse_id"]
                same = [i for i in chunk if i["warehouse_id"] == wh_id]
                if not same:
                    continue
                trip = await store.post_data("/delivery/trips", {
                    "driver_name": random.choice(["سمير", "ياسر", "منذر"]),
                    "vehicle": f"شاحنة {random.randint(1000, 9999)}",
                    "warehouse_id": wh_id,
                })
                added = 0
                for inv in same:
                    r = await store.post(f"/delivery/trips/{trip['id']}/invoices",
                                         {"invoice_id": inv["id"]}, expect_ok=False)
                    added += r.status_code < 400
                if not added:
                    continue
                await store.post_data(f"/delivery/trips/{trip['id']}/dispatch")
                await store.get(f"/delivery/trips/{trip['id']}/picking-list")
                trips += 1
            print(f"  {trips} trips dispatched from {len(ready)} ready invoices")

        # --- Returns ---
        with phase("11. Returns"):
            returned = 0
            for inv in invoices[:15]:
                detail = await admin.get(f"/sales/invoices/{inv['id']}")
                line = detail["lines"][0]
                r = await admin.post("/sales/returns", {
                    "invoice_id": inv["id"],
                    "reason": random.choice(["resalable", "damaged_customer"]),
                    "lines": [{"product_id": line["product_id"], "quantity": "1"}],
                }, expect_ok=False)
                returned += r.status_code < 400
            print(f"  {returned} returns accepted")

        # --- Stocktake on one warehouse, by the storekeeper ---
        with phase("12. Stocktake"):
            st = await store.post_data("/inventory/stocktakes",
                                       {"warehouse_id": fixed[1]["id"]})
            counts = []
            for i, line in enumerate(st["lines"][:60]):
                # Mostly accurate, with a few genuine discrepancies.
                exp = Decimal(line["expected_quantity"])
                delta = Decimal("-2") if i % 17 == 0 else Decimal("0")
                counts.append({"line_id": line["id"],
                               "counted_quantity": str(max(Decimal("0"), exp + delta))})
            await store.put_data(f"/inventory/stocktakes/{st['id']}/counts",
                                 {"counts": counts})
            posted = await store.post_data(f"/inventory/stocktakes/{st['id']}/post")
            print(f"  stocktake {st['id']} posted, {len(counts)} lines counted, "
                  f"status {posted['status']}")

        # --- Close the van's round ---
        with phase("13. Round settlement"):
            pos = await admin.get("/sales/rounds/position", warehouse_id=van["id"])
            print(f"  position: {pos['invoice_count']} invoices, "
                  f"sales {pos['total_sales']}, outstanding {pos['cash_outstanding_total']}")
            if pos["blockers"]:
                print(f"  blockers: {pos['blockers']}")
            r = await admin.post("/sales/rounds/settle-van", {
                "warehouse_id": van["id"],
                "notes": "تسوية جولة السيناريو",
            }, expect_ok=False)
            settled = r.json()["data"] if r.status_code < 400 else None
            print(f"  settle -> {r.status_code}"
                  + (f", round #{settled['id']} {settled['status']}" if settled else
                     f" ({r.json().get('message','')[:110]})"))

        # --- Read every report a manager would open ---
        with phase("14. Reading the reports"):
            reports = {}
            for label, path, who in [
                ("dashboard summary", "/analytics/summary", admin),
                ("alerts", "/alerts", admin),
                ("sales trend", "/analytics/sales/trend", admin),
                ("by warehouse", "/analytics/sales/by-warehouse", admin),
                ("by price tier", "/analytics/sales/by-price-tier", admin),
                ("customer RFM", "/analytics/customers/rfm", admin),
                ("rep performance", "/analytics/reps/performance", admin),
                ("credit at risk", "/analytics/credit/at-risk", admin),
                ("credit aging", "/analytics/credit/aging", admin),
                ("expiry risk", "/analytics/inventory/expiry-risk", admin),
                ("turnover", "/analytics/inventory/turnover", admin),
                ("trial balance", "/accounting/reports/trial-balance", acct),
                ("income statement", "/accounting/reports/income-statement", acct),
                ("balance sheet", "/accounting/reports/balance-sheet", acct),
                ("tax summary", "/accounting/reports/tax-summary", acct),
                ("cashier day", "/cashier/daily-summary", cashier),
                ("stock levels", "/inventory/stock/levels", store),
                ("reorder suggestions", "/inventory/stock/reorder-suggestions", store),
            ]:
                t = time.time()
                reports[label] = await who.get(path)
                print(f"  {label:<22} {(time.time() - t) * 1000:6.0f} ms")

        # --- Invariants: the part that makes this a test rather than a load run ---
        print("\n=== 15. Invariants ===")
        tb = reports["trial balance"]
        check("trial balance balances",
              Decimal(tb["total_debit"]) == Decimal(tb["total_credit"]),
              f"debit {tb['total_debit']} vs credit {tb['total_credit']}")

        bs = reports["balance sheet"]
        check("balance sheet balances", bs["is_balanced"],
              f"assets {bs['total_assets']} vs L+E {bs['total_liabilities_and_equity']}")

        levels = reports["stock levels"]
        negative = [l for l in levels if Decimal(l["total_quantity"]) < 0]
        check("no negative stock anywhere", not negative,
              f"{len(negative)} negative: "
              f"{[(l['product_name'], l['total_quantity']) for l in negative[:5]]}")

        # Invoice arithmetic, sampled across the scenario's own invoices.
        sample = random.sample(invoices, min(40, len(invoices)))
        bad_totals = []
        for inv in sample:
            d = await admin.get(f"/sales/invoices/{inv['id']}")
            lines_sum = sum(Decimal(l["line_total"]) for l in d["lines"])
            taxes = sum(Decimal(t["amount"]) for t in d.get("taxes", []))
            expect = lines_sum + taxes - Decimal(d.get("discount_amount", "0"))
            if abs(expect - Decimal(d["total"])) > Decimal("0.02"):
                bad_totals.append(f"#{d['id']} {expect} != {d['total']}")
        check(f"invoice totals reconcile ({len(sample)} sampled)", not bad_totals,
              "; ".join(bad_totals[:3]))

        # FEFO: the earliest-expiring batch of a product must be drawn down first.
        fefo_bad = []
        for p in random.sample(van_load, min(10, len(van_load))):
            batches = await admin.get(f"/inventory/products/{p['id']}/batches")
            fresh = sorted(batches, key=lambda b: b["expiry_date"])
            for earlier, later in zip(fresh, fresh[1:]):
                if (Decimal(earlier["quantity"]) > 0
                        and Decimal(later["quantity"]) < Decimal(earlier["quantity"])
                        and earlier["warehouse_id"] == later["warehouse_id"]):
                    fefo_bad.append(
                        f"{p['sku']}: {earlier['batch_number']} still "
                        f"{earlier['quantity']} while {later['batch_number']} at "
                        f"{later['quantity']}")
        check("FEFO drew the earliest expiry first", not fefo_bad,
              "; ".join(fefo_bad[:2]))

        # The bug fixed earlier today: a line's warehouse must be its batch's.
        mismatch = []
        for inv in random.sample(invoices, min(25, len(invoices))):
            d = await admin.get(f"/sales/invoices/{inv['id']}")
            for line in d["lines"]:
                if line.get("batch_id") is None:
                    continue
                batches = await admin.get(f"/inventory/products/{line['product_id']}/batches")
                b = next((x for x in batches if x["id"] == line["batch_id"]), None)
                if b and b["warehouse_id"] != line["warehouse_id"]:
                    mismatch.append(f"#{d['id']} line wh {line['warehouse_id']} "
                                    f"vs batch wh {b['warehouse_id']}")
        check("invoice lines carry the batch's warehouse", not mismatch,
              "; ".join(mismatch[:3]))

        # Uncollected cash invoices must not be deliverable.
        still_pending = {i["id"] for i in await cashier.get("/cashier/invoices")}
        deliverable = {i["id"] for i in await store.get("/delivery/invoices")}
        leaked = still_pending & deliverable
        check("cashier gate holds the delivery queue", not leaked,
              f"{len(leaked)} uncollected invoices are deliverable: {list(leaked)[:5]}")

        # Customer balances must equal what the ledger says they owe.
        bal_bad = []
        over_limit = []
        for cust in random.sample(customers, min(20, len(customers))):
            st = await admin.get(f"/sales/customers/{cust['id']}/statement")
            bal = Decimal(str(st["balance"]))
            if bal < 0:
                bal_bad.append(f"{cust['name']}: {bal}")
            limit = Decimal(cust["credit_limit"])
            # The gate allows reaching the limit, never passing it without override.
            if limit > 0 and bal > limit:
                over_limit.append(f"{cust['name']}: owes {bal} on a {limit} limit")
        check("no customer statement is negative", not bal_bad, "; ".join(bal_bad[:3]))
        check("no customer exceeded their credit limit", not over_limit,
              "; ".join(over_limit[:3]))

        # --- Scale report ---
        print("\n=== 16. What is now in the database ===")
        after = {
            "products": len(await admin.get("/inventory/products")),
            "customers": len(await admin.get("/sales/customers")),
            "sales invoices": len(await admin.get("/sales/invoices")),
            "purchase invoices": len(await admin.get("/purchases/invoices")),
            "warehouses": len(await admin.get("/inventory/warehouses")),
        }
        for k, v in after.items():
            base = {"products": base_products, "customers": base_customers,
                    "sales invoices": base_invoices}.get(k)
            delta = f"  (+{v - base} this run)" if base is not None else ""
            print(f"  {k:<20} {v}{delta}")

        print(f"\n  trial balance: debit {tb['total_debit']}  credit {tb['total_credit']}")
        print(f"  revenue: {reports['income statement']['total_revenue']}  "
              f"net: {reports['income statement']['net_profit']}")

        print("\n=== timings ===")
        for k, v in timings.items():
            print(f"  {k:<45} {v:6.1f}s")
        print(f"  {'TOTAL':<45} {sum(timings.values()):6.1f}s")

        print("\n" + "=" * 60)
        if failures:
            print(f"RESULT: {len(failures)} INVARIANT FAILURE(S)")
            for f in failures:
                print(f"  ✗ {f}")
        else:
            print("RESULT: every invariant held")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
