import { Alert, Badge, Button, Card, Loading, PaginatedTable, Stat, Table, money, qty } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api from "../services/api";

export default function DashboardPage() {
  const kpis = useFetch(() => api.get("/reports/dashboard"));
  const topProducts = useFetch(() => api.get("/reports/top-products", { params: { limit: 5 } }));
  const salesmanPerf = useFetch(() => api.get("/reports/salesman-performance"));
  const levels = useFetch(() => api.get("/inventory/stock/levels"));
  const nearExpiry = useFetch(() => api.get("/inventory/stock/near-expiry", { params: { days: 30 } }));
  const products = useFetch(() => api.get("/inventory/products"));

  if (kpis.loading || levels.loading || nearExpiry.loading || products.loading) return <Loading />;
  const error = kpis.error || levels.error || nearExpiry.error || products.error;
  const d = kpis.data || {};

  const expired = (nearExpiry.data || []).filter((item) => item.days_remaining < 0);
  const salesGrowth = d.sales_this_month?.prev_revenue > 0
    ? (((d.sales_this_month.revenue - d.sales_this_month.prev_revenue) / d.sales_this_month.prev_revenue) * 100).toFixed(1)
    : null;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold">لوحة التحكم التحليلية</h1>
      <Alert>{error}</Alert>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="إيرادات المبيعات (هذا الشهر)"
          value={money(d.sales_this_month?.revenue)}
          hint={`${d.sales_this_month?.count ?? 0} فاتورة${salesGrowth ? ` — ${salesGrowth > 0 ? "+" : ""}${salesGrowth}% من الشهر السابق` : ""}`}
        />
        <Stat
          label="المشتريات (هذا الشهر)"
          value={money(d.purchases_this_month?.total)}
          hint={`${d.purchases_this_month?.count ?? 0} فاتورة شراء`}
          tone="blue"
        />
        <Stat
          label="المرتجعات (هذا الشهر)"
          value={money(d.returns_this_month?.total)}
          hint={`${d.returns_this_month?.count ?? 0} مرتجع`}
          tone="rose"
        />
        <Stat
          label="ذمم العملاء المستحقة"
          value={money(d.outstanding_receivables)}
          hint="المبالغ غير المحصلة بعد"
          tone="amber"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label="عدد الأصناف النشطة" value={d.total_products ?? products.data?.length ?? 0} />
        <Stat label="أصناف تحت الحد الأدنى" value={d.low_stock_count ?? 0} tone={d.low_stock_count > 0 ? "rose" : "emerald"} />
        <Stat label="أرصدة مخزنية نشطة" value={levels.data?.length ?? 0} />
      </div>

      {/* Top Products & Salesman Performance */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card title="أكثر الأصناف مبيعاً (هذا الشهر)">
          <Table
            columns={[
              { key: "sku", label: "الرمز" },
              { key: "product_name", label: "الصنف" },
              { key: "total_quantity", label: "الكمية المباعة", render: (r) => qty(r.total_quantity) },
              { key: "total_revenue", label: "الإيراد", render: (r) => money(r.total_revenue) },
            ]}
            rows={topProducts.data}
            keyField="product_id"
            empty="لا توجد مبيعات هذا الشهر بعد."
          />
        </Card>

        <Card title="أداء مناديب المبيعات (هذا الشهر)">
          <Table
            columns={[
              { key: "salesman_name", label: "المندوب" },
              { key: "invoice_count", label: "الفواتير", render: (r) => r.invoice_count },
              { key: "total_revenue", label: "الإجمالي", render: (r) => money(r.total_revenue) },
              { key: "collected", label: "المحصّل", render: (r) => money(r.collected) },
            ]}
            rows={salesmanPerf.data}
            keyField="salesman_id"
            empty="لا يوجد مناديب مبيعات نشطين هذا الشهر."
          />
        </Card>
      </div>

      <Card title="تنبيهات الصلاحية — الأقرب انتهاءً أولاً">
        <PaginatedTable
          columns={[
            { key: "product_name", label: "الصنف" },
            { key: "warehouse_name", label: "المستودع" },
            { key: "batch_number", label: "التشغيليلة" },
            { key: "expiry_date", label: "تاريخ الانتهاء" },
            { key: "quantity", label: "الكمية", render: (r) => qty(r.quantity) },
            {
              key: "days_remaining",
              label: "الأيام المتبقية",
              render: (r) =>
                r.days_remaining < 0 ? (
                  <Badge tone="red">منتهية منذ {-r.days_remaining} يوم</Badge>
                ) : (
                  <Badge tone={r.days_remaining <= 7 ? "red" : "amber"}>
                    {r.days_remaining} يوم
                  </Badge>
                ),
            },
          ]}
          rows={nearExpiry.data}
          keyField="batch_id"
          empty="لا توجد تشغيلات قريبة الانتهاء — ممتاز!"
          searchable
          searchPlaceholder="بحث بالصنف..."
        />
      </Card>

      <Card title="أرصدة المخزون الحالية">
        <PaginatedTable
          columns={[
            { key: "product_name", label: "الصنف" },
            { key: "warehouse_name", label: "المستودع" },
            {
              key: "total_quantity",
              label: "الرصيد",
              render: (r) => `${qty(r.total_quantity)} ${r.base_unit_name}`,
            },
          ]}
          rows={levels.data}
          keyField="product_id"
          empty="المخزون فارغ حالياً."
          searchable
          searchPlaceholder="بحث بالصنف أو المستودع..."
        />
      </Card>
    </div>
  );
}
