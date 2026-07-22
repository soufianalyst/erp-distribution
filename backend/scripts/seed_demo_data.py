"""One-off script: populates a fresh dev database with 12 months of realistic
wholesale-food-distribution activity for the analytics/RFM dashboard.

Deliberately NOT uniform-random: bakes in Pareto customers, winner/dead-stock
products, seasonal demand, near-expiry batches, and a spread of credit
collection behavior so RFM segmentation and waste/credit reports have real
signal to show. Run against an already-migrated, otherwise-empty database:

    DATABASE_URL=sqlite+aiosqlite:///path/to/dev.db python -m scripts.seed_demo_data
"""

import asyncio
import random
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.api.schemas.auth import UserCreate
from app.api.schemas.delivery import StopStatusUpdate, TripCreate
from app.api.schemas.inventory import ProductCreate, ProductUnitIn, WarehouseCreate
from app.api.schemas.purchases import (
    PurchaseInvoiceCreate,
    PurchaseLineIn,
    SupplierCreate,
)
from app.api.schemas.sales import (
    CustomerCreate,
    CustomerPaymentCreate,
    ReturnLineIn,
    SalesInvoiceCreate,
    SalesLineIn,
    SalesReturnCreate,
)
from app.core.exceptions import AppException
from app.db.session import AsyncSessionLocal
from app.domain.models.accounting import JournalEntry
from app.domain.models.inventory import Product
from app.domain.models.user import User, UserRole
from app.services.auth.auth_service import AuthService
from app.services.delivery.delivery_service import DeliveryService
from app.services.inventory.product_service import ProductService
from app.services.inventory.warehouse_service import WarehouseService
from app.services.purchases.purchase_service import PurchaseService
from app.services.sales.sales_service import SalesService

random.seed(42)

TODAY = date.today()
YEAR_START = TODAY - timedelta(days=365)


def month_start(index: int) -> date:
    """Start date of demo-month `index` (0-based, 0 = 12 months ago)."""
    return YEAR_START + timedelta(days=30 * index)


# --- Catalog definitions -----------------------------------------------------

CATEGORIES = {
    "grains": {
        "warehouse": "الرئيسي",
        "shelf_life_days": (365, 540),
        "price_range": (8, 25),
        "unit": "كيس",
        "alt_unit": ("كرتونة", 12),
        "names": [
            "أرز بسمتي",
            "أرز مصري",
            "سكر أبيض",
            "سكر بني",
            "دقيق فاخر",
            "دقيق أبيض",
            "شعيرية",
            "معكرونة قلم",
            "معكرونة صدفة",
            "عدس أحمر",
            "عدس أصفر",
            "فول مدمس",
            "حمص جاف",
            "برغل",
            "فريكة",
            "طحينة",
            "زيت ذرة",
            "زيت زيتون",
            "خل تفاح",
            "ملح طعام",
        ],
    },
    "dairy_frozen": {
        "warehouse": "مستودع التبريد",
        "shelf_life_days": (90, 180),
        "price_range": (15, 45),
        "unit": "كيلو",
        "alt_unit": None,
        "names": [
            "جبنة بيضاء",
            "جبنة رومي",
            "لبنة",
            "زبادي",
            "زبدة",
            "دجاج مجمد",
            "لحم بقري مجمد",
            "سمك بلطي مجمد",
            "خضار مشكلة مجمدة",
            "بازلاء مجمدة",
            "ذرة مجمدة",
            "كبدة دجاج مجمدة",
            "نقانق",
            "برجر لحم",
            "أجنحة دجاج مجمدة",
        ],
    },
    "cleaning_bev": {
        "warehouse": "مستودع الفرعي",
        "shelf_life_days": (270, 400),
        "price_range": (10, 35),
        "unit": "عبوة",
        "alt_unit": ("كرتونة", 6),
        "names": [
            "منظف أرضيات",
            "صابون سائل",
            "معجون تنظيف",
            "مبيض ملابس",
            "مسحوق غسيل",
            "منعم أقمشة",
            "مياه معدنية",
            "عصير برتقال",
            "عصير مانجو",
            "مشروب غازي",
            "شاي مجروش",
            "قهوة تركية",
            "نسكافيه",
            "كولا",
            "مياه غازية",
        ],
    },
    "misc": {
        "warehouse": "الرئيسي",
        "shelf_life_days": (200, 365),
        "price_range": (5, 20),
        "unit": "علبة",
        "alt_unit": ("كرتونة", 24),
        "names": [
            "طماطم معلبة",
            "فول معلب",
            "تونة معلبة",
            "ذرة معلبة",
            "مربى فراولة",
            "عسل نحل",
            "بسكويت",
            "شوكولاتة",
            "حلاوة طحينية",
            "كاتشب",
        ],
    },
}

SUPPLIERS = {
    "grains": "شركة الأغذية المتحدة",
    "dairy_frozen": "مؤسسة الألبان الذهبية",
    "cleaning_bev": "شركة المنظفات والمشروبات الحديثة",
    "misc": "مؤسسة الوادي للمواد الغذائية",
}

SALES_REPS = ["أحمد المندوب", "سارة المندوبة", "خالد المندوب", "منى المندوبة"]

DRIVERS = ["أبو محمد", "سامي السائق", "ياسر التوصيل"]


def make_products() -> list[dict]:
    """Flat list of product specs with an archetype: winner / steady / dead."""
    products = []
    sku_counter = {}
    for cat_key, cat in CATEGORIES.items():
        for i, name in enumerate(cat["names"]):
            sku_counter[cat_key] = sku_counter.get(cat_key, 0) + 1
            sku = f"{cat_key.upper()[:4]}-{sku_counter[cat_key]:02d}"
            roll = random.random()
            archetype = "winner" if roll < 0.2 else ("dead" if roll < 0.4 else "steady")
            wholesale = Decimal(random.randint(*cat["price_range"]))
            half_wholesale = (wholesale * Decimal("1.07")).quantize(Decimal("0.01"))
            retail = (wholesale * Decimal("1.15")).quantize(Decimal("0.01"))
            products.append(
                {
                    "sku": sku,
                    "name": name,
                    "category": cat_key,
                    "warehouse": cat["warehouse"],
                    "base_unit_name": cat["unit"],
                    "alt_unit": cat["alt_unit"],
                    "wholesale_price": wholesale,
                    "half_wholesale_price": half_wholesale,
                    "retail_price": retail,
                    "shelf_life_days": cat["shelf_life_days"],
                    "archetype": archetype,
                }
            )
    return products


def make_customers() -> list[dict]:
    """50 customers across archetypes that drive RFM segmentation."""
    customers = []

    def add(prefix, count, **kwargs):
        for i in range(count):
            customers.append({"name": f"{prefix} {i + 1}", **kwargs})

    add(
        "سوبرماركت النخبة",
        5,
        archetype="vip",
        price_tier="wholesale",
        credit_limit=Decimal(random.choice([15000, 20000, 25000])),
        active_months=(0, 12),
        monthly_orders=(2, 4),
        collection_rate=0.95,
    )
    add(
        "محلات الوفرة",
        15,
        archetype="steady",
        price_tier="half_wholesale",
        credit_limit=Decimal(random.choice([3000, 5000, 8000])),
        active_months=(0, 12),
        monthly_orders=(0, 2),
        collection_rate=0.80,
    )
    add(
        "بقالة الحي",
        15,
        archetype="occasional",
        price_tier="retail",
        credit_limit=Decimal(random.choice([500, 1000, 2000])),
        active_months=(0, 12),
        monthly_orders=(0, 1),
        collection_rate=0.70,
    )
    add(
        "متجر متعثر",
        8,
        archetype="at_risk",
        price_tier="half_wholesale",
        credit_limit=Decimal(3000),
        active_months=(0, 6),
        monthly_orders=(1, 2),
        collection_rate=0.30,
    )
    add(
        "زبون جديد",
        5,
        archetype="new",
        price_tier="retail",
        credit_limit=Decimal(1500),
        active_months=(10, 12),
        monthly_orders=(1, 3),
        collection_rate=0.60,
    )
    add(
        "عميل متعسر",
        2,
        archetype="delinquent",
        price_tier="half_wholesale",
        credit_limit=Decimal(4000),
        active_months=(0, 8),
        monthly_orders=(1, 2),
        collection_rate=0.05,
    )
    return customers


UNITS_PER_LINE = {
    "grains": (5, 40),
    "dairy_frozen": (3, 25),
    "cleaning_bev": (4, 30),
    "misc": (6, 40),
}


async def patch_invoice_date(session, invoice, target_date: date) -> None:
    invoice.invoice_date = target_date
    result = await session.execute(
        select(JournalEntry).where(
            JournalEntry.reference_type == "sales_invoice",
            JournalEntry.reference_id == invoice.id,
        )
    )
    for entry in result.scalars().all():
        entry.entry_date = target_date
    await session.commit()


async def patch_return_date(session, sales_return, target_date: date) -> None:
    from datetime import datetime, timezone

    sales_return.created_at = datetime.combine(
        target_date, datetime.min.time(), tzinfo=timezone.utc
    )
    result = await session.execute(
        select(JournalEntry).where(
            JournalEntry.reference_type == "sales_return",
            JournalEntry.reference_id == sales_return.id,
        )
    )
    for entry in result.scalars().all():
        entry.entry_date = target_date
    await session.commit()


async def main() -> None:
    async with AsyncSessionLocal() as session:
        admin_result = await session.execute(
            select(User).where(User.role == UserRole.ADMIN).limit(1)
        )
        admin = admin_result.scalar_one_or_none()
        if admin is None:
            raise RuntimeError("No admin user found — start the backend once first.")

        warehouse_service = WarehouseService(session)
        product_service = ProductService(session)
        purchase_service = PurchaseService(session)
        sales_service = SalesService(session)
        delivery_service = DeliveryService(session)
        auth_service = AuthService(session)

        # --- Sales reps ---
        print("Creating sales reps...")
        rep_ids = []
        for i, name in enumerate(SALES_REPS):
            existing = await auth_service._get_by_username(f"rep{i + 1}")
            if existing:
                rep_ids.append(existing.id)
                continue
            user = await auth_service.create_user(
                UserCreate(
                    username=f"rep{i + 1}",
                    full_name=name,
                    password="Rep@12345",
                    role=UserRole.SALES,
                )
            )
            rep_ids.append(user.id)
        print(f"  sales reps created")

        # --- Users for every role ---
        print("Creating role users...")
        role_users = [
            ("storekeeper", "أمين المستودع علي", UserRole.STOREKEEPER),
            ("accountant", "المحاسب محمود", UserRole.ACCOUNTANT),
            ("cashier", "أمين الصندوق كريم", UserRole.CASHIER),
            ("driver", "سائق التوصيل سمير", UserRole.DRIVER),
        ]
        for username, full_name, role in role_users:
            existing = await auth_service._get_by_username(username)
            if not existing:
                await auth_service.create_user(
                    UserCreate(
                        username=username,
                        full_name=full_name,
                        password="User@12345",
                        role=role,
                    )
                )
        print("  role users created")

        # --- Skip demo data if already seeded ---
        product_count = await session.scalar(select(Product).limit(1))
        if product_count is not None:
            print("Demo data already exists — skipping product/invoice generation.")
            print("Done.")
            return

        # --- Users for every role ---
        print("Creating role users...")
        role_users = [
            ("storekeeper", "أمين المستودع علي", UserRole.STOREKEEPER),
            ("accountant", "المحاسب محمود", UserRole.ACCOUNTANT),
            ("cashier", "أمين الصندوق كريم", UserRole.CASHIER),
            ("driver", "سائق التوصيل سمير", UserRole.DRIVER),
        ]
        for username, full_name, role in role_users:
            existing = await auth_service._get_by_username(username)
            if not existing:
                await auth_service.create_user(
                    UserCreate(
                        username=username,
                        full_name=full_name,
                        password="User@12345",
                        role=role,
                    )
                )
        print("  role users created")

        # --- Products ---
        print("Creating products...")
        product_specs = make_products()
        product_records = {}
        for spec in product_specs:
            units = []
            if spec["alt_unit"]:
                units.append(
                    ProductUnitIn(name=spec["alt_unit"][0], factor=spec["alt_unit"][1])
                )
            product = await product_service.create_product(
                ProductCreate(
                    sku=spec["sku"],
                    name=spec["name"],
                    base_unit_name=spec["base_unit_name"],
                    wholesale_price=spec["wholesale_price"],
                    half_wholesale_price=spec["half_wholesale_price"],
                    retail_price=spec["retail_price"],
                    min_stock_level=Decimal(20),
                    warehouse_id=warehouse_ids[spec["warehouse"]],
                    units=units,
                )
            )
            product_records[spec["sku"]] = {"product": product, "spec": spec}
        print(f"  {len(product_records)} products created")

        # --- Suppliers ---
        print("Creating suppliers...")
        supplier_ids = {}
        for cat_key, name in SUPPLIERS.items():
            s = await purchase_service.create_supplier(SupplierCreate(name=name))
            supplier_ids[cat_key] = s.id

        # --- Purchases: restock rounds per category ---
        print("Generating purchase history...")
        batch_counters: dict[str, int] = {}
        near_expiry_skus = random.sample(list(product_records.keys()), 6)
        rounds_per_category = 8
        for cat_key in CATEGORIES:
            cat_products = [
                p for p in product_records.values() if p["spec"]["category"] == cat_key
            ]
            for round_idx in range(rounds_per_category):
                round_date = YEAR_START + timedelta(days=round_idx * 45)
                if round_date > TODAY - timedelta(days=5):
                    continue
                lines = []
                for rec in cat_products:
                    spec = rec["spec"]
                    # Dead stock only gets restocked in the first two rounds.
                    if spec["archetype"] == "dead" and round_idx >= 2:
                        continue
                    sku = spec["sku"]
                    batch_counters[sku] = batch_counters.get(sku, 0) + 1
                    shelf_min, shelf_max = spec["shelf_life_days"]
                    expiry = round_date + timedelta(
                        days=random.randint(shelf_min, shelf_max)
                    )
                    if expiry <= TODAY:
                        expiry = TODAY + timedelta(days=random.randint(60, 120))
                    qty = {
                        "winner": random.randint(300, 500),
                        "steady": random.randint(120, 250),
                        "dead": random.randint(60, 100),
                    }[spec["archetype"]]
                    cost = (spec["wholesale_price"] * Decimal("0.72")).quantize(
                        Decimal("0.0001")
                    ) * Decimal(str(round(random.uniform(0.9, 1.1), 3)))
                    lines.append(
                        PurchaseLineIn(
                            product_id=rec["product"].id,
                            batch_number=f"{sku}-B{batch_counters[sku]}",
                            expiry_date=expiry,
                            quantity=Decimal(qty),
                            unit_cost=cost.quantize(Decimal("0.0001")),
                        )
                    )
                if not lines:
                    continue
                await purchase_service.create_invoice(
                    PurchaseInvoiceCreate(
                        supplier_id=supplier_ids[cat_key],
                        warehouse_id=warehouse_ids[CATEGORIES[cat_key]["warehouse"]],
                        payment_method="credit",
                        invoice_date=round_date,
                        lines=lines,
                    ),
                    created_by=admin.id,
                )

        # Deliberate near-expiry batches (a handful, expiring within the next ~3 weeks).
        print("Injecting near-expiry batches for waste-risk testing...")
        for sku in near_expiry_skus:
            rec = product_records[sku]
            batch_counters[sku] = batch_counters.get(sku, 0) + 1
            await purchase_service.create_invoice(
                PurchaseInvoiceCreate(
                    supplier_id=supplier_ids[rec["spec"]["category"]],
                    warehouse_id=warehouse_ids[rec["spec"]["warehouse"]],
                    payment_method="cash",
                    invoice_date=TODAY - timedelta(days=random.randint(20, 40)),
                    lines=[
                        PurchaseLineIn(
                            product_id=rec["product"].id,
                            batch_number=f"{sku}-EXP",
                            expiry_date=TODAY + timedelta(days=random.randint(4, 20)),
                            quantity=Decimal(random.randint(30, 80)),
                            unit_cost=(
                                rec["spec"]["wholesale_price"] * Decimal("0.72")
                            ).quantize(Decimal("0.0001")),
                        )
                    ],
                ),
                created_by=admin.id,
            )

        # --- Customers ---
        print("Creating customers...")
        customer_specs = make_customers()
        customer_records = []
        for spec in customer_specs:
            rep_id = random.choice(rep_ids)
            customer = await sales_service.create_customer(
                CustomerCreate(
                    name=spec["name"],
                    phone=f"07{random.randint(70000000, 99999999)}",
                    price_tier=spec["price_tier"],
                    credit_limit=spec["credit_limit"],
                    salesman_id=rep_id,
                )
            )
            customer_records.append({"customer": customer, "spec": spec})
        print(f"  {len(customer_records)} customers created")

        # --- Sales invoices ---
        print("Generating sales invoices (this takes a while)...")
        winners = [
            r for r in product_records.values() if r["spec"]["archetype"] == "winner"
        ]
        steady = [
            r for r in product_records.values() if r["spec"]["archetype"] == "steady"
        ]
        dead = [r for r in product_records.values() if r["spec"]["archetype"] == "dead"]

        created_invoices: list[dict] = []
        invoice_count = 0
        for month_idx in range(12):
            m_start = month_start(month_idx)
            seasonal_boost = 1.4 if month_idx in (5, 6, 10, 11) else 1.0

            for rec in customer_records:
                spec = rec["spec"]
                active_from, active_to = spec["active_months"]
                if not (active_from <= month_idx < active_to):
                    continue
                min_o, max_o = spec["monthly_orders"]
                count = round(random.randint(min_o, max_o) * seasonal_boost)
                for _ in range(count):
                    day_offset = random.randint(0, 27)
                    invoice_date = m_start + timedelta(days=day_offset)
                    if invoice_date > TODAY:
                        continue

                    pool = winners * 5 + steady * 2
                    if month_idx < 3:
                        pool += dead
                    # Real orders are mostly single-category (dry goods, or frozen,
                    # or cleaning) so most invoices stay single-warehouse and can
                    # ride a delivery trip; ~20% deliberately mix categories.
                    if random.random() > 0.2:
                        same_cat = random.choice(list(CATEGORIES.keys()))
                        cat_pool = [
                            p for p in pool if p["spec"]["category"] == same_cat
                        ]
                        if cat_pool:
                            pool = cat_pool
                    n_lines = random.randint(1, 3)
                    picks = random.sample(pool, min(n_lines, len(pool)))
                    lines = []
                    for pick in picks:
                        cat = pick["spec"]["category"]
                        lo, hi = UNITS_PER_LINE[cat]
                        lines.append(
                            SalesLineIn(
                                product_id=pick["product"].id,
                                quantity=Decimal(random.randint(lo, hi)),
                            )
                        )

                    est_subtotal = sum(
                        (
                            {
                                "wholesale": pick["product"].wholesale_price,
                                "half_wholesale": pick["product"].half_wholesale_price,
                                "retail": pick["product"].retail_price,
                            }[spec["price_tier"]]
                            * line.quantity
                        )
                        for pick, line in zip(picks, lines)
                    )
                    payment_method = "credit" if random.random() < 0.65 else "cash"
                    if payment_method == "credit":
                        balance = await sales_service.customer_balance(
                            rec["customer"].id
                        )
                        est_total = est_subtotal * Decimal("1.16")
                        if balance + est_total > spec["credit_limit"]:
                            payment_method = "cash"

                    fulfillment = "delivery" if random.random() < 0.7 else "pickup"

                    try:
                        invoice = await sales_service.create_invoice(
                            SalesInvoiceCreate(
                                customer_id=rec["customer"].id,
                                payment_method=payment_method,
                                fulfillment=fulfillment,
                                apply_vat=random.random() > 0.05,
                                lines=lines,
                            ),
                            admin,
                        )
                    except AppException:
                        continue

                    await patch_invoice_date(session, invoice, invoice_date)
                    created_invoices.append(
                        {"invoice": invoice, "date": invoice_date, "customer": rec}
                    )
                    invoice_count += 1
                    if invoice_count % 100 == 0:
                        print(f"  {invoice_count} invoices so far...")

        print(f"Total invoices created: {invoice_count}")

        # --- Returns ---
        print("Generating returns...")
        return_targets = random.sample(
            created_invoices, k=max(1, int(len(created_invoices) * 0.1))
        )
        for entry in return_targets:
            invoice = entry["invoice"]
            if not invoice.lines:
                continue
            line = random.choice(invoice.lines)
            return_qty = min(line.quantity, Decimal(random.randint(1, 3)))
            if return_qty <= 0:
                continue
            reason = (
                "resellable"
                if random.random() < 0.7
                else random.choice(["damaged_customer", "damaged_transport"])
            )
            try:
                sales_return = await sales_service.create_return(
                    SalesReturnCreate(
                        invoice_id=invoice.id,
                        reason=reason,
                        lines=[
                            ReturnLineIn(
                                product_id=line.product_id, quantity=return_qty
                            )
                        ],
                    ),
                    admin,
                )
            except AppException:
                continue
            return_date = min(
                entry["date"] + timedelta(days=random.randint(1, 10)), TODAY
            )
            await patch_return_date(session, sales_return, return_date)

        # --- Customer payments (collection behavior) ---
        print("Generating customer payments...")
        for rec in customer_records:
            spec = rec["spec"]
            customer = rec["customer"]
            balance = await sales_service.customer_balance(customer.id)
            if balance <= 0:
                continue
            target_payment = balance * Decimal(str(spec["collection_rate"]))
            installments = random.randint(1, 3)
            for i in range(installments):
                current_balance = await sales_service.customer_balance(customer.id)
                if current_balance <= 0:
                    break
                chunk = min(target_payment / installments, current_balance)
                if chunk <= 0:
                    continue
                pay_date = TODAY - timedelta(days=random.randint(1, 60))
                await sales_service.create_payment(
                    CustomerPaymentCreate(
                        customer_id=customer.id,
                        amount=chunk.quantize(Decimal("0.01")),
                        payment_date=pay_date,
                        method=random.choice(["cash", "bank"]),
                    ),
                    admin,
                )

        # --- Delivery: group delivery-fulfillment invoices into trips ---
        print("Generating delivery trips...")
        by_warehouse_week: dict[tuple, list] = {}
        for entry in created_invoices:
            invoice = entry["invoice"]
            if invoice.fulfillment.value != "delivery" or invoice.warehouse_id is None:
                continue
            week = entry["date"].isocalendar()[1]
            key = (invoice.warehouse_id, week)
            by_warehouse_week.setdefault(key, []).append(entry)

        trip_count = 0
        MAX_STOPS_PER_TRIP = 12
        for (wh_id, _week), entries in by_warehouse_week.items():
            # Split a busy warehouse-week into as many trips as needed — every
            # delivery invoice must ride a trip, none silently left behind.
            for chunk_start in range(0, len(entries), MAX_STOPS_PER_TRIP):
                chunk = entries[chunk_start : chunk_start + MAX_STOPS_PER_TRIP]
                trip_date = min(e["date"] for e in chunk)
                trip = await delivery_service.create_trip(
                    TripCreate(
                        driver_name=random.choice(DRIVERS),
                        vehicle=f"شاحنة {random.randint(1000, 9999)}",
                        warehouse_id=wh_id,
                        trip_date=trip_date,
                    ),
                    created_by=admin.id,
                )
                for e in chunk:
                    try:
                        trip = await delivery_service.add_invoice(
                            trip.id, e["invoice"].id
                        )
                    except AppException:
                        continue
                stop_ids = [s.id for s in trip.stops]
                if not stop_ids:
                    continue
                trip = await delivery_service.dispatch_trip(trip.id)
                for stop_id in stop_ids:
                    status = "delivered" if random.random() < 0.9 else "failed"
                    await delivery_service.update_stop_status(
                        trip.id, stop_id, StopStatusUpdate(status=status)
                    )
                await delivery_service.complete_trip(trip.id)
                trip_count += 1
        print(f"  {trip_count} delivery trips created")

        # --- Pickup handovers ---
        print("Handing over pickup invoices...")
        pickup_count = 0
        for entry in created_invoices:
            invoice = entry["invoice"]
            if invoice.fulfillment.value != "pickup":
                continue
            if random.random() < 0.8:
                try:
                    await sales_service.mark_picked_up(invoice.id)
                    pickup_count += 1
                except AppException:
                    continue
        print(f"  {pickup_count} pickups handed over")

        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
