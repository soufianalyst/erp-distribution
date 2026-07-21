import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Input,
  Loading,
  Modal,
  PaginatedTable,
  Select,
  Table,
  money,
  qty,
} from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const RETURN_REASONS = [
  { value: "defective", label: "بضاعة تالفة" },
  { value: "wrong_item", label: "بضاعة خاطئة" },
  { value: "excess", label: "فائض كمية" },
  { value: "quality", label: "عدم مطابقة للمواصفات" },
];

const EMPTY_LINE = { product_id: "", product_label: "", batch_number: "", expiry_date: "", quantity: "", unit_id: "", unit_cost: "" };
const EMPTY_RETURN_LINE = { product_id: "", quantity: "", unit_cost: "" };

const productLabel = (p) => `${p.sku} — ${p.name}`;

function PurchaseForm({ suppliers, warehouses, products, onCreated, invoice }) {
  const editing = !!invoice;
  const [form, setForm] = useState(
    editing
      ? {
          supplier_id: String(invoice.supplier_id),
          warehouse_id: String(invoice.warehouse_id),
          payment_method: invoice.payment_method,
          shipping_cost: String(invoice.shipping_cost),
          vat_amount: String(invoice.vat_amount),
          supplier_invoice_number: invoice.supplier_invoice_number ?? "",
        }
      : {
          supplier_id: "",
          warehouse_id: "",
          payment_method: "credit",
          shipping_cost: "0",
          vat_amount: "0",
          supplier_invoice_number: "",
        }
  );
  const [lines, setLines] = useState(
    editing
      ? invoice.lines.map((l) => {
          const product = products.find((p) => p.id === l.product_id);
          return {
            product_id: String(l.product_id),
            product_label: product ? productLabel(product) : "",
            batch_number: l.batch_number,
            expiry_date: l.expiry_date,
            quantity: String(l.quantity),
            unit_id: "",
            unit_cost: String(l.unit_cost),
          };
        })
      : [{ ...EMPTY_LINE }]
  );
  const [error, setError] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const setLine = (index, key, value) =>
    setLines(lines.map((l, i) => (i === index ? { ...l, [key]: value } : l)));

  const setProductLine = (index, value) => {
    const match = products.find((p) => productLabel(p) === value);
    setLines(
      lines.map((l, i) =>
        i === index
          ? { ...l, product_label: value, product_id: match ? String(match.id) : "", unit_id: "" }
          : l
      )
    );
    // Auto-fill warehouse from product's default warehouse if not yet set.
    if (match?.default_warehouse_id && !form.warehouse_id) {
      setForm({ ...form, warehouse_id: String(match.default_warehouse_id) });
    }
  };

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    if (lines.some((l) => l.product_label && !l.product_id)) {
      setError("يجب اختيار صنف صحيح من القائمة لكل سطر.");
      return;
    }
    try {
      const payload = {
        ...form,
        supplier_invoice_number: form.supplier_invoice_number || null,
        lines: lines
          .filter((l) => l.product_id && l.quantity)
          .map(({ product_label, ...l }) => ({ ...l, unit_id: l.unit_id || null })),
      };
      const { data } = editing
        ? await api.put(`/purchases/invoices/${invoice.id}`, payload)
        : await api.post("/purchases/invoices", payload);
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
            <span className="text-xs font-normal text-slate-400 mr-2">
              (Tab في آخر حقل يضيف سطراً جديداً)
            </span>
          </span>
          <Button type="button" variant="secondary" onClick={() => setLines([...lines, { ...EMPTY_LINE }])}>
            + سطر
          </Button>
        </div>

        <datalist id="purchase-products">
          {products.map((p) => (
            <option key={p.id} value={productLabel(p)} />
          ))}
        </datalist>

        {lines.map((line, index) => {
          const product = products.find((p) => String(p.id) === String(line.product_id));
          return (
            <div key={index} className="mb-2 grid grid-cols-12 items-end gap-2">
              <div className="col-span-3">
                <Input
                  label={index === 0 ? "الصنف (اكتب للبحث)" : undefined}
                  list="purchase-products"
                  placeholder="ابحث بالرمز أو الاسم..."
                  value={line.product_label ?? ""}
                  onChange={(e) => setProductLine(index, e.target.value)}
                  required
                />
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
                  onKeyDown={(e) => {
                    if (
                      e.key === "Tab" &&
                      !e.shiftKey &&
                      index === lines.length - 1 &&
                      line.product_id &&
                      line.quantity &&
                      line.unit_cost
                    ) {
                      setLines([...lines, { ...EMPTY_LINE }]);
                    }
                  }}
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

      <Button type="submit">{editing ? "حفظ التعديلات" : "تثبيت الفاتورة وإدخال البضاعة"}</Button>
    </form>
  );
}

function PurchaseReturnForm({ suppliers, products, onCreated }) {
  const [form, setForm] = useState({
    invoice_id: "",
    reason: "defective",
    vat_amount: "0",
    notes: "",
  });
  const [lines, setLines] = useState([{ ...EMPTY_RETURN_LINE }]);
  const [error, setError] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const setLine = (index, key, value) =>
    setLines(lines.map((l, i) => (i === index ? { ...l, [key]: value } : l)));

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    const validLines = lines.filter((l) => l.product_id && l.quantity);
    if (!form.invoice_id) {
      setError("يجب تحديد فاتورة الشراء الأصلية.");
      return;
    }
    if (validLines.length === 0) {
      setError("يجب إضافة صنف واحد على الأقل.");
      return;
    }
    try {
      const { data } = await api.post("/purchases/returns", {
        invoice_id: parseInt(form.invoice_id),
        reason: form.reason,
        vat_amount: parseFloat(form.vat_amount || "0"),
        notes: form.notes || null,
        lines: validLines.map((l) => ({
          product_id: parseInt(l.product_id),
          quantity: parseFloat(l.quantity),
          unit_cost: parseFloat(l.unit_cost || "0"),
        })),
      });
      setForm({ invoice_id: "", reason: "defective", vat_amount: "0", notes: "" });
      setLines([{ ...EMPTY_RETURN_LINE }]);
      onCreated(data.data);
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Alert>{error}</Alert>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Input label="رقم فاتورة الشراء" type="number" min="1" value={form.invoice_id} onChange={set("invoice_id")} required />
        <Select label="سبب المرتجع" value={form.reason} onChange={set("reason")}>
          {RETURN_REASONS.map((r) => (
            <option key={r.value} value={r.value}>{r.label}</option>
          ))}
        </Select>
        <Input label="ضريبة القيمة المضافة" type="number" step="0.01" min="0" value={form.vat_amount} onChange={set("vat_amount")} />
        <Input label="ملاحظات" value={form.notes} onChange={set("notes")} />
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-bold text-slate-600">أسطر المرتجع</span>
          <Button type="button" variant="secondary" onClick={() => setLines([...lines, { ...EMPTY_RETURN_LINE }])}>+ سطر</Button>
        </div>
        {lines.map((line, index) => (
          <div key={index} className="mb-2 grid grid-cols-12 items-end gap-2">
            <div className="col-span-5">
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
            <div className="col-span-3">
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
            <div className="col-span-3">
              <Input
                label={index === 0 ? "تكلفة الوحدة" : undefined}
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
                <Button type="button" variant="danger" onClick={() => setLines(lines.filter((_, i) => i !== index))}>×</Button>
              )}
            </div>
          </div>
        ))}
      </div>
      <Button type="submit">تسجيل المرتجع</Button>
    </form>
  );
}

export default function PurchasesPage() {
  const { can } = useAuth();
  const canBuy = can("purchases.create");
  const canReturn = can("purchases.returns");
  const [tab, setTab] = useState("list");
  const [viewing, setViewing] = useState(null);
  const [editing, setEditing] = useState(null);
  const [notice, setNotice] = useState(null);

  const invoices = useFetch(() => api.get("/purchases/invoices"));
  const suppliers = useFetch(() => api.get("/purchases/suppliers"));
  const warehouses = useFetch(() => api.get("/inventory/warehouses"));
  const products = useFetch(() => api.get("/inventory/products", { params: { is_active: true } }));
  const returns = useFetch(() => api.get("/purchases/returns"));

  if (suppliers.loading || warehouses.loading || products.loading) return <Loading />;

  return (
    <div className="space-y-6">
      {notice && <Alert>{notice}</Alert>}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-extrabold">فواتير المشتريات</h1>
        <div className="flex gap-2">
          <Button variant={tab === "list" ? "primary" : "secondary"} onClick={() => setTab("list")}>
            الفواتير
          </Button>
          {canBuy && (
            <Button variant={tab === "new" ? "primary" : "secondary"} onClick={() => setTab("new")}>
              + فاتورة جديدة
            </Button>
          )}
          {canReturn && (
            <Button variant={tab === "returns" ? "primary" : "secondary"} onClick={() => setTab("returns")}>
              المرتجعات
            </Button>
          )}
        </div>
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
      ) : tab === "returns" && canReturn ? (
        <Card title="مرتجعات الشراء — إرجاع بضاعة للمورد وتعديل المخزون">
          <PurchaseReturnForm
            suppliers={suppliers.data}
            products={products.data}
            onCreated={() => {
              setNotice("تم تسجيل المرتجع بنجاح.");
              returns.reload();
              invoices.reload();
            }}
          />
          <div className="mt-6">
            <h3 className="mb-3 text-lg font-extrabold">المرتجعات المسجلة</h3>
            <Alert>{returns.error}</Alert>
            {returns.loading ? (
              <Loading />
            ) : (
              <PaginatedTable
                columns={[
                  { key: "id", label: "#" },
                  { key: "created_at", label: "التاريخ", render: (r) => r.created_at?.slice(0, 10) || "" },
                  { key: "invoice_id", label: "فاتورة #" },
                  {
                    key: "supplier_id",
                    label: "المورد",
                    render: (r) => suppliers.data.find((s) => s.id === r.supplier_id)?.name ?? r.supplier_id,
                  },
                  {
                    key: "reason",
                    label: "السبب",
                    render: (r) => {
                      const found = RETURN_REASONS.find((rr) => rr.value === r.reason);
                      return <Badge tone="amber">{found ? found.label : r.reason}</Badge>;
                    },
                  },
                  {
                    key: "total",
                    label: "الإجمالي",
                    render: (r) => <b className="text-rose-700">{money(r.total)}</b>,
                  },
                ]}
                rows={returns.data}
                empty="لا توجد مرتجعات مسجلة."
                searchable
                searchPlaceholder="بحث بالمورد..."
              />
            )}
          </div>
        </Card>
      ) : (
        <Card>
          <Alert>{invoices.error}</Alert>
          {invoices.loading ? (
            <Loading />
          ) : (
            <PaginatedTable
              columns={[
                { key: "id", label: "#" },
                { key: "invoice_date", label: "التاريخ" },
                { key: "supplier_id", label: "المورد", render: (r) => suppliers.data.find((s) => s.id === r.supplier_id)?.name ?? r.supplier_id, searchable: (r) => suppliers.data.find((s) => s.id === r.supplier_id)?.name ?? "" },
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
              searchable
              searchPlaceholder="بحث بالمورد أو رقم الفاتورة..."
              filterField="payment_method"
              filterLabel="طريقة الدفع"
              filterOptions={[
                { value: "cash", label: "نقدي" },
                { value: "credit", label: "آجل" },
              ]}
              dateFromField="invoice_date"
              dateToField="invoice_date"
              amountField="total"
              amountLabel="الإجمالي"
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
          <div className="space-y-4">
            <Table
              columns={[
                {
                  key: "product_id",
                  label: "الصنف",
                  render: (r) => products.data.find((p) => p.id === r.product_id)?.name ?? r.product_id,
                },
                { key: "batch_number", label: "التشغيليلة" },
                { key: "expiry_date", label: "الانتهاء" },
                { key: "quantity", label: "الكمية", render: (r) => qty(r.quantity) },
                { key: "unit_cost", label: "تكلفة الوحدة", render: (r) => money(r.unit_cost) },
                { key: "line_total", label: "الإجمالي", render: (r) => money(r.line_total) },
              ]}
              rows={viewing.lines}
            />
            <div className="flex items-center justify-between border-t border-slate-200 pt-3">
              <div className="flex gap-2">
                {can("purchases.edit") && (
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setEditing(viewing);
                      setViewing(null);
                    }}
                  >
                    تعديل
                  </Button>
                )}
                {can("purchases.delete") && (
                  <Button
                    variant="danger"
                    onClick={async () => {
                      if (
                        !window.confirm(
                          `حذف فاتورة الشراء رقم ${viewing.id} نهائياً؟ سيُعاد المخزون وتُحذف قيودها المحاسبية.`
                        )
                      )
                        return;
                      try {
                        await api.delete(`/purchases/invoices/${viewing.id}`);
                        setViewing(null);
                        setNotice(`تم حذف الفاتورة رقم ${viewing.id} وإعادة المخزون.`);
                        invoices.reload();
                      } catch (err) {
                        alert(apiMessage(err));
                      }
                    }}
                  >
                    حذف
                  </Button>
                )}
              </div>
              <div className="flex gap-6 text-sm font-bold">
                <span>البضاعة: {money(viewing.subtotal)}</span>
                <span>الشحن: {money(viewing.shipping_cost)}</span>
                <span>الضريبة: {money(viewing.vat_amount)}</span>
                <span className="text-emerald-700">الإجمالي: {money(viewing.total)}</span>
              </div>
            </div>
          </div>
        )}
      </Modal>

      <Modal
        open={!!editing}
        title={editing ? `تعديل فاتورة الشراء رقم ${editing.id}` : ""}
        onClose={() => setEditing(null)}
        wide
      >
        {editing && (
          <PurchaseForm
            invoice={editing}
            suppliers={suppliers.data}
            warehouses={warehouses.data}
            products={products.data}
            onCreated={(invoice) => {
              setEditing(null);
              setViewing(invoice);
              setNotice(`تم تعديل فاتورة الشراء رقم ${invoice.id} وإعادة احتساب المخزون والقيود.`);
              invoices.reload();
            }}
          />
        )}
      </Modal>
    </div>
  );
}
