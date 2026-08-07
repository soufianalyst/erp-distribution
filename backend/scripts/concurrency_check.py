"""Does concurrent invoicing corrupt stock? A controlled experiment, not an opinion.

Each test creates a brand-new product with an exactly known quantity in one batch,
fires simultaneous invoice posts at it over HTTP, then compares three numbers that
must agree:

    opening stock  -  units actually sold  ==  closing stock

Any gap is stock the system has lost track of. A negative closing stock is an
oversell; a closing stock higher than it should be is silent inventory inflation,
which is worse — nothing fails, and the shelf quietly disagrees with the screen
until someone counts.

    cd backend && python -m scripts.concurrency_check

Needs a real PostgreSQL and a running server on localhost:8000. The pytest suite
CANNOT cover this: it runs on in-memory SQLite behind a StaticPool, one shared
connection, so two transactions never overlap — which is exactly why 390 passing
tests never caught the bug this script found.

On an unfixed build it reports, reproducibly: 120 units sold out of 100, four
different customers each sold the same single unit, and 100 units vanishing from a
200-unit batch under twelve simultaneous sales. Run it after touching anything in
the stock allocation path.

Observes only — it changes no application code.
"""

import asyncio
import sys
from decimal import Decimal

import httpx

BASE = "http://localhost:8000/api/v1"
PW = {"admin": "Admin@1234", "rep1": "Rep@12345", "rep2": "Rep@12345",
      "rep3": "Rep@12345", "rep4": "Rep@12345"}

results: list[tuple[str, bool, str]] = []


def verdict(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"\n  {'PASS' if ok else 'FAIL'}: {name}")
    print(f"        {detail}")


async def token(c: httpx.AsyncClient, user: str) -> dict:
    r = await c.post(f"{BASE}/auth/login", json={"username": user, "password": PW[user]})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


class Fixture:
    """A product with a single batch of exactly `qty` units, and customers with
    unlimited credit so nothing but stock can refuse a sale."""

    def __init__(self, c, admin):
        self.c, self.admin = c, admin

    async def warehouse(self, name):
        existing = {w["name"]: w for w in (await self.c.get(
            f"{BASE}/inventory/warehouses", headers=self.admin)).json()["data"]}
        if name in existing:
            return existing[name]["id"]
        r = await self.c.post(f"{BASE}/inventory/warehouses", headers=self.admin,
                              json={"name": name})
        return r.json()["data"]["id"]

    async def product(self, sku, warehouse_id, qty, price="10"):
        r = await self.c.post(f"{BASE}/inventory/products", headers=self.admin, json={
            "sku": sku, "name": f"اختبار التزامن {sku}", "base_unit_name": "حبة",
            "wholesale_price": price, "half_wholesale_price": price,
            "retail_price": price, "warehouse_id": warehouse_id,
        })
        assert r.status_code == 201, r.text
        pid = r.json()["data"]["id"]
        rec = await self.c.post(f"{BASE}/inventory/stock/receive", headers=self.admin, json={
            "product_id": pid, "warehouse_id": warehouse_id,
            "batch_number": f"{sku}-B1", "expiry_date": "2027-12-31",
            "quantity": str(qty), "unit_cost": "5",
        })
        assert rec.status_code in (200, 201), rec.text
        return pid

    async def customer(self, name, salesman_id):
        """Re-used across runs — the experiment must be repeatable, and a second
        run failing on a duplicate name tells us nothing about concurrency."""
        existing = {c["name"]: c for c in (await self.c.get(
            f"{BASE}/sales/customers", headers=self.admin)).json()["data"]}
        if name in existing:
            return existing[name]["id"]
        r = await self.c.post(f"{BASE}/sales/customers", headers=self.admin, json={
            "name": name, "price_tier": "wholesale",
            "credit_limit": "999999", "salesman_id": salesman_id,
        })
        assert r.status_code == 201, r.text
        return r.json()["data"]["id"]

    async def stock_of(self, product_id):
        r = await self.c.get(f"{BASE}/inventory/products/{product_id}/batches",
                             headers=self.admin)
        return sum(Decimal(b["quantity"]) for b in r.json()["data"])


async def sell(c, rep_headers, customer_id, product_id, qty):
    """One invoice post. Returns (ok, sold_units, message)."""
    r = await c.post(f"{BASE}/sales/invoices", headers=rep_headers, json={
        "customer_id": customer_id, "payment_method": "cash",
        "fulfillment": "pickup", "tax_rate_ids": [],
        "lines": [{"product_id": product_id, "quantity": str(qty)}],
    })
    if r.status_code >= 400:
        return False, Decimal("0"), r.json().get("message", r.text[:120])
    return True, Decimal(str(qty)), f"invoice {r.json()['data']['id']}"


async def main() -> None:
    async with httpx.AsyncClient(timeout=120.0,
                                 limits=httpx.Limits(max_connections=30)) as c:
        admin = await token(c, "admin")
        reps = {u: await token(c, u) for u in ("rep1", "rep2", "rep3", "rep4")}
        users = {u["username"]: u for u in
                 (await c.get(f"{BASE}/auth/users", headers=admin)).json()["data"]}
        fx = Fixture(c, admin)
        wh = await fx.warehouse("مستودع اختبار التزامن")

        # Each rep sells to their own customer — the API refuses a salesman
        # invoicing a shop that is not on their round.
        custs = {u: await fx.customer(f"عميل التزامن {u}", users[u]["id"])
                 for u in reps}

        stamp = int(asyncio.get_event_loop().time() * 1000) % 100000

        # ------------------------------------------------------------------
        print("\n" + "=" * 68)
        print("TEST 1 — four reps, ample stock, all sell the same product at once")
        print("=" * 68)
        print("  Nothing should be refused. The question is whether the stock")
        print("  arithmetic survives: 4 x 10 units must leave exactly 60 of 100.")
        pid = await fx.product(f"CC1-{stamp}", wh, 100)
        opening = await fx.stock_of(pid)
        outcomes = await asyncio.gather(*[
            sell(c, reps[u], custs[u], pid, 10) for u in reps])
        sold = sum(o[1] for o in outcomes)
        closing = await fx.stock_of(pid)
        print(f"\n  opening {opening} | sold {sold} | closing {closing} "
              f"| expected {opening - sold}")
        for u, (ok, q, msg) in zip(reps, outcomes):
            print(f"    {u}: {'sold ' + str(q) if ok else 'REFUSED — ' + msg}")
        verdict(
            "concurrent sales of one product keep stock exact",
            closing == opening - sold,
            f"closing {closing}, expected {opening - sold}; "
            f"{'consistent' if closing == opening - sold else f'{closing - (opening - sold)} units unaccounted for'}",
        )

        # ------------------------------------------------------------------
        print("\n" + "=" * 68)
        print("TEST 2 — oversell: four reps want 30 each, only 100 in stock")
        print("=" * 68)
        print("  120 demanded against 100 available. At most three may succeed,")
        print("  and stock must never go below zero.")
        pid2 = await fx.product(f"CC2-{stamp}", wh, 100)
        opening2 = await fx.stock_of(pid2)
        outcomes2 = await asyncio.gather(*[
            sell(c, reps[u], custs[u], pid2, 30) for u in reps])
        sold2 = sum(o[1] for o in outcomes2)
        closing2 = await fx.stock_of(pid2)
        succeeded = sum(1 for o in outcomes2 if o[0])
        print(f"\n  opening {opening2} | sold {sold2} | closing {closing2} "
              f"| {succeeded}/4 succeeded")
        for u, (ok, q, msg) in zip(reps, outcomes2):
            print(f"    {u}: {'sold ' + str(q) if ok else 'REFUSED — ' + msg}")
        verdict("never sells more than exists", sold2 <= opening2,
                f"sold {sold2} out of {opening2} available")
        verdict("stock never goes negative", closing2 >= 0,
                f"closing stock {closing2}")
        verdict("oversell test: stock arithmetic is exact",
                closing2 == opening2 - sold2,
                f"closing {closing2}, expected {opening2 - sold2}")

        # ------------------------------------------------------------------
        print("\n" + "=" * 68)
        print("TEST 3 — the hard case: everyone wants the last unit")
        print("=" * 68)
        print("  1 unit in stock, four reps each ask for it simultaneously.")
        print("  Exactly one must win.")
        pid3 = await fx.product(f"CC3-{stamp}", wh, 1)
        outcomes3 = await asyncio.gather(*[
            sell(c, reps[u], custs[u], pid3, 1) for u in reps])
        winners = sum(1 for o in outcomes3 if o[0])
        closing3 = await fx.stock_of(pid3)
        print(f"\n  winners {winners}/4 | closing stock {closing3}")
        for u, (ok, q, msg) in zip(reps, outcomes3):
            print(f"    {u}: {'WON' if ok else 'refused — ' + msg}")
        verdict("exactly one rep gets the last unit", winners == 1,
                f"{winners} reps were each sold the same single unit"
                if winners != 1 else "one winner, as required")

        # ------------------------------------------------------------------
        print("\n" + "=" * 68)
        print("TEST 4 — different products at once (the everyday case)")
        print("=" * 68)
        pids = [await fx.product(f"CC4-{stamp}-{i}", wh, 50) for i in range(4)]
        outcomes4 = await asyncio.gather(*[
            sell(c, reps[u], custs[u], p, 20) for u, p in zip(reps, pids)])
        bad = []
        for p, (ok, q, msg) in zip(pids, outcomes4):
            left = await fx.stock_of(p)
            if not ok or left != Decimal("30"):
                bad.append(f"product {p}: ok={ok} left={left} ({msg})")
        verdict("reps on different products never interfere", not bad,
                "; ".join(bad) if bad else "all four sold cleanly, 30 left of each")

        # ------------------------------------------------------------------
        print("\n" + "=" * 68)
        print("TEST 5 — heavier contention: 12 simultaneous sales, one product")
        print("=" * 68)
        print("  200 in stock, 12 posts of 10 = 120 demanded. All should succeed")
        print("  and stock must land on exactly 80.")
        pid5 = await fx.product(f"CC5-{stamp}", wh, 200)
        opening5 = await fx.stock_of(pid5)
        reps_cycle = list(reps) * 3
        outcomes5 = await asyncio.gather(*[
            sell(c, reps[u], custs[u], pid5, 10) for u in reps_cycle])
        sold5 = sum(o[1] for o in outcomes5)
        closing5 = await fx.stock_of(pid5)
        refused5 = [o[2] for o in outcomes5 if not o[0]]
        print(f"\n  opening {opening5} | sold {sold5} | closing {closing5} "
              f"| expected {opening5 - sold5} | refused {len(refused5)}")
        if refused5:
            print(f"    first refusal: {refused5[0]}")
        verdict("stock exact under heavier contention",
                closing5 == opening5 - sold5,
                f"closing {closing5}, expected {opening5 - sold5}; "
                f"gap {closing5 - (opening5 - sold5)}")

        # ------------------------------------------------------------------
        # The ledger is the other thing concurrency can break.
        tb = (await c.get(f"{BASE}/accounting/reports/trial-balance",
                          headers=admin)).json()["data"]
        verdict("the ledger still balances after all of this",
                Decimal(tb["total_debit"]) == Decimal(tb["total_credit"]),
                f"debit {tb['total_debit']} credit {tb['total_credit']}")

        print("\n" + "=" * 68)
        failed = [r for r in results if not r[1]]
        print(f"{len(results) - len(failed)}/{len(results)} checks passed")
        for name, _, detail in failed:
            print(f"  FAIL {name}: {detail}")
        print("=" * 68)
        sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
