"""Reporting endpoints: dashboard KPIs, top products, salesman performance, damage reports, tax report, income statement, balance sheet."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permissions
from app.api.schemas.common import APIResponse
from app.api.schemas.reports import (
    BalanceSheetOut,
    DamageRow,
    DashboardData,
    IncomeStatementOut,
    SalesmanPerfRow,
    TaxReportOut,
    TopProductRow,
)
from app.db.session import get_db
from app.services.reports.report_service import ReportService

router = APIRouter(prefix="/reports", tags=["Reports"])

# Dashboard and reports require the reports.view permission (admin, sales, accountant).
dashboard_dep = Depends(require_permissions("reports.view"))


@router.get(
    "/dashboard",
    response_model=APIResponse[DashboardData],
    dependencies=[dashboard_dep],
)
async def get_dashboard(db: AsyncSession = Depends(get_db)) -> APIResponse[DashboardData]:
    """لوحة تحكم تحليلية: ملخص المبيعات والمشتريات والمرتجعات والأرصدة."""
    kpis = await ReportService(db).dashboard_kpis()
    return APIResponse(data=DashboardData(**kpis))


@router.get(
    "/top-products",
    response_model=APIResponse[list[TopProductRow]],
    dependencies=[dashboard_dep],
)
async def get_top_products(
    limit: int = Query(default=5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[TopProductRow]]:
    """أكثر الأصناف مبيعاً هذا الشهر حسب الكمية."""
    data = await ReportService(db).top_products(limit)
    return APIResponse(data=[TopProductRow(**row) for row in data])


@router.get(
    "/salesman-performance",
    response_model=APIResponse[list[SalesmanPerfRow]],
    dependencies=[dashboard_dep],
)
async def get_salesman_performance(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[SalesmanPerfRow]]:
    """أداء مناديب المبيعات هذا الشهر حسب عدد الفواتير والإيرادات."""
    data = await ReportService(db).salesman_performance()
    return APIResponse(data=[SalesmanPerfRow(**row) for row in data])


@router.get(
    "/damage-report",
    response_model=APIResponse[list[DamageRow]],
    dependencies=[dashboard_dep],
)
async def get_damage_report(
    date_from: date | None = Query(default=None, description="من تاريخ"),
    date_to: date | None = Query(default=None, description="إلى تاريخ"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[DamageRow]]:
    """تقرير التالف: مرتجعات بسبب العميل أو النقل مجمعة حسب الصنف والسبب."""
    data = await ReportService(db).damage_report(date_from, date_to)
    return APIResponse(data=[DamageRow(**row) for row in data])


@router.get(
    "/tax-report",
    response_model=APIResponse[TaxReportOut],
    dependencies=[dashboard_dep],
)
async def get_tax_report(
    date_from: date | None = Query(default=None, description="من تاريخ"),
    date_to: date | None = Query(default=None, description="إلى تاريخ"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[TaxReportOut]:
    """تقرير الضريبة: ضريبة محصلة على المبيعات، مرتجعات، مدفوعة على المشتريات، وصافي المستحق للحكومة."""
    data = await ReportService(db).tax_report(date_from, date_to)
    return APIResponse(data=TaxReportOut(**data))


@router.get(
    "/income-statement",
    response_model=APIResponse[IncomeStatementOut],
    dependencies=[dashboard_dep],
)
async def get_income_statement(
    date_from: date | None = Query(default=None, description="من تاريخ"),
    date_to: date | None = Query(default=None, description="إلى تاريخ"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[IncomeStatementOut]:
    """قائمة الدخل (قائمة الدخل): الإيرادات ناقص تكلفة البضاعة المباعة ناقص المصروفات = صافي الربح."""
    data = await ReportService(db).income_statement(date_from, date_to)
    return APIResponse(data=IncomeStatementOut(**data))


@router.get(
    "/balance-sheet",
    response_model=APIResponse[BalanceSheetOut],
    dependencies=[dashboard_dep],
)
async def get_balance_sheet(
    as_of_date: date | None = Query(default=None, description="حتى تاريخ"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[BalanceSheetOut]:
    """الميزانية العمومية: الأصول = الخصوم + حقوق الملكية في تاريخ معين."""
    data = await ReportService(db).balance_sheet(as_of_date)
    return APIResponse(data=BalanceSheetOut(**data))
