import { useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Label,
  LabelList,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { Alert, Badge, Button, Card, Loading, Table, money, qty } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api from "../services/api";

const TIER_LABELS = { wholesale: "جملة", half_wholesale: "نصف جملة", retail: "تجزئة" };

// Chart fill colors (bars/scatter dots) — kept vivid/saturated for visibility
// against grid lines. Badge text uses a separate light-bg/dark-text palette
// below so labels stay readable regardless of segment (matches the shared
// Badge component's existing light-bg/dark-text convention).
const SEGMENT_COLORS = {
  "بطل (Champion)": "#059669",
  "الأكثر مبيعاً": "#059669",
  نشط: "#0284c7",
  ثابت: "#0284c7",
  "بحاجة لعناية": "#d97706",
  عادي: "#64748b",
  "معرض للخطر": "#ea580c",
  متراجع: "#ea580c",
  "خامل (Lost)": "#e11d48",
  "راكد (Dead Stock)": "#e11d48",
  "لم يشترِ بعد": "#94a3b8",
  "لم يُباع بعد": "#94a3b8",
};

const SEGMENT_BADGE_STYLES = {
  "بطل (Champion)": "bg-emerald-100 text-emerald-800",
  "الأكثر مبيعاً": "bg-emerald-100 text-emerald-800",
  نشط: "bg-sky-100 text-sky-800",
  ثابت: "bg-sky-100 text-sky-800",
  "بحاجة لعناية": "bg-amber-100 text-amber-800",
  عادي: "bg-slate-100 text-slate-700",
  "معرض للخطر": "bg-orange-100 text-orange-800",
  متراجع: "bg-orange-100 text-orange-800",
  "خامل (Lost)": "bg-rose-100 text-rose-800",
  "راكد (Dead Stock)": "bg-rose-100 text-rose-800",
  "لم يشترِ بعد": "bg-slate-100 text-slate-500",
  "لم يُباع بعد": "bg-slate-100 text-slate-500",
};

// Shared chart typography — recharts' defaults (12px, light gray #666) are too
// faint to read comfortably; every axis/legend/tooltip in this file uses these.
const AXIS_TICK_STYLE = { fontSize: 13, fill: "#334155", fontWeight: 600 };
const AXIS_LABEL_STYLE = { fontSize: 13, fill: "#0f172a", fontWeight: 700 };
const LEGEND_STYLE = { fontSize: 13, fontWeight: 700, color: "#334155" };
const TOOLTIP_CONTENT_STYLE = {
  fontSize: 13,
  borderRadius: 8,
  border: "1px solid #e2e8f0",
  boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
};
const TOOLTIP_LABEL_STYLE = { fontWeight: 700, color: "#0f172a", marginBottom: 4 };
const TOOLTIP_ITEM_STYLE = { color: "#334155", fontWeight: 600 };
const DATA_LABEL_STYLE = { fontSize: 12, fontWeight: 700, fill: "#0f172a" };
// For labels drawn inside a colored bar (narrow two-column charts, where an
// outside label would collide with the category axis) — white for contrast.
const INSIDE_DATA_LABEL_STYLE = { fontSize: 12, fontWeight: 700, fill: "#ffffff" };

function segmentBadge(segment) {
  const cls = SEGMENT_BADGE_STYLES[segment] || "bg-slate-100 text-slate-700";
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-bold ${cls}`}>
      {segment}
    </span>
  );
}

function Kpi({ label, value, tone = "slate", hint }) {
  const tones = {
    emerald: "text-emerald-700",
    rose: "text-rose-700",
    amber: "text-amber-700",
    sky: "text-sky-700",
    slate: "text-slate-800",
  };
  return (
    <div className="rounded-xl bg-white p-5 shadow-sm">
      <div className="text-sm font-bold text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-extrabold ${tones[tone]}`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-400">{hint}</div>}
    </div>
  );
}

const TABS = [
  { id: "overview", label: "📊 نظرة عامة" },
  { id: "customers", label: "🧑‍💼 تحليل العملاء (RFM)" },
  { id: "products", label: "📦 تحليل الأصناف (RFM)" },
  { id: "inventory", label: "🗑️ المخزون والهدر" },
  { id: "credit", label: "💳 الذمم والمخاطر الائتمانية" },
  { id: "delivery", label: "🚛 التوزيع والاستلام" },
  { id: "reps", label: "🏅 أداء المناديب" },
];

export default function AnalyticsPage() {
  const [tab, setTab] = useState("overview");

  const summary = useFetch(() => api.get("/analytics/summary"));
  const salesTrend = useFetch(() => api.get("/analytics/sales/trend"));
  const byWarehouse = useFetch(() => api.get("/analytics/sales/by-warehouse"));
  const byPriceTier = useFetch(() => api.get("/analytics/sales/by-price-tier"));
  const returnsTrend = useFetch(() => api.get("/analytics/returns/trend"));
  const customerRfm = useFetch(() => api.get("/analytics/customers/rfm"));
  const productRfm = useFetch(() => api.get("/analytics/products/rfm"));
  const expiryRisk = useFetch(() => api.get("/analytics/inventory/expiry-risk"));
  const turnover = useFetch(() => api.get("/analytics/inventory/turnover"));
  const arAging = useFetch(() => api.get("/analytics/credit/aging"));
  const creditRisk = useFetch(() => api.get("/analytics/credit/at-risk"));
  const fulfillment = useFetch(() => api.get("/analytics/delivery/fulfillment"));
  const drivers = useFetch(() => api.get("/analytics/delivery/drivers"));
  const reps = useFetch(() => api.get("/analytics/reps/performance"));

  const loadingCore = summary.loading || salesTrend.loading;
  if (loadingCore) return <Loading />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-extrabold">لوحة التحليلات والتقارير</h1>
      </div>

      <div className="flex flex-wrap gap-2">
        {TABS.map((t) => (
          <Button
            key={t.id}
            variant={tab === t.id ? "primary" : "secondary"}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </Button>
        ))}
      </div>

      {tab === "overview" && (
        <OverviewTab
          summary={summary.data}
          salesTrend={salesTrend.data || []}
          byWarehouse={byWarehouse.data || []}
          byPriceTier={byPriceTier.data || []}
          returnsTrend={returnsTrend.data || []}
        />
      )}

      {tab === "customers" && (
        <CustomerRfmTab rows={customerRfm.data || []} loading={customerRfm.loading} />
      )}

      {tab === "products" && (
        <ProductRfmTab rows={productRfm.data || []} loading={productRfm.loading} />
      )}

      {tab === "inventory" && (
        <InventoryTab
          expiryRisk={expiryRisk.data || []}
          turnover={turnover.data || []}
          loading={expiryRisk.loading || turnover.loading}
        />
      )}

      {tab === "credit" && (
        <CreditTab
          aging={arAging.data || []}
          risk={creditRisk.data || []}
          loading={arAging.loading || creditRisk.loading}
        />
      )}

      {tab === "delivery" && (
        <DeliveryTab
          fulfillment={fulfillment.data || []}
          drivers={drivers.data || []}
          loading={fulfillment.loading || drivers.loading}
        />
      )}

      {tab === "reps" && <RepsTab rows={reps.data || []} loading={reps.loading} />}
    </div>
  );
}

function OverviewTab({ summary, salesTrend, byWarehouse, byPriceTier, returnsTrend }) {
  if (!summary) return <Loading />;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Kpi label="الإيرادات (12 شهراً)" value={money(summary.total_revenue_12m)} tone="emerald" />
        <Kpi label="هامش الربح (12 شهراً)" value={money(summary.total_margin_12m)} tone="sky" />
        <Kpi label="متوسط قيمة الفاتورة" value={money(summary.avg_order_value)} tone="slate" />
        <Kpi label="عملاء نشطون" value={qty(summary.active_customers_12m)} tone="slate" />
        <Kpi
          label="ذمم العملاء المستحقة"
          value={money(summary.ar_outstanding)}
          tone="amber"
          hint="إجمالي المبالغ المستحقة على جميع العملاء"
        />
        <Kpi
          label="قيمة مخزون معرضة للهدر"
          value={money(summary.waste_risk_value_30d)}
          tone="rose"
          hint="تشغيلات تنتهي صلاحيتها خلال 30 يوماً"
        />
        <Kpi label="نسبة المرتجعات" value={`${summary.return_rate_pct_12m}%`} tone="rose" />
        <Kpi label="عدد الفواتير (12 شهراً)" value={qty(summary.invoice_count_12m)} tone="slate" />
      </div>

      <Card title="اتجاه المبيعات الشهري">
        <div className="h-72 w-full" dir="ltr">
          <ResponsiveContainer>
            <AreaChart data={salesTrend} margin={{ top: 10, right: 10, left: 10, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="period" reversed tick={AXIS_TICK_STYLE} />
              <YAxis tick={AXIS_TICK_STYLE} width={70} />
              <Tooltip
                formatter={(v) => money(v)}
                contentStyle={TOOLTIP_CONTENT_STYLE}
                labelStyle={TOOLTIP_LABEL_STYLE}
                itemStyle={TOOLTIP_ITEM_STYLE}
              />
              <Legend wrapperStyle={LEGEND_STYLE} />
              <Area type="monotone" dataKey="revenue" name="الإيرادات" stroke="#059669" fill="#a7f3d0" strokeWidth={2} />
              <Area type="monotone" dataKey="margin" name="الهامش" stroke="#0284c7" fill="#bae6fd" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card title="نقدي مقابل آجل شهرياً">
        <div className="h-64 w-full" dir="ltr">
          <ResponsiveContainer>
            <BarChart data={salesTrend} margin={{ top: 10, right: 10, left: 10, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="period" reversed tick={AXIS_TICK_STYLE} />
              <YAxis tick={AXIS_TICK_STYLE} width={70} />
              <Tooltip
                formatter={(v) => money(v)}
                contentStyle={TOOLTIP_CONTENT_STYLE}
                labelStyle={TOOLTIP_LABEL_STYLE}
                itemStyle={TOOLTIP_ITEM_STYLE}
              />
              <Legend wrapperStyle={LEGEND_STYLE} />
              <Bar dataKey="cash_revenue" name="نقدي" fill="#059669" stackId="a" />
              <Bar dataKey="credit_revenue" name="آجل" fill="#d97706" stackId="a" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Card title="الإيرادات حسب المستودع">
          <div className="h-56 w-full" dir="ltr">
            <ResponsiveContainer>
              <BarChart data={byWarehouse} layout="vertical" margin={{ top: 5, right: 15, left: 5, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" tick={AXIS_TICK_STYLE} />
                <YAxis dataKey="warehouse_name" type="category" width={110} tick={AXIS_TICK_STYLE} interval={0} />
                <Tooltip
                  formatter={(v) => money(v)}
                  contentStyle={TOOLTIP_CONTENT_STYLE}
                  labelStyle={TOOLTIP_LABEL_STYLE}
                  itemStyle={TOOLTIP_ITEM_STYLE}
                />
                <Bar dataKey="revenue" name="الإيرادات" fill="#0284c7">
                  <LabelList dataKey="revenue" position="insideRight" formatter={money} style={INSIDE_DATA_LABEL_STYLE} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="الإيرادات حسب فئة السعر">
          <div className="h-56 w-full" dir="ltr">
            <ResponsiveContainer>
              <BarChart
                data={byPriceTier.map((r) => ({ ...r, tier_label: TIER_LABELS[r.price_tier] || r.price_tier }))}
                layout="vertical"
                margin={{ top: 5, right: 15, left: 5, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" tick={AXIS_TICK_STYLE} />
                <YAxis dataKey="tier_label" type="category" width={110} tick={AXIS_TICK_STYLE} interval={0} />
                <Tooltip
                  formatter={(v) => money(v)}
                  contentStyle={TOOLTIP_CONTENT_STYLE}
                  labelStyle={TOOLTIP_LABEL_STYLE}
                  itemStyle={TOOLTIP_ITEM_STYLE}
                />
                <Bar dataKey="revenue" name="الإيرادات" fill="#059669">
                  <LabelList dataKey="revenue" position="insideRight" formatter={money} style={INSIDE_DATA_LABEL_STYLE} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <Card title="اتجاه نسبة المرتجعات الشهرية">
        <div className="h-64 w-full" dir="ltr">
          <ResponsiveContainer>
            <LineChart data={returnsTrend} margin={{ top: 10, right: 10, left: 10, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="period" reversed tick={AXIS_TICK_STYLE} />
              <YAxis unit="%" tick={AXIS_TICK_STYLE} width={50} />
              <Tooltip
                formatter={(v) => `${v}%`}
                contentStyle={TOOLTIP_CONTENT_STYLE}
                labelStyle={TOOLTIP_LABEL_STYLE}
                itemStyle={TOOLTIP_ITEM_STYLE}
              />
              <Legend wrapperStyle={LEGEND_STYLE} />
              <Line
                type="monotone"
                dataKey="return_rate_pct"
                name="نسبة المرتجعات"
                stroke="#e11d48"
                strokeWidth={2}
                dot={{ r: 3 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>
    </div>
  );
}

function segmentCounts(rows) {
  const counts = {};
  for (const r of rows) counts[r.segment] = (counts[r.segment] || 0) + 1;
  return Object.entries(counts).map(([segment, count]) => ({ segment, count }));
}

function CustomerRfmTab({ rows, loading }) {
  if (loading) return <Loading />;
  const segments = segmentCounts(rows);
  const scatterData = rows.map((r) => ({
    x: r.recency_days ?? 400,
    y: r.frequency,
    z: Number(r.monetary),
    ...r,
  }));

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Card title="توزيع شرائح العملاء">
          <div className="h-64 w-full" dir="ltr">
            <ResponsiveContainer>
              <BarChart data={segments} layout="vertical" margin={{ top: 5, right: 40, left: 5, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" allowDecimals={false} tick={AXIS_TICK_STYLE} />
                <YAxis dataKey="segment" type="category" width={140} tick={AXIS_TICK_STYLE} interval={0} />
                <Tooltip contentStyle={TOOLTIP_CONTENT_STYLE} labelStyle={TOOLTIP_LABEL_STYLE} itemStyle={TOOLTIP_ITEM_STYLE} />
                <Bar dataKey="count" name="عدد العملاء">
                  <LabelList dataKey="count" position="right" style={DATA_LABEL_STYLE} />
                  {segments.map((s, i) => (
                    <Cell key={i} fill={SEGMENT_COLORS[s.segment] || "#64748b"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="الحداثة × التكرار (حجم الفقاعة = القيمة النقدية)">
          <div className="h-64 w-full" dir="ltr">
            <ResponsiveContainer>
              <ScatterChart margin={{ top: 10, right: 20, left: 10, bottom: 20 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" dataKey="x" name="أيام منذ آخر شراء" tick={AXIS_TICK_STYLE}>
                  <Label value="الحداثة (يوم)" position="insideBottom" offset={-10} style={AXIS_LABEL_STYLE} />
                </XAxis>
                <YAxis type="number" dataKey="y" name="التكرار" tick={AXIS_TICK_STYLE} width={45}>
                  <Label value="التكرار" angle={-90} position="insideLeft" style={AXIS_LABEL_STYLE} />
                </YAxis>
                <ZAxis type="number" dataKey="z" range={[30, 400]} name="القيمة" />
                <Tooltip
                  formatter={(v, n) => (n === "z" ? money(v) : v)}
                  labelFormatter={() => ""}
                  content={({ payload }) =>
                    payload?.[0] ? (
                      <div className="rounded-lg border border-slate-200 bg-white p-2.5 text-xs shadow-lg">
                        <b className="text-slate-900">{payload[0].payload.customer_name}</b>
                        <div className="mt-1 font-semibold text-slate-600">الحداثة: {payload[0].payload.x} يوم</div>
                        <div className="font-semibold text-slate-600">التكرار: {payload[0].payload.y}</div>
                        <div className="font-semibold text-slate-600">القيمة: {money(payload[0].payload.z)}</div>
                      </div>
                    ) : null
                  }
                />
                <Scatter data={scatterData}>
                  {scatterData.map((d, i) => (
                    <Cell key={i} fill={SEGMENT_COLORS[d.segment] || "#64748b"} />
                  ))}
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <Card title="تفاصيل تحليل RFM للعملاء">
        <Table
          columns={[
            { key: "customer_name", label: "العميل" },
            { key: "salesman_name", label: "المندوب", render: (r) => r.salesman_name || "—" },
            {
              key: "recency_days",
              label: "الحداثة",
              render: (r) => (r.recency_days === null ? "—" : `${r.recency_days} يوم`),
            },
            { key: "frequency", label: "التكرار" },
            { key: "monetary", label: "القيمة النقدية", render: (r) => money(r.monetary) },
            { key: "segment", label: "الشريحة", render: (r) => segmentBadge(r.segment) },
          ]}
          rows={rows}
          keyField="customer_id"
        />
      </Card>
    </div>
  );
}

function ProductRfmTab({ rows, loading }) {
  if (loading) return <Loading />;
  const segments = segmentCounts(rows);
  // Waste-risk highlight: dead stock still sitting on soon-to-expire batches.
  const wasteRisk = rows
    .filter((r) => r.segment === "راكد (Dead Stock)" && r.nearest_expiry_days !== null && r.nearest_expiry_days <= 60)
    .sort((a, b) => a.nearest_expiry_days - b.nearest_expiry_days);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Card title="توزيع شرائح الأصناف">
          <div className="h-64 w-full" dir="ltr">
            <ResponsiveContainer>
              <BarChart data={segments} layout="vertical" margin={{ top: 5, right: 40, left: 5, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" allowDecimals={false} tick={AXIS_TICK_STYLE} />
                <YAxis dataKey="segment" type="category" width={140} tick={AXIS_TICK_STYLE} interval={0} />
                <Tooltip contentStyle={TOOLTIP_CONTENT_STYLE} labelStyle={TOOLTIP_LABEL_STYLE} itemStyle={TOOLTIP_ITEM_STYLE} />
                <Bar dataKey="count" name="عدد الأصناف">
                  <LabelList dataKey="count" position="right" style={DATA_LABEL_STYLE} />
                  {segments.map((s, i) => (
                    <Cell key={i} fill={SEGMENT_COLORS[s.segment] || "#64748b"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="أعلى 10 أصناف من حيث القيمة">
          <div className="h-64 w-full" dir="ltr">
            <ResponsiveContainer>
              <BarChart data={rows.slice(0, 10)} layout="vertical" margin={{ top: 5, right: 60, left: 5, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" tick={AXIS_TICK_STYLE} />
                <YAxis dataKey="product_name" type="category" width={130} tick={AXIS_TICK_STYLE} interval={0} />
                <Tooltip
                  formatter={(v) => money(v)}
                  contentStyle={TOOLTIP_CONTENT_STYLE}
                  labelStyle={TOOLTIP_LABEL_STYLE}
                  itemStyle={TOOLTIP_ITEM_STYLE}
                />
                <Bar dataKey="monetary" name="القيمة النقدية" fill="#059669">
                  <LabelList dataKey="monetary" position="right" formatter={money} style={DATA_LABEL_STYLE} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      {wasteRisk.length > 0 && (
        <Card title="⚠️ أولوية الهدر: أصناف راكدة قريبة من انتهاء الصلاحية">
          <Table
            columns={[
              { key: "product_name", label: "الصنف" },
              { key: "sku", label: "الرمز" },
              { key: "stock_on_hand", label: "المخزون الحالي", render: (r) => qty(r.stock_on_hand) },
              {
                key: "nearest_expiry_days",
                label: "أقرب انتهاء صلاحية",
                render: (r) => <Badge tone="red">{r.nearest_expiry_days} يوم</Badge>,
              },
              {
                key: "recency_days",
                label: "آخر بيع",
                render: (r) => (r.recency_days === null ? "لم يُبع" : `منذ ${r.recency_days} يوم`),
              },
            ]}
            rows={wasteRisk}
            keyField="product_id"
          />
        </Card>
      )}

      <Card title="تفاصيل تحليل RFM للأصناف">
        <Table
          columns={[
            { key: "product_name", label: "الصنف" },
            { key: "sku", label: "الرمز" },
            {
              key: "recency_days",
              label: "الحداثة",
              render: (r) => (r.recency_days === null ? "—" : `${r.recency_days} يوم`),
            },
            { key: "frequency", label: "التكرار" },
            { key: "monetary", label: "الإيرادات", render: (r) => money(r.monetary) },
            { key: "margin", label: "الهامش", render: (r) => money(r.margin) },
            { key: "stock_on_hand", label: "المخزون الحالي", render: (r) => qty(r.stock_on_hand) },
            {
              key: "nearest_expiry_days",
              label: "أقرب انتهاء",
              render: (r) => (r.nearest_expiry_days === null ? "—" : `${r.nearest_expiry_days} يوم`),
            },
            { key: "segment", label: "الشريحة", render: (r) => segmentBadge(r.segment) },
          ]}
          rows={rows}
          keyField="product_id"
        />
      </Card>
    </div>
  );
}

function InventoryTab({ expiryRisk, turnover, loading }) {
  if (loading) return <Loading />;
  return (
    <div className="space-y-6">
      <Card title="⚠️ تشغيلات قريبة من انتهاء الصلاحية (30 يوماً) — القيمة المعرضة للخطر">
        <Table
          columns={[
            { key: "product_name", label: "الصنف" },
            { key: "warehouse_name", label: "المستودع" },
            { key: "batch_number", label: "التشغيلة" },
            { key: "expiry_date", label: "تاريخ الانتهاء" },
            {
              key: "days_remaining",
              label: "الأيام المتبقية",
              render: (r) => (
                <Badge tone={r.days_remaining <= 7 ? "red" : "amber"}>{r.days_remaining} يوم</Badge>
              ),
            },
            { key: "quantity", label: "الكمية", render: (r) => qty(r.quantity) },
            {
              key: "value_at_risk",
              label: "القيمة المعرضة للخطر",
              render: (r) => <b className="text-rose-700">{money(r.value_at_risk)}</b>,
            },
          ]}
          rows={expiryRisk}
          keyField="batch_id"
          empty="لا توجد تشغيلات قريبة من الانتهاء — ممتاز!"
        />
      </Card>

      <Card title="معدل دوران المخزون (أعلى 15 صنفاً من حيث تكلفة المبيعات)">
        <div className="h-72 w-full" dir="ltr">
          <ResponsiveContainer>
            <BarChart data={turnover.slice(0, 15)} layout="vertical" margin={{ top: 5, right: 40, left: 5, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" tick={AXIS_TICK_STYLE} />
              <YAxis dataKey="product_name" type="category" width={140} tick={AXIS_TICK_STYLE} interval={0} />
              <Tooltip contentStyle={TOOLTIP_CONTENT_STYLE} labelStyle={TOOLTIP_LABEL_STYLE} itemStyle={TOOLTIP_ITEM_STYLE} />
              <Bar dataKey="turnover_ratio" name="معدل الدوران" fill="#0284c7">
                <LabelList dataKey="turnover_ratio" position="right" style={DATA_LABEL_STYLE} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>
    </div>
  );
}

function CreditTab({ aging, risk, loading }) {
  if (loading) return <Loading />;
  const agingTotals = ["bucket_0_30", "bucket_31_60", "bucket_61_90", "bucket_90_plus"].map((key) => ({
    bucket: { bucket_0_30: "0-30 يوم", bucket_31_60: "31-60 يوم", bucket_61_90: "61-90 يوم", bucket_90_plus: "90+ يوم" }[key],
    total: aging.reduce((sum, r) => sum + Number(r[key]), 0),
  }));

  return (
    <div className="space-y-6">
      <Card title="إجمالي أعمار الذمم المدينة">
        <div className="h-56 w-full" dir="ltr">
          <ResponsiveContainer>
            <BarChart data={agingTotals} margin={{ top: 20, right: 10, left: 10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="bucket" tick={AXIS_TICK_STYLE} />
              <YAxis tick={AXIS_TICK_STYLE} width={70} />
              <Tooltip
                formatter={(v) => money(v)}
                contentStyle={TOOLTIP_CONTENT_STYLE}
                labelStyle={TOOLTIP_LABEL_STYLE}
                itemStyle={TOOLTIP_ITEM_STYLE}
              />
              <Bar dataKey="total" name="المبلغ المستحق">
                <LabelList dataKey="total" position="top" formatter={money} style={DATA_LABEL_STYLE} />
                {agingTotals.map((_, i) => (
                  <Cell key={i} fill={["#059669", "#0284c7", "#d97706", "#e11d48"][i]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card title="العملاء الأعلى استغلالاً لحدهم الائتماني">
        <Table
          columns={[
            { key: "customer_name", label: "العميل" },
            { key: "outstanding_balance", label: "المستحق", render: (r) => money(r.outstanding_balance) },
            { key: "credit_limit", label: "الحد الائتماني", render: (r) => money(r.credit_limit) },
            {
              key: "utilization_pct",
              label: "نسبة الاستغلال",
              render: (r) => (
                <Badge tone={Number(r.utilization_pct) >= 90 ? "red" : Number(r.utilization_pct) >= 60 ? "amber" : "green"}>
                  {r.utilization_pct}%
                </Badge>
              ),
            },
            {
              key: "recency_days",
              label: "آخر شراء",
              render: (r) => (r.recency_days === null ? "—" : `منذ ${r.recency_days} يوم`),
            },
          ]}
          rows={risk}
          keyField="customer_id"
        />
      </Card>

      <Card title="تفاصيل أعمار الذمم حسب العميل">
        <Table
          columns={[
            { key: "customer_name", label: "العميل" },
            { key: "bucket_0_30", label: "0-30 يوم", render: (r) => money(r.bucket_0_30) },
            { key: "bucket_31_60", label: "31-60 يوم", render: (r) => money(r.bucket_31_60) },
            { key: "bucket_61_90", label: "61-90 يوم", render: (r) => money(r.bucket_61_90) },
            {
              key: "bucket_90_plus",
              label: "90+ يوم",
              render: (r) => <b className="text-rose-700">{money(r.bucket_90_plus)}</b>,
            },
            { key: "total_outstanding", label: "الإجمالي", render: (r) => <b>{money(r.total_outstanding)}</b> },
          ]}
          rows={aging}
          keyField="customer_id"
        />
      </Card>
    </div>
  );
}

function DeliveryTab({ fulfillment, drivers, loading }) {
  if (loading) return <Loading />;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {fulfillment.map((f) => (
          <Card key={f.fulfillment} title={f.fulfillment === "delivery" ? "🚛 التوصيل" : "🏬 الاستلام من المستودع"}>
            <div className="grid grid-cols-3 gap-4 text-center">
              <div>
                <div className="text-2xl font-extrabold text-slate-800">{qty(f.invoice_count)}</div>
                <div className="text-xs font-bold text-slate-500">إجمالي الفواتير</div>
              </div>
              <div>
                <div className="text-2xl font-extrabold text-emerald-700">{qty(f.completed_count)}</div>
                <div className="text-xs font-bold text-slate-500">مكتملة</div>
              </div>
              <div>
                <div className="text-2xl font-extrabold text-rose-700">{f.completion_rate_pct}%</div>
                <div className="text-xs font-bold text-slate-500">نسبة الإنجاز</div>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <Card title="أداء السائقين">
        <Table
          columns={[
            { key: "driver_name", label: "السائق" },
            { key: "trip_count", label: "عدد الرحلات" },
            { key: "delivered_stops", label: "طلبيات مسلَّمة" },
            { key: "failed_stops", label: "طلبيات فاشلة" },
            {
              key: "failure_rate_pct",
              label: "نسبة الفشل",
              render: (r) => (
                <Badge tone={Number(r.failure_rate_pct) >= 20 ? "red" : "green"}>{r.failure_rate_pct}%</Badge>
              ),
            },
          ]}
          rows={drivers}
          keyField="driver_name"
        />
      </Card>
    </div>
  );
}

function RepsTab({ rows, loading }) {
  if (loading) return <Loading />;
  return (
    <div className="space-y-6">
      <Card title="الإيرادات حسب المندوب">
        <div className="h-64 w-full" dir="ltr">
          <ResponsiveContainer>
            <BarChart data={rows} layout="vertical" margin={{ top: 5, right: 60, left: 5, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" tick={AXIS_TICK_STYLE} />
              <YAxis dataKey="salesman_name" type="category" width={130} tick={AXIS_TICK_STYLE} interval={0} />
              <Tooltip
                formatter={(v) => money(v)}
                contentStyle={TOOLTIP_CONTENT_STYLE}
                labelStyle={TOOLTIP_LABEL_STYLE}
                itemStyle={TOOLTIP_ITEM_STYLE}
              />
              <Bar dataKey="revenue" name="الإيرادات" fill="#059669">
                <LabelList dataKey="revenue" position="right" formatter={money} style={DATA_LABEL_STYLE} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card title="تفاصيل أداء المناديب">
        <Table
          columns={[
            { key: "salesman_name", label: "المندوب" },
            { key: "revenue", label: "الإيرادات", render: (r) => money(r.revenue) },
            { key: "invoice_count", label: "عدد الفواتير" },
            { key: "avg_basket", label: "متوسط الفاتورة", render: (r) => money(r.avg_basket) },
            { key: "customer_count", label: "عدد العملاء النشطين" },
            {
              key: "return_rate_pct",
              label: "نسبة المرتجعات",
              render: (r) => (
                <Badge tone={Number(r.return_rate_pct) >= 5 ? "red" : "green"}>{r.return_rate_pct}%</Badge>
              ),
            },
          ]}
          rows={rows}
          keyField="salesman_id"
        />
      </Card>
    </div>
  );
}
