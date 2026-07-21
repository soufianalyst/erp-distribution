import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Input,
  Loading,
  PaginatedTable,
  Select,
  Table,
  money,
  qty,
} from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const ADJ_REASON_OPTIONS = [
  "جرد ميداني",
  "تالف",
  "فائض",
  "نقص",
  "تعديل يدوي",
];

function UnitOptions({ product }) {
  if (!product) return null;
  return (
    <>
      <option value="">{product.base_unit_name} (أساسية)</option>
      {product.units.map((u) => (
        <option key={u.id} value={u.id}>
          {u.name} = {Number(u.factor)} {product.base_unit_name}
        </option>
      ))}
    </>
  );
}

function ReceiveForm({ products, warehouses, onDone }) {
  const [form, setForm] = useState({
    product_id: "",
    warehouse_id: "",
    batch_number: "",
    expiry_date: "",
    quantity: "",
    unit_id: "",
  });
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const product = products.find((p) => String(p.id) === form.product_id);

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    try {
      const { data } = await api.post("/inventory/stock/receive", {
        ...form,
        unit_id: form.unit_id || null,
      });
      setSuccess(data.message);
      setForm({ ...form, batch_number: "", expiry_date: "", quantity: "" });
      onDone();
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Alert>{error}</Alert>
      <Alert tone="success">{success}</Alert>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Select label="الصنف" value={form.product_id} onChange={set("product_id")} required>
          <option value="">— اختر الصنف —</option>
          {products.map((p) => (
            <option key={p.id} value={p.id}>
              {p.sku} — {p.name}
            </option>
          ))}
        </Select>
        <Select label="المستودع" value={form.warehouse_id} onChange={set("warehouse_id")} required>
          <option value="">— اختر المستودع —</option>
          {warehouses.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </Select>
        <Input label="رقم التشغيلة (إلزامي)" value={form.batch_number} onChange={set("batch_number")} required />
        <Input label="تاريخ الانتهاء (إلزامي)" type="date" value={form.expiry_date} onChange={set("expiry_date")} required />
        <Input label="الكمية" type="number" step="any" min="0.001" value={form.quantity} onChange={set("quantity")} required />
        <Select label="وحدة القياس" value={form.unit_id} onChange={set("unit_id")}>
          <UnitOptions product={product} />
        </Select>
      </div>
      <Button type="submit">استلام البضاعة</Button>
    </form>
  );
}

function TransferForm({ products, warehouses, onDone }) {
  const [form, setForm] = useState({
    product_id: "",
    from_warehouse_id: "",
    to_warehouse_id: "",
    quantity: "",
    unit_id: "",
  });
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const product = products.find((p) => String(p.id) === form.product_id);

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    setResult(null);
    try {
      const { data } = await api.post("/inventory/stock/transfer", {
        ...form,
        unit_id: form.unit_id || null,
      });
      setResult(data.data);
      onDone();
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Alert>{error}</Alert>
      {result && (
        <Alert tone="success">
          تم التحويل حسب FEFO:{" "}
          {result.map((m) => `${m.batch_number} (${qty(m.quantity)})`).join("، ")}
        </Alert>
      )}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Select label="الصنف" value={form.product_id} onChange={set("product_id")} required>
          <option value="">— اختر الصنف —</option>
          {products.map((p) => (
            <option key={p.id} value={p.id}>
              {p.sku} — {p.name}
            </option>
          ))}
        </Select>
        <Select label="من مستودع" value={form.from_warehouse_id} onChange={set("from_warehouse_id")} required>
          <option value="">—</option>
          {warehouses.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </Select>
        <Select label="إلى مستودع" value={form.to_warehouse_id} onChange={set("to_warehouse_id")} required>
          <option value="">—</option>
          {warehouses.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </Select>
        <Input label="الكمية" type="number" step="any" min="0.001" value={form.quantity} onChange={set("quantity")} required />
        <Select label="وحدة القياس" value={form.unit_id} onChange={set("unit_id")}>
          <UnitOptions product={product} />
        </Select>
      </div>
      <Button type="submit">تحويل البضاعة</Button>
    </form>
  );
}

function AdjustmentForm({ products, warehouses, onDone }) {
  const [form, setForm] = useState({
    warehouse_id: "",
    adjustment_type: "increase",
    reason: "",
    adjustment_date: "",
  });
  const [lines, setLines] = useState([
    { product_id: "", quantity: "", unit_cost: "", notes: "" },
  ]);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const setLine = (index, key, value) =>
    setLines(lines.map((l, i) => (i === index ? { ...l, [key]: value } : l)));

  const addLine = () => setLines([...lines, { product_id: "", quantity: "", unit_cost: "", notes: "" }]);
  const removeLine = (index) => setLines(lines.filter((_, i) => i !== index));

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    const validLines = lines.filter((l) => l.product_id && l.quantity);
    if (validLines.length === 0) {
      setError("يجب إضافة سطر واحد على الأقل.");
      return;
    }
    try {
      const payload = {
        ...form,
        adjustment_date: form.adjustment_date || null,
        lines: validLines.map((l) => ({
          product_id: parseInt(l.product_id),
          quantity: parseFloat(l.quantity),
          unit_cost: parseFloat(l.unit_cost || "0"),
          notes: l.notes || null,
        })),
      };
      const { data } = await api.post("/inventory/stock/adjustments", payload);
      setSuccess(data.message);
      setForm({ warehouse_id: "", adjustment_type: "increase", reason: "", adjustment_date: "" });
      setLines([{ product_id: "", quantity: "", unit_cost: "", notes: "" }]);
      onDone();
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Alert>{error}</Alert>
      <Alert tone="success">{success}</Alert>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Select label="المستودع" value={form.warehouse_id} onChange={set("warehouse_id")} required>
          <option value="">— اختر المستودع —</option>
          {warehouses.map((w) => (
            <option key={w.id} value={w.id}>{w.name}</option>
          ))}
        </Select>
        <Select label="نوع التعديل" value={form.adjustment_type} onChange={set("adjustment_type")}>
          <option value="increase">زيادة (+)</option>
          <option value="decrease">تخفيض (−)</option>
        </Select>
        <Input label="سبب التعديل (إلزامي)" value={form.reason} onChange={set("reason")} required />
        <Input label="تاريخ التعديل" type="date" value={form.adjustment_date} onChange={set("adjustment_date")} />
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-bold text-slate-600">أسطر التعديل</span>
          <Button type="button" variant="secondary" onClick={addLine}>+ سطر</Button>
        </div>
        {lines.map((line, index) => (
          <div key={index} className="mb-2 grid grid-cols-12 items-end gap-2">
            <div className="col-span-4">
              <Select
                label={index === 0 ? "الصنف" : undefined}
                value={line.product_id}
                onChange={(e) => setLine(index, "product_id", e.target.value)}
                required
              >
                <option value="">— اختر الصنف —</option>
                {products.map((p) => (
                  <option key={p.id} value={p.id}>{p.sku} — {p.name}</option>
                ))}
              </Select>
            </div>
            <div className="col-span-2">
              <Input
                label={index === 0 ? "الكمية" : undefined}
                type="number"
                step="any"
                min="0.001"
                value={line.quantity}
                onChange={(e) => setLine(index, "quantity", e.target.value)}
                required
              />
            </div>
            <div className="col-span-2">
              <Input
                label={index === 0 ? "سعر الوحدة" : undefined}
                type="number"
                step="any"
                min="0"
                value={line.unit_cost}
                onChange={(e) => setLine(index, "unit_cost", e.target.value)}
              />
            </div>
            <div className="col-span-3">
              <Input
                label={index === 0 ? "ملاحظات" : undefined}
                value={line.notes}
                onChange={(e) => setLine(index, "notes", e.target.value)}
              />
            </div>
            <div className="col-span-1">
              {lines.length > 1 && (
                <Button type="button" variant="danger" onClick={() => removeLine(index)}>×</Button>
              )}
            </div>
          </div>
        ))}
      </div>
      <Button type="submit">تسجيل التعديل</Button>
    </form>
  );
}

export default function StockPage() {
  const { can } = useAuth();
  const canReceive = can("stock.receive");
  const canTransfer = can("stock.transfer");
  const canAdjust = can("stock.adjust");
  const [tab, setTab] = useState("levels");

  const products = useFetch(() => api.get("/inventory/products"));
  const warehouses = useFetch(() => api.get("/inventory/warehouses"));
  const levels = useFetch(() => api.get("/inventory/stock/levels"));
  const nearExpiry = useFetch(() => api.get("/inventory/stock/near-expiry", { params: { days: 60 } }));
  const adjustments = useFetch(() => api.get("/inventory/stock/adjustments"));

  const reloadAll = () => {
    levels.reload();
    nearExpiry.reload();
    adjustments.reload();
  };

  const TABS = [
    { id: "levels", label: "الأرصدة" },
    ...(canReceive ? [{ id: "receive", label: "استلام بضاعة" }] : []),
    ...(canTransfer ? [{ id: "transfer", label: "تحويل بين المستودعات" }] : []),
    ...(canAdjust ? [{ id: "adjust", label: "تعديل المخزون" }] : []),
    { id: "expiry", label: "قرب الانتهاء" },
  ];

  if (products.loading || warehouses.loading) return <Loading />;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold">حركة المخزون</h1>
      <div className="flex gap-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`rounded-lg px-4 py-2 text-sm font-bold ${
              tab === t.id ? "bg-emerald-700 text-white" : "bg-white text-slate-600 hover:bg-slate-50"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "levels" && (
        <Card title="أرصدة المخزون حسب الصنف والمستودع">
          <Alert>{levels.error}</Alert>
          {levels.loading ? (
            <Loading />
          ) : (
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
              searchable
              searchPlaceholder="بحث بالصنف أو المستودع..."
            />
          )}
        </Card>
      )}

      {tab === "receive" && canReceive && (
        <Card title="استلام بضاعة — لا استلام دون رقم تشغيلة وتاريخ انتهاء">
          <ReceiveForm products={products.data} warehouses={warehouses.data} onDone={reloadAll} />
        </Card>
      )}

      {tab === "transfer" && canTransfer && (
        <Card title="تحويل بضاعة — يتم اختيار التشغيلات الأقرب انتهاءً أولاً (FEFO)">
          <TransferForm products={products.data} warehouses={warehouses.data} onDone={reloadAll} />
        </Card>
      )}

      {tab === "adjust" && canAdjust && (
        <>
          <Card title="تسجيل تعديل مخزون (زيادة أو تخفيض)">
            <AdjustmentForm products={products.data} warehouses={warehouses.data} onDone={reloadAll} />
          </Card>
          <Card title="حركات التعديلات المسجلة">
            <Alert>{adjustments.error}</Alert>
            {adjustments.loading ? (
              <Loading />
            ) : (
              <PaginatedTable
                columns={[
                  { key: "id", label: "#" },
                  { key: "adjustment_date", label: "التاريخ" },
                  {
                    key: "adjustment_type",
                    label: "النوع",
                    render: (r) =>
                      r.adjustment_type === "increase" ? (
                        <Badge tone="green">زيادة (+)</Badge>
                      ) : (
                        <Badge tone="red">تخفيض (−)</Badge>
                      ),
                  },
                  { key: "reason", label: "السبب" },
                  {
                    key: "lines",
                    label: "الأصناف",
                    render: (r) =>
                      r.lines
                        ? r.lines.map((l) => `${l.product_id} × ${qty(l.quantity)}`).join(", ")
                        : "",
                  },
                ]}
                rows={adjustments.data}
                empty="لا توجد تعديلات مسجلة."
                searchable
                searchPlaceholder="بحث بالسبب..."
              />
            )}
          </Card>
        </>
      )}

      {tab === "expiry" && (
        <Card title="التشغيلات القريبة من الانتهاء (60 يوم)">
          {nearExpiry.loading ? (
            <Loading />
          ) : (
            <PaginatedTable
              columns={[
                { key: "product_name", label: "الصنف" },
                { key: "warehouse_name", label: "المستودع" },
                { key: "batch_number", label: "التشغيليلة" },
                { key: "expiry_date", label: "تاريخ الانتهاء" },
                { key: "quantity", label: "الكمية", render: (r) => qty(r.quantity) },
                {
                  key: "days_remaining",
                  label: "المتبقي",
                  render: (r) =>
                    r.days_remaining < 0 ? (
                      <Badge tone="red">منتهية</Badge>
                    ) : (
                      <Badge tone="amber">{r.days_remaining} يوم</Badge>
                    ),
                },
              ]}
              rows={nearExpiry.data}
              keyField="batch_id"
              empty="لا توجد تشغيلات قريبة الانتهاء."
              searchable
              searchPlaceholder="بحث بالصنف أو التشغيلة..."
            />
          )}
        </Card>
      )}
    </div>
  );
}
