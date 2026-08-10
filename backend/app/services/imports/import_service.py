"""Loading a legacy system into this one, in one transaction or not at all.

Three rules shape everything here.

**Nothing is written until everything is understood.** The whole upload is parsed,
typed and cross-checked in memory first; a single bad row rejects the file. A
half-loaded customer ledger is far harder to unpick than a rejected spreadsheet,
because nobody can tell afterwards which half arrived.

**History is recorded, not replayed.** Imported invoices post to the ledger, so
receivables and revenue are real, but they never touch stock. Stock comes from the
opening-stock sheet, which is the count on the shelf today; replaying historical
sales against it would deduct goods that left the building years ago.

**The books must be provable.** Every customer sheet carries the balance the old
system says they owe, and the run finishes by comparing that against the balance
this system computes. A migration nobody reconciled is a migration nobody can trust.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.imports import (
    ImportErrorOut,
    ImportReportOut,
    ReconciliationRowOut,
    SheetResultOut,
)
from app.core.exceptions import AppException
from app.domain.models.inventory import Product, ProductBatch, ProductUnit, Warehouse
from app.domain.models.sales import (
    Customer,
    CustomerPayment,
    PriceTier,
    SalesInvoice,
    SalesInvoiceLine,
    SalesInvoiceTax,
    SalesPaymentMethod,
)
from app.domain.models.user import User
from app.services.accounting.accounting_service import (
    ACCOUNTS_RECEIVABLE,
    SALES_DISCOUNT,
    SALES_REVENUE,
    VAT,
    AccountingService,
    cash_or_bank,
)
from app.services.imports import reader
from app.services.imports.spec import SHEETS, SHEETS_BY_NAME, Column, Sheet

TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0")

# Rounding slack when checking a file's own arithmetic. Legacy systems round per
# line; ours rounds the total. One piastre of disagreement is their rounding, not a
# broken export — anything larger is a real inconsistency worth refusing.
TOLERANCE = Decimal("0.01")

# Batch every historical line without one is attached to. Zero quantity and a
# past expiry, so FEFO can never select it: `stock_query.sellable()` requires
# quantity > 0 AND expiry_date > today, and this fails both.
ARCHIVE_BATCH = "LEGACY"


@dataclass
class Issue:
    sheet: str
    row: int | None
    column: str | None
    message: str


@dataclass
class Parsed:
    """Everything read out of the upload, typed, before anything is checked."""

    rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    def add(self, sheet: str, row: int | None, column: str | None, message: str) -> None:
        self.issues.append(Issue(sheet, row, column, message))


class ImportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.accounting = AccountingService(session)

    # --- Entry point ---
    async def run(
        self,
        files: dict[str, bytes],
        *,
        dry_run: bool,
        user: User,
    ) -> ImportReportOut:
        """Validate the upload and, unless this is a dry run, apply it.

        `files` maps an uploaded filename to its bytes: either one .xlsx holding
        every sheet, or one CSV per sheet named after it.
        """
        parsed = self._parse(files)
        if not parsed.rows:
            raise AppException(
                400,
                "لم يُعثر على أي ورقة معروفة في الملفات المرفوعة. "
                "نزّل القالب واستخدم أسماء الأوراق كما هي.",
            )

        await self._validate(parsed)

        counts = {name: len(rows) for name, rows in parsed.rows.items()}
        if parsed.issues:
            return self._report(parsed, counts, applied=False, reconciliation=[])

        if dry_run:
            return self._report(parsed, counts, applied=False, reconciliation=[])

        reconciliation = await self._apply(parsed, user)
        return self._report(parsed, counts, applied=True, reconciliation=reconciliation)

    # --- Reading ---
    def _parse(self, files: dict[str, bytes]) -> Parsed:
        """Filenames to typed rows, collecting every type error as it goes."""
        raw: dict[str, list[dict[str, str]]] = {}
        for filename, content in files.items():
            lower = filename.lower()
            if lower.endswith((".xlsx", ".xlsm")):
                for sheet_name, rows in reader.read_workbook(content).items():
                    if sheet_name in SHEETS_BY_NAME:
                        raw[sheet_name] = rows
            elif lower.endswith(".csv"):
                stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0].strip()
                if stem not in SHEETS_BY_NAME:
                    raise AppException(
                        400,
                        f"اسم الملف «{filename}» غير معروف. "
                        f"الأسماء المقبولة: {'، '.join(SHEETS_BY_NAME)}.",
                    )
                raw[stem] = reader.read_csv(content, stem)
            else:
                raise AppException(
                    400, f"صيغة الملف «{filename}» غير مدعومة. استخدم .xlsx أو .csv."
                )

        parsed = Parsed()
        for sheet in SHEETS:
            if sheet.name not in raw:
                continue
            parsed.rows[sheet.name] = self._type_rows(sheet, raw[sheet.name], parsed)
        return parsed

    def _type_rows(
        self, sheet: Sheet, rows: list[dict[str, str]], parsed: Parsed
    ) -> list[dict[str, Any]]:
        """Convert one sheet's text into typed values, one issue per bad cell."""
        if rows:
            present = set(rows[0])
            missing = [c.name for c in sheet.columns if c.required and c.name not in present]
            if missing:
                parsed.add(
                    sheet.name, None, None,
                    f"أعمدة إلزامية مفقودة: {'، '.join(missing)}. نزّل القالب من جديد.",
                )
                return []

        typed: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            # +2: row 1 is the header, and spreadsheet rows are 1-based. The number
            # reported must be the one the user sees in Excel's gutter.
            line = index + 2
            record: dict[str, Any] = {"__row__": line}
            # A row whose cells are the Arabic column labels is a header someone
            # pasted in — most likely by copying the examples sheet, headings and
            # all. Saying that once beats emitting a type error per column.
            if any(row.get(c.name, "") == c.label for c in sheet.columns):
                parsed.add(
                    sheet.name, line, None,
                    "هذا السطر يحتوي على عناوين وليس بيانات — احذفه قبل الرفع.",
                )
                continue
            for column in sheet.columns:
                value, error = self._cell(column, row.get(column.name, ""))
                if error:
                    parsed.add(sheet.name, line, column.name, error)
                record[column.name] = value
            typed.append(record)
        return typed

    @staticmethod
    def _cell(column: Column, text: str) -> tuple[Any, str | None]:
        text = text.strip()
        if not text:
            if column.required:
                return None, f"«{column.label}» إلزامي ولا يمكن تركه فارغاً."
            return None, None
        if column.kind == "decimal":
            return reader.parse_decimal(text)
        if column.kind == "int":
            return reader.parse_int(text)
        if column.kind == "date":
            return reader.parse_date(text)
        if column.kind == "bool":
            return reader.parse_bool(text)
        if column.kind == "choice":
            if text not in column.choices:
                return None, (
                    f"«{text}» غير مقبول. القيم المسموحة: {'، '.join(column.choices)}."
                )
            return text, None
        return text, None

    # --- Checking ---
    async def _validate(self, parsed: Parsed) -> None:
        """Everything that needs more than one cell to judge."""
        products = parsed.rows.get("products", [])
        stock = parsed.rows.get("opening_stock", [])
        customers = parsed.rows.get("customers", [])
        headers = parsed.rows.get("sales_invoices", [])
        lines = parsed.rows.get("sales_invoice_lines", [])
        payments = parsed.rows.get("customer_payments", [])

        self._reject_duplicates(parsed, "products", products, "sku", "رمز الصنف")
        self._reject_duplicates(parsed, "customers", customers, "name", "اسم العميل")
        self._reject_duplicates(
            parsed, "sales_invoices", headers, "invoice_ref", "رقم الفاتورة"
        )
        self._reject_duplicates(
            parsed, "customer_payments", payments, "payment_ref", "رقم السند"
        )
        self._reject_duplicates(
            parsed, "products", [p for p in products if p.get("barcode")],
            "barcode", "الباركود",
        )

        # A batch is unique per product+warehouse; two rows for the same one would
        # silently overwrite each other rather than add up.
        seen_batches: dict[tuple, int] = {}
        for row in stock:
            key = (row.get("sku"), row.get("warehouse"), row.get("batch_number"))
            if None in key:
                continue
            if key in seen_batches:
                parsed.add(
                    "opening_stock", row["__row__"], "batch_number",
                    f"التشغيلة «{key[2]}» للصنف «{key[0]}» مكررة "
                    f"(وردت أيضاً في السطر {seen_batches[key]}).",
                )
            seen_batches[key] = row["__row__"]

        sku_in_file = {p["sku"] for p in products if p.get("sku")}
        known_skus = sku_in_file | await self._existing(Product.sku)
        for sheet_name, rows in (("opening_stock", stock), ("sales_invoice_lines", lines)):
            for row in rows:
                sku = row.get("sku")
                if sku and sku not in known_skus:
                    parsed.add(
                        sheet_name, row["__row__"], "sku",
                        f"الصنف «{sku}» غير موجود في ورقة الأصناف ولا في النظام.",
                    )

        names_in_file = {c["name"] for c in customers if c.get("name")}
        known_customers = names_in_file | await self._existing(Customer.name)
        for sheet_name, rows in (
            ("sales_invoices", headers), ("customer_payments", payments)
        ):
            for row in rows:
                name = row.get("customer_name")
                if name and name not in known_customers:
                    parsed.add(
                        sheet_name, row["__row__"], "customer_name",
                        f"العميل «{name}» غير موجود في ورقة العملاء ولا في النظام.",
                    )

        usernames = await self._existing(User.username)
        for sheet_name, rows in (("customers", customers), ("sales_invoices", headers)):
            for row in rows:
                username = row.get("salesman_username")
                if username and username not in usernames:
                    parsed.add(
                        sheet_name, row["__row__"], "salesman_username",
                        f"لا يوجد مستخدم باسم «{username}». استخدم اسم المستخدم لا الاسم الكامل.",
                    )

        await self._reject_already_imported(parsed, headers, payments)
        self._check_invoice_arithmetic(parsed, headers, lines)

        for row in stock:
            quantity = row.get("quantity")
            if quantity is not None and quantity < 0:
                parsed.add(
                    "opening_stock", row["__row__"], "quantity",
                    "الكمية لا يمكن أن تكون سالبة.",
                )
        for row in payments:
            amount = row.get("amount")
            if amount is not None and amount <= 0:
                parsed.add(
                    "customer_payments", row["__row__"], "amount",
                    "المبلغ يجب أن يكون أكبر من صفر.",
                )

    def _check_invoice_arithmetic(
        self, parsed: Parsed, headers: list[dict], lines: list[dict]
    ) -> None:
        """The file must agree with itself.

        A header whose subtotal does not match its own lines means the export lost
        something. Importing either figure would be picking one at random and calling
        it the truth, so the file is refused and the user goes back to the source.
        """
        by_ref: dict[str, list[dict]] = defaultdict(list)
        for line in lines:
            if line.get("invoice_ref"):
                by_ref[line["invoice_ref"]].append(line)

        refs = {h["invoice_ref"] for h in headers if h.get("invoice_ref")}
        for line in lines:
            ref = line.get("invoice_ref")
            if ref and ref not in refs:
                parsed.add(
                    "sales_invoice_lines", line["__row__"], "invoice_ref",
                    f"لا يوجد رأس فاتورة بالرقم «{ref}».",
                )

        for header in headers:
            ref = header.get("invoice_ref")
            row = header["__row__"]
            if not ref:
                continue
            invoice_lines = by_ref.get(ref, [])
            if not invoice_lines:
                parsed.add(
                    "sales_invoices", row, "invoice_ref",
                    f"الفاتورة «{ref}» بلا أسطر في ورقة الأسطر.",
                )
                continue

            computed = sum(
                (
                    (line["quantity"] * line["unit_price"]).quantize(TWO_PLACES)
                    for line in invoice_lines
                    if line.get("quantity") is not None and line.get("unit_price") is not None
                ),
                ZERO,
            )
            subtotal = header.get("subtotal") or ZERO
            if abs(computed - subtotal) > TOLERANCE:
                parsed.add(
                    "sales_invoices", row, "subtotal",
                    f"المجموع المكتوب {subtotal} لا يساوي مجموع الأسطر {computed} "
                    f"للفاتورة «{ref}».",
                )

            discount = header.get("discount_amount") or ZERO
            tax = header.get("tax_amount") or ZERO
            total = header.get("total") or ZERO
            expected = subtotal - discount + tax
            if abs(expected - total) > TOLERANCE:
                parsed.add(
                    "sales_invoices", row, "total",
                    f"الإجمالي {total} لا يساوي (المجموع {subtotal} − الخصم {discount} "
                    f"+ الضريبة {tax}) = {expected}.",
                )

            paid = header.get("paid_amount") or ZERO
            if paid < 0:
                parsed.add("sales_invoices", row, "paid_amount", "المدفوع لا يكون سالباً.")
            elif paid - total > TOLERANCE:
                parsed.add(
                    "sales_invoices", row, "paid_amount",
                    f"المدفوع {paid} يتجاوز إجمالي الفاتورة {total}.",
                )

    async def _reject_already_imported(
        self, parsed: Parsed, headers: list[dict], payments: list[dict]
    ) -> None:
        """Re-uploading a file must not double the books."""
        refs = [h["invoice_ref"] for h in headers if h.get("invoice_ref")]
        if refs:
            existing = set(
                (
                    await self.session.execute(
                        select(SalesInvoice.legacy_ref).where(
                            SalesInvoice.legacy_ref.in_(refs)
                        )
                    )
                ).scalars()
            )
            for header in headers:
                if header.get("invoice_ref") in existing:
                    parsed.add(
                        "sales_invoices", header["__row__"], "invoice_ref",
                        f"الفاتورة «{header['invoice_ref']}» مستوردة من قبل. "
                        "احذفها من الملف أو استخدم رقماً مختلفاً.",
                    )

        payment_refs = [p["payment_ref"] for p in payments if p.get("payment_ref")]
        if payment_refs:
            existing = set(
                (
                    await self.session.execute(
                        select(CustomerPayment.legacy_ref).where(
                            CustomerPayment.legacy_ref.in_(payment_refs)
                        )
                    )
                ).scalars()
            )
            for payment in payments:
                if payment.get("payment_ref") in existing:
                    parsed.add(
                        "customer_payments", payment["__row__"], "payment_ref",
                        f"السند «{payment['payment_ref']}» مستورد من قبل.",
                    )

    @staticmethod
    def _reject_duplicates(
        parsed: Parsed, sheet: str, rows: list[dict], key: str, label: str
    ) -> None:
        seen: dict[Any, int] = {}
        for row in rows:
            value = row.get(key)
            if value is None:
                continue
            if value in seen:
                parsed.add(
                    sheet, row["__row__"], key,
                    f"{label} «{value}» مكرر (ورد أيضاً في السطر {seen[value]}).",
                )
            else:
                seen[value] = row["__row__"]

    async def _existing(self, column) -> set[str]:
        return set((await self.session.execute(select(column))).scalars())

    # --- Writing ---
    async def _apply(self, parsed: Parsed, user: User) -> list[ReconciliationRowOut]:
        """Write everything, in dependency order, inside one transaction."""
        warehouses = await self._upsert_warehouses(parsed)
        products = await self._upsert_products(parsed, warehouses)
        await self._upsert_opening_stock(parsed, products, warehouses)
        customers = await self._upsert_customers(parsed)
        await self._create_invoices(parsed, products, customers, warehouses, user)
        await self._create_payments(parsed, customers, user)
        await self.session.commit()
        return await self._reconcile(parsed)

    async def _upsert_warehouses(self, parsed: Parsed) -> dict[str, Warehouse]:
        """Warehouses named anywhere in the upload, created if new.

        Created rather than rejected: a warehouse is a container, and refusing the
        whole import because a store name is new would be pedantry.
        """
        names: set[str] = set()
        for sheet_name in ("products", "opening_stock", "sales_invoices"):
            for row in parsed.rows.get(sheet_name, []):
                if row.get("warehouse"):
                    names.add(row["warehouse"])

        existing = {
            warehouse.name: warehouse
            for warehouse in (
                await self.session.execute(select(Warehouse))
            ).scalars()
        }
        for name in sorted(names - set(existing)):
            warehouse = Warehouse(name=name)
            self.session.add(warehouse)
            existing[name] = warehouse
        await self.session.flush()
        return existing

    async def _upsert_products(
        self, parsed: Parsed, warehouses: dict[str, Warehouse]
    ) -> dict[str, Product]:
        rows = parsed.rows.get("products", [])
        existing = {
            product.sku: product
            for product in (await self.session.execute(select(Product))).scalars()
        }
        for row in rows:
            product = existing.get(row["sku"])
            if product is None:
                product = Product(sku=row["sku"])
                self.session.add(product)
                existing[row["sku"]] = product
            product.name = row["name"]
            product.base_unit_name = row["base_unit_name"]
            product.barcode = row.get("barcode") or None
            product.wholesale_price = row["wholesale_price"]
            product.half_wholesale_price = row["half_wholesale_price"]
            product.retail_price = row["retail_price"]
            product.min_stock_level = row.get("min_stock_level") or ZERO
            if row.get("warehouse"):
                product.warehouse_id = warehouses[row["warehouse"]].id
            product.is_active = row.get("is_active") if row.get("is_active") is not None else True

            await self.session.flush()
            # Units are replaced wholesale rather than merged: a re-import is the
            # user restating the product, and a leftover unit from a previous run
            # would be a conversion factor nobody chose.
            #
            # Deleted by statement rather than through `product.units`, because
            # reaching for the relationship on a freshly added instance triggers a
            # lazy load, which an async session cannot service.
            await self.session.execute(
                sa_delete(ProductUnit).where(ProductUnit.product_id == product.id)
            )
            for name_key, factor_key in (
                ("unit1_name", "unit1_factor"), ("unit2_name", "unit2_factor")
            ):
                name, factor = row.get(name_key), row.get(factor_key)
                if name and factor and factor > 0:
                    self.session.add(
                        ProductUnit(product_id=product.id, name=name, factor=factor)
                    )
        await self.session.flush()
        return existing

    async def _upsert_opening_stock(
        self,
        parsed: Parsed,
        products: dict[str, Product],
        warehouses: dict[str, Warehouse],
    ) -> None:
        """Set what is on the shelf. Not a receipt — an assertion of fact."""
        for row in parsed.rows.get("opening_stock", []):
            product = products[row["sku"]]
            warehouse = warehouses[row["warehouse"]]
            batch = (
                await self.session.execute(
                    select(ProductBatch).where(
                        ProductBatch.product_id == product.id,
                        ProductBatch.warehouse_id == warehouse.id,
                        ProductBatch.batch_number == row["batch_number"],
                    )
                )
            ).scalar_one_or_none()
            if batch is None:
                batch = ProductBatch(
                    product_id=product.id,
                    warehouse_id=warehouse.id,
                    batch_number=row["batch_number"],
                )
                self.session.add(batch)
            batch.expiry_date = row["expiry_date"]
            batch.quantity = row["quantity"]
            batch.unit_cost = row.get("unit_cost")
        await self.session.flush()

    async def _upsert_customers(self, parsed: Parsed) -> dict[str, Customer]:
        rows = parsed.rows.get("customers", [])
        existing = {
            customer.name: customer
            for customer in (await self.session.execute(select(Customer))).scalars()
        }
        salesmen = {
            user.username: user.id
            for user in (await self.session.execute(select(User))).scalars()
        }
        for row in rows:
            customer = existing.get(row["name"])
            if customer is None:
                customer = Customer(name=row["name"])
                self.session.add(customer)
                existing[row["name"]] = customer
            customer.phone = row.get("phone")
            customer.address = row.get("address")
            if row.get("price_tier"):
                customer.price_tier = PriceTier(row["price_tier"])
            customer.credit_limit = row.get("credit_limit") or ZERO
            customer.opening_balance = row.get("opening_balance") or ZERO
            if row.get("salesman_username"):
                customer.salesman_id = salesmen[row["salesman_username"]]
            customer.is_active = row.get("is_active") if row.get("is_active") is not None else True
        await self.session.flush()
        return existing

    async def _archive_batch(
        self, product: Product, warehouse: Warehouse, batch_number: str, expiry
    ) -> ProductBatch:
        """A batch for a historical line to point at.

        `SalesInvoiceLine.batch_id` is NOT NULL, but the lot a sale consumed three
        years ago no longer exists. Rather than loosen the schema — which would cost
        every future invoice its traceability — a placeholder is created holding zero
        units and an expiry in the past, so FEFO cannot reach it from either
        direction. If the batch number does exist (it was named in the opening stock)
        that real row is reused, and deliberately not decremented: today's count is
        already today's count.
        """
        batch = (
            await self.session.execute(
                select(ProductBatch).where(
                    ProductBatch.product_id == product.id,
                    ProductBatch.warehouse_id == warehouse.id,
                    ProductBatch.batch_number == batch_number,
                )
            )
        ).scalar_one_or_none()
        if batch is None:
            batch = ProductBatch(
                product_id=product.id,
                warehouse_id=warehouse.id,
                batch_number=batch_number,
                expiry_date=expiry,
                quantity=ZERO,
                unit_cost=None,
            )
            self.session.add(batch)
            await self.session.flush()
        return batch

    async def _create_invoices(
        self,
        parsed: Parsed,
        products: dict[str, Product],
        customers: dict[str, Customer],
        warehouses: dict[str, Warehouse],
        user: User,
    ) -> None:
        headers = parsed.rows.get("sales_invoices", [])
        if not headers:
            return

        by_ref: dict[str, list[dict]] = defaultdict(list)
        for line in parsed.rows.get("sales_invoice_lines", []):
            by_ref[line["invoice_ref"]].append(line)

        salesmen = {
            u.username: u.id for u in (await self.session.execute(select(User))).scalars()
        }
        fallback_warehouse = next(iter(warehouses.values()), None)

        for header in headers:
            customer = customers[header["customer_name"]]
            warehouse = (
                warehouses.get(header.get("warehouse")) if header.get("warehouse") else None
            ) or fallback_warehouse
            if warehouse is None:
                raise AppException(
                    400, "لا يوجد أي مستودع في النظام لربط الفواتير المستوردة به."
                )

            subtotal = header.get("subtotal") or ZERO
            discount = header.get("discount_amount") or ZERO
            tax = header.get("tax_amount") or ZERO
            total = header.get("total") or ZERO
            paid = header.get("paid_amount") or ZERO
            invoice_date = header["invoice_date"]
            # Historical invoices are settled business. Stamping the confirmation
            # keeps them out of the cashier's queue even before `legacy_ref` filters
            # them, and records a date that matches the document rather than today.
            confirmed_at = datetime.combine(invoice_date, time.min, tzinfo=timezone.utc)

            invoice = SalesInvoice(
                legacy_ref=header["invoice_ref"],
                customer_id=customer.id,
                salesman_id=salesmen.get(header.get("salesman_username") or ""),
                warehouse_id=warehouse.id,
                invoice_date=invoice_date,
                payment_method=SalesPaymentMethod(header["payment_method"]),
                subtotal=subtotal,
                discount_amount=discount,
                vat_amount=tax,
                total=total,
                paid_amount=paid,
                payment_confirmed_at=confirmed_at,
                notes=header.get("notes"),
                created_by=user.id,
            )
            if tax > 0:
                invoice.taxes.append(
                    SalesInvoiceTax(
                        tax_rate_id=None,
                        name=header.get("tax_name") or "ضريبة مستوردة",
                        rate=header.get("tax_rate") or ZERO,
                        amount=tax,
                    )
                )

            for line in by_ref[header["invoice_ref"]]:
                product = products[line["sku"]]
                batch = await self._archive_batch(
                    product,
                    warehouse,
                    line.get("batch_number") or ARCHIVE_BATCH,
                    invoice_date,
                )
                quantity = line["quantity"]
                unit_price = line["unit_price"]
                invoice.lines.append(
                    SalesInvoiceLine(
                        product_id=product.id,
                        batch_id=batch.id,
                        batch_number=batch.batch_number,
                        warehouse_id=warehouse.id,
                        quantity=quantity,
                        unit_price=unit_price,
                        unit_cost=line.get("unit_cost"),
                        line_total=(quantity * unit_price).quantize(TWO_PLACES),
                    )
                )

            self.session.add(invoice)
            await self.session.flush()
            await self._post_invoice(invoice, customer, user)

    async def _post_invoice(
        self, invoice: SalesInvoice, customer: Customer, user: User
    ) -> None:
        """The revenue side of the sale, and the cash if it was settled.

        Cost of goods sold is deliberately not posted. It would credit inventory for
        goods this ledger never debited — no purchase history is imported — and drive
        the inventory account negative by the entire cost of everything ever sold.
        The stock figure comes from the opening-stock sheet instead, and margin
        reporting is unaffected because it reads `SalesInvoiceLine.unit_cost` rather
        than the ledger.
        """
        items = [
            (ACCOUNTS_RECEIVABLE, invoice.total, ZERO),
            (SALES_REVENUE, ZERO, invoice.subtotal),
            (VAT, ZERO, invoice.vat_amount),
        ]
        if invoice.discount_amount > 0:
            items.insert(1, (SALES_DISCOUNT, invoice.discount_amount, ZERO))
        await self.accounting.add_entry_no_commit(
            entry_date=invoice.invoice_date,
            description=(
                f"فاتورة مبيعات مستوردة {invoice.legacy_ref} للعميل ({customer.name})"
            ),
            items=items,
            reference_type="sales_invoice",
            reference_id=invoice.id,
            created_by=user.id,
        )
        if invoice.paid_amount > 0:
            # Without this the ledger shows the whole invoice outstanding while the
            # customer's statement shows it settled, and the two never agree.
            await self.accounting.add_entry_no_commit(
                entry_date=invoice.invoice_date,
                description=f"تحصيل فاتورة مستوردة {invoice.legacy_ref}",
                items=[
                    (cash_or_bank(invoice.payment_method.value), invoice.paid_amount, ZERO),
                    (ACCOUNTS_RECEIVABLE, ZERO, invoice.paid_amount),
                ],
                reference_type="sales_invoice_payment",
                reference_id=invoice.id,
                created_by=user.id,
            )

    async def _create_payments(
        self, parsed: Parsed, customers: dict[str, Customer], user: User
    ) -> None:
        for row in parsed.rows.get("customer_payments", []):
            customer = customers[row["customer_name"]]
            payment = CustomerPayment(
                legacy_ref=row["payment_ref"],
                customer_id=customer.id,
                amount=row["amount"],
                payment_date=row["payment_date"],
                method=row["method"],
                reference=row.get("reference"),
                notes=row.get("notes"),
                created_by=user.id,
            )
            self.session.add(payment)
            await self.session.flush()
            await self.accounting.add_entry_no_commit(
                entry_date=payment.payment_date,
                description=(
                    f"سند قبض مستورد {payment.legacy_ref} من العميل ({customer.name})"
                ),
                items=[
                    (cash_or_bank(payment.method), payment.amount, ZERO),
                    (ACCOUNTS_RECEIVABLE, ZERO, payment.amount),
                ],
                reference_type="customer_payment",
                reference_id=payment.id,
                created_by=user.id,
            )

    # --- Proving it ---
    async def _reconcile(self, parsed: Parsed) -> list[ReconciliationRowOut]:
        """Compare what this system now says each customer owes with what the old
        one said.

        The single most useful thing this module produces. Every migration mistake
        that matters — a double-counted opening balance, a missing invoice, a receipt
        entered twice — shows up here as a customer whose two numbers disagree.
        """
        from app.services.sales.sales_service import SalesService

        sales = SalesService(self.session)
        rows: list[ReconciliationRowOut] = []
        for row in parsed.rows.get("customers", []):
            expected = row.get("expected_balance")
            if expected is None:
                continue
            customer = (
                await self.session.execute(
                    select(Customer).where(Customer.name == row["name"])
                )
            ).scalar_one()
            actual = await sales.customer_balance(customer.id)
            difference = (actual - expected).quantize(TWO_PLACES)
            rows.append(
                ReconciliationRowOut(
                    customer_name=customer.name,
                    expected_balance=expected.quantize(TWO_PLACES),
                    actual_balance=actual.quantize(TWO_PLACES),
                    difference=difference,
                    matches=abs(difference) <= TOLERANCE,
                )
            )
        rows.sort(key=lambda r: abs(r.difference), reverse=True)
        return rows

    def _report(
        self,
        parsed: Parsed,
        counts: dict[str, int],
        *,
        applied: bool,
        reconciliation: list[ReconciliationRowOut],
    ) -> ImportReportOut:
        errors = [
            ImportErrorOut(
                sheet=issue.sheet,
                sheet_title=SHEETS_BY_NAME[issue.sheet].title
                if issue.sheet in SHEETS_BY_NAME
                else issue.sheet,
                row=issue.row,
                column=issue.column,
                message=issue.message,
            )
            # Capped so a file with a wrong header does not return fifty thousand
            # identical errors; the count above the list tells the real story.
            for issue in parsed.issues[:200]
        ]
        mismatched = [r for r in reconciliation if not r.matches]
        return ImportReportOut(
            applied=applied,
            sheets=[
                SheetResultOut(
                    sheet=name,
                    title=SHEETS_BY_NAME[name].title,
                    rows=count,
                )
                for name, count in counts.items()
            ],
            error_count=len(parsed.issues),
            errors=errors,
            reconciliation=reconciliation,
            reconciliation_mismatches=len(mismatched),
            message=self._message(applied, parsed, counts, len(mismatched)),
        )

    @staticmethod
    def _message(
        applied: bool, parsed: Parsed, counts: dict[str, int], mismatches: int
    ) -> str:
        total = sum(counts.values())
        if parsed.issues:
            return (
                f"الملف مرفوض: {len(parsed.issues)} خطأ. لم يُحفظ أي سطر. "
                "صحّح الأخطاء أدناه وأعد الرفع."
            )
        if not applied:
            return f"الفحص ناجح: {total} سطراً جاهزة للاستيراد، ولم يُحفظ شيء بعد."
        if mismatches:
            return (
                f"تم استيراد {total} سطراً. تنبيه: {mismatches} عميلاً "
                "رصيدهم لا يطابق النظام القديم — راجع جدول المطابقة."
            )
        return f"تم استيراد {total} سطراً بنجاح، وكل الأرصدة مطابقة للنظام القديم."
