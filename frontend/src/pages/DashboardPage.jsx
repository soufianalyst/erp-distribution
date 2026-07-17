import { Alert, Badge, Card, Loading, Stat, Table, qty } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api from "../services/api";

export default function DashboardPage() {
  const levels = useFetch(() => api.get("/inventory/stock/levels"));
  const nearExpiry = useFetch(() => api.get("/inventory/stock/near-expiry", { params: { days: 30 } }));
  const products = useFetch(() => api.get("/inventory/products"));

  if (levels.loading || nearExpiry.loading || products.loading) return <Loading />;
  const error = levels.error || nearExpiry.error || products.error;

  const expired = (nearExpiry.data || []).filter((item) => item.days_remaining < 0);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold">لوحة التحكم</h1>
      <Alert>{error}</Alert>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="عدد الأصناف" value={products.data?.length ?? 0} />
        <Stat label="أرصدة مخزنية نشطة" value={levels.data?.length ?? 0} />
        <Stat
          label="تشغيلات قرب الانتهاء (30 يوم)"
          value={nearExpiry.data?.length ?? 0}
          tone="amber"
        />
        <Stat label="تشغيلات منتهية في المخزون" value={expired.length} tone="rose" />
      </div>

      <Card title="تنبيهات الصلاحية — الأقرب انتهاءً أولاً">
        <Table
          columns={[
            { key: "product_name", label: "الصنف" },
            { key: "warehouse_name", label: "المستودع" },
            { key: "batch_number", label: "التشغيلة" },
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
        />
      </Card>

      <Card title="أرصدة المخزون الحالية">
        <Table
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
        />
      </Card>
    </div>
  );
}
