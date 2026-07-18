"""Settings business logic: configurable tax rates and company identity."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.settings import (
    CompanySettingsUpdate,
    TaxRateCreate,
    TaxRateUpdate,
)
from app.core.exceptions import AppException
from app.domain.models.sales import SalesInvoiceTax
from app.domain.models.settings import CompanySettings, TaxRate


class SettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- Tax rates ---
    async def get_tax_rate(self, tax_rate_id: int) -> TaxRate:
        tax_rate = await self.session.get(TaxRate, tax_rate_id)
        if tax_rate is None:
            raise AppException(404, "الضريبة غير موجودة.")
        return tax_rate

    async def list_tax_rates(self, active_only: bool = False) -> list[TaxRate]:
        stmt = select(TaxRate).order_by(TaxRate.id)
        if active_only:
            stmt = stmt.where(TaxRate.is_active.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _clear_other_defaults(self, except_id: int | None = None) -> None:
        result = await self.session.execute(
            select(TaxRate).where(TaxRate.is_default.is_(True))
        )
        for tax_rate in result.scalars().all():
            if tax_rate.id != except_id:
                tax_rate.is_default = False

    async def create_tax_rate(self, data: TaxRateCreate) -> TaxRate:
        existing = await self.session.execute(
            select(TaxRate).where(TaxRate.code == data.code)
        )
        if existing.scalar_one_or_none() is not None:
            raise AppException(409, "يوجد رمز ضريبة مطابق مسجل من قبل.")

        tax_rate = TaxRate(
            name=data.name,
            code=data.code,
            rate=data.rate,
            country=data.country,
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
        tax_rate = await self.get_tax_rate(tax_rate_id)
        if data.name is not None:
            tax_rate.name = data.name
        if data.rate is not None:
            tax_rate.rate = data.rate
        if data.country is not None:
            tax_rate.country = data.country
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
        company = await self.get_company_settings()
        if data.name is not None:
            company.name = data.name
        if data.tagline is not None:
            company.tagline = data.tagline
        if data.address is not None:
            company.address = data.address
        if data.phone is not None:
            company.phone = data.phone
        if data.tax_number is not None:
            company.tax_number = data.tax_number
        if data.currency_code is not None:
            company.currency_code = data.currency_code
        if data.currency_symbol is not None:
            company.currency_symbol = data.currency_symbol
        await self.session.commit()
        await self.session.refresh(company)
        return company
