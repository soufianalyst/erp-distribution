// The analytics dashboard: RFM segmentation of customers and products, revenue
// trends, waste and expiry risk, credit exposure, delivery performance and
// salesman results.
//
// Read-only throughout — every figure is derived from what the transactional
// modules already recorded, so nothing here can change the books.
import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
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
import { useNavigate } from "react-router-dom";
import { Alert, Badge, Button, Card, Input, Loading, Select, Table, money, qty } from "../components/Ui";
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
  "بطل (Champion)": "bg-emerald-100 dark:bg-emerald-900/50 text-emerald-800 dark:text-emerald-300",
  "الأكثر مبيعاً": "bg-emerald-100 dark:bg-emerald-900/50 text-emerald-800 dark:text-emerald-300",
  نشط: "bg-sky-100 dark:bg-sky-900/50 text-sky-800 dark:text-sky-300",
  ثابت: "bg-sky-100 dark:bg-sky-900/50 text-sky-800 dark:text-sky-300",
  "بحاجة لعناية": "bg-amber-100 dark:bg-amber-900/50 text-amber-800 dark:text-amber-300",
  عادي: "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300",
  "معرض للخطر": "bg-orange-100 dark:bg-orange-900/50 text-orange-800 dark:text-orange-300",
  متراجع: "bg-orange-100 dark:bg-orange-900/50 text-orange-800 dark:text-orange-300",
  "خامل (Lost)": "bg-rose-100 dark:bg-rose-900/50 text-rose-800 dark:text-rose-300",
  "راكد (Dead Stock)": "bg-rose-100 dark:bg-rose-900/50 text-rose-800 dark:text-rose-300",
  "لم يشترِ بعد": "bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400",
  "لم يُباع بعد": "bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400",
};

// Shared chart typography — recharts' defaults (12px, light gray #666) are too
// faint to read comfortably; every axis/legend/tooltip in this file uses these.
// Colours come from CSS variables (see index.css) so they follow day/night mode:
// recharts paints inline, out of reach of Tailwind's dark: variants.
const AXIS_TICK_STYLE = { fontSize: 13, fill: "var(--chart-tick)", fontWeight: 600 };
const AXIS_LABEL_STYLE = { fontSize: 13, fill: "var(--chart-label)", fontWeight: 700 };
const LEGEND_STYLE = { fontSize: 13, fontWeight: 700, color: "var(--chart-tick)" };
const TOOLTIP_CONTENT_STYLE = {
  fontSize: 13,
  borderRadius: 8,
  backgroundColor: "var(--chart-surface)",
  border: "1px solid var(--chart-border)",
  boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
};
const TOOLTIP_LABEL_STYLE = { fontWeight: 700, color: "var(--chart-label)", marginBottom: 4 };
const TOOLTIP_ITEM_STYLE = { color: "var(--chart-tick)", fontWeight: 600 };
const DATA_LABEL_STYLE = { fontSize: 12, fontWeight: 700, fill: "var(--chart-label)" };
// For labels drawn inside a colored bar (narrow two-column charts, where an
// outside label would collide with the category axis) — white for contrast.
const INSIDE_DATA_LABEL_STYLE = { fontSize: 12, fontWeight: 700, fill: "#ffffff" };

function segmentBadge(segment) {
  const cls = SEGMENT_BADGE_STYLES[segment] || "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300";
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-bold ${cls}`}>
      {segment}
    </span>
  );
}

function Kpi({ label, value, tone = "slate", hint }) {
  const tones = {
    emerald: "text-emerald-700 dark:text-emerald-400",
    rose: "text-rose-700 dark:text-rose-400",
    amber: "text-amber-700 dark:text-amber-400",
    sky: "text-sky-700 dark:text-sky-400",
    slate: "text-slate-800 dark:text-slate-100",
  };
  return (
    <div className="rounded-xl bg-white dark:bg-slate-800 p-5 shadow-sm">
      <div className="text-sm font-bold text-slate-500 dark:text-slate-400">{label}</div>
      <div className={`mt-1 text-2xl font-extrabold ${tones[tone]}`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-400 dark:text-slate-500">{hint}</div>}
    </div>
  );
}

const TABS = [
  { id: "overview", label: "📊 نظرة عامة" },
  { id: "customers", label: "🧑‍💼 تحليل العملاء (RFM)" },
  { id: "products", label: "📦 تحليل الأصناف (RFM)" },
  { id: "inventory", label: "🗑️ المخزون والهدر" },
  { id: "pareto", label: "⚖️ تحليل 20/80" },
  { id: "discounts", label: "🏷️ الخصومات" },
  { id: "lapsing", label: "📞 عملاء توقفوا عن الشراء" },
  { id: "credit", label: "💳 الذمم والمخاطر الائتمانية" },
  { id: "delivery", label: "🚛 التوزيع والاستلام" },
  { id: "reps", label: "🏅 أداء المناديب" },
];

export default function AnalyticsPage() {
  const [tab, setTab] = useState("overview");
  // RFM slicers. "" means no filter — the params are omitted rather than sent
  // empty, because the API types them as optional integers and rejects "".
  const [rfmProductId, setRfmProductId] = useState("");
  const [rfmCustomerId, setRfmCustomerId] = useState("");

  const summary = useFetch(() => api.get("/analytics/summary"));
  const salesTrend = useFetch(() => api.get("/analytics/sales/trend"));
  const byWarehouse = useFetch(() => api.get("/analytics/sales/by-warehouse"));
  const byPriceTier = useFetch(() => api.get("/analytics/sales/by-price-tier"));
  const returnsTrend = useFetch(() => api.get("/analytics/returns/trend"));
  const customerRfm = useFetch(
    () =>
      api.get("/analytics/customers/rfm", {
        params: rfmProductId ? { product_id: rfmProductId } : {},
      }),
    [rfmProductId]
  );
  const productRfm = useFetch(
    () =>
      api.get("/analytics/products/rfm", {
        params: rfmCustomerId ? { customer_id: rfmCustomerId } : {},
      }),
    [rfmCustomerId]
  );
  // The slicer option lists. Products are picked by typing (there are over a
  // thousand); customers fit a dropdown.
  const products = useFetch(() => api.get("/inventory/products/lookup"));
  const customers = useFetch(() => api.get("/sales/customers"));
  const expiryRisk = useFetch(() => api.get("/analytics/inventory/expiry-risk"));
  const turnover = useFetch(() => api.get("/analytics/inventory/turnover"));
  const lapsing = useFetch(() => api.get("/analytics/customers/lapsing"));
  const arAging = useFetch(() => api.get("/analytics/credit/aging"));
  const creditRisk = useFetch(() => api.get("/analytics/credit/at-risk"));
  const fulfillment = useFetch(() => api.get("/analytics/delivery/fulfillment"));
  const drivers = useFetch(() => api.get("/analytics/delivery/drivers"));
  const reps = useFetch(() => api.get("/analytics/reps/performance"));

  const loadingCore = summary.loading || salesTrend.loading;
  if (loadingCore) return <Loading />;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
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
        <CustomerRfmTab
          rows={customerRfm.data || []}
          loading={customerRfm.loading}
          error={customerRfm.error}
          products={products.data || []}
          productId={rfmProductId}
          onProductChange={setRfmProductId}
        />
      )}

      {tab === "products" && (
        <ProductRfmTab
          rows={productRfm.data || []}
          loading={productRfm.loading}
          error={productRfm.error}
          customers={customers.data || []}
          customerId={rfmCustomerId}
          onCustomerChange={setRfmCustomerId}
        />
      )}

      {tab === "inventory" && (
        <InventoryTab
          expiryRisk={expiryRisk.data || []}
          turnover={turnover.data || []}
          loading={expiryRisk.loading || turnover.loading}
        />
      )}

      {tab === "pareto" && <ParetoCard />}

      {tab === "discounts" && <DiscountReportCard />}

      {tab === "lapsing" && (
        <LapsingTab report={lapsing.data} loading={lapsing.loading} />
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
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
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
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
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
                <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
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
                <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
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
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
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

function CustomerRfmTab({
  rows,
  loading,
  error,
  products,
  productId,
  onProductChange,
}) {
  const segments = segmentCounts(rows);
  const scatterData = rows.map((r) => ({
    x: r.recency_days ?? 400,
    y: r.frequency,
    z: Number(r.monetary),
    ...r,
  }));

  return (
    <div className="space-y-6">
      <RfmSlicer
        label="الصنف"
        hint={
          productId
            ? "المؤشرات الثلاثة محسوبة على هذا الصنف وحده. القيمة هي قيمة أسطر الصنف قبل الضريبة."
            : "كل الأصناف. القيمة هي إجمالي الفاتورة بعد الخصم ومع الضريبة."
        }
        onClear={() => onProductChange("")}
        cleared={!productId}
      >
        <ProductPicker
          products={products}
          value={productId}
          onChange={onProductChange}
        />
      </RfmSlicer>

      <Alert>{error}</Alert>
      {/* The slicer stays mounted while the new figures load, so the control the
          user just touched does not vanish underneath them on every change. */}
      {loading ? (
        <Loading />
      ) : (
      <>
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Card title="توزيع شرائح العملاء">
          <div className="h-64 w-full" dir="ltr">
            <ResponsiveContainer>
              <BarChart data={segments} layout="vertical" margin={{ top: 5, right: 40, left: 5, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
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
                <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
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
                      <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-2.5 text-xs shadow-lg">
                        <b className="text-slate-900 dark:text-slate-50">{payload[0].payload.customer_name}</b>
                        <div className="mt-1 font-semibold text-slate-600 dark:text-slate-400">الحداثة: {payload[0].payload.x} يوم</div>
                        <div className="font-semibold text-slate-600 dark:text-slate-400">التكرار: {payload[0].payload.y}</div>
                        <div className="font-semibold text-slate-600 dark:text-slate-400">القيمة: {money(payload[0].payload.z)}</div>
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
            {
              key: "monetary",
              label: productId ? "قيمة الصنف" : "القيمة النقدية",
              render: (r) => money(r.monetary),
            },
            { key: "segment", label: "الشريحة", render: (r) => segmentBadge(r.segment) },
          ]}
          rows={rows}
          keyField="customer_id"
        />
      </Card>
      </>
      )}
    </div>
  );
}

function ProductRfmTab({
  rows,
  loading,
  error,
  customers,
  customerId,
  onCustomerChange,
}) {
  const segments = segmentCounts(rows);
  // Waste-risk highlight: dead stock still sitting on soon-to-expire batches.
  const wasteRisk = rows
    .filter((r) => r.segment === "راكد (Dead Stock)" && r.nearest_expiry_days !== null && r.nearest_expiry_days <= 60)
    .sort((a, b) => a.nearest_expiry_days - b.nearest_expiry_days);

  return (
    <div className="space-y-6">
      <RfmSlicer
        label="العميل"
        hint={
          customerId
            ? "المبيعات والهامش لهذا العميل وحده. المخزون وأقرب صلاحية على مستوى الشركة."
            : "كل العملاء."
        }
        onClear={() => onCustomerChange("")}
        cleared={!customerId}
      >
        <Select
          value={customerId}
          onChange={(e) => onCustomerChange(e.target.value)}
          aria-label="العميل"
        >
          <option value="">كل العملاء</option>
          {customers.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
      </RfmSlicer>

      <Alert>{error}</Alert>
      {loading ? (
        <Loading />
      ) : (
      <>
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Card title="توزيع شرائح الأصناف">
          <div className="h-64 w-full" dir="ltr">
            <ResponsiveContainer>
              <BarChart data={segments} layout="vertical" margin={{ top: 5, right: 40, left: 5, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
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
                <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
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
      </>
      )}
    </div>
  );
}

// The filter bar shared by both RFM tabs. The hint under it spells out what the
// figures mean once a filter is on, because "القيمة النقدية" changes basis between
// the unfiltered and filtered views and a column header alone cannot say so.
function RfmSlicer({ label, hint, children, onClear, cleared }) {
  return (
    <Card>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[16rem] flex-1">
          <label className="mb-1 block text-sm font-bold text-slate-700 dark:text-slate-300">
            {label}
          </label>
          {children}
        </div>
        {!cleared && (
          <Button variant="secondary" onClick={onClear}>
            إلغاء التصفية
          </Button>
        )}
      </div>
      <p className="mt-2 text-xs font-semibold text-slate-500 dark:text-slate-400">
        {hint}
      </p>
    </Card>
  );
}

// Over a thousand products, so the same type-to-search datalist the invoice form
// uses rather than a dropdown nobody can scroll.
function ProductPicker({ products, value, onChange }) {
  const selected = products.find((p) => String(p.id) === String(value));
  const [text, setText] = useState(selected ? productOptionLabel(selected) : "");

  // Follow the filter when it changes from outside — "إلغاء التصفية" has to empty
  // the box too, or the screen would show a product name next to unfiltered figures.
  // Partial typing never reaches here, because it does not change `value`.
  useEffect(() => {
    if (!value) return setText("");
    const current = products.find((p) => String(p.id) === String(value));
    if (current) setText(productOptionLabel(current));
  }, [value, products]);

  const handle = (raw) => {
    setText(raw);
    const typed = raw.trim();
    if (!typed) return onChange("");
    // Commit only on an exact hit, so half-typed text neither fires a request per
    // keystroke nor silently leaves a stale filter applied. The SKU and the bare
    // name count as hits too: warehouse and office staff type codes from memory,
    // and making them reproduce " — " to be understood would be pointless.
    const key = typed.toLowerCase();
    const match =
      products.find((p) => productOptionLabel(p).toLowerCase() === key) ||
      products.find((p) => (p.sku || "").toLowerCase() === key) ||
      products.find((p) => (p.name || "").toLowerCase() === key);
    if (match) onChange(String(match.id));
  };

  return (
    <>
      <Input
        list="rfm-product-options"
        placeholder="كل الأصناف — اكتب الرمز أو الاسم للتصفية..."
        value={text}
        onChange={(e) => handle(e.target.value)}
      />
      <datalist id="rfm-product-options">
        {products.map((p) => (
          <option key={p.id} value={productOptionLabel(p)} />
        ))}
      </datalist>
    </>
  );
}

const productOptionLabel = (p) => `${p.sku} — ${p.name}`;

const DAMAGE_REASON_LABELS = {
  expired: "منتهي الصلاحية",
  damaged: "تالف",
  spoiled: "فاسد",
  count_shortfall: "نقص عند الجرد",
  other: "أخرى",
};

// 20/80, with the column that makes it a decision instead of a leaderboard.
//
// Every ABC report shows value descending. This one puts what each line *ties up*
// beside what it earns — stock at cost for a product, unpaid balance for a customer —
// because a ranking on its own tells a manager what they already suspected, while the
// pairing tells them where the money is sitting.
//
// The verdict sentence comes from the server rather than being composed here. It is a
// reading of the distribution, including the case where the famous curve simply is
// not present, and that judgement belongs next to the arithmetic that produced it.
const CLASS_TONE = { A: "green", B: "blue", C: "amber", D: "red" };
const CLASS_BAR = {
  A: "#059669",
  B: "#0284c7",
  C: "#d97706",
  D: "#e11d48",
};

// Enough bars to see the elbow, few enough to read the labels. The table below
// carries the full list.
const CHART_ROWS = 30;

function ParetoCard() {
  const [dimension, setDimension] = useState("products");
  const [measure, setMeasure] = useState("revenue");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const report = useFetch(
    () =>
      api.get("/analytics/pareto", {
        params: {
          dimension,
          measure,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        },
      }),
    [dimension, measure, dateFrom, dateTo]
  );

  const data = report.data;
  const isProducts = dimension === "products";
  const carryingLabel = isProducts ? "قيمة المخزون" : "رصيد غير محصَّل";

  const chartRows = (data?.items ?? [])
    .filter((item) => item.rank > 0)
    .slice(0, CHART_ROWS)
    .map((item) => ({
      name: item.code || item.name,
      value: Number(item.value),
      cumulative: Number(item.cumulative_share),
      abc: item.abc_class,
    }));

  const classColumns = [
    {
      key: "label",
      label: "الفئة",
      render: (row) => <Badge tone={CLASS_TONE[row.abc_class]}>{row.label}</Badge>,
    },
    { key: "entities", label: "العدد" },
    { key: "entity_share", label: "% من العدد", render: (row) => `${qty(row.entity_share)}%` },
    { key: "value", label: "القيمة", render: (row) => money(row.value) },
    {
      key: "value_share",
      label: "% من القيمة",
      render: (row) => <span className="font-bold">{qty(row.value_share)}%</span>,
    },
    { key: "carrying_value", label: carryingLabel, render: (row) => money(row.carrying_value) },
    {
      key: "carrying_share",
      label: "% منه",
      // The number the report exists for: what the tail ties up.
      render: (row) => (
        <span className="font-bold text-amber-700 dark:text-amber-400">
          {qty(row.carrying_share)}%
        </span>
      ),
    },
  ];

  const columns = [
    {
      key: "rank",
      label: "#",
      // Class D has no rank; a dash says so rather than a misleading zero.
      render: (row) => (row.rank > 0 ? row.rank : "—"),
      sortValue: (row) => (row.rank > 0 ? row.rank : Number.MAX_SAFE_INTEGER),
    },
    {
      key: "name",
      label: isProducts ? "الصنف" : "العميل",
      render: (row) => (
        <span className="flex flex-col">
          <span>{row.name}</span>
          {row.code ? (
            <span className="text-xs text-slate-500 dark:text-slate-400">{row.code}</span>
          ) : null}
        </span>
      ),
      search: (row) => `${row.name} ${row.code ?? ""}`,
    },
    {
      key: "abc_class",
      label: "الفئة",
      render: (row) => <Badge tone={CLASS_TONE[row.abc_class]}>{row.abc_class}</Badge>,
    },
    {
      key: "value",
      label: measure === "revenue" ? "الإيراد" : "الربح",
      render: (row) => money(row.value),
      sortValue: (row) => Number(row.value),
    },
    {
      key: "share",
      label: "النسبة",
      render: (row) => `${qty(row.share)}%`,
      sortValue: (row) => Number(row.share),
    },
    {
      key: "cumulative_share",
      label: "التراكمي",
      render: (row) => (row.rank > 0 ? `${qty(row.cumulative_share)}%` : "—"),
      sortValue: (row) => Number(row.cumulative_share),
    },
    {
      key: "carrying_value",
      label: carryingLabel,
      render: (row) => money(row.carrying_value),
      sortValue: (row) => Number(row.carrying_value),
    },
    { key: "last_activity", label: "آخر حركة", render: (row) => row.last_activity || "—" },
  ];

  return (
    <Card title="⚖️ تحليل 20/80 — تصنيف أ ب ج">
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Select
          label="المحور"
          value={dimension}
          onChange={(e) => setDimension(e.target.value)}
        >
          <option value="products">الأصناف</option>
          <option value="customers">العملاء</option>
        </Select>
        <Select label="المقياس" value={measure} onChange={(e) => setMeasure(e.target.value)}>
          <option value="revenue">الإيراد</option>
          <option value="profit">الربح الإجمالي</option>
        </Select>
        <Input
          label="من تاريخ"
          type="date"
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
        />
        <Input
          label="إلى تاريخ"
          type="date"
          value={dateTo}
          onChange={(e) => setDateTo(e.target.value)}
        />
      </div>

      <Alert>{report.error}</Alert>

      {report.loading ? (
        <Loading />
      ) : (
        <div className="space-y-5">
          {/* The reading, first and in words. A manager who reads only one line of
              this screen should read the one that names the conclusion. */}
          <div className="rounded-lg border border-sky-200 bg-sky-50 p-4 text-sm font-bold leading-relaxed text-sky-900 dark:border-sky-900 dark:bg-sky-950/50 dark:text-sky-200">
            {data?.verdict}
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-800/60">
              <div className="font-extrabold text-slate-500 dark:text-slate-400">
                {measure === "revenue" ? "إجمالي الإيراد" : "إجمالي الربح"}
              </div>
              <div className="text-lg font-extrabold">{money(data?.total_value)}</div>
            </div>
            <div className="rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-800/60">
              <div className="font-extrabold text-slate-500 dark:text-slate-400">
                {carryingLabel}
              </div>
              <div className="text-lg font-extrabold text-amber-700 dark:text-amber-400">
                {money(data?.total_carrying_value)}
              </div>
            </div>
            <div className="rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-800/60">
              <div className="font-extrabold text-slate-500 dark:text-slate-400">
                حصة الأكبر ١ / ٥ / ١٠
              </div>
              <div className="text-lg font-extrabold">
                {[1, 5, 10]
                  .map((rank) =>
                    data?.top_shares?.[rank] ? `${qty(data.top_shares[rank])}%` : "—"
                  )
                  .join(" · ")}
              </div>
            </div>
          </div>

          {/* Bars for value, a line for the cumulative share: the elbow is where the
              80% is reached, and seeing it is worth more than reading the number. */}
          {chartRows.length ? (
            <div className="h-80 w-full">
              <ResponsiveContainer>
                <ComposedChart data={chartRows} margin={{ top: 10, right: 10, bottom: 60, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#94a3b8" strokeOpacity={0.3} />
                  <XAxis
                    dataKey="name"
                    angle={-45}
                    textAnchor="end"
                    interval={0}
                    height={70}
                    tick={{ fontSize: 10 }}
                  />
                  <YAxis yAxisId="value" tick={{ fontSize: 11 }} />
                  <YAxis
                    yAxisId="cumulative"
                    orientation="right"
                    domain={[0, 100]}
                    unit="%"
                    tick={{ fontSize: 11 }}
                  />
                  <Tooltip
                    formatter={(value, name) =>
                      name === "التراكمي" ? `${value}%` : money(value)
                    }
                  />
                  <Legend />
                  <Bar yAxisId="value" dataKey="value" name="القيمة" radius={[3, 3, 0, 0]}>
                    {chartRows.map((row) => (
                      <Cell key={row.name} fill={CLASS_BAR[row.abc]} />
                    ))}
                  </Bar>
                  <Line
                    yAxisId="cumulative"
                    type="monotone"
                    dataKey="cumulative"
                    name="التراكمي"
                    stroke="#7c3aed"
                    strokeWidth={2}
                    dot={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          ) : null}

          {/* The class summary — the actual finding on this data: class A holds a
              fifth of the stock while D, which sold nothing, holds over half. Four
              rows, but still the shared Table: hand-rolling the markup here would
              have exempted this whole file from the pagination convention check. */}
          <Table
            columns={classColumns}
            rows={data?.classes ?? []}
            keyField="abc_class"
            searchable={false}
            empty="لا توجد فئات لعرضها."
          />

          <Table
            columns={columns}
            rows={data?.items ?? []}
            keyField="entity_id"
            empty="لا توجد بيانات في هذه الفترة."
          />
        </div>
      )}
    </Card>
  );
}


function DiscountReportCard() {
  const navigate = useNavigate();
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const report = useFetch(
    () =>
      api.get("/analytics/sales/discount-report", {
        params: { date_from: dateFrom || undefined, date_to: dateTo || undefined },
      }),
    [dateFrom, dateTo]
  );

  const printReport = () => {
    const params = new URLSearchParams();
    if (dateFrom) params.set("from", dateFrom);
    if (dateTo) params.set("to", dateTo);
    navigate(`/print/discount-report?${params.toString()}`);
  };

  const data = report.data;
  return (
    <Card title="🏷️ تقرير الخصومات الممنوحة — لفترة محددة">
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Input label="من تاريخ" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        <Input label="إلى تاريخ" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        <Button variant="secondary" onClick={printReport}>
          🖨️ طباعة التقرير
        </Button>
      </div>
      <Alert>{report.error}</Alert>
      {report.loading ? (
        <Loading />
      ) : (
        <div className="space-y-5">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
            <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-3 text-sm">
              <div className="font-extrabold text-slate-500 dark:text-slate-400">عدد الفواتير المخصومة</div>
              <div className="text-lg font-extrabold">{data?.invoice_count ?? 0}</div>
            </div>
            <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-3 text-sm">
              <div className="font-extrabold text-slate-500 dark:text-slate-400">إجمالي الخصومات</div>
              <div className="text-lg font-extrabold text-amber-700 dark:text-amber-400">{money(data?.total_discount)}</div>
            </div>
            <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-3 text-sm">
              <div className="font-extrabold text-slate-500 dark:text-slate-400">قبل الخصم</div>
              <div className="text-lg font-extrabold">{money(data?.total_gross)}</div>
            </div>
            <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-3 text-sm">
              <div className="font-extrabold text-slate-500 dark:text-slate-400">صافي المحصّل</div>
              <div className="text-lg font-extrabold text-emerald-700 dark:text-emerald-400">{money(data?.total_net)}</div>
            </div>
          </div>

          <div>
            <h3 className="mb-2 text-sm font-extrabold text-slate-600 dark:text-slate-400">حسب العميل</h3>
            <Table
              columns={[
                { key: "customer_name", label: "العميل" },
                { key: "invoice_count", label: "عدد الفواتير" },
                {
                  key: "discount_amount",
                  label: "إجمالي الخصم",
                  render: (r) => <b className="text-amber-700 dark:text-amber-400">{money(r.discount_amount)}</b>,
                },
              ]}
              rows={data?.by_customer}
              keyField="customer_id"
              empty="لا توجد خصومات في هذه الفترة."
            />
          </div>

          <div>
            <h3 className="mb-2 text-sm font-extrabold text-slate-600 dark:text-slate-400">حسب المندوب</h3>
            <Table
              columns={[
                { key: "salesman_name", label: "المندوب" },
                { key: "invoice_count", label: "عدد الفواتير" },
                {
                  key: "discount_amount",
                  label: "إجمالي الخصم",
                  render: (r) => <b className="text-amber-700 dark:text-amber-400">{money(r.discount_amount)}</b>,
                },
              ]}
              rows={data?.by_salesman}
              keyField={(r) => String(r.salesman_id)}
              empty="لا توجد خصومات في هذه الفترة."
            />
          </div>

          <div>
            <h3 className="mb-2 text-sm font-extrabold text-slate-600 dark:text-slate-400">الفواتير المخصومة</h3>
            <Table
              columns={[
                { key: "invoice_id", label: "#", render: (r) => `#${r.invoice_id}` },
                { key: "invoice_date", label: "التاريخ" },
                { key: "customer_name", label: "العميل" },
                { key: "salesman_name", label: "المندوب", render: (r) => r.salesman_name ?? "—" },
                { key: "gross_amount", label: "قبل الخصم", render: (r) => money(r.gross_amount) },
                {
                  key: "discount_amount",
                  label: "الخصم",
                  render: (r) => <b className="text-amber-700 dark:text-amber-400">{money(r.discount_amount)}</b>,
                },
                { key: "total", label: "المستحق", render: (r) => <b>{money(r.total)}</b> },
              ]}
              rows={data?.invoices}
              keyField="invoice_id"
              empty="لا توجد خصومات في هذه الفترة."
            />
          </div>
        </div>
      )}
    </Card>
  );
}

function DamageReportCard() {
  const navigate = useNavigate();
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const report = useFetch(
    () =>
      api.get("/analytics/inventory/damage-report", {
        params: { date_from: dateFrom || undefined, date_to: dateTo || undefined },
      }),
    [dateFrom, dateTo]
  );

  const printReport = () => {
    const params = new URLSearchParams();
    if (dateFrom) params.set("from", dateFrom);
    if (dateTo) params.set("to", dateTo);
    navigate(`/print/damage-report?${params.toString()}`);
  };

  return (
    <Card title="🗑️ تقرير التالف/الهالك — لفترة محددة">
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Input label="من تاريخ" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        <Input label="إلى تاريخ" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        <Button variant="secondary" onClick={printReport}>
          🖨️ طباعة التقرير
        </Button>
      </div>
      <Alert>{report.error}</Alert>
      {report.loading ? (
        <Loading />
      ) : (
        <div className="space-y-5">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-3 text-sm">
              <div className="font-extrabold text-slate-500 dark:text-slate-400">عدد عمليات الإتلاف</div>
              <div className="text-lg font-extrabold">{report.data?.adjustment_count ?? 0}</div>
            </div>
            <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-3 text-sm">
              <div className="font-extrabold text-slate-500 dark:text-slate-400">إجمالي الكمية</div>
              <div className="text-lg font-extrabold">{qty(report.data?.total_quantity ?? 0)}</div>
            </div>
            <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-3 text-sm">
              <div className="font-extrabold text-slate-500 dark:text-slate-400">إجمالي قيمة الخسارة</div>
              <div className="text-lg font-extrabold text-rose-700 dark:text-rose-400">
                {money(report.data?.total_cost ?? 0)}
              </div>
            </div>
          </div>

          <div>
            <div className="mb-2 text-sm font-extrabold text-slate-600 dark:text-slate-400">حسب السبب</div>
            <Table
              columns={[
                {
                  key: "reason",
                  label: "السبب",
                  render: (r) => (
                    <Badge tone="red">{DAMAGE_REASON_LABELS[r.reason] ?? r.reason}</Badge>
                  ),
                },
                { key: "adjustment_count", label: "عدد العمليات" },
                { key: "total_quantity", label: "الكمية", render: (r) => qty(r.total_quantity) },
                {
                  key: "total_cost",
                  label: "قيمة الخسارة",
                  render: (r) => <b className="text-rose-700 dark:text-rose-400">{money(r.total_cost)}</b>,
                },
              ]}
              rows={report.data?.by_reason}
              keyField="reason"
              empty="لا يوجد تالف في هذه الفترة."
            />
          </div>

          <div>
            <div className="mb-2 text-sm font-extrabold text-slate-600 dark:text-slate-400">حسب الصنف</div>
            <Table
              columns={[
                { key: "product_name", label: "الصنف" },
                {
                  key: "total_quantity",
                  label: "الكمية",
                  render: (r) => `${qty(r.total_quantity)} ${r.base_unit_name}`,
                },
                {
                  key: "total_cost",
                  label: "قيمة الخسارة",
                  render: (r) => <b className="text-rose-700 dark:text-rose-400">{money(r.total_cost)}</b>,
                },
              ]}
              rows={report.data?.by_product}
              keyField="product_id"
              empty="لا يوجد تالف في هذه الفترة."
            />
          </div>
        </div>
      )}
    </Card>
  );
}

function InventoryTab({ expiryRisk, turnover, loading }) {
  if (loading) return <Loading />;
  return (
    <div className="space-y-6">
      <DamageReportCard />
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
              render: (r) => <b className="text-rose-700 dark:text-rose-400">{money(r.value_at_risk)}</b>,
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
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
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

// A call list, not a report. Every row is one phone call, and the columns exist to
// let a rep argue with the flag before dialling: "silent 21 days, usually orders every
// 6" is a fact they can check against what they know about the shop. A screen that
// only said "at risk" would be ignored by the second week.
function LapsingTab({ report, loading }) {
  if (loading) return <Loading />;
  if (!report) return <Loading />;

  const rows = report.items || [];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Kpi label="عملاء توقفوا عن الشراء" value={qty(report.total_customers)} tone="rose" />
        <Kpi
          label="قيمة سنوية معرضة للفقدان"
          value={money(report.annual_value_at_risk)}
          tone="amber"
          hint="مبيعات هؤلاء العملاء سنوياً إن استمروا على وتيرتهم السابقة"
        />
        <Kpi
          label="حد التنبيه"
          // Spelled out rather than "3×": the multiplication sign reorders around the
          // digit under RTL and came out as "×3".
          value={`${report.overdue_multiple} أضعاف`}
          tone="slate"
          hint="يُرصد العميل عند تجاوز صمته ثلاثة أضعاف الفترة المعتادة بين طلباته"
        />
      </div>

      <Card title="قائمة الاتصال — مرتبة حسب حجم ما قد نخسره">
        <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
          يُقاس كل عميل بوتيرته هو، لا بمدة ثابتة للجميع. فالبقالة التي تطلب كل ثلاثة
          أيام وصمتت أسبوعين حالة عاجلة، والفندق الذي يطلب كل شهرين ليس كذلك.
        </p>
        <Table
          columns={[
            { key: "customer_name", label: "العميل" },
            { key: "phone", label: "الهاتف", render: (r) => r.phone || "—" },
            { key: "salesman_name", label: "المندوب", render: (r) => r.salesman_name || "—" },
            {
              key: "silent_days",
              label: "مدة الانقطاع",
              render: (r) => `${r.silent_days} يوم`,
            },
            {
              key: "usual_gap_days",
              label: "المعتاد بين الطلبات",
              render: (r) => `${r.usual_gap_days} يوم`,
            },
            {
              key: "overdue_multiple",
              label: "التأخر عن المعتاد",
              render: (r) => (
                <Badge tone={Number(r.overdue_multiple) >= 6 ? "red" : "amber"}>
                  {r.overdue_multiple} ضعف
                </Badge>
              ),
            },
            { key: "orders_count", label: "عدد الطلبات", render: (r) => qty(r.orders_count) },
            {
              key: "annual_value",
              label: "قيمته السنوية",
              render: (r) => money(r.annual_value),
            },
            { key: "last_order", label: "آخر طلب" },
          ]}
          rows={rows}
          keyField="customer_id"
          empty="لا يوجد عملاء متوقفون — كل العملاء يشترون بوتيرتهم المعتادة."
        />
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
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
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
              render: (r) => <b className="text-rose-700 dark:text-rose-400">{money(r.bucket_90_plus)}</b>,
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
                <div className="text-2xl font-extrabold text-slate-800 dark:text-slate-100">{qty(f.invoice_count)}</div>
                <div className="text-xs font-bold text-slate-500 dark:text-slate-400">إجمالي الفواتير</div>
              </div>
              <div>
                <div className="text-2xl font-extrabold text-emerald-700 dark:text-emerald-400">{qty(f.completed_count)}</div>
                <div className="text-xs font-bold text-slate-500 dark:text-slate-400">مكتملة</div>
              </div>
              <div>
                <div className="text-2xl font-extrabold text-rose-700 dark:text-rose-400">{f.completion_rate_pct}%</div>
                <div className="text-xs font-bold text-slate-500 dark:text-slate-400">نسبة الإنجاز</div>
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
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
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
