"""Settings business logic: configurable tax rates and company identity."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.settings import (
    CompanySettingsUpdate,
    TaxRateCreate,
    TaxRateUpdate,
)
from app.core.countries import is_valid_country
from app.core import business_day
from app.core.exceptions import AppException
from app.domain.models.sales import SalesInvoiceTax
from app.domain.models.settings import CompanySettings, TaxRate


class SettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- Tax rates ---
    async def get_tax_rate(self, tax_rate_id: int) -> TaxRate:
        """Fetch a configured tax or raise a 404."""
        tax_rate = await self.session.get(TaxRate, tax_rate_id)
        if tax_rate is None:
            raise AppException(404, "الضريبة غير موجودة.")
        return tax_rate

    async def list_tax_rates(
        self, active_only: bool = False, in_scope_only: bool = False
    ) -> list[TaxRate]:
        """All configured taxes, or only the ones that apply where we operate.

        `in_scope_only` is what the invoice forms ask for: a tax with no country
        applies everywhere, while a country-specific one is only offered when it
        matches the company's own country. The control panel asks without it, so
        an admin can still see and manage taxes for other countries.
        """
        stmt = select(TaxRate).order_by(TaxRate.country_code.nulls_first(), TaxRate.id)
        if active_only:
            stmt = stmt.where(TaxRate.is_active.is_(True))
        if in_scope_only:
            company = await self.get_company_settings()
            if company.country_code is None:
                # No country set yet: only universal taxes are unambiguous.
                stmt = stmt.where(TaxRate.country_code.is_(None))
            else:
                stmt = stmt.where(
                    (TaxRate.country_code.is_(None))
                    | (TaxRate.country_code == company.country_code)
                )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _validate_country(code: str | None) -> str | None:
        """Reject codes outside the reference list so pickers and data stay in sync."""
        normalised = code.upper() if code else None
        if not is_valid_country(normalised):
            raise AppException(400, "رمز الدولة غير معروف؛ اختر دولة من القائمة.")
        return normalised

    async def _clear_other_defaults(self, except_id: int | None = None) -> None:
        result = await self.session.execute(
            select(TaxRate).where(TaxRate.is_default.is_(True))
        )
        for tax_rate in result.scalars().all():
            if tax_rate.id != except_id:
                tax_rate.is_default = False

    async def create_tax_rate(self, data: TaxRateCreate) -> TaxRate:
        """Define a tax; codes are unique, and at most one may be the default."""
        existing = await self.session.execute(
            select(TaxRate).where(TaxRate.code == data.code)
        )
        if existing.scalar_one_or_none() is not None:
            raise AppException(409, "يوجد رمز ضريبة مطابق مسجل من قبل.")

        tax_rate = TaxRate(
            name=data.name,
            code=data.code,
            rate=data.rate,
            country_code=self._validate_country(data.country_code),
            is_active=data.is_active,
            is_default=data.is_default,
        )
        self.session.add(tax_rate)
        if data.is_default:
            await self.session.flush()
            await self._clear_other_defaults(except_id=tax_rate.id)
        await self.session.commit()
        await self.session.refresh(tax_rate)
        return tax_rate

    async def update_tax_rate(self, tax_rate_id: int, data: TaxRateUpdate) -> TaxRate:
        """Amend a tax's name, rate, country scope, or active/default flags."""
        tax_rate = await self.get_tax_rate(tax_rate_id)
        if data.name is not None:
            tax_rate.name = data.name
        if data.rate is not None:
            tax_rate.rate = data.rate
        if data.country_code is not None:
            tax_rate.country_code = self._validate_country(data.country_code)
        if data.is_active is not None:
            tax_rate.is_active = data.is_active
        if data.is_default is not None:
            tax_rate.is_default = data.is_default
            if data.is_default:
                await self._clear_other_defaults(except_id=tax_rate.id)
        await self.session.commit()
        await self.session.refresh(tax_rate)
        return tax_rate

    async def delete_tax_rate(self, tax_rate_id: int) -> None:
        """Delete a tax rate. Past invoices keep their own snapshot (name/rate/amount)

        of what was charged, so this never corrupts historical data — it just
        detaches those rows from the now-gone tax definition.
        """
        tax_rate = await self.get_tax_rate(tax_rate_id)
        applied = await self.session.execute(
            select(SalesInvoiceTax).where(SalesInvoiceTax.tax_rate_id == tax_rate_id)
        )
        for row in applied.scalars().all():
            row.tax_rate_id = None
        await self.session.delete(tax_rate)
        await self.session.commit()

    # --- Company settings (singleton) ---
    async def get_company_settings(self) -> CompanySettings:
        """The singleton company record, created with defaults on first read."""
        result = await self.session.execute(select(CompanySettings).limit(1))
        company = result.scalar_one_or_none()
        if company is None:
            # First read ever: create a sensible default row so the app never
            # shows blank print headers.
            company = CompanySettings(
                name="شركتي",
                tagline=None,
                currency_code="SAR",
                currency_symbol="ر.س",
            )
            self.session.add(company)
            await self.session.commit()
            await self.session.refresh(company)
        return company

    async def update_company_settings(
        self, data: CompanySettingsUpdate
    ) -> CompanySettings:
        """Amend company identity, country and currency.

        Optional fields distinguish an explicit null (clear it) from an omitted
        one (leave it), so the panel can empty a field it once set.
        """
        company = await self.get_company_settings()
        sent = data.model_fields_set

        # Optional fields distinguish "not sent" from an explicit null, so the
        # panel can actually clear one — emptying an address, or picking
        # "— لم تُحدد —" for the country. Treating null as "leave alone" here
        # would make those fields set-once.
        for field in ("tagline", "address", "phone", "tax_number",
                      "statistical_number"):
            if field in sent:
                setattr(company, field, getattr(data, field))
        if "country_code" in sent:
            company.country_code = self._validate_country(data.country_code)

        # The timezone decides where the business day starts, so a typo would land
        # in the cashier's closing report rather than here. Rejected at the point of
        # saving, which is the only place a human is around to correct it.
        if data.timezone is not None:
            if not business_day.is_valid(data.timezone):
                raise AppException(
                    400,
                    f"المنطقة الزمنية ({data.timezone}) غير معروفة؛ اختر واحدة من القائمة.",
                )
            company.timezone = data.timezone

        # Name and currency are required columns: null means "leave alone"
        # because there is no valid empty value to fall back to.
        if data.name is not None:
            company.name = data.name
        if data.currency_code is not None:
            company.currency_code = data.currency_code
        if data.currency_symbol is not None:
            company.currency_symbol = data.currency_symbol

        # Replenishment. Required columns with sensible defaults, so null means
        # "leave alone" — there is no meaningful empty lead time.
        for field in (
            "default_lead_time_days", "safety_stock_days", "reorder_review_days",
            "markdown_max_discount_percent", "credit_block_after_days",
        ):
            value = getattr(data, field)
            if value is not None:
                setattr(company, field, value)
        await self.session.commit()
        await self.session.refresh(company)
        return company
