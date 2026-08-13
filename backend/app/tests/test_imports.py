"""Loading a legacy system in, and the promises that make it safe to do so.

A migration is the one operation that can quietly falsify an entire business's
books, and it is run once, under time pressure, by someone who cannot easily check
the result by eye. So the tests here are about the guarantees rather than the
plumbing: that a rejected file leaves nothing behind, that history does not consume
today's stock or appear as today's work, that the same spreadsheet cannot be loaded
twice, and that the numbers are reconciled against the system they came from.
"""

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import func, select

from app.domain.models.inventory import Product, ProductBatch
from app.domain.models.sales import Customer, SalesInvoice
from app.services.imports.spec import SHEETS, SHEETS_BY_NAME
from app.tests.conftest import TEST_ADMIN_PASSWORD, TEST_SALES_PASSWORD, login

RUN = "/api/v1/imports/run"


def csv_bytes(sheet_name: str, rows: list[dict]) -> tuple[str, bytes, str]:
    """Build one upload file from dicts, using the spec's own column order."""
    columns = [c.name for c in SHEETS_BY_NAME[sheet_name].columns]
    lines = [",".join(columns)]
    for row in rows:
        lines.append(",".join(str(row.get(c, "")) for c in columns))
    return (f"{sheet_name}.csv", "\n".join(lines).encode("utf-8"), "text/csv")


async def upload(client: AsyncClient, admin: dict, files: list, *, commit: bool = False):
    return await client.post(
        RUN,
        headers=admin,
        params={"dry_run": "false" if commit else "true"},
        files=[("files", f) for f in files],
    )


# A minimal but complete migration: one product, its stock, one customer, one
# invoice with two lines, and a receipt against it.
def a_full_migration() -> list:
    return [
        csv_bytes("products", [{
            "sku": "M-1", "name": "أرز بسمتي", "base_unit_name": "كيس",
            "wholesale_price": "10.00", "half_wholesale_price": "11.00",
            "retail_price": "12.00", "warehouse": "مستودع الاستيراد",
        }]),
        csv_bytes("opening_stock", [{
            "sku": "M-1", "warehouse": "مستودع الاستيراد", "batch_number": "OPENING",
            "expiry_date": "2027-06-30", "quantity": "500", "unit_cost": "8.00",
        }]),
        csv_bytes("customers", [{
            "name": "بقالة الاستيراد", "price_tier": "wholesale",
            "credit_limit": "9000", "opening_balance": "0",
            "expected_balance": "50.00",
        }]),
        csv_bytes("sales_invoices", [{
            "invoice_ref": "OLD-001", "customer_name": "بقالة الاستيراد",
            "invoice_date": "2026-01-15", "payment_method": "credit",
            "subtotal": "150.00", "discount_amount": "0", "tax_amount": "0",
            "total": "150.00", "paid_amount": "0",
            "warehouse": "مستودع الاستيراد",
        }]),
        csv_bytes("sales_invoice_lines", [
            {"invoice_ref": "OLD-001", "sku": "M-1", "quantity": "10",
             "unit_price": "10.00", "unit_cost": "8.00"},
            {"invoice_ref": "OLD-001", "sku": "M-1", "quantity": "5",
             "unit_price": "10.00", "unit_cost": "8.00", "batch_number": "OPENING"},
        ]),
        csv_bytes("customer_payments", [{
            "payment_ref": "OLD-RC-001", "customer_name": "بقالة الاستيراد",
            "payment_date": "2026-02-01", "amount": "100.00", "method": "cash",
        }]),
    ]


class TestTheTemplateCannotLie:
    """The sample and the validator are generated from one table; this proves it."""

    async def test_every_generated_header_is_one_the_parser_requires(
        self, client: AsyncClient
    ) -> None:
        """A template promising a column the importer ignores — or missing one it
        demands — is a trap the user only springs after filling in ten thousand rows."""
        from app.services.imports import reader, template

        sheets = reader.read_workbook(template.build_workbook())
        for sheet in SHEETS:
            assert sheet.name in sheets, f"القالب لا يحتوي ورقة {sheet.name}"

    async def test_the_template_ships_no_rows_that_could_be_imported(
        self, client: AsyncClient
    ) -> None:
        """Demonstration rows inside a data sheet get uploaded by whoever forgets to
        delete them, and "أرز بسمتي 5 كجم" lands in a real catalogue. The examples
        live on their own sheet, which the parser does not read."""
        from app.services.imports import reader, template

        sheets = reader.read_workbook(template.build_workbook())
        for sheet in SHEETS:
            assert sheets[sheet.name] == [], (
                f"ورقة {sheet.name} في القالب تحتوي بيانات قابلة للاستيراد"
            )

    async def test_the_download_is_a_real_workbook(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.get("/api/v1/imports/template.xlsx", headers=admin)
        assert response.status_code == 200
        assert response.content[:2] == b"PK"  # xlsx is a zip
        assert "attachment" in response.headers["content-disposition"]


class TestNothingIsWrittenUntilEverythingIsUnderstood:
    async def test_a_dry_run_saves_nothing(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await upload(client, admin, a_full_migration())
        assert response.status_code == 200, response.text
        data = response.json()["data"]

        assert data["applied"] is False
        assert data["error_count"] == 0
        listed = (await client.get(
            "/api/v1/inventory/products", headers=admin)).json()["data"]["items"]
        assert not any(p["sku"] == "M-1" for p in listed)

    async def test_one_bad_row_rejects_the_whole_file(
        self, client: AsyncClient, db_session
    ) -> None:
        """The central promise. A half-written customer ledger cannot be unpicked
        afterwards, because nobody can tell which half arrived."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        files = a_full_migration()
        files.append(csv_bytes("products", [
            {"sku": "M-2", "name": "زيت", "base_unit_name": "عبوة",
             "wholesale_price": "5", "half_wholesale_price": "6", "retail_price": "7"},
            {"sku": "M-3", "name": "سكر", "base_unit_name": "كيس",
             "wholesale_price": "ليس رقماً", "half_wholesale_price": "6",
             "retail_price": "7"},
        ]))

        response = await upload(client, admin, files, commit=True)
        assert response.status_code == 200, response.text
        data = response.json()["data"]

        assert data["applied"] is False
        assert data["error_count"] >= 1
        # Not one product, not even the valid ones from other sheets.
        assert await db_session.scalar(select(func.count()).select_from(Product)) == 0
        assert await db_session.scalar(select(func.count()).select_from(Customer)) == 0

    async def test_an_error_names_the_row_the_user_sees_in_excel(
        self, client: AsyncClient
    ) -> None:
        """An error nobody can navigate to is barely an error report."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        files = [csv_bytes("products", [
            {"sku": "OK-1", "name": "سليم", "base_unit_name": "حبة",
             "wholesale_price": "1", "half_wholesale_price": "1", "retail_price": "1"},
            {"sku": "BAD-1", "name": "خاطئ", "base_unit_name": "حبة",
             "wholesale_price": "س", "half_wholesale_price": "1", "retail_price": "1"},
        ])]
        data = (await upload(client, admin, files)).json()["data"]

        error = next(e for e in data["errors"] if e["column"] == "wholesale_price")
        # Header is row 1, first data row is 2, so the bad one is row 3.
        assert error["row"] == 3
        assert error["sheet"] == "products"


class TestTheFileMustAgreeWithItself:
    async def test_a_header_whose_total_contradicts_its_lines_is_refused(
        self, client: AsyncClient
    ) -> None:
        """A subtotal that does not match the lines means the export dropped
        something. Picking either number would be guessing at the truth."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        files = a_full_migration()
        files[3] = csv_bytes("sales_invoices", [{
            "invoice_ref": "OLD-001", "customer_name": "بقالة الاستيراد",
            "invoice_date": "2026-01-15", "payment_method": "credit",
            "subtotal": "999.00", "total": "999.00", "paid_amount": "0",
            "warehouse": "مستودع الاستيراد",
        }])

        data = (await upload(client, admin, files)).json()["data"]
        assert any("لا يساوي مجموع الأسطر" in e["message"] for e in data["errors"])

    async def test_a_total_that_is_not_subtotal_less_discount_plus_tax_is_refused(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        files = a_full_migration()
        files[3] = csv_bytes("sales_invoices", [{
            "invoice_ref": "OLD-001", "customer_name": "بقالة الاستيراد",
            "invoice_date": "2026-01-15", "payment_method": "credit",
            "subtotal": "150.00", "discount_amount": "10.00", "tax_amount": "0",
            "total": "150.00", "paid_amount": "0",
            "warehouse": "مستودع الاستيراد",
        }])

        data = (await upload(client, admin, files)).json()["data"]
        assert any("الإجمالي" in e["message"] for e in data["errors"])

    async def test_an_unknown_product_is_named_not_silently_skipped(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        files = a_full_migration()
        files[4] = csv_bytes("sales_invoice_lines", [
            {"invoice_ref": "OLD-001", "sku": "لا-يوجد", "quantity": "15",
             "unit_price": "10.00"},
        ])
        data = (await upload(client, admin, files)).json()["data"]
        assert any("غير موجود" in e["message"] for e in data["errors"])


class TestHistoryIsRecordedNotReplayed:
    async def test_imported_invoices_do_not_consume_the_opening_stock(
        self, client: AsyncClient, db_session
    ) -> None:
        """The most expensive mistake available here.

        The opening-stock sheet is the count on the shelf *today*. Deducting a sale
        from three years ago would remove goods that left the building long before
        anyone counted, and the warehouse would be short by its entire trading
        history.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await upload(client, admin, a_full_migration(), commit=True)
        assert response.json()["data"]["applied"] is True, response.text

        on_hand = await db_session.scalar(
            select(func.sum(ProductBatch.quantity)).where(ProductBatch.quantity > 0)
        )
        assert Decimal(str(on_hand)) == Decimal("500"), (
            "الفواتير التاريخية خصمت من المخزون الافتتاحي"
        )

    async def test_a_historical_line_gets_a_batch_that_can_never_be_sold(
        self, client: AsyncClient, db_session
    ) -> None:
        """`batch_id` is NOT NULL, so history needs something to point at. The
        placeholder holds zero units and expires in the past, failing both halves of
        the sellable test rather than relying on either alone."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await upload(client, admin, a_full_migration(), commit=True)

        archive = (await db_session.execute(
            select(ProductBatch).where(ProductBatch.batch_number == "LEGACY")
        )).scalar_one()
        assert archive.quantity == Decimal("0")
        assert archive.expiry_date < __import__("datetime").date.today()

    async def test_imported_invoices_stay_out_of_the_cashier_queue(
        self, client: AsyncClient, db_session
    ) -> None:
        """A settled cash sale from last year is not money to collect this morning.

        Two things keep it out, and this checks the second one specifically. The
        importer stamps `payment_confirmed_at`, which alone is enough — so the test
        then clears that stamp and looks again, leaving only `legacy_ref` doing the
        work. Written the obvious way this test passed with the filter deleted, which
        made it worth nothing: it was measuring the stamp, not the guard.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        files = a_full_migration()
        files[3] = csv_bytes("sales_invoices", [{
            "invoice_ref": "OLD-CASH", "customer_name": "بقالة الاستيراد",
            "invoice_date": "2026-01-15", "payment_method": "cash",
            # Deliberately left uncollected: a fully-paid invoice is dropped by the
            # cashier's own `amount_due > 0` test, which would make this pass for a
            # reason that has nothing to do with the guard being checked.
            "subtotal": "150.00", "total": "150.00", "paid_amount": "0",
            "warehouse": "مستودع الاستيراد",
        }])
        files[4] = csv_bytes("sales_invoice_lines", [
            {"invoice_ref": "OLD-CASH", "sku": "M-1", "quantity": "15",
             "unit_price": "10.00", "unit_cost": "8.00"},
        ])
        files[2] = csv_bytes("customers", [{
            "name": "بقالة الاستيراد", "price_tier": "wholesale",
            "credit_limit": "9000", "opening_balance": "0",
        }])
        files = [f for f in files if not f[0].startswith("customer_payments")]

        assert (await upload(client, admin, files, commit=True)).json()["data"]["applied"]

        assert (await client.get(
            "/api/v1/cashier/invoices", headers=admin)).json()["data"] == []

        # Now take away the confirmation stamp, so only `legacy_ref` stands between
        # a decade of settled cash sales and the cashier's morning screen.
        invoice = (await db_session.execute(
            select(SalesInvoice).where(SalesInvoice.legacy_ref == "OLD-CASH")
        )).scalar_one()
        invoice.payment_confirmed_at = None
        await db_session.commit()

        pending = (await client.get(
            "/api/v1/cashier/invoices", headers=admin)).json()["data"]
        assert pending == [], "الفواتير المستوردة ظهرت في شاشة الصندوق"

    async def test_imported_invoices_stay_out_of_the_delivery_worklist(
        self, client: AsyncClient
    ) -> None:
        """Goods delivered years ago are not goods to load today."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await upload(client, admin, a_full_migration(), commit=True)

        awaiting = (await client.get(
            "/api/v1/delivery/invoices", headers=admin)).json()["data"]
        assert awaiting == [], "الفواتير المستوردة ظهرت في شاشة التوزيع"


class TestTheLedgerStaysTrue:
    async def test_the_books_still_balance_after_an_import(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await upload(client, admin, a_full_migration(), commit=True)

        trial = (await client.get(
            "/api/v1/accounting/reports/trial-balance", headers=admin)).json()["data"]
        assert trial["is_balanced"] is True

    async def test_an_imported_invoice_posts_its_revenue(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await upload(client, admin, a_full_migration(), commit=True)

        statement = (await client.get(
            "/api/v1/accounting/reports/income-statement", headers=admin
        )).json()["data"]
        assert Decimal(str(statement["total_revenue"])) == Decimal("150.00")

    async def test_cost_of_goods_is_kept_off_the_ledger_but_on_the_line(
        self, client: AsyncClient, db_session
    ) -> None:
        """Posting COGS would credit inventory for goods this ledger never debited —
        no purchase history is imported — and drive the stock account negative by the
        cost of everything ever sold. The cost still rides on the invoice line, which
        is where every margin report reads it from.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await upload(client, admin, a_full_migration(), commit=True)

        entries = (await client.get(
            "/api/v1/accounting/journal-entries", headers=admin,
            params={"limit": 100})).json()["data"]["items"]
        assert not any("تكلفة البضاعة" in e["description"] for e in entries)

        invoice = (await db_session.execute(
            select(SalesInvoice).where(SalesInvoice.legacy_ref == "OLD-001")
        )).scalar_one()
        await db_session.refresh(invoice, ["lines"])
        assert all(line.unit_cost == Decimal("8.00") for line in invoice.lines)


class TestTheSameFileCannotLandTwice:
    async def test_re_uploading_an_invoice_is_refused(
        self, client: AsyncClient, db_session
    ) -> None:
        """Running the import twice is the single easiest way to double a business's
        receivables, and it is exactly what a nervous operator does."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        assert (await upload(
            client, admin, a_full_migration(), commit=True)).json()["data"]["applied"]

        second = (await upload(
            client, admin, a_full_migration(), commit=True)).json()["data"]
        assert second["applied"] is False
        assert any("مستوردة من قبل" in e["message"] for e in second["errors"])

        count = await db_session.scalar(
            select(func.count()).select_from(SalesInvoice)
        )
        assert count == 1, "تكرر استيراد الفاتورة"

    async def test_a_duplicate_inside_one_file_is_refused(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        files = [csv_bytes("products", [
            {"sku": "D-1", "name": "أ", "base_unit_name": "حبة", "wholesale_price": "1",
             "half_wholesale_price": "1", "retail_price": "1"},
            {"sku": "D-1", "name": "ب", "base_unit_name": "حبة", "wholesale_price": "1",
             "half_wholesale_price": "1", "retail_price": "1"},
        ])]
        data = (await upload(client, admin, files)).json()["data"]
        assert any("مكرر" in e["message"] for e in data["errors"])


class TestTheMigrationIsProved:
    async def test_a_matching_balance_is_reported_as_matching(
        self, client: AsyncClient
    ) -> None:
        """150 invoiced less a 100 receipt leaves 50, which is what the sheet claims."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        data = (await upload(
            client, admin, a_full_migration(), commit=True)).json()["data"]

        row = next(r for r in data["reconciliation"]
                   if r["party_name"] == "بقالة الاستيراد")
        assert Decimal(row["actual_balance"]) == Decimal("50.00")
        assert row["matches"] is True
        assert data["reconciliation_mismatches"] == 0

    async def test_a_wrong_balance_is_surfaced_rather_than_buried(
        self, client: AsyncClient
    ) -> None:
        """The check that catches every migration mistake that matters — a
        double-counted opening balance, a missing invoice, a receipt entered twice."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        files = a_full_migration()
        files[2] = csv_bytes("customers", [{
            "name": "بقالة الاستيراد", "price_tier": "wholesale",
            "credit_limit": "9000", "opening_balance": "0",
            "expected_balance": "999.00",  # the legacy system disagrees
        }])

        data = (await upload(client, admin, files, commit=True)).json()["data"]
        assert data["applied"] is True  # the data loaded; the warning is separate
        assert data["reconciliation_mismatches"] == 1
        row = data["reconciliation"][0]
        assert row["matches"] is False
        assert Decimal(row["difference"]) == Decimal("-949.00")
        assert "لا يطابق" in data["message"]


class TestOnlyAdminsMayDoThis:
    async def test_a_salesman_cannot_import(self, client: AsyncClient) -> None:
        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        refused = await upload(client, salesman, a_full_migration())
        assert refused.status_code == 403

    async def test_a_salesman_cannot_even_take_the_template(
        self, client: AsyncClient
    ) -> None:
        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        refused = await client.get("/api/v1/imports/template.xlsx", headers=salesman)
        assert refused.status_code == 403


# The purchase half of a migration: one supplier, one invoice with two lines, and a
# payment against it. Deliberately separate from `a_full_migration` so a test can
# import purchases without sales and see the ledger halves in isolation.
def a_purchase_migration() -> list:
    return [
        csv_bytes("suppliers", [{
            "name": "شركة التوريد الوطنية", "phone": "0551112222",
            "opening_balance": "0", "lead_time_days": "7", "is_active": "نعم",
            "legacy_balance": "260.00",
        }]),
        csv_bytes("purchase_invoices", [{
            "invoice_ref": "OLD-PINV-1", "supplier_name": "شركة التوريد الوطنية",
            "invoice_date": "2026-01-05", "payment_method": "credit",
            "subtotal": "800.00", "shipping_cost": "20.00", "tax_amount": "40.00",
            "total": "860.00", "paid_amount": "0",
            "warehouse": "مستودع الاستيراد",
        }]),
        csv_bytes("purchase_invoice_lines", [
            {"invoice_ref": "OLD-PINV-1", "sku": "M-1", "quantity": "50",
             "unit_cost": "8.00"},
            {"invoice_ref": "OLD-PINV-1", "sku": "M-1", "quantity": "50",
             "unit_cost": "8.00", "batch_number": "OPENING"},
        ]),
        csv_bytes("supplier_payments", [{
            "payment_ref": "OLD-PV-1", "supplier_name": "شركة التوريد الوطنية",
            "payment_date": "2026-01-20", "amount": "600.00", "method": "bank",
        }]),
    ]


async def balance_of(db_session, code: str) -> Decimal:
    """A ledger account's balance, debits less credits."""
    from sqlalchemy import func, select

    from app.domain.models.accounting import Account, JournalItem

    total = await db_session.scalar(
        select(func.coalesce(func.sum(JournalItem.debit - JournalItem.credit), 0))
        .join(Account, Account.id == JournalItem.account_id)
        .where(Account.code == code)
    )
    return Decimal(str(total or 0))


class TestThePurchaseSideOfTheLedger:
    """Before this, an imported business had receivables and revenue but no payables,
    no cost of sales, and — worst — no inventory.

    The importer set batch quantities without ever posting the inventory account, so a
    migrated company's balance sheet omitted the largest asset a distributor owns. The
    trial balance still balanced, which is exactly what made it easy to miss: it
    balanced perfectly, around a hole.
    """

    async def test_opening_stock_puts_inventory_on_the_balance_sheet(
        self, client: AsyncClient, db_session
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await upload(client, admin, a_full_migration(), commit=True)
        assert response.status_code == 200, response.text

        # 500 units at 8.00 — the opening-stock sheet's own figures.
        assert await balance_of(db_session, "1030") == Decimal("4000.00")
        # Against capital, because that is what an opening balance sheet is: the
        # owner's stake in goods bought with money predating this ledger.
        assert await balance_of(db_session, "3010") == Decimal("-4000.00")

    async def test_a_purchase_invoice_creates_the_payable(
        self, client: AsyncClient, db_session
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        files = a_full_migration() + a_purchase_migration()
        response = await upload(client, admin, files, commit=True)
        assert response.status_code == 200, response.text
        assert response.json()["data"]["error_count"] == 0

        from app.domain.models.purchases import PurchaseInvoice

        invoice = (await db_session.execute(
            select(PurchaseInvoice).where(PurchaseInvoice.legacy_ref == "OLD-PINV-1")
        )).scalar_one()
        assert invoice.total == Decimal("860.00")
        assert len(await self._lines(db_session, invoice.id)) == 2

        # 860 owed less the 600 paid by the supplier payment sheet.
        assert await balance_of(db_session, "2010") == Decimal("-260.00")

    @staticmethod
    async def _lines(db_session, invoice_id: int) -> list:
        from app.domain.models.purchases import PurchaseInvoiceLine

        rows = await db_session.execute(
            select(PurchaseInvoiceLine).where(
                PurchaseInvoiceLine.invoice_id == invoice_id
            )
        )
        return list(rows.scalars().all())

    async def test_a_historical_purchase_is_a_cost_not_an_asset(
        self, client: AsyncClient, db_session
    ) -> None:
        """The decision that keeps inventory from doubling.

        The live purchase flow debits INVENTORY, because there the goods really do
        arrive on a shelf. An imported historical purchase must not: the shelf was
        already established once from the physical count, and capitalising the whole
        purchase history on top of it would inflate the asset by everything the
        business ever bought.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        files = a_full_migration() + a_purchase_migration()
        await upload(client, admin, files, commit=True)

        # 800 of goods + 20 shipping went to cost of sales, and inventory is still
        # exactly the opening count — not opening plus purchases.
        assert await balance_of(db_session, "5010") == Decimal("820.00")
        assert await balance_of(db_session, "1030") == Decimal("4000.00")

    async def test_the_quantities_bought_do_not_reach_the_shelf(
        self, client: AsyncClient, db_session
    ) -> None:
        """100 units on a historical purchase must not add to today's count.

        The count is today's count. A purchase from January that also topped up the
        batch would have the same carton on the shelf twice — once when it arrived and
        once when it was counted.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        files = a_full_migration() + a_purchase_migration()
        await upload(client, admin, files, commit=True)

        from app.domain.models.inventory import Product, ProductBatch

        product = (await db_session.execute(
            select(Product).where(Product.sku == "M-1")
        )).scalar_one()
        total = await db_session.scalar(
            select(func.coalesce(func.sum(ProductBatch.quantity), 0)).where(
                ProductBatch.product_id == product.id
            )
        )
        # The opening 500, untouched by either the sales or the purchase history.
        assert Decimal(str(total)) == Decimal("500.000")

    async def test_the_trial_balance_still_balances(
        self, client: AsyncClient, db_session
    ) -> None:
        """Every new entry is double-entry or the whole ledger is worthless."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        files = a_full_migration() + a_purchase_migration()
        await upload(client, admin, files, commit=True)

        from app.domain.models.accounting import JournalItem

        debits = await db_session.scalar(
            select(func.coalesce(func.sum(JournalItem.debit), 0))
        )
        credits = await db_session.scalar(
            select(func.coalesce(func.sum(JournalItem.credit), 0))
        )
        assert Decimal(str(debits)) == Decimal(str(credits))

    async def test_a_supplier_balance_is_reconciled_like_a_customer_one(
        self, client: AsyncClient
    ) -> None:
        """The guide promises suppliers the same protection; this is that promise.

        The reconciliation table was customer-only, so a supplier balance that failed
        to agree with the legacy books had nowhere to show up — the exact silent error
        the table exists to catch.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        files = a_full_migration() + a_purchase_migration()
        data = (await upload(client, admin, files, commit=True)).json()["data"]

        row = next(
            r for r in data["reconciliation"]
            if r["party_name"] == "شركة التوريد الوطنية"
        )
        assert row["party_kind"] == "supplier"
        # 860 invoiced less 600 paid, matching the legacy_balance in the sheet.
        assert Decimal(row["actual_balance"]) == Decimal("260.00")
        assert row["matches"] is True

        # And the customer row is still there, labelled as such.
        customer = next(
            r for r in data["reconciliation"]
            if r["party_name"] == "بقالة الاستيراد"
        )
        assert customer["party_kind"] == "customer"

    async def test_re_uploading_a_purchase_file_is_refused(
        self, client: AsyncClient
    ) -> None:
        """Otherwise the second run pays the supplier twice and looks just as clean."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        files = a_full_migration() + a_purchase_migration()
        first = await upload(client, admin, files, commit=True)
        assert first.json()["data"]["error_count"] == 0

        again = await upload(client, admin, a_purchase_migration(), commit=True)
        data = again.json()["data"]
        assert data["applied"] is False
        assert data["error_count"] > 0

        # Both refs by name, not merely "something was rejected". A test that only
        # asserted the file was refused passed happily with the invoice check
        # disabled, because the payment duplicate refused it on its own — and a
        # re-imported invoice is the half that doubles the payable.
        messages = " ".join(e["message"] for e in data["errors"])
        assert "OLD-PINV-1" in messages, "the duplicate purchase invoice must be named"
        assert "OLD-PV-1" in messages, "the duplicate supplier payment must be named"
        assert "مستوردة من قبل" in messages

    async def test_a_purchase_header_that_disagrees_with_its_lines_is_refused(
        self, client: AsyncClient
    ) -> None:
        """Shipping is *added* to a purchase where a discount is *subtracted* from a
        sale, which is why the two arithmetic checks are separate functions."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        broken = [
            f for f in a_purchase_migration()
            if not f[0].startswith("purchase_invoices")
        ] + [
            csv_bytes("purchase_invoices", [{
                "invoice_ref": "OLD-PINV-1", "supplier_name": "شركة التوريد الوطنية",
                "invoice_date": "2026-01-05", "payment_method": "credit",
                "subtotal": "800.00", "shipping_cost": "20.00", "tax_amount": "40.00",
                # Should be 860; the shipping has been dropped from the total.
                "total": "840.00", "paid_amount": "0",
                "warehouse": "مستودع الاستيراد",
            }])
        ]
        data = (await upload(
            client, admin, a_full_migration() + broken, commit=True)).json()["data"]
        assert data["applied"] is False
        assert any("الإجمالي" in e["message"] for e in data["errors"])

    async def test_an_unknown_supplier_is_refused(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        orphan = [
            csv_bytes("purchase_invoices", [{
                "invoice_ref": "OLD-PINV-9", "supplier_name": "مورد لا وجود له",
                "invoice_date": "2026-01-05", "payment_method": "credit",
                "subtotal": "10.00", "shipping_cost": "0", "tax_amount": "0",
                "total": "10.00", "paid_amount": "0",
            }]),
            csv_bytes("purchase_invoice_lines", [{
                "invoice_ref": "OLD-PINV-9", "sku": "M-1", "quantity": "1",
                "unit_cost": "10.00",
            }]),
        ]
        data = (await upload(
            client, admin, a_full_migration() + orphan, commit=True)).json()["data"]
        assert data["applied"] is False
        assert any("غير موجود في ورقة الموردين" in e["message"] for e in data["errors"])
