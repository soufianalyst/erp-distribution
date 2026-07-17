import { useState } from "react";
import { useNavigate } from "react-router-dom";
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

const EMPTY_LINE = { product_id: "", product_label: "", quantity: "", unit_id: "" };

const productLabel = (p) => `${p.sku} — ${p.name}`;

export const REASON_LABELS = {
  resellable: "صالح لإعادة البيع",
  damaged_customer: "تالف بسبب العميل",
  damaged_transport: "تالف بسبب النقل",
};

// Aggregate an existing invoice's batch-level lines back into per-product form lines.
function linesFromInvoice(invoice, products) {
  const byProduct = {};
  for (const line of invoice.lines) {
    byProduct[line.product_id] =
      (byProduct[line.product_id] || 0) + Number(line.quantity);
  }
  return Object.entries(byProduct).map(([product_id, quantity]) => {
    const product = products.find((p) => p.id === Number(product_id));
    return {
      product_id,
      product_label: product ? productLabel(product) : "",
      quantity: String(quantity),
      unit_id: "",
    };
  });
}

function InvoiceForm({ customers, warehouses, products, isAdmin, onCreated, invoice }) {
  const editing = !!invoice;
  const [form, setForm] = useState(
    editing
      ? {
          customer_id: String(invoice.customer_id),
          payment_method: invoice.payment_method,
          fulfillment: invoice.fulfillment,
          apply_vat: Number(invoice.vat_amount) > 0,
          credit_override: false,
        }
      : {
          customer_id: "",
          payment_method: "cash",
          fulfillment: "delivery",
          apply_vat: true,
          credit_override: false,
        }
  );
  const [lines, setLines] = useState(
    editing ? linesFromInvoice(invoice, products) : [{ ...EMPTY_LINE }]
  );
  const [error, setError] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const setLine = (index, key, value) =>
    setLines(lines.map((l, i) => (i === index ? { ...l, [key]: value } : l)));

  // Type-to-search: resolve the typed label back to a product id.
  const setProductLine = (index, value) => {
    const match = products.find((p) => productLabel(p) === value);
    setLines(
      lines.map((l, i) =>
        i === index
          ? {
              ...l,
              product_label: value,
              product_id: match ? String(match.id) : "",
              unit_id: "",
            }
          : l
      )
    );
  };

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    if (lines.some((l) => l.product_label && !l.product_id)) {
      setError("اختر الصنف من قائمة البحث لكل سطر (اكتب ثم اختر من الاقتراحات).");
      return;
    }
    const payload = {
      ...form,
      lines: lines
        .filter((l) => l.product_id && l.quantity)
        .map((l) => ({ ...l, unit_id: l.unit_id || null })),
    };
    try {
      const { data } = editing
        ? await api.put(`/sales/invoices/${invoice.id}`, payload)
        : await api.post("/sales/invoices", payload);
      onCreated(data.data);
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Alert>{error}</Alert>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Select label="العميل" value={form.customer_id} onChange={set("customer_id")} required>
          <option value="">— اختر العميل —</option>
          {customers.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
        <Select label="طريقة الدفع" value={form.payment_method} onChange={set("payment_method")}>
          <option value="cash">نقدي</option>
          <option value="credit">آجل</option>
        </Select>
        <Select label="طريقة الاستلام" value={form.fulfillment} onChange={set("fulfillment")}>
          <option value="delivery">توصيل إلى العميل (رحلة توزيع)</option>
          <option value="pickup">استلام من المستودع (عند محلنا)</option>
        </Select>
      </div>

      <label className="flex items-center gap-2 text-sm font-bold text-slate-600">
        <input
          type="checkbox"
          checked={form.apply_vat}
          onChange={(e) => setForm({ ...form, apply_vat: e.target.checked })}
        />
        إصدار الفاتورة مع ضريبة القيمة المضافة
      </label>

      <datalist id="invoice-products">
        {products.map((p) => (
          <option key={p.id} value={productLabel(p)} />
        ))}
      </datalist>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-bold text-slate-600">
            أسطر الفاتورة{" "}
            <span className="text-xs font-normal text-slate-400">
              (Tab في آخر حقل يضيف سطراً جديداً)
            </span>
          </span>
          <Button type="button" variant="secondary" onClick={() => setLines([...lines, { ...EMPTY_LINE }])}>
            + سطر
          </Button>
        </div>
        {lines.map((line, index) => {
          const product = products.find((p) => String(p.id) === String(line.product_id));
          return (
            <div key={index} className="mb-2 grid grid-cols-12 items-end gap-2">
              <div className="col-span-6">
                <Input
                  label={index === 0 ? "الصنف (اكتب للبحث)" : undefined}
                  list="invoice-products"
                  placeholder="ابحث بالرمز أو الاسم..."
                  value={line.product_label ?? ""}
                  onChange={(e) => setProductLine(index, e.target.value)}
                  required
                />
                {product && (
                  <div className="mt-0.5 text-xs font-bold text-emerald-700">
                    المستودع:{" "}
                    {warehouses.find((w) => w.id === product.warehouse_id)?.name ??
                      "⚠️ الصنف غير مرتبط بمستودع"}
                  </div>
                )}
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
              <div className="col-span-3">
                <Select
                  label={index === 0 ? "الوحدة" : undefined}
                  value={line.unit_id}
                  onChange={(e) => setLine(index, "unit_id", e.target.value)}
                  onKeyDown={(e) => {
                    // Tab on the last line appends a fresh row for rapid entry.
                    if (
                      e.key === "Tab" &&
                      !e.shiftKey &&
                      index === lines.length - 1 &&
                      line.product_id &&
                      line.quantity
                    ) {
                      e.preventDefault();
                      setLines([...lines, { ...EMPTY_LINE }]);
                      setTimeout(() => {
                        const inputs = document.querySelectorAll(
                          `input[list="invoice-products"]`
                        );
                        const newInput = inputs[inputs.length - 1];
                        if (newInput) newInput.focus();
                      }, 0);
                    }
                  }}
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
                {lines.length > 1 && (
                  <Button
                    type="button"
                    variant="danger"
                    onClick={() => setLines(lines.filter((_, i) => i !== index))}
                  >
                    ×
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {isAdmin && form.payment_method === "credit" && (
        <label className="flex items-center gap-2 text-sm font-bold text-amber-700">
          <input
            type="checkbox"
            checked={form.credit_override}
            onChange={(e) => setForm({ ...form, credit_override: e.target.checked })}
          />
          موافقة المدير: السماح بتجاوز الحد الائتماني
        </label>
      )}

      <Button type="submit">{editing ? "حفظ التعديلات" : "إصدار الفاتورة"}</Button>
    </form>
  );
}

function ReturnForm({ invoice, products, onDone }) {
  // Aggregate the invoice's batch lines into per-product sold totals.
  const soldByProduct = {};
  for (const line of invoice.lines) {
    soldByProduct[line.product_id] = (soldByProduct[line.product_id] || 0) + Number(line.quantity);
  }
  const productIds = Object.keys(soldByProduct);

  const [reason, setReason] = useState("resellable");
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
      const { data } = await api.post("/sales/returns", {
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
      <Select label="تصنيف المرتجع" value={reason} onChange={(e) => setReason(e.target.value)}>
        {Object.entries(REASON_LABELS).map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </Select>
      {reason === "resellable" ? (
        <p className="text-xs font-bold text-emerald-700">
          البضاعة الصالحة تعود تلقائياً إلى تشغيلاتها الأصلية في المخزون.
        </p>
      ) : (
        <p className="text-xs font-bold text-rose-700">
          البضاعة التالفة لا تعود للمخزون وتسجل كخسارة تلف في الحسابات.
        </p>
      )}
      {productIds.map((id) => {
        const product = products.find((p) => p.id === Number(id));
        return (
          <div key={id} className="grid grid-cols-2 items-end gap-4">
            <div className="text-sm font-bold">
              {product?.name ?? `صنف ${id}`}
              <div className="text-xs font-normal text-slate-500">
                المباع: {qty(soldByProduct[id])} {product?.base_unit_name ?? ""}
              </div>
            </div>
            <Input
              label="الكمية المرتجعة"
              type="number"
              step="any"
              min="0"
              max={soldByProduct[id]}
              value={quantities[id] ?? ""}
              onChange={(e) => setQuantities({ ...quantities, [id]: e.target.value })}
            />
          </div>
        );
      })}
      <Button type="submit" variant="danger">
        تسجيل المرتجع
      </Button>
    </form>
  );
}

export default function SalesPage() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const canSell = can("sales.create");
  const [tab, setTab] = useState("list");
  const [viewing, setViewing] = useState(null);
  const [editing, setEditing] = useState(null);
  const [returnFor, setReturnFor] = useState(null);
  const [notice, setNotice] = useState(null);

  const invoices = useFetch(() => api.get("/sales/invoices"));
  const returns = useFetch(() => api.get("/sales/returns"));
  const customers = useFetch(() => api.get("/sales/customers"));
  const warehouses = useFetch(() => api.get("/inventory/warehouses"));
  const products = useFetch(() => api.get("/inventory/products"));

  if (customers.loading || warehouses.loading || products.loading) return <Loading />;

  const TABS = [
    { id: "list", label: "القائمة" },
    ...(canSell ? [{ id: "new", label: "+ فاتورة جديدة" }] : []),
    { id: "returns", label: "المرتجعات" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-extrabold">فواتير المبيعات</h1>
        <div className="flex gap-2">
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
      </div>

      <Alert tone="success">{notice}</Alert>

      {tab === "new" && canSell && (
        <Card title="فاتورة مبيعات جديدة — يتم خصم المخزون تلقائياً حسب FEFO">
          <InvoiceForm
            customers={customers.data}
            warehouses={warehouses.data}
            products={products.data}
            isAdmin={can("sales.credit_override")}
            onCreated={(invoice) => {
              setViewing(invoice);
              setTab("list");
              setNotice(null);
              invoices.reload();
            }}
          />
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
                {
                  key: "customer_id",
                  label: "العميل",
                  render: (r) => customers.data.find((c) => c.id === r.customer_id)?.name ?? r.customer_id,
                },
                {
                  key: "payment_method",
                  label: "الدفع",
                  render: (r) =>
                    r.payment_method === "cash" ? <Badge tone="green">نقدي</Badge> : <Badge tone="amber">آجل</Badge>,
                },
                {
                  key: "fulfillment",
                  label: "الاستلام",
                  render: (r) =>
                    r.fulfillment === "pickup" ? (
                      r.picked_up_at ? (
                        <Badge tone="green">تم الاستلام</Badge>
                      ) : (
                        <Badge tone="amber">استلام من المستودع</Badge>
                      )
                    ) : (
                      <Badge tone="blue">توصيل</Badge>
                    ),
                },
                { key: "subtotal", label: "قبل الضريبة", render: (r) => money(r.subtotal) },
                { key: "vat_amount", label: "الضريبة", render: (r) => money(r.vat_amount) },
                {
                  key: "total",
                  label: "الإجمالي",
                  render: (r) =>
                    Number(r.returned_total) > 0 ? (
                      <div>
                        <b>{money(r.total)}</b>
                        <div className="text-xs text-rose-600">
                          بعد المرتجع: {money(Number(r.total) - Number(r.returned_total))}
                        </div>
                      </div>
                    ) : (
                      <b>{money(r.total)}</b>
                    ),
                },
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
              empty="لا توجد فواتير مبيعات بعد."
            />
          )}
        </Card>
      )}

      {tab === "returns" && (
        <Card title="مرتجعات المبيعات">
          <Alert>{returns.error}</Alert>
          {returns.loading ? (
            <Loading />
          ) : (
            <Table
              columns={[
                { key: "id", label: "#" },
                { key: "invoice_id", label: "الفاتورة", render: (r) => `#${r.invoice_id}` },
                {
                  key: "reason",
                  label: "التصنيف",
                  render: (r) => (
                    <Badge tone={r.reason === "resellable" ? "green" : "red"}>
                      {REASON_LABELS[r.reason]}
                    </Badge>
                  ),
                },
                { key: "subtotal", label: "قبل الضريبة", render: (r) => money(r.subtotal) },
                { key: "vat_amount", label: "الضريبة", render: (r) => money(r.vat_amount) },
                { key: "total", label: "الإجمالي", render: (r) => <b>{money(r.total)}</b> },
                { key: "created_at", label: "التاريخ", render: (r) => r.created_at?.slice(0, 10) },
              ]}
              rows={returns.data}
              empty="لا توجد مرتجعات بعد."
            />
          )}
        </Card>
      )}

      <Modal
        open={!!viewing}
        title={viewing ? `فاتورة مبيعات رقم ${viewing.id}` : ""}
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
                { key: "batch_number", label: "التشغيلة (FEFO)" },
                { key: "quantity", label: "الكمية", render: (r) => qty(r.quantity) },
                { key: "unit_price", label: "سعر الوحدة", render: (r) => money(r.unit_price) },
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
                          <Badge tone={ret.reason === "resellable" ? "green" : "red"}>
                            {REASON_LABELS[ret.reason]}
                          </Badge>
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

            <div className="flex items-center justify-between border-t border-slate-200 pt-3">
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  onClick={() => navigate(`/print/invoice/${viewing.id}`)}
                >
                  🖨️ طباعة
                </Button>
                {can("sales.edit") && (
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
                {can("sales.returns") && (
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
                {can("sales.delete") && (
                  <Button
                    variant="danger"
                    onClick={async () => {
                      if (
                        !window.confirm(
                          `حذف الفاتورة رقم ${viewing.id} نهائياً؟ سيُعاد المخزون وتُحذف قيودها المحاسبية.`
                        )
                      )
                        return;
                      try {
                        await api.delete(`/sales/invoices/${viewing.id}`);
                        setViewing(null);
                        setNotice(`تم حذف الفاتورة رقم ${viewing.id} وإعادة المخزون.`);
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
              <div className="flex gap-6 text-sm font-bold">
                <span>قبل الضريبة: {money(viewing.subtotal)}</span>
                <span>الضريبة: {money(viewing.vat_amount)}</span>
                <span className="text-emerald-700">الإجمالي: {money(viewing.total)}</span>
                {Number(viewing.returned_total) > 0 && (
                  <span className="text-rose-700">
                    المرتجعات: {money(viewing.returned_total)} — الصافي:{" "}
                    {money(Number(viewing.total) - Number(viewing.returned_total))}
                  </span>
                )}
              </div>
            </div>
          </div>
        )}
      </Modal>

      <Modal
        open={!!editing}
        title={editing ? `تعديل الفاتورة رقم ${editing.id} (موافقة المدير)` : ""}
        onClose={() => setEditing(null)}
        wide
      >
        {editing && (
          <InvoiceForm
            invoice={editing}
            customers={customers.data}
            warehouses={warehouses.data}
            products={products.data}
            isAdmin={can("sales.credit_override")}
            onCreated={(invoice) => {
              setEditing(null);
              setViewing(invoice);
              setNotice(`تم تعديل الفاتورة رقم ${invoice.id} وإعادة احتساب المخزون والقيود.`);
              invoices.reload();
            }}
          />
        )}
      </Modal>

      <Modal
        open={!!returnFor}
        title={returnFor ? `مرتجع عن الفاتورة رقم ${returnFor.id}` : ""}
        onClose={() => setReturnFor(null)}
      >
        {returnFor && (
          <ReturnForm
            invoice={returnFor}
            products={products.data}
            onDone={(ret) => {
              setReturnFor(null);
              setNotice(`تم تسجيل المرتجع رقم ${ret.id} بقيمة ${money(ret.total)} بنجاح.`);
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
