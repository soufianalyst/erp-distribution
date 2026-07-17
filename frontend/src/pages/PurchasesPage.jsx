import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Input,
  Loading,
  Modal,
  Select,
  Table,
  money,
  qty,
} from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const EMPTY_LINE = { product_id: "", batch_number: "", expiry_date: "", quantity: "", unit_id: "", unit_cost: "" };

function PurchaseForm({ suppliers, warehouses, products, onCreated }) {
  const [form, setForm] = useState({
    supplier_id: "",
    warehouse_id: "",
    payment_method: "credit",
    shipping_cost: "0",
    vat_amount: "0",
    supplier_invoice_number: "",
  });
  const [lines, setLines] = useState([{ ...EMPTY_LINE }]);
  const [error, setError] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const setLine = (index, key, value) =>
    setLines(lines.map((l, i) => (i === index ? { ...l, [key]: value } : l)));

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      const { data } = await api.post("/purchases/invoices", {
        ...form,
        supplier_invoice_number: form.supplier_invoice_number || null,
        lines: lines
          .filter((l) => l.product_id && l.quantity)
          .map((l) => ({ ...l, unit_id: l.unit_id || null })),
      });
      onCreated(data.data);
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Alert>{error}</Alert>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Select label="المورد" value={form.supplier_id} onChange={set("supplier_id")} required>
          <option value="">— اختر المورد —</option>
          {suppliers.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </Select>
        <Select label="المستودع المستلم" value={form.warehouse_id} onChange={set("warehouse_id")} required>
          <option value="">— اختر المستودع —</option>
          {warehouses.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </Select>
        <Select label="طريقة الدفع" value={form.payment_method} onChange={set("payment_method")}>
          <option value="credit">آجل</option>
          <option value="cash">نقدي</option>
        </Select>
        <Input label="رقم فاتورة المورد (اختياري)" value={form.supplier_invoice_number} onChange={set("supplier_invoice_number")} />
        <Input label="تكلفة الشحن" type="number" step="0.01" min="0" value={form.shipping_cost} onChange={set("shipping_cost")} />
        <Input label="ضريبة القيمة المضافة" type="number" step="0.01" min="0" value={form.vat_amount} onChange={set("vat_amount")} />
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-bold text-slate-600">
            أسطر الفاتورة — رقم التشغيلة وتاريخ الانتهاء إلزاميان لكل سطر
          </span>
          <Button type="button" variant="secondary" onClick={() => setLines([...lines, { ...EMPTY_LINE }])}>
            + سطر
          </Button>
        </div>
        {lines.map((line, index) => {
          const product = products.find((p) => String(p.id) === String(line.product_id));
          return (
            <div key={index} className="mb-2 grid grid-cols-12 items-end gap-2">
              <div className="col-span-3">
                <Select
                  label={index === 0 ? "الصنف" : undefined}
                  value={line.product_id}
                  onChange={(e) => setLine(index, "product_id", e.target.value)}
                  required
                >
                  <option value="">—</option>
                  {products.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.sku} — {p.name}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="col-span-2">
                <Input
                  label={index === 0 ? "التشغيلة" : undefined}
                  value={line.batch_number}
                  onChange={(e) => setLine(index, "batch_number", e.target.value)}
                  required
                />
              </div>
              <div className="col-span-2">
                <Input
                  label={index === 0 ? "تاريخ الانتهاء" : undefined}
                  type="date"
                  value={line.expiry_date}
                  onChange={(e) => setLine(index, "expiry_date", e.target.value)}
                  required
                />
              </div>
              <div className="col-span-1">
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
                <Select
                  label={index === 0 ? "الوحدة" : undefined}
                  value={line.unit_id}
                  onChange={(e) => setLine(index, "unit_id", e.target.value)}
                >
                  {product ? (
                    <>
                      <option value="">{product.base_unit_name}</option>
                      {product.units.map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.name}
                        </option>
                      ))}
                    </>
                  ) : (
                    <option value="">—</option>
                  )}
                </Select>
              </div>
              <div className="col-span-1">
                <Input
                  label={index === 0 ? "سعر الشراء" : undefined}
                  type="number"
                  step="any"
                  min="0"
                  value={line.unit_cost}
                  onChange={(e) => setLine(index, "unit_cost", e.target.value)}
                  required
                />
              </div>
              <div className="col-span-1">
                {lines.length > 1 && (
                  <Button type="button" variant="danger" onClick={() => setLines(lines.filter((_, i) => i !== index))}>
                    ×
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <Button type="submit">تثبيت الفاتورة وإدخال البضاعة</Button>
    </form>
  );
}

export default function PurchasesPage() {
  const { can } = useAuth();
  const canBuy = can("purchases.create");
  const [tab, setTab] = useState("list");
  const [viewing, setViewing] = useState(null);

  const invoices = useFetch(() => api.get("/purchases/invoices"));
  const suppliers = useFetch(() => api.get("/purchases/suppliers"));
  const warehouses = useFetch(() => api.get("/inventory/warehouses"));
  const products = useFetch(() => api.get("/inventory/products"));

  if (suppliers.loading || warehouses.loading || products.loading) return <Loading />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-extrabold">فواتير المشتريات</h1>
        {canBuy && (
          <div className="flex gap-2">
            <Button variant={tab === "list" ? "primary" : "secondary"} onClick={() => setTab("list")}>
              القائمة
            </Button>
            <Button variant={tab === "new" ? "primary" : "secondary"} onClick={() => setTab("new")}>
              + فاتورة جديدة
            </Button>
          </div>
        )}
      </div>

      {tab === "new" && canBuy ? (
        <Card title="فاتورة شراء جديدة — تُدخل البضاعة للمخزون في عملية واحدة">
          <PurchaseForm
            suppliers={suppliers.data}
            warehouses={warehouses.data}
            products={products.data}
            onCreated={(invoice) => {
              setViewing(invoice);
              setTab("list");
              invoices.reload();
            }}
          />
        </Card>
      ) : (
        <Card>
          <Alert>{invoices.error}</Alert>
          {invoices.loading ? (
            <Loading />
          ) : (
            <Table
              columns={[
                { key: "id", label: "#" },
                { key: "invoice_date", label: "التاريخ" },
                { key: "supplier_id", label: "المورد", render: (r) => suppliers.data.find((s) => s.id === r.supplier_id)?.name ?? r.supplier_id },
                {
                  key: "payment_method",
                  label: "الدفع",
                  render: (r) =>
                    r.payment_method === "cash" ? <Badge tone="green">نقدي</Badge> : <Badge tone="amber">آجل</Badge>,
                },
                { key: "subtotal", label: "البضاعة", render: (r) => money(r.subtotal) },
                { key: "shipping_cost", label: "الشحن", render: (r) => money(r.shipping_cost) },
                { key: "total", label: "الإجمالي", render: (r) => <b>{money(r.total)}</b> },
                {
                  key: "view",
                  label: "",
                  render: (r) => (
                    <Button variant="secondary" onClick={() => setViewing(r)}>
                      عرض
                    </Button>
                  ),
                },
              ]}
              rows={invoices.data}
              empty="لا توجد فواتير مشتريات بعد."
            />
          )}
        </Card>
      )}

      <Modal
        open={!!viewing}
        title={viewing ? `فاتورة شراء رقم ${viewing.id}` : ""}
        onClose={() => setViewing(null)}
        wide
      >
        {viewing && (
          <Table
            columns={[
              {
                key: "product_id",
                label: "الصنف",
                render: (r) => products.data.find((p) => p.id === r.product_id)?.name ?? r.product_id,
              },
              { key: "batch_number", label: "التشغيلة" },
              { key: "expiry_date", label: "الانتهاء" },
              { key: "quantity", label: "الكمية", render: (r) => qty(r.quantity) },
              { key: "unit_cost", label: "تكلفة الوحدة", render: (r) => money(r.unit_cost) },
              { key: "line_total", label: "الإجمالي", render: (r) => money(r.line_total) },
            ]}
            rows={viewing.lines}
          />
        )}
      </Modal>
    </div>
  );
}
