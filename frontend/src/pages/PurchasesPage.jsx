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

const PAYMENT_METHOD_LABELS = { cash: "نقدي", card: "بطاقة", credit: "آجل" };
const PAYMENT_METHOD_TONE = { cash: "green", card: "blue", credit: "amber" };

// Record-keeping only — goods always leave the warehouse back to the supplier
// regardless of reason (unlike sales returns, there is no "resellable" branch).
export const PURCHASE_RETURN_REASON_LABELS = {
  defective: "تالف / معيب",
  wrong_item: "صنف خاطئ",
  excess: "فائض عن الحاجة",
  other: "أخرى",
};

function PurchaseForm({ suppliers, warehouses, products, taxRates, onCreated, invoice }) {
  const editing = !!invoice;
  const defaultTaxRate = taxRates.find((t) => t.is_default);
  const [form, setForm] = useState(
    editing
      ? {
          supplier_id: String(invoice.supplier_id),
          warehouse_id: String(invoice.warehouse_id),
          payment_method: invoice.payment_method,
          shipping_cost: String(invoice.shipping_cost),
          tax_rate_ids: invoice.taxes.map((t) => t.tax_rate_id).filter((id) => id != null),
          supplier_invoice_number: invoice.supplier_invoice_number || "",
          invoice_date: invoice.invoice_date,
        }
      : {
          supplier_id: "",
          warehouse_id: "",
          payment_method: "credit",
          shipping_cost: "0",
          tax_rate_ids: defaultTaxRate ? [defaultTaxRate.id] : [],
          supplier_invoice_number: "",
        }
  );
  const [lines, setLines] = useState(
    editing
      ? invoice.lines.map((l) => ({
          product_id: String(l.product_id),
          batch_number: l.batch_number,
          expiry_date: l.expiry_date,
          quantity: String(l.quantity),
          unit_id: "",
          unit_cost: String(l.unit_cost),
        }))
      : [{ ...EMPTY_LINE }]
  );
  const [error, setError] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const toggleTax = (taxId) =>
    setForm((f) => ({
      ...f,
      tax_rate_ids: f.tax_rate_ids.includes(taxId)
        ? f.tax_rate_ids.filter((id) => id !== taxId)
        : [...f.tax_rate_ids, taxId],
    }));
  const setLine = (index, key, value) =>
    setLines(lines.map((l, i) => (i === index ? { ...l, [key]: value } : l)));

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    const payload = {
      ...form,
      supplier_invoice_number: form.supplier_invoice_number || null,
      lines: lines
        .filter((l) => l.product_id && l.quantity)
        .map((l) => ({ ...l, unit_id: l.unit_id || null })),
    };
    try {
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
          <option value="card">بطاقة</option>
        </Select>
        <Input label="رقم فاتورة المورد (اختياري)" value={form.supplier_invoice_number} onChange={set("supplier_invoice_number")} />
        <Input label="تكلفة الشحن" type="number" step="0.01" min="0" value={form.shipping_cost} onChange={set("shipping_cost")} />
      </div>

      <div>
        <span className="mb-1 block text-sm font-bold text-slate-600">
          الضرائب المطبّقة (يمكن اختيار أكثر من ضريبة)
        </span>
        <div className="flex flex-wrap gap-3 rounded-lg border border-slate-300 bg-white p-3">
          {taxRates.filter((t) => t.is_active).length === 0 && (
            <span className="text-sm text-slate-400">لا توجد ضرائب مفعّلة.</span>
          )}
          {taxRates
            .filter((t) => t.is_active)
            .map((t) => (
              <label key={t.id} className="flex items-center gap-2 text-sm font-bold text-slate-700">
                <input
                  type="checkbox"
                  checked={form.tax_rate_ids.includes(t.id)}
                  onChange={() => toggleTax(t.id)}
                />
                {t.name} ({t.rate}%)
              </label>
            ))}
        </div>
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
                  {products
                    .filter((p) => p.is_active || String(p.id) === String(line.product_id))
                    .map((p) => (
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

      <Button type="submit">{editing ? "حفظ التعديلات" : "تثبيت الفاتورة وإدخال البضاعة"}</Button>
    </form>
  );
}

function PurchaseReturnForm({ invoice, products, onDone }) {
  // Aggregate the invoice's batch lines into per-product received totals.
  const receivedByProduct = {};
  for (const line of invoice.lines) {
    receivedByProduct[line.product_id] =
      (receivedByProduct[line.product_id] || 0) + Number(line.quantity);
  }
  const productIds = Object.keys(receivedByProduct);

  const [reason, setReason] = useState("defective");
  const [quantities, setQuantities] = useState({});
  const [error, setError] = useState(null);

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    const lines = productIds
      .filter((id) => Number(quantities[id]) > 0)
      .map((id) => ({ product_id: Number(id), quantity: quantities[id] }));
    if (!lines.length) {
      setError("أدخل كمية مرتجعة لصنف واحد على الأقل.");
      return;
    }
    try {
      const { data } = await api.post("/purchases/returns", {
        invoice_id: invoice.id,
        reason,
        lines,
      });
      onDone(data.data);
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Alert>{error}</Alert>
      <Select label="سبب الإرجاع" value={reason} onChange={(e) => setReason(e.target.value)}>
        {Object.entries(PURCHASE_RETURN_REASON_LABELS).map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </Select>
      <p className="text-xs font-bold text-rose-700">
        البضاعة المرتجعة تخرج نهائياً من المخزون وتعود للمورد، أياً كان السبب.
      </p>
      {productIds.map((id) => {
        const product = products.find((p) => p.id === Number(id));
        return (
          <div key={id} className="grid grid-cols-2 items-end gap-4">
            <div className="text-sm font-bold">
              {product?.name ?? `صنف ${id}`}
              <div className="text-xs font-normal text-slate-500">
                المستلم: {qty(receivedByProduct[id])} {product?.base_unit_name ?? ""}
              </div>
            </div>
            <Input
              label="الكمية المرتجعة"
              type="number"
              step="any"
              min="0"
              max={receivedByProduct[id]}
              value={quantities[id] ?? ""}
              onChange={(e) => setQuantities({ ...quantities, [id]: e.target.value })}
            />
          </div>
        );
      })}
      <Button type="submit" variant="danger">
        تسجيل مرتجع المشتريات
      </Button>
    </form>
  );
}

export default function PurchasesPage() {
  const { can } = useAuth();
  const canBuy = can("purchases.create");
  const [tab, setTab] = useState("list");
  const [viewing, setViewing] = useState(null);
  const [editing, setEditing] = useState(null);
  const [returnFor, setReturnFor] = useState(null);
  const [notice, setNotice] = useState(null);

  const invoices = useFetch(() => api.get("/purchases/invoices"));
  const returns = useFetch(() => api.get("/purchases/returns"));
  const suppliers = useFetch(() => api.get("/purchases/suppliers"));
  const warehouses = useFetch(() => api.get("/inventory/warehouses"));
  const products = useFetch(() => api.get("/inventory/products"));
  const taxRates = useFetch(() => api.get("/settings/tax-rates", { params: { active_only: true } }));

  if (suppliers.loading || warehouses.loading || products.loading || taxRates.loading) {
    return <Loading />;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-extrabold">فواتير المشتريات</h1>
        <div className="flex gap-2">
          <Button variant={tab === "list" ? "primary" : "secondary"} onClick={() => setTab("list")}>
            القائمة
          </Button>
          {canBuy && (
            <Button variant={tab === "new" ? "primary" : "secondary"} onClick={() => setTab("new")}>
              + فاتورة جديدة
            </Button>
          )}
          <Button variant={tab === "returns" ? "primary" : "secondary"} onClick={() => setTab("returns")}>
            المرتجعات
          </Button>
        </div>
      </div>

      <Alert tone="success">{notice}</Alert>

      {tab === "new" && canBuy && (
        <Card title="فاتورة شراء جديدة — تُدخل البضاعة للمخزون في عملية واحدة">
          <PurchaseForm
            suppliers={suppliers.data}
            warehouses={warehouses.data}
            products={products.data}
            taxRates={taxRates.data || []}
            onCreated={(invoice) => {
              setViewing(invoice);
              setTab("list");
              setNotice(null);
              invoices.reload();
            }}
          />
        </Card>
      )}

      {tab === "returns" && (
        <Card title="مرتجعات المشتريات">
          <Alert>{returns.error}</Alert>
          {returns.loading ? (
            <Loading />
          ) : (
            <Table
              columns={[
                { key: "id", label: "#" },
                { key: "invoice_id", label: "الفاتورة", render: (r) => `#${r.invoice_id}` },
                {
                  key: "supplier_id",
                  label: "المورد",
                  render: (r) => suppliers.data.find((s) => s.id === r.supplier_id)?.name ?? r.supplier_id,
                },
                {
                  key: "reason",
                  label: "السبب",
                  render: (r) => <Badge tone="red">{PURCHASE_RETURN_REASON_LABELS[r.reason]}</Badge>,
                },
                { key: "subtotal", label: "قبل الضريبة", render: (r) => money(r.subtotal) },
                { key: "vat_amount", label: "الضريبة", render: (r) => money(r.vat_amount) },
                { key: "total", label: "الإجمالي", render: (r) => <b>{money(r.total)}</b> },
                { key: "created_at", label: "التاريخ", render: (r) => r.created_at?.slice(0, 10) },
              ]}
              rows={returns.data}
              empty="لا توجد مرتجعات مشتريات بعد."
            />
          )}
        </Card>
      )}

      {tab === "list" && (
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
                  render: (r) => (
                    <Badge tone={PAYMENT_METHOD_TONE[r.payment_method]}>
                      {PAYMENT_METHOD_LABELS[r.payment_method]}
                    </Badge>
                  ),
                },
                {
                  key: "payment_confirmed_at",
                  label: "حالة السداد",
                  render: (r) =>
                    r.payment_method === "credit" ? (
                      <Badge tone="slate">آجل — عبر حساب المورد</Badge>
                    ) : r.payment_confirmed_at ? (
                      <Badge tone="green">تم السداد</Badge>
                    ) : (
                      <Badge tone="amber">بانتظار الصندوق</Badge>
                    ),
                },
                { key: "subtotal", label: "البضاعة", render: (r) => money(r.subtotal) },
                { key: "shipping_cost", label: "الشحن", render: (r) => money(r.shipping_cost) },
                { key: "vat_amount", label: "الضريبة", render: (r) => money(r.vat_amount) },
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
          <div className="space-y-4">
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

            {(() => {
              const invoiceReturns = (returns.data || []).filter(
                (r) => r.invoice_id === viewing.id
              );
              if (!invoiceReturns.length) return null;
              return (
                <div className="rounded-lg border border-rose-200 bg-rose-50 p-3">
                  <div className="mb-2 text-sm font-bold text-rose-700">
                    مرتجعات هذه الفاتورة ({invoiceReturns.length})
                  </div>
                  <div className="space-y-3">
                    {invoiceReturns.map((ret) => (
                      <div key={ret.id} className="rounded border border-rose-100 bg-white p-2">
                        <div className="mb-1 flex items-center justify-between text-xs">
                          <span className="font-bold">
                            مرتجع #{ret.id} — {ret.created_at?.slice(0, 10)}
                          </span>
                          <Badge tone="red">{PURCHASE_RETURN_REASON_LABELS[ret.reason]}</Badge>
                        </div>
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="text-slate-500">
                              <th className="text-right font-normal">الصنف</th>
                              <th className="text-right font-normal">الكمية</th>
                              <th className="text-right font-normal">القيمة</th>
                            </tr>
                          </thead>
                          <tbody>
                            {ret.lines.map((line) => (
                              <tr key={line.id}>
                                <td>
                                  {products.data.find((p) => p.id === line.product_id)?.name ??
                                    line.product_id}
                                </td>
                                <td>{qty(line.quantity)}</td>
                                <td>{money(line.line_total)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        <div className="mt-1 text-right text-xs font-bold text-rose-700">
                          إجمالي هذا المرتجع: {money(ret.total)}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })()}

            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex flex-wrap items-center gap-6 text-sm font-bold">
                {viewing.payment_method === "credit" ? (
                  <Badge tone="slate">آجل — عبر حساب المورد</Badge>
                ) : viewing.payment_confirmed_at ? (
                  <Badge tone="green">تم السداد من الصندوق</Badge>
                ) : (
                  <Badge tone="amber">بانتظار السداد من الصندوق</Badge>
                )}
                <span>البضاعة: {money(viewing.subtotal)}</span>
                <span>الشحن: {money(viewing.shipping_cost)}</span>
                {viewing.taxes.map((t) => (
                  <span key={t.id}>
                    {t.name} ({t.rate}%): {money(t.amount)}
                  </span>
                ))}
                <span className="text-emerald-700">الإجمالي: {money(viewing.total)}</span>
              </div>
              <div className="flex gap-2">
                {can("purchases.returns") && (
                  <Button
                    variant="danger"
                    onClick={() => {
                      setReturnFor(viewing);
                      setViewing(null);
                    }}
                  >
                    تسجيل مرتجع لهذه الفاتورة
                  </Button>
                )}
                {can("purchases.edit") && (
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setEditing(viewing);
                      setViewing(null);
                    }}
                  >
                    ✏️ تعديل
                  </Button>
                )}
                {can("purchases.delete") && (
                  <Button
                    variant="danger"
                    onClick={async () => {
                      if (
                        !window.confirm(
                          `حذف فاتورة الشراء رقم ${viewing.id} نهائياً؟ سيُعكس أثرها على المخزون وتُحذف قيودها المحاسبية.`
                        )
                      )
                        return;
                      try {
                        await api.delete(`/purchases/invoices/${viewing.id}`);
                        setViewing(null);
                        setNotice(`تم حذف فاتورة الشراء رقم ${viewing.id} وعكس أثرها على المخزون.`);
                        invoices.reload();
                      } catch (err) {
                        alert(apiMessage(err));
                      }
                    }}
                  >
                    🗑️ حذف
                  </Button>
                )}
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
            taxRates={taxRates.data || []}
            onCreated={(invoice) => {
              setEditing(null);
              setViewing(invoice);
              setNotice(`تم تعديل فاتورة الشراء رقم ${invoice.id} وإعادة احتساب المخزون والقيود.`);
              invoices.reload();
            }}
          />
        )}
      </Modal>

      <Modal
        open={!!returnFor}
        title={returnFor ? `مرتجع عن فاتورة الشراء رقم ${returnFor.id}` : ""}
        onClose={() => setReturnFor(null)}
      >
        {returnFor && (
          <PurchaseReturnForm
            invoice={returnFor}
            products={products.data}
            onDone={() => {
              setReturnFor(null);
              setNotice("تم تسجيل مرتجع المشتريات بنجاح.");
              setTab("returns");
              returns.reload();
              invoices.reload();
            }}
          />
        )}
      </Modal>
    </div>
  );
}
