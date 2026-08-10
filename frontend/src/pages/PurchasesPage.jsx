// Purchasing: supplier invoices, returns, and purchase orders with their
// deliveries.
//
// An order carries no stock or accounting effect until a delivery is received,
// at which point it raises an ordinary purchase invoice. The order form opens
// with a worklist of items that are out of stock or below their minimum.
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
  useUnsavedGuard,
  qty,
} from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

// Matches the shared Table's page size, so the pager and the server agree.
const PAGE_SIZE = 15;

const EMPTY_LINE = { product_id: "", batch_number: "", expiry_date: "", quantity: "", unit_id: "", unit_cost: "" };
const EMPTY_ORDER_LINE = { product_id: "", quantity: "", unit_id: "", unit_cost: "" };

const PAYMENT_METHOD_LABELS = { cash: "نقدي", card: "بطاقة", credit: "آجل" };
const PAYMENT_METHOD_TONE = { cash: "green", card: "blue", credit: "amber" };

const ORDER_STATUS_LABELS = {
  draft: "مسودة",
  sent: "مرسل للمورد",
  partially_received: "مستلم جزئياً",
  received: "مستلم بالكامل",
  cancelled: "ملغى",
};
const ORDER_STATUS_TONE = {
  draft: "slate",
  sent: "blue",
  partially_received: "amber",
  received: "green",
  cancelled: "red",
};

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
        <span className="mb-1 block text-sm font-bold text-slate-600 dark:text-slate-400">
          الضرائب المطبّقة (يمكن اختيار أكثر من ضريبة)
        </span>
        <div className="flex flex-wrap gap-3 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 p-3">
          {taxRates.filter((t) => t.is_active).length === 0 && (
            <span className="text-sm text-slate-400 dark:text-slate-500">لا توجد ضرائب مفعّلة.</span>
          )}
          {taxRates
            .filter((t) => t.is_active)
            .map((t) => (
              <label key={t.id} className="flex items-center gap-2 text-sm font-bold text-slate-700 dark:text-slate-300">
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
          <span className="text-sm font-bold text-slate-600 dark:text-slate-400">
            أسطر الفاتورة — رقم التشغيلة وتاريخ الانتهاء إلزاميان لكل سطر{" "}
            <span className="text-xs font-normal text-slate-400 dark:text-slate-500">
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
            <div key={index} className={`line-row ${index === 0 ? "line-row-first" : ""} mb-2 grid grid-cols-12 items-end gap-2 max-sm:grid-cols-1 max-sm:[&>*]:col-span-1`}>
              <div className="col-span-3">
                <Select
                  label="الصنف"
                  data-purchase-product
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
                  label="التشغيلة"
                  value={line.batch_number}
                  onChange={(e) => setLine(index, "batch_number", e.target.value)}
                  required
                />
              </div>
              <div className="col-span-2">
                <Input
                  label="تاريخ الانتهاء"
                  type="date"
                  value={line.expiry_date}
                  onChange={(e) => setLine(index, "expiry_date", e.target.value)}
                  required
                />
              </div>
              <div className="col-span-1">
                <Input
                  label="الكمية"
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
                  label="الوحدة"
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
                  label="سعر الشراء"
                  type="number"
                  step="any"
                  min="0"
                  value={line.unit_cost}
                  onChange={(e) => setLine(index, "unit_cost", e.target.value)}
                  onKeyDown={(e) => {
                    // Tab out of the last line's final field appends a fresh row,
                    // so the storekeeper never needs the mouse while keying in goods.
                    if (
                      e.key === "Tab" &&
                      !e.shiftKey &&
                      index === lines.length - 1 &&
                      line.product_id &&
                      line.quantity &&
                      line.unit_cost
                    ) {
                      e.preventDefault();
                      setLines([...lines, { ...EMPTY_LINE }]);
                      setTimeout(() => {
                        const selects = document.querySelectorAll(
                          "select[data-purchase-product]"
                        );
                        const newSelect = selects[selects.length - 1];
                        if (newSelect) newSelect.focus();
                      }, 0);
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

function ReorderWorklist({ onAdd, addedIds }) {
  const suggestions = useFetch(() => api.get("/inventory/stock/reorder-suggestions"));
  if (suggestions.loading) return <Loading />;
  const rows = (suggestions.data || []).filter((s) => !addedIds.includes(String(s.product_id)));

  return (
    <div className="rounded-lg border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-bold text-amber-900 dark:text-amber-200">
          أصناف تحتاج إعادة طلب — نفدت أو وصلت حدها الأدنى
          <span className="block text-xs font-normal text-amber-800 dark:text-amber-300">
            للتذكير فقط؛ يمكنك إضافة أي صنف آخر للطلب حتى لو كان مخزونه جيداً.
          </span>
        </span>
        {rows.length > 1 && (
          <Button type="button" variant="secondary" onClick={() => rows.forEach(onAdd)}>
            أضف الكل
          </Button>
        )}
      </div>
      <Alert>{suggestions.error}</Alert>
      {rows.length === 0 ? (
        <p className="text-sm font-bold text-emerald-800 dark:text-emerald-300">
          {(suggestions.data || []).length
            ? "تمت إضافة كل الأصناف المقترحة إلى الطلب."
            : "لا توجد أصناف نفدت أو تحت الحد الأدنى — المخزون بحالة جيدة."}
        </p>
      ) : (
        // Was a hand-built table inside a fixed-height scroll box: with a thousand
        // products, "reached its minimum" is not a short list, and scrolling a panel
        // is not the same as paging one. The shared Table brings search and sorting
        // with it, which is what you actually want here — sort by shortfall.
        <Table
          columns={[
            {
              key: "name",
              label: "الصنف",
              render: (s) => (
                <span className="font-bold">
                  {s.sku} — {s.name}
                  {s.out_of_stock && (
                    <span className="ms-2">
                      <Badge tone="red">نفد</Badge>
                    </span>
                  )}
                </span>
              ),
              search: (s) => `${s.sku} ${s.name}`,
            },
            {
              key: "current_stock",
              label: "المتوفر",
              render: (s) => `${qty(s.current_stock)} ${s.base_unit_name}`,
              sortValue: (s) => Number(s.current_stock),
            },
            {
              key: "reorder_point",
              label: "نقطة الطلب",
              render: (s) => (
                <span className="whitespace-nowrap">
                  {qty(s.reorder_point)}{" "}
                  {s.computed ? (
                    <Badge tone="green">محسوبة</Badge>
                  ) : (
                    <Badge tone="slate">يدوية</Badge>
                  )}
                </span>
              ),
              sortValue: (s) => Number(s.reorder_point),
            },
            {
              key: "suggested_quantity",
              label: "الكمية المقترحة",
              render: (s) => (
                <span className="font-bold text-emerald-700 dark:text-emerald-400">
                  {qty(s.suggested_quantity)}
                  {s.capped_by_expiry && (
                    <span className="ms-2">
                      <Badge tone="amber">محدودة بالصلاحية</Badge>
                    </span>
                  )}
                </span>
              ),
              sortValue: (s) => Number(s.suggested_quantity),
            },
            {
              key: "actions",
              label: "",
              sortable: false,
              render: (s) => (
                <Button type="button" variant="secondary" onClick={() => onAdd(s)}>
                  + أضف للطلب
                </Button>
              ),
            },
          ]}
          rows={rows}
          keyField="product_id"
          searchPlaceholder="بحث في الأصناف المقترحة..."
          renderDetail={(s) => (
            <div className="text-sm text-slate-600 dark:text-slate-400">
              {/* The arithmetic in words. A buyer who cannot see why the number is
                  what it is has no way to disagree with it, and a suggestion you
                  cannot disagree with is one you stop reading. */}
              {s.basis}
            </div>
          )}
        />
      )}
    </div>
  );
}

function PurchaseOrderForm({ suppliers, warehouses, products, order, onDone }) {
  const editing = !!order;
  const [form, setForm] = useState(
    editing
      ? {
          supplier_id: String(order.supplier_id),
          warehouse_id: String(order.warehouse_id),
          expected_date: order.expected_date || "",
          notes: order.notes || "",
        }
      : { supplier_id: "", warehouse_id: "", expected_date: "", notes: "" }
  );
  const [lines, setLines] = useState(
    editing
      ? order.lines.map((l) => ({
          product_id: String(l.product_id),
          quantity: String(l.quantity),
          unit_id: "",
          unit_cost: String(l.unit_cost),
        }))
      : [{ ...EMPTY_ORDER_LINE }]
  );
  const [error, setError] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const setLine = (index, key, value) =>
    setLines(lines.map((l, i) => (i === index ? { ...l, [key]: value } : l)));

  // Pull a suggested item onto the order. The quantity is the computed one — enough
  // to last until the next review, already trimmed to what will sell before it
  // expires — falling back to the plain shortfall if there was nothing to compute.
  const addSuggestion = (s) => {
    const suggested =
      Number(s.suggested_quantity) > 0 ? s.suggested_quantity : s.shortfall;
    const line = {
      product_id: String(s.product_id),
      quantity: Number(suggested) > 0 ? String(suggested) : "",
      unit_id: "",
      unit_cost: s.last_unit_cost != null ? String(s.last_unit_cost) : "",
    };
    setLines((current) => {
      // Reuse the trailing blank row rather than leaving an empty line behind.
      const withoutBlank = current.filter((l) => l.product_id || l.quantity);
      if (withoutBlank.some((l) => l.product_id === line.product_id)) return current;
      return [...withoutBlank, line];
    });
  };

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    const payload = {
      supplier_id: form.supplier_id,
      warehouse_id: form.warehouse_id,
      expected_date: form.expected_date || null,
      notes: form.notes || null,
      lines: lines
        .filter((l) => l.product_id && l.quantity)
        .map((l) => ({ ...l, unit_id: l.unit_id || null })),
    };
    if (!payload.lines.length) {
      setError("أضف صنفاً واحداً على الأقل للطلب.");
      return;
    }
    try {
      const { data } = editing
        ? await api.put(`/purchases/orders/${order.id}`, payload)
        : await api.post("/purchases/orders", payload);
      onDone(data.data);
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  const expectedTotal = lines.reduce(
    (sum, l) => sum + (Number(l.quantity) || 0) * (Number(l.unit_cost) || 0),
    0
  );

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
        <Select label="المستودع المتوقع" value={form.warehouse_id} onChange={set("warehouse_id")} required>
          <option value="">— اختر المستودع —</option>
          {warehouses.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </Select>
        <Input label="تاريخ التوريد المتوقع (اختياري)" type="date" value={form.expected_date} onChange={set("expected_date")} />
      </div>

      {!editing && (
        <ReorderWorklist
          addedIds={lines.map((l) => l.product_id).filter(Boolean)}
          onAdd={addSuggestion}
        />
      )}

      <div>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-bold text-slate-600 dark:text-slate-400">
            أسطر الطلب — الأسعار متوقعة، والفعلي يُسجّل عند الاستلام{" "}
            <span className="text-xs font-normal text-slate-400 dark:text-slate-500">
              (Tab في آخر حقل يضيف سطراً جديداً)
            </span>
          </span>
          <Button type="button" variant="secondary" onClick={() => setLines([...lines, { ...EMPTY_ORDER_LINE }])}>
            + سطر
          </Button>
        </div>
        {lines.map((line, index) => {
          const product = products.find((p) => String(p.id) === String(line.product_id));
          return (
            <div key={index} className={`line-row ${index === 0 ? "line-row-first" : ""} mb-2 grid grid-cols-12 items-end gap-2 max-sm:grid-cols-1 max-sm:[&>*]:col-span-1`}>
              <div className="col-span-5">
                <Select
                  label="الصنف"
                  data-order-product
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
                  label="الكمية"
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
                  label="الوحدة"
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
              <div className="col-span-2">
                <Input
                  label="السعر المتوقع"
                  type="number"
                  step="any"
                  min="0"
                  value={line.unit_cost}
                  onChange={(e) => setLine(index, "unit_cost", e.target.value)}
                  onKeyDown={(e) => {
                    // Same keyboard flow as the purchase invoice: Tab out of the
                    // last field opens a fresh row, no mouse needed.
                    if (
                      e.key === "Tab" &&
                      !e.shiftKey &&
                      index === lines.length - 1 &&
                      line.product_id &&
                      line.quantity &&
                      line.unit_cost
                    ) {
                      e.preventDefault();
                      setLines([...lines, { ...EMPTY_ORDER_LINE }]);
                      setTimeout(() => {
                        const selects = document.querySelectorAll("select[data-order-product]");
                        const newSelect = selects[selects.length - 1];
                        if (newSelect) newSelect.focus();
                      }, 0);
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

      <Input label="ملاحظات (اختياري)" value={form.notes} onChange={set("notes")} />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="text-sm font-bold text-slate-700 dark:text-slate-300">
          القيمة المتوقعة للطلب: <span className="text-emerald-700 dark:text-emerald-400">{money(expectedTotal)}</span>
        </span>
        <Button type="submit">{editing ? "حفظ التعديلات" : "حفظ الطلب كمسودة"}</Button>
      </div>
    </form>
  );
}

function ReceiveOrderForm({ order, products, warehouses, taxRates, onDone }) {
  const defaultTaxRate = (taxRates || []).find((t) => t.is_default);
  const outstanding = order.lines.filter((l) => Number(l.outstanding_quantity) > 0);
  const [form, setForm] = useState({
    payment_method: "credit",
    warehouse_id: String(order.warehouse_id),
    supplier_invoice_number: "",
    shipping_cost: "0",
    tax_rate_ids: defaultTaxRate ? [defaultTaxRate.id] : [],
  });
  // Prefilled with everything still owed, so a full delivery is one click.
  const [rows, setRows] = useState(
    Object.fromEntries(
      outstanding.map((l) => [
        l.id,
        {
          quantity: String(l.outstanding_quantity),
          batch_number: "",
          expiry_date: "",
          unit_cost: String(l.unit_cost),
        },
      ])
    )
  );
  const [error, setError] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const setRow = (lineId, key, value) =>
    setRows((current) => ({ ...current, [lineId]: { ...current[lineId], [key]: value } }));
  const toggleTax = (taxId) =>
    setForm((f) => ({
      ...f,
      tax_rate_ids: f.tax_rate_ids.includes(taxId)
        ? f.tax_rate_ids.filter((id) => id !== taxId)
        : [...f.tax_rate_ids, taxId],
    }));

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    const lines = Object.entries(rows)
      .filter(([, r]) => Number(r.quantity) > 0)
      .map(([lineId, r]) => ({
        order_line_id: Number(lineId),
        quantity: r.quantity,
        batch_number: r.batch_number,
        expiry_date: r.expiry_date,
        unit_cost: r.unit_cost || null,
      }));
    if (!lines.length) {
      setError("أدخل كمية مستلمة لصنف واحد على الأقل.");
      return;
    }
    try {
      const { data } = await api.post(`/purchases/orders/${order.id}/receive`, {
        ...form,
        supplier_invoice_number: form.supplier_invoice_number || null,
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
      <p className="text-xs font-bold text-slate-600 dark:text-slate-400">
        الكميات المعروضة هي المتبقية على الطلب؛ عدّلها إن وصل جزء منها فقط. رقم التشغيلة
        وتاريخ الانتهاء إلزاميان لكل صنف يدخل المخزون.
      </p>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Select label="طريقة الدفع" value={form.payment_method} onChange={set("payment_method")}>
          <option value="credit">آجل</option>
          <option value="cash">نقدي</option>
          <option value="card">بطاقة</option>
        </Select>
        <Select label="المستودع المستلم" value={form.warehouse_id} onChange={set("warehouse_id")} required>
          {warehouses.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </Select>
        <Input label="رقم فاتورة المورد (اختياري)" value={form.supplier_invoice_number} onChange={set("supplier_invoice_number")} />
        <Input label="تكلفة الشحن" type="number" step="0.01" min="0" value={form.shipping_cost} onChange={set("shipping_cost")} />
      </div>

      <div>
        <span className="mb-1 block text-sm font-bold text-slate-600 dark:text-slate-400">الضرائب المطبّقة</span>
        <div className="flex flex-wrap gap-3 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 p-3">
          {(taxRates || []).filter((t) => t.is_active).length === 0 && (
            <span className="text-sm text-slate-400 dark:text-slate-500">لا توجد ضرائب مفعّلة.</span>
          )}
          {(taxRates || [])
            .filter((t) => t.is_active)
            .map((t) => (
              <label key={t.id} className="flex items-center gap-2 text-sm font-bold text-slate-700 dark:text-slate-300">
                <input type="checkbox" checked={form.tax_rate_ids.includes(t.id)} onChange={() => toggleTax(t.id)} />
                {t.name} ({t.rate}%)
              </label>
            ))}
        </div>
      </div>

      {outstanding.map((line) => {
        const product = products.find((p) => p.id === line.product_id);
        const row = rows[line.id];
        return (
          <div
            key={line.id}
            className="grid grid-cols-12 items-end gap-2 rounded-lg border border-slate-200 dark:border-slate-700 p-2 max-sm:grid-cols-1 max-sm:[&>*]:col-span-1 dark:border-slate-700"
          >
            <div className="col-span-4 text-sm font-bold">
              {product?.name ?? `صنف ${line.product_id}`}
              <div className="text-xs font-normal text-slate-500 dark:text-slate-400">
                المتبقي: {qty(line.outstanding_quantity)} {product?.base_unit_name ?? ""} — من أصل{" "}
                {qty(line.quantity)}
              </div>
            </div>
            <div className="col-span-2">
              <Input
                label="الكمية المستلمة"
                type="number"
                step="any"
                min="0"
                max={line.outstanding_quantity}
                value={row.quantity}
                onChange={(e) => setRow(line.id, "quantity", e.target.value)}
              />
            </div>
            <div className="col-span-2">
              <Input
                label="التشغيلة"
                value={row.batch_number}
                onChange={(e) => setRow(line.id, "batch_number", e.target.value)}
                required={Number(row.quantity) > 0}
              />
            </div>
            <div className="col-span-2">
              <Input
                label="تاريخ الانتهاء"
                type="date"
                value={row.expiry_date}
                onChange={(e) => setRow(line.id, "expiry_date", e.target.value)}
                required={Number(row.quantity) > 0}
              />
            </div>
            <div className="col-span-2">
              <Input
                label="التكلفة الفعلية"
                type="number"
                step="any"
                min="0"
                value={row.unit_cost}
                onChange={(e) => setRow(line.id, "unit_cost", e.target.value)}
              />
            </div>
          </div>
        );
      })}

      <Button type="submit">استلام التوريد وإصدار فاتورة الشراء</Button>
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
      <p className="text-xs font-bold text-rose-700 dark:text-rose-400">
        البضاعة المرتجعة تخرج نهائياً من المخزون وتعود للمورد، أياً كان السبب.
      </p>
      {productIds.map((id) => {
        const product = products.find((p) => p.id === Number(id));
        return (
          <div key={id} className="grid grid-cols-2 items-end gap-4">
            <div className="text-sm font-bold">
              {product?.name ?? `صنف ${id}`}
              <div className="text-xs font-normal text-slate-500 dark:text-slate-400">
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
  const canOrder = can("purchases.orders");
  const [tab, setTab] = useState("list");
  // The new-invoice form lives in a tab, not a dialog, so switching away would
  // silently discard it — guard the switch the same way modals are guarded.
  const newInvoiceGuard = useUnsavedGuard(tab === "new");
  const switchTab = (next) => {
    if (next === tab) return;
    if (tab === "new" && !newInvoiceGuard.confirmLeave()) return;
    setTab(next);
  };
  const [viewing, setViewing] = useState(null);
  const [editing, setEditing] = useState(null);
  const [returnFor, setReturnFor] = useState(null);
  const [notice, setNotice] = useState(null);
  // Purchase orders: `newOrder` opens the create dialog, `editingOrder` the edit
  // one (drafts only), `receivingOrder` the delivery form, `viewingOrder` details.
  const [newOrder, setNewOrder] = useState(false);
  const [editingOrder, setEditingOrder] = useState(null);
  const [receivingOrder, setReceivingOrder] = useState(null);
  const [viewingOrder, setViewingOrder] = useState(null);

  // Paged: 858 KB and a thousand rows on one seeded year, to show fifteen.
  const [invoicePage, setInvoicePage] = useState(1);
  const invoices = useFetch(
    () =>
      api.get("/purchases/invoices", {
        params: {
          limit: PAGE_SIZE,
          offset: (invoicePage - 1) * PAGE_SIZE,
        },
      }),
    [invoicePage]
  );

  /** Open one invoice from a purchase order, whichever page it happens to live on. */
  const openInvoiceById = async (invoiceId) => {
    try {
      const response = await api.get(`/purchases/invoices/${invoiceId}`);
      setViewingOrder(null);
      setViewing(response.data.data);
      setTab("list");
    } catch {
      // Deliberately quiet: the order screen is not the place to raise an error
      // banner, and the invoice being unreachable is not something the user can act
      // on from here.
    }
  };

  const orders = useFetch(() => api.get("/purchases/orders"));
  const returns = useFetch(() => api.get("/purchases/returns"));
  const suppliers = useFetch(() => api.get("/purchases/suppliers"));
  const warehouses = useFetch(() => api.get("/inventory/warehouses"));
  const products = useFetch(() => api.get("/inventory/products"));
  const taxRates = useFetch(() => api.get("/settings/tax-rates", { params: { active_only: true, in_scope_only: true } }));

  if (suppliers.loading || warehouses.loading || products.loading || taxRates.loading) {
    return <Loading />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-extrabold">فواتير المشتريات</h1>
        <div className="flex flex-wrap gap-2">
          <Button variant={tab === "list" ? "primary" : "secondary"} onClick={() => switchTab("list")}>
            القائمة
          </Button>
          {canBuy && (
            <Button variant={tab === "new" ? "primary" : "secondary"} onClick={() => switchTab("new")}>
              + فاتورة جديدة
            </Button>
          )}
          <Button variant={tab === "orders" ? "primary" : "secondary"} onClick={() => switchTab("orders")}>
            طلبات الشراء
          </Button>
          <Button variant={tab === "returns" ? "primary" : "secondary"} onClick={() => switchTab("returns")}>
            المرتجعات
          </Button>
        </div>
      </div>

      <Alert tone="success">{notice}</Alert>

      {tab === "new" && canBuy && (
        <Card title="فاتورة شراء جديدة — تُدخل البضاعة للمخزون في عملية واحدة">
          <div ref={newInvoiceGuard.ref}>
            <PurchaseForm
              suppliers={suppliers.data}
              warehouses={warehouses.data}
              products={products.data}
              taxRates={taxRates.data || []}
              onCreated={(invoice) => {
                // Saved, so the fields are no longer unsaved work.
                newInvoiceGuard.markClean();
                setViewing(invoice);
                setTab("list");
                setNotice(null);
                invoices.reload();
              }}
            />
          </div>
        </Card>
      )}

      {tab === "orders" && (
        <Card
          title="طلبات الشراء — لا أثر على المخزون أو الحسابات حتى استلام التوريد"
          actions={
            canOrder && (
              <Button onClick={() => setNewOrder(true)}>+ طلب شراء جديد</Button>
            )
          }
        >
          <Alert>{orders.error}</Alert>
          {orders.loading ? (
            <Loading />
          ) : (
            <Table
              columns={[
                { key: "id", label: "#" },
                { key: "order_date", label: "تاريخ الطلب" },
                {
                  key: "supplier_id",
                  label: "المورد",
                  render: (r) => suppliers.data.find((s) => s.id === r.supplier_id)?.name ?? r.supplier_id,
                },
                { key: "expected_date", label: "التوريد المتوقع", render: (r) => r.expected_date || "—" },
                {
                  key: "status",
                  label: "الحالة",
                  render: (r) => (
                    <Badge tone={ORDER_STATUS_TONE[r.status]}>{ORDER_STATUS_LABELS[r.status]}</Badge>
                  ),
                },
                {
                  key: "progress",
                  label: "المستلم",
                  render: (r) => {
                    const ordered = r.lines.reduce((sum, l) => sum + Number(l.quantity), 0);
                    const received = r.lines.reduce((sum, l) => sum + Number(l.received_quantity), 0);
                    return `${qty(received)} / ${qty(ordered)}`;
                  },
                },
                { key: "subtotal", label: "القيمة المتوقعة", render: (r) => <b>{money(r.subtotal)}</b> },
                {
                  key: "actions",
                  label: "",
                  render: (r) => (
                    <div className="flex flex-wrap gap-1">
                      <Button variant="secondary" onClick={() => setViewingOrder(r)}>
                        عرض
                      </Button>
                      {canOrder && r.status === "draft" && (
                        <>
                          <Button variant="secondary" onClick={() => setEditingOrder(r)}>
                            ✏️
                          </Button>
                          <Button
                            onClick={async () => {
                              if (!window.confirm(`إرسال طلب الشراء رقم ${r.id} للمورد؟ لا يمكن تعديله بعد الإرسال.`))
                                return;
                              try {
                                await api.post(`/purchases/orders/${r.id}/send`);
                                setNotice(`تم إرسال طلب الشراء رقم ${r.id} للمورد.`);
                                orders.reload();
                              } catch (err) {
                                alert(apiMessage(err));
                              }
                            }}
                          >
                            إرسال
                          </Button>
                        </>
                      )}
                      {canOrder && (r.status === "sent" || r.status === "partially_received") && (
                        <Button onClick={() => setReceivingOrder(r)}>استلام توريد</Button>
                      )}
                      {canOrder && r.status !== "received" && r.status !== "cancelled" && (
                        <Button
                          variant="danger"
                          onClick={async () => {
                            const reason = window.prompt(
                              `إلغاء طلب الشراء رقم ${r.id}؟ اكتب سبب الإلغاء (اختياري):`
                            );
                            if (reason === null) return;
                            try {
                              await api.post(`/purchases/orders/${r.id}/cancel`, {
                                cancel_reason: reason || null,
                              });
                              setNotice(`تم إلغاء طلب الشراء رقم ${r.id}.`);
                              orders.reload();
                            } catch (err) {
                              alert(apiMessage(err));
                            }
                          }}
                        >
                          إلغاء
                        </Button>
                      )}
                    </div>
                  ),
                },
              ]}
              rows={orders.data}
              empty="لا توجد طلبات شراء بعد."
            />
          )}
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
              rows={invoices.data?.items || []}
              serverPaged={{
                total: invoices.data?.total || 0,
                page: invoicePage,
                onPageChange: setInvoicePage,
              }}
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
                <div className="rounded-lg border border-rose-200 dark:border-rose-900 bg-rose-50 dark:bg-rose-950/40 p-3">
                  <div className="mb-2 text-sm font-bold text-rose-700 dark:text-rose-400">
                    مرتجعات هذه الفاتورة ({invoiceReturns.length})
                  </div>
                  <div className="space-y-3">
                    {invoiceReturns.map((ret) => (
                      <div key={ret.id} className="rounded border border-rose-100 dark:border-rose-900 bg-white dark:bg-slate-800 p-2">
                        <div className="mb-1 flex items-center justify-between text-xs">
                          <span className="font-bold">
                            مرتجع #{ret.id} — {ret.created_at?.slice(0, 10)}
                          </span>
                          <Badge tone="red">{PURCHASE_RETURN_REASON_LABELS[ret.reason]}</Badge>
                        </div>
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="text-slate-500 dark:text-slate-400">
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
                        <div className="mt-1 text-right text-xs font-bold text-rose-700 dark:text-rose-400">
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
                <span className="text-emerald-700 dark:text-emerald-400">الإجمالي: {money(viewing.total)}</span>
              </div>
              <div className="flex flex-wrap gap-2">
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

      <Modal open={newOrder} title="طلب شراء جديد" onClose={() => setNewOrder(false)} wide>
        {newOrder && (
          <PurchaseOrderForm
            suppliers={suppliers.data}
            warehouses={warehouses.data}
            products={products.data}
            onDone={(order) => {
              setNewOrder(false);
              setNotice(`تم حفظ طلب الشراء رقم ${order.id} كمسودة — أرسله للمورد عند الجاهزية.`);
              orders.reload();
            }}
          />
        )}
      </Modal>

      <Modal
        open={!!editingOrder}
        title={editingOrder ? `تعديل طلب الشراء رقم ${editingOrder.id}` : ""}
        onClose={() => setEditingOrder(null)}
        wide
      >
        {editingOrder && (
          <PurchaseOrderForm
            order={editingOrder}
            suppliers={suppliers.data}
            warehouses={warehouses.data}
            products={products.data}
            onDone={(order) => {
              setEditingOrder(null);
              setNotice(`تم تعديل طلب الشراء رقم ${order.id}.`);
              orders.reload();
            }}
          />
        )}
      </Modal>

      <Modal
        open={!!receivingOrder}
        title={receivingOrder ? `استلام توريد على طلب الشراء رقم ${receivingOrder.id}` : ""}
        onClose={() => setReceivingOrder(null)}
        wide
      >
        {receivingOrder && (
          <ReceiveOrderForm
            order={receivingOrder}
            products={products.data}
            warehouses={warehouses.data}
            taxRates={taxRates.data || []}
            onDone={(invoice) => {
              setReceivingOrder(null);
              setNotice(
                `تم استلام التوريد وإصدار فاتورة الشراء رقم ${invoice.id} وإدخال البضاعة للمخزون.`
              );
              orders.reload();
              invoices.reload();
            }}
          />
        )}
      </Modal>

      <Modal
        open={!!viewingOrder}
        title={viewingOrder ? `طلب الشراء رقم ${viewingOrder.id}` : ""}
        onClose={() => setViewingOrder(null)}
        wide
      >
        {viewingOrder && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-4 text-sm font-bold">
              <Badge tone={ORDER_STATUS_TONE[viewingOrder.status]}>
                {ORDER_STATUS_LABELS[viewingOrder.status]}
              </Badge>
              <span>
                المورد:{" "}
                {suppliers.data.find((s) => s.id === viewingOrder.supplier_id)?.name ??
                  viewingOrder.supplier_id}
              </span>
              <span>
                المستودع:{" "}
                {warehouses.data.find((w) => w.id === viewingOrder.warehouse_id)?.name ??
                  viewingOrder.warehouse_id}
              </span>
              <span>تاريخ الطلب: {viewingOrder.order_date}</span>
              {viewingOrder.expected_date && <span>التوريد المتوقع: {viewingOrder.expected_date}</span>}
            </div>

            <Table
              columns={[
                {
                  key: "product_id",
                  label: "الصنف",
                  render: (r) => products.data.find((p) => p.id === r.product_id)?.name ?? r.product_id,
                },
                { key: "quantity", label: "المطلوب", render: (r) => qty(r.quantity) },
                { key: "received_quantity", label: "المستلم", render: (r) => qty(r.received_quantity) },
                {
                  key: "outstanding_quantity",
                  label: "المتبقي",
                  render: (r) =>
                    Number(r.outstanding_quantity) > 0 ? (
                      <b className="text-amber-700 dark:text-amber-400">{qty(r.outstanding_quantity)}</b>
                    ) : (
                      <Badge tone="green">مكتمل</Badge>
                    ),
                },
                { key: "unit_cost", label: "السعر المتوقع", render: (r) => money(r.unit_cost) },
                { key: "line_total", label: "الإجمالي المتوقع", render: (r) => money(r.line_total) },
              ]}
              rows={viewingOrder.lines}
            />

            {viewingOrder.received_invoice_ids.length > 0 && (
              <div className="rounded-lg border border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-950/40 p-3 text-sm">
                <div className="mb-1 font-bold text-emerald-800 dark:text-emerald-300">
                  التوريدات المستلمة على هذا الطلب ({viewingOrder.received_invoice_ids.length})
                </div>
                <div className="flex flex-wrap gap-2">
                  {/* Fetched by id on click rather than looked up in the loaded list.
                      The list is one page now, so a receipt older than the current
                      page would not be found — the button would render without its
                      amount and do nothing when pressed, which looks like a dead
                      control rather than a missing row. */}
                  {viewingOrder.received_invoice_ids.map((invoiceId) => (
                    <Button
                      key={invoiceId}
                      variant="secondary"
                      onClick={() => openInvoiceById(invoiceId)}
                    >
                      فاتورة شراء #{invoiceId}
                    </Button>
                  ))}
                </div>
              </div>
            )}

            {viewingOrder.status === "cancelled" && (
              <p className="text-sm font-bold text-rose-700 dark:text-rose-400">
                ألغي هذا الطلب{viewingOrder.cancelled_at ? ` بتاريخ ${viewingOrder.cancelled_at.slice(0, 10)}` : ""}
                {viewingOrder.cancel_reason ? ` — السبب: ${viewingOrder.cancel_reason}` : ""}.
              </p>
            )}
            {viewingOrder.notes && (
              <p className="text-sm text-slate-600 dark:text-slate-400">ملاحظات: {viewingOrder.notes}</p>
            )}
            <div className="text-right text-sm font-bold text-emerald-700 dark:text-emerald-400">
              القيمة المتوقعة للطلب: {money(viewingOrder.subtotal)}
            </div>
          </div>
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
