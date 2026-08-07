// Sales: invoices, returns, quotations and the commission report.
//
// Several invoices can be drafted at once as tabs, because a counter often
// juggles customers. Issuing one deducts stock FEFO, checks the credit limit,
// applies the selected taxes and posts the accounting entry — all in one
// transaction that either wholly succeeds or wholly fails.
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  CancelButton,
  Card,
  Input,
  Loading,
  Modal,
  Select,
  Table,
  money,
  qty,
  useUnsavedGuard,
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

const PAYMENT_METHOD_LABELS = { cash: "نقدي", card: "بطاقة", credit: "آجل" };
const PAYMENT_METHOD_TONE = { cash: "green", card: "blue", credit: "amber" };

const TIER_PRICE_FIELD = {
  wholesale: "wholesale_price",
  half_wholesale: "half_wholesale_price",
  retail: "retail_price",
};

const round2 = (n) => Math.round((Number(n) + Number.EPSILON) * 100) / 100;

/**
 * Preview of what the invoice will bill, using the same tier pricing the server
 * applies. Only a preview: the amount the user confirms is sent as-is and the
 * server stays authoritative for the final figures.
 */
function previewTotals({ lines, products, customer, taxRates, taxRateIds }) {
  const priceField = TIER_PRICE_FIELD[customer?.price_tier] ?? "wholesale_price";
  let subtotal = 0;
  for (const line of lines) {
    const product = products.find((p) => String(p.id) === String(line.product_id));
    if (!product || !line.quantity) continue;
    const unit = product.units?.find((u) => String(u.id) === String(line.unit_id));
    const baseQty = Number(line.quantity) * (unit ? Number(unit.factor) : 1);
    subtotal += baseQty * Number(product[priceField] ?? 0);
  }
  subtotal = round2(subtotal);

  const applied = taxRates.filter((t) => taxRateIds.includes(t.id));
  const taxes = applied.map((t) => ({
    name: t.name,
    rate: t.rate,
    amount: round2((subtotal * Number(t.rate)) / 100),
  }));
  const vat = round2(taxes.reduce((sum, t) => sum + t.amount, 0));
  return { subtotal, taxes, vat, gross: round2(subtotal + vat) };
}

/**
 * Finalize step: shows what the invoice comes to and lets the user set the
 * amount actually collected. Charging less records the difference as a discount
 * — this is how 12,005 gets rounded down to 12,000 at the counter.
 */
function FinalizeInvoice({ totals, initialCollectable, onConfirm, onCancel, busy }) {
  const [collectable, setCollectable] = useState(
    initialCollectable != null ? String(initialCollectable) : String(totals.gross)
  );
  const entered = collectable === "" ? null : Number(collectable);
  const invalid = entered === null || Number.isNaN(entered) || entered < 0 || entered > totals.gross;
  const discount = invalid ? 0 : round2(totals.gross - entered);

  // Offer the obvious "drop the odd change" targets, skipping any that would
  // raise the amount or duplicate the exact total.
  const roundTargets = [1, 5, 10, 50, 100]
    .map((step) => Math.floor(totals.gross / step) * step)
    .filter((v, i, arr) => v > 0 && v < totals.gross && arr.indexOf(v) === i);

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 p-3 text-sm">
        <div className="flex justify-between py-0.5">
          <span className="font-bold text-slate-600 dark:text-slate-400">قبل الضريبة</span>
          <span>{money(totals.subtotal)}</span>
        </div>
        {totals.taxes.map((t) => (
          <div key={t.name} className="flex justify-between py-0.5">
            <span className="font-bold text-slate-600 dark:text-slate-400">
              {t.name} ({t.rate}%)
            </span>
            <span>{money(t.amount)}</span>
          </div>
        ))}
        <div className="mt-1 flex justify-between border-t border-slate-300 dark:border-slate-600 pt-1 text-base">
          <span className="font-extrabold">إجمالي الفاتورة</span>
          <span className="font-extrabold">{money(totals.gross)}</span>
        </div>
      </div>

      <Input
        label="المبلغ المطلوب تحصيله (يمكن تعديله للتدوير)"
        type="number"
        step="any"
        min="0"
        max={totals.gross}
        value={collectable}
        onChange={(e) => setCollectable(e.target.value)}
        autoFocus
      />

      {roundTargets.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-bold text-slate-500 dark:text-slate-400">تدوير سريع:</span>
          {roundTargets.map((v) => (
            <Button
              key={v}
              type="button"
              variant="secondary"
              onClick={() => setCollectable(String(v))}
            >
              {money(v)}
            </Button>
          ))}
          <Button type="button" variant="secondary" onClick={() => setCollectable(String(totals.gross))}>
            بدون خصم
          </Button>
        </div>
      )}

      {invalid ? (
        <Alert>أدخل مبلغاً بين 0 و {money(totals.gross)}.</Alert>
      ) : discount > 0 ? (
        <Alert tone="success">
          سيتم تسجيل خصم بقيمة {money(discount)} — المبلغ المستحق على العميل {money(entered)}.
        </Alert>
      ) : (
        <p className="text-sm font-bold text-slate-500 dark:text-slate-400">بدون خصم — سيُحصّل كامل المبلغ.</p>
      )}

      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={busy}>
          رجوع للتعديل
        </Button>
        <Button
          type="button"
          onClick={() => onConfirm(entered)}
          disabled={invalid || busy}
        >
          {busy ? "جارٍ التثبيت..." : "تثبيت الفاتورة"}
        </Button>
      </div>
    </div>
  );
}

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

function InvoiceForm({
  customers,
  warehouses,
  products,
  taxRates,
  isAdmin,
  onCreated,
  invoice,
  // Several invoice forms can be mounted at once (draft tabs), so the datalist
  // id and the "focus the new line" lookup must be scoped to this instance.
  formId = "invoice",
}) {
  const editing = !!invoice;
  const productListId = `${formId}-products`;
  const rootRef = useRef(null);
  const defaultTaxRate = taxRates.find((t) => t.is_default);
  const [form, setForm] = useState(
    editing
      ? {
          customer_id: String(invoice.customer_id),
          payment_method: invoice.payment_method,
          fulfillment: invoice.fulfillment,
          tax_rate_ids: invoice.taxes.map((t) => t.tax_rate_id).filter((id) => id != null),
          credit_override: false,
        }
      : {
          customer_id: "",
          payment_method: "cash",
          fulfillment: "delivery",
          tax_rate_ids: defaultTaxRate ? [defaultTaxRate.id] : [],
          credit_override: false,
        }
  );
  const [lines, setLines] = useState(
    editing ? linesFromInvoice(invoice, products) : [{ ...EMPTY_LINE }]
  );
  const [error, setError] = useState(null);
  const [finalizing, setFinalizing] = useState(false);
  const [busy, setBusy] = useState(false);
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

  const readyLines = () =>
    lines
      .filter((l) => l.product_id && l.quantity)
      .map((l) => ({ ...l, unit_id: l.unit_id || null }));

  // Submitting opens the finalize step rather than posting straight away, so the
  // collectable amount can be adjusted before the invoice exists.
  const submit = (event) => {
    event.preventDefault();
    setError(null);
    if (lines.some((l) => l.product_label && !l.product_id)) {
      setError("اختر الصنف من قائمة البحث لكل سطر (اكتب ثم اختر من الاقتراحات).");
      return;
    }
    if (!readyLines().length) {
      setError("أضف سطراً واحداً على الأقل بصنف وكمية.");
      return;
    }
    setFinalizing(true);
  };

  const post = async (collectableAmount) => {
    setError(null);
    setBusy(true);
    const payload = {
      ...form,
      lines: readyLines(),
      collectable_amount: collectableAmount,
    };
    try {
      const { data } = editing
        ? await api.put(`/sales/invoices/${invoice.id}`, payload)
        : await api.post("/sales/invoices", payload);
      setFinalizing(false);
      onCreated(data.data);
    } catch (err) {
      setError(apiMessage(err));
      setFinalizing(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
    <form ref={rootRef} onSubmit={submit} className="space-y-4">
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
          <option value="card">بطاقة</option>
          <option value="credit">آجل</option>
        </Select>
        <Select label="طريقة الاستلام" value={form.fulfillment} onChange={set("fulfillment")}>
          <option value="delivery">توصيل إلى العميل (رحلة توزيع)</option>
          <option value="pickup">استلام من المستودع (عند محلنا)</option>
        </Select>
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

      <datalist id={productListId}>
        {products
          .filter((p) => p.is_active)
          .map((p) => (
            <option key={p.id} value={productLabel(p)} />
          ))}
      </datalist>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-bold text-slate-600 dark:text-slate-400">
            أسطر الفاتورة{" "}
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
              <div className="col-span-6">
                <Input
                  label="الصنف (اكتب للبحث)"
                  list={productListId}
                  placeholder="ابحث بالرمز أو الاسم..."
                  value={line.product_label ?? ""}
                  onChange={(e) => setProductLine(index, e.target.value)}
                  required
                />
                {product && (
                  <div className="mt-0.5 text-xs font-bold text-emerald-700 dark:text-emerald-400">
                    المستودع:{" "}
                    {warehouses.find((w) => w.id === product.warehouse_id)?.name ??
                      "⚠️ الصنف غير مرتبط بمستودع"}
                  </div>
                )}
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
              <div className="col-span-3">
                <Select
                  label="الوحدة"
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
                        // Scoped to this form so other open drafts are ignored.
                        const inputs = (rootRef.current ?? document).querySelectorAll(
                          `input[list="${productListId}"]`
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
        <label className="flex items-center gap-2 text-sm font-bold text-amber-700 dark:text-amber-400">
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

    {/* Kept outside the form: a nested form would let Enter in the amount field
        re-trigger submit, and this step has nothing to preserve on close. */}
    <Modal
      open={finalizing}
      title={editing ? "تأكيد التعديل والمبلغ المحصّل" : "تأكيد الفاتورة والمبلغ المحصّل"}
      onClose={() => setFinalizing(false)}
      guardUnsaved={false}
    >
      <FinalizeInvoice
        totals={previewTotals({
          lines,
          products,
          customer: customers.find((c) => String(c.id) === String(form.customer_id)),
          taxRates,
          taxRateIds: form.tax_rate_ids,
        })}
        initialCollectable={editing ? invoice.total : null}
        busy={busy}
        onCancel={() => setFinalizing(false)}
        onConfirm={post}
      />
    </Modal>
    </>
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
        <p className="text-xs font-bold text-emerald-700 dark:text-emerald-400">
          البضاعة الصالحة تعود تلقائياً إلى تشغيلاتها الأصلية في المخزون.
        </p>
      ) : (
        <p className="text-xs font-bold text-rose-700 dark:text-rose-400">
          البضاعة التالفة لا تعود للمخزون وتسجل كخسارة تلف في الحسابات.
        </p>
      )}
      {productIds.map((id) => {
        const product = products.find((p) => p.id === Number(id));
        return (
          <div key={id} className="grid grid-cols-2 items-end gap-4">
            <div className="text-sm font-bold">
              {product?.name ?? `صنف ${id}`}
              <div className="text-xs font-normal text-slate-500 dark:text-slate-400">
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

function CommissionsTab() {
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const report = useFetch(
    () =>
      api.get("/sales/reports/commissions", {
        params: {
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        },
      }),
    [dateFrom, dateTo]
  );

  return (
    <Card title="عمولات المناديب — صافي المبيعات (بعد خصم المرتجعات) × نسبة العمولة">
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Input label="من تاريخ" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        <Input label="إلى تاريخ" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
      </div>
      <Alert>{report.error}</Alert>
      {report.loading ? (
        <Loading />
      ) : (
        <>
          <Table
            columns={[
              { key: "salesman_name", label: "المندوب" },
              { key: "total_sales", label: "إجمالي المبيعات", render: (r) => money(r.total_sales) },
              { key: "total_returns", label: "المرتجعات", render: (r) => money(r.total_returns) },
              { key: "net_sales", label: "صافي المبيعات", render: (r) => money(r.net_sales) },
              { key: "commission_rate", label: "نسبة العمولة", render: (r) => `${r.commission_rate}%` },
              {
                key: "commission_amount",
                label: "قيمة العمولة",
                render: (r) => <b>{money(r.commission_amount)}</b>,
              },
            ]}
            rows={report.data?.rows}
            empty="لا توجد مبيعات لمندوبين خلال هذه الفترة."
          />
          {!!report.data?.rows?.length && (
            <div className="mt-3 text-left text-sm font-extrabold text-emerald-800 dark:text-emerald-300">
              إجمالي العمولات: {money(report.data.total_commission)}
            </div>
          )}
        </>
      )}
    </Card>
  );
}

/**
 * One open sales-invoice draft. Every draft stays mounted while the drafts area
 * is showing — only the active one is visible — so switching between them keeps
 * each form's half-entered state intact.
 *
 * Each draft owns its own unsaved-changes guard and registers it with the page,
 * so closing a draft (or leaving the area) can ask about that specific one.
 */
function InvoiceDraft({ draft, active, registry, ...formProps }) {
  const guard = useUnsavedGuard(true);

  useEffect(() => {
    registry.current.set(draft.id, guard);
    return () => {
      registry.current.delete(draft.id);
    };
  }, [draft.id, guard, registry]);

  return (
    <div ref={guard.ref} hidden={!active}>
      <InvoiceForm formId={`draft-${draft.id}`} {...formProps} />
    </div>
  );
}

/**
 * Asks what to do with money owed back after a return on an already-paid invoice.
 *
 * Deliberately offers no default. A walk-in who paid cash usually wants the money;
 * a wholesale account usually prefers it against the next invoice — and only the
 * person at the counter knows which. Guessing would be worse than asking, because a
 * wrong guess is silent.
 *
 * Choosing a refund records the decision and queues it for the till; the cashier
 * hands the cash over, which is a separate act by a separate person so it lands in
 * the day's cash movements and the drawer reconciles.
 */
function CreditDecision({ credit, onDone }) {
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const choose = async (resolution) => {
    setBusy(resolution);
    setError(null);
    try {
      await api.post(`/sales/credits/${credit.id}/resolve`, { resolution });
      onDone(
        resolution === "refunded"
          ? `سيُردّ ${money(credit.amount)} للعميل نقداً — يُصرف من شاشة الصندوق.`
          : `بقي ${money(credit.amount)} رصيداً في حساب العميل.`
      );
    } catch (err) {
      setError(apiMessage(err));
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      <Alert>{error}</Alert>
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm dark:border-amber-900 dark:bg-amber-950/50">
        <div className="font-extrabold text-amber-800 dark:text-amber-200">
          العميل دفع أكثر مما يستحقّ الآن بمقدار {money(credit.amount)}
        </div>
        <p className="mt-1 text-amber-800 dark:text-amber-200">
          الفاتورة رقم {credit.invoiceId} كانت مدفوعة بالكامل، والمرتجع خفّض قيمتها.
          اختر كيف يُسوَّى الفرق.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <button
          type="button"
          disabled={!!busy}
          onClick={() => choose("refunded")}
          className="rounded-xl border border-slate-300 p-4 text-start transition hover:border-emerald-600 hover:bg-emerald-50 disabled:opacity-50 dark:border-slate-600 dark:hover:border-emerald-500 dark:hover:bg-emerald-950/40"
        >
          <div className="text-base font-extrabold">💵 ردّ نقدي</div>
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            يُسجَّل كمستحقّ على الصندوق، ويصرفه أمين الصندوق للعميل.
          </div>
        </button>
        <button
          type="button"
          disabled={!!busy}
          onClick={() => choose("credited")}
          className="rounded-xl border border-slate-300 p-4 text-start transition hover:border-sky-600 hover:bg-sky-50 disabled:opacity-50 dark:border-slate-600 dark:hover:border-sky-500 dark:hover:bg-sky-950/40"
        >
          <div className="text-base font-extrabold">📄 رصيد في الحساب</div>
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            يبقى المبلغ لصالح العميل ويُخصم من فاتورته القادمة.
          </div>
        </button>
      </div>
      <p className="text-xs text-slate-400 dark:text-slate-500">
        يمكن مراجعة المبالغ المستحقّة للعملاء لاحقاً من شاشة الصندوق.
      </p>
    </div>
  );
}

const QUOTATION_STATUS_LABELS = { draft: "مسودة", converted: "تم التحويل", cancelled: "ملغاة" };
const QUOTATION_STATUS_TONE = { draft: "amber", converted: "green", cancelled: "red" };

function QuotationForm({ customers, products, taxRates, onCreated }) {
  const defaultTaxRate = taxRates.find((t) => t.is_default);
  const [form, setForm] = useState({
    customer_id: "",
    valid_until: "",
    tax_rate_ids: defaultTaxRate ? [defaultTaxRate.id] : [],
    notes: "",
  });
  const [lines, setLines] = useState([{ ...EMPTY_LINE }]);
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
  const setProductLine = (index, value) => {
    const match = products.find((p) => productLabel(p) === value);
    setLines(
      lines.map((l, i) =>
        i === index
          ? { ...l, product_label: value, product_id: match ? String(match.id) : "" }
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
      customer_id: form.customer_id,
      valid_until: form.valid_until || null,
      tax_rate_ids: form.tax_rate_ids,
      notes: form.notes || null,
      lines: lines
        .filter((l) => l.product_id && l.quantity)
        .map((l) => ({ product_id: l.product_id, quantity: l.quantity })),
    };
    try {
      const { data } = await api.post("/sales/quotations", payload);
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
        <Input label="صالح حتى (اختياري)" type="date" value={form.valid_until} onChange={set("valid_until")} />
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

      <datalist id="quotation-products">
        {products
          .filter((p) => p.is_active)
          .map((p) => (
            <option key={p.id} value={productLabel(p)} />
          ))}
      </datalist>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-bold text-slate-600 dark:text-slate-400">أسطر العرض</span>
          <Button type="button" variant="secondary" onClick={() => setLines([...lines, { ...EMPTY_LINE }])}>
            + سطر
          </Button>
        </div>
        {lines.map((line, index) => (
          <div key={index} className={`line-row ${index === 0 ? "line-row-first" : ""} mb-2 grid grid-cols-12 items-end gap-2 max-sm:grid-cols-1 max-sm:[&>*]:col-span-1`}>
            <div className="col-span-8">
              <Input
                label="الصنف (اكتب للبحث)"
                list="quotation-products"
                placeholder="ابحث بالرمز أو الاسم..."
                value={line.product_label ?? ""}
                onChange={(e) => setProductLine(index, e.target.value)}
                required
              />
            </div>
            <div className="col-span-4">
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
          </div>
        ))}
      </div>

      <Input label="ملاحظات (اختياري)" value={form.notes} onChange={set("notes")} />

      <div className="flex justify-end">
        <Button type="submit">إنشاء عرض السعر</Button>
      </div>
    </form>
  );
}

function ConvertQuotationForm({ quotation, isAdmin, onConverted, onClose }) {
  const [form, setForm] = useState({
    payment_method: "cash",
    fulfillment: "delivery",
    credit_override: false,
  });
  const [error, setError] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      const { data } = await api.post(`/sales/quotations/${quotation.id}/convert`, form);
      onConverted(data.data);
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Alert>{error}</Alert>
      <Select label="طريقة الدفع" value={form.payment_method} onChange={set("payment_method")}>
        <option value="cash">نقدي</option>
        <option value="card">بطاقة</option>
        <option value="credit">آجل</option>
      </Select>
      <Select label="طريقة الاستلام" value={form.fulfillment} onChange={set("fulfillment")}>
        <option value="delivery">توصيل إلى العميل (رحلة توزيع)</option>
        <option value="pickup">استلام من المستودع (عند محلنا)</option>
      </Select>
      {isAdmin && (
        <label className="flex items-center gap-2 text-sm font-bold text-slate-700 dark:text-slate-300">
          <input
            type="checkbox"
            checked={form.credit_override}
            onChange={(e) => setForm({ ...form, credit_override: e.target.checked })}
          />
          تجاوز الحد الائتماني (موافقة المدير)
        </label>
      )}
      <div className="flex justify-end gap-2">
        <CancelButton onClose={onClose} />
        <Button type="submit">تحويل إلى فاتورة</Button>
      </div>
    </form>
  );
}

function QuotationsTab({ customers, products, taxRates, canQuote, isAdmin, onInvoiceCreated }) {
  const quotations = useFetch(() => api.get("/sales/quotations"));
  const [creating, setCreating] = useState(false);
  const [converting, setConverting] = useState(null);
  const [notice, setNotice] = useState(null);

  const cancelQuotation = async (quotation) => {
    if (!window.confirm(`إلغاء عرض السعر رقم ${quotation.id}؟`)) return;
    try {
      await api.post(`/sales/quotations/${quotation.id}/cancel`);
      quotations.reload();
    } catch (err) {
      alert(apiMessage(err));
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-extrabold">عروض الأسعار</h2>
        {canQuote && <Button onClick={() => setCreating(true)}>+ عرض سعر جديد</Button>}
      </div>
      <Alert tone="success">{notice}</Alert>
      <Card>
        <Alert>{quotations.error}</Alert>
        {quotations.loading ? (
          <Loading />
        ) : (
          <Table
            columns={[
              { key: "id", label: "#" },
              { key: "quote_date", label: "التاريخ" },
              {
                key: "customer_id",
                label: "العميل",
                render: (r) => customers.find((c) => c.id === r.customer_id)?.name ?? r.customer_id,
              },
              { key: "valid_until", label: "صالح حتى", render: (r) => r.valid_until ?? "—" },
              { key: "total", label: "الإجمالي", render: (r) => money(r.total) },
              {
                key: "status",
                label: "الحالة",
                render: (r) => (
                  <Badge tone={QUOTATION_STATUS_TONE[r.status]}>
                    {QUOTATION_STATUS_LABELS[r.status]}
                  </Badge>
                ),
              },
              {
                key: "actions",
                label: "",
                render: (r) =>
                  r.status === "draft" && canQuote ? (
                    <div className="flex flex-wrap gap-2">
                      <Button variant="secondary" onClick={() => setConverting(r)}>
                        تحويل إلى فاتورة
                      </Button>
                      <Button variant="danger" onClick={() => cancelQuotation(r)}>
                        إلغاء
                      </Button>
                    </div>
                  ) : r.converted_invoice_id ? (
                    <span className="text-xs text-slate-500 dark:text-slate-400">فاتورة #{r.converted_invoice_id}</span>
                  ) : null,
              },
            ]}
            rows={quotations.data}
            empty="لا توجد عروض أسعار بعد."
          />
        )}
      </Card>

      <Modal open={creating} title="عرض سعر جديد" onClose={() => setCreating(false)}>
        <QuotationForm
          customers={customers}
          products={products}
          taxRates={taxRates}
          onCreated={() => {
            setCreating(false);
            setNotice("تم إنشاء عرض السعر بنجاح.");
            quotations.reload();
          }}
        />
      </Modal>

      <Modal
        open={!!converting}
        title={converting ? `تحويل عرض السعر رقم ${converting.id} إلى فاتورة` : ""}
        onClose={() => setConverting(null)}
      >
        {converting && (
          <ConvertQuotationForm
            quotation={converting}
            isAdmin={isAdmin}
            onConverted={(invoice) => {
              setConverting(null);
              setNotice(`تم التحويل بنجاح إلى الفاتورة رقم ${invoice.id}.`);
              quotations.reload();
              onInvoiceCreated();
            }}
            onClose={() => setConverting(null)}
          />
        )}
      </Modal>
    </div>
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
  // A return on an already-paid invoice leaves money owed back; this holds
  // the pending credit until someone chooses refund or account balance.
  const [creditDecision, setCreditDecision] = useState(null);
  const [notice, setNotice] = useState(null);

  // Several invoices can be entered side by side — one draft per tab, so a
  // salesman serving a queue can park a half-finished invoice and pick it up
  // again without losing anything. Drafts live only while the page is open.
  const [drafts, setDrafts] = useState([]);
  const [activeDraftId, setActiveDraftId] = useState(null);
  const nextDraftId = useRef(1);
  // Each mounted draft registers its unsaved-changes guard here, keyed by id.
  const draftGuards = useRef(new Map());

  const openDraft = () => {
    const id = nextDraftId.current++;
    setDrafts((current) => [...current, { id }]);
    setActiveDraftId(id);
    setTab("drafts");
  };

  const closeDraft = (id) => {
    const guard = draftGuards.current.get(id);
    if (guard && !guard.confirmLeave()) return;
    setDrafts((current) => {
      const remaining = current.filter((d) => d.id !== id);
      if (id === activeDraftId) {
        setActiveDraftId(remaining.length ? remaining[remaining.length - 1].id : null);
        if (!remaining.length) setTab("list");
      }
      return remaining;
    });
  };

  // A submitted draft is no longer unsaved work, so drop its guard before
  // closing it — otherwise it would ask to discard what was just saved.
  const finishDraft = (id) => {
    draftGuards.current.delete(id);
    setDrafts((current) => {
      const remaining = current.filter((d) => d.id !== id);
      setActiveDraftId(remaining.length ? remaining[remaining.length - 1].id : null);
      if (!remaining.length) setTab("list");
      return remaining;
    });
  };

  const anyDraftDirty = () =>
    [...draftGuards.current.values()].some((g) => g.isDirty());

  // Leaving the drafts area keeps the drafts alive, but warn once if any hold
  // unsaved input so it is never a silent loss.
  const switchTab = (next) => {
    if (next === tab) return;
    if (tab === "drafts" && anyDraftDirty()) {
      const ok = window.confirm(
        "لديك فواتير مسودة تحتوي بيانات غير محفوظة. ستبقى المسودات مفتوحة — هل تريد المتابعة؟"
      );
      if (!ok) return;
    }
    setTab(next);
  };

  const invoices = useFetch(() => api.get("/sales/invoices"));
  const returns = useFetch(() => api.get("/sales/returns"));

  // Cancelling a credit note moves stock and money back, so the invoice list and the
  // customer figures both go stale — reload them, not just the returns table.
  const cancelReturn = async (sales_return) => {
    const reason = window.prompt(
      `إلغاء المرتجع رقم ${sales_return.id}؟\n` +
        "ستُسحب الكمية من المخزون ويُعكس القيد المحاسبي، وتعود الفاتورة مستحقة بكاملها.\n" +
        "سبب الإلغاء (اختياري):"
    );
    // prompt returns null when dismissed, "" when confirmed with nothing typed.
    if (reason === null) return;
    try {
      const { data } = await api.post(`/sales/returns/${sales_return.id}/cancel`, {
        cancel_reason: reason || null,
      });
      setNotice(data.message);
      returns.reload();
      invoices.reload();
    } catch (err) {
      alert(apiMessage(err));
    }
  };

  const customers = useFetch(() => api.get("/sales/customers"));
  const warehouses = useFetch(() => api.get("/inventory/warehouses"));
  const products = useFetch(() => api.get("/inventory/products"));
  const taxRates = useFetch(() => api.get("/settings/tax-rates", { params: { active_only: true, in_scope_only: true } }));

  if (customers.loading || warehouses.loading || products.loading || taxRates.loading) {
    return <Loading />;
  }

  const canViewCommissions = can("sales.commission_view");
  const canCancelReturn = can("sales.returns_cancel");
  const canQuote = can("sales.quotations");
  const TABS = [
    { id: "list", label: "القائمة" },
    ...(canSell && drafts.length ? [{ id: "drafts", label: `المسودات (${drafts.length})` }] : []),
    { id: "quotations", label: "عروض الأسعار" },
    { id: "returns", label: "المرتجعات" },
    ...(canViewCommissions ? [{ id: "commissions", label: "عمولات المناديب" }] : []),
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-extrabold">فواتير المبيعات</h1>
        <div className="flex flex-wrap gap-2">
          {TABS.map((t) => (
            <Button
              key={t.id}
              variant={tab === t.id ? "primary" : "secondary"}
              onClick={() => switchTab(t.id)}
            >
              {t.label}
            </Button>
          ))}
          {canSell && <Button onClick={openDraft}>+ فاتورة جديدة</Button>}
        </div>
      </div>

      <Alert tone="success">{notice}</Alert>

      {tab === "drafts" && canSell && drafts.length > 0 && (
        <Card>
          {/* One row of draft tabs — click to switch, × to close that draft. */}
          <div className="mb-4 flex flex-wrap items-center gap-2 border-b border-slate-200 dark:border-slate-700 pb-3">
            {drafts.map((d, index) => (
              <div
                key={d.id}
                className={`flex items-center gap-1 rounded-lg px-1 ${
                  d.id === activeDraftId ? "bg-emerald-700 text-white" : "bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-300 dark:border-slate-600"
                }`}
              >
                <button
                  type="button"
                  onClick={() => setActiveDraftId(d.id)}
                  className="px-2 py-1.5 text-sm font-bold"
                >
                  فاتورة {index + 1}
                </button>
                <button
                  type="button"
                  onClick={() => closeDraft(d.id)}
                  title="إغلاق هذه المسودة"
                  className={`px-1.5 text-lg leading-none ${
                    d.id === activeDraftId ? "text-white/80 hover:text-white" : "text-slate-400 dark:text-slate-500 hover:text-slate-700"
                  }`}
                >
                  ×
                </button>
              </div>
            ))}
            <Button variant="secondary" onClick={openDraft}>
              + مسودة
            </Button>
          </div>

          <p className="mb-4 text-sm font-bold text-slate-600 dark:text-slate-400">
            فاتورة مبيعات جديدة — يتم خصم المخزون تلقائياً حسب FEFO
          </p>

          {drafts.map((d) => (
            <InvoiceDraft
              key={d.id}
              draft={d}
              active={d.id === activeDraftId}
              registry={draftGuards}
              customers={customers.data}
              warehouses={warehouses.data}
              products={products.data}
              taxRates={taxRates.data || []}
              isAdmin={can("sales.credit_override")}
              onCreated={(invoice) => {
                finishDraft(d.id);
                setViewing(invoice);
                setNotice(`تم إصدار الفاتورة رقم ${invoice.id} بنجاح.`);
                invoices.reload();
              }}
            />
          ))}
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
                  render: (r) => (
                    <Badge tone={PAYMENT_METHOD_TONE[r.payment_method]}>
                      {PAYMENT_METHOD_LABELS[r.payment_method]}
                    </Badge>
                  ),
                },
                {
                  key: "payment_confirmed_at",
                  label: "حالة التحصيل",
                  render: (r) =>
                    r.payment_method === "credit" ? (
                      <Badge tone="slate">آجل — عبر الحسابات</Badge>
                    ) : r.payment_confirmed_at ? (
                      <Badge tone="green">تم التحصيل</Badge>
                    ) : (
                      <Badge tone="amber">بانتظار الصندوق</Badge>
                    ),
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
                  key: "discount_amount",
                  label: "الخصم",
                  render: (r) =>
                    Number(r.discount_amount) > 0 ? (
                      <span className="font-bold text-amber-700 dark:text-amber-400">{money(r.discount_amount)}</span>
                    ) : (
                      "—"
                    ),
                },
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
                {
                  key: "discount_amount",
                  label: "حصة الخصم",
                  render: (r) =>
                    Number(r.discount_amount) > 0 ? (
                      <span className="font-bold text-amber-700 dark:text-amber-400">
                        − {money(r.discount_amount)}
                      </span>
                    ) : (
                      "—"
                    ),
                },
                {
                  key: "total",
                  label: "صافي الإشعار",
                  render: (r) =>
                    r.status === "cancelled" ? (
                      <span className="text-slate-400 line-through">{money(r.total)}</span>
                    ) : (
                      <b>{money(r.total)}</b>
                    ),
                },
                { key: "created_at", label: "التاريخ", render: (r) => r.created_at?.slice(0, 10) },
                {
                  key: "status",
                  label: "الحالة",
                  render: (r) =>
                    r.status === "cancelled" ? (
                      <div>
                        <Badge tone="red">ملغى</Badge>
                        {r.cancel_reason && (
                          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                            {r.cancel_reason}
                          </div>
                        )}
                      </div>
                    ) : (
                      <Badge tone="green">مُثبَّت</Badge>
                    ),
                },
                {
                  key: "actions",
                  label: "",
                  render: (r) =>
                    r.status !== "cancelled" && canCancelReturn ? (
                      <Button variant="danger" onClick={() => cancelReturn(r)}>
                        إلغاء
                      </Button>
                    ) : null,
                },
              ]}
              rows={returns.data}
              empty="لا توجد مرتجعات بعد."
            />
          )}
        </Card>
      )}

      {tab === "quotations" && (
        <QuotationsTab
          customers={customers.data}
          products={products.data}
          taxRates={taxRates.data || []}
          canQuote={canQuote}
          isAdmin={can("sales.credit_override")}
          onInvoiceCreated={() => invoices.reload()}
        />
      )}

      {tab === "commissions" && canViewCommissions && <CommissionsTab />}

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
                          <Badge tone={ret.reason === "resellable" ? "green" : "red"}>
                            {REASON_LABELS[ret.reason]}
                          </Badge>
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
                          {Number(ret.discount_amount) > 0 && (
                            <span className="me-2 font-normal text-amber-700 dark:text-amber-400">
                              (قبل الخصم {money(ret.subtotal)} − حصة الخصم{" "}
                              {money(ret.discount_amount)})
                            </span>
                          )}
                          إجمالي هذا المرتجع: {money(ret.total)}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })()}

            <div className="flex items-center justify-between border-t border-slate-200 dark:border-slate-700 pt-3">
              <div className="flex flex-wrap gap-2">
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
              <div className="flex flex-wrap items-center gap-6 text-sm font-bold">
                {viewing.payment_method === "credit" ? (
                  <Badge tone="slate">آجل — يُحصّل عبر الحسابات</Badge>
                ) : viewing.payment_confirmed_at ? (
                  <Badge tone="green">تم التحصيل من الصندوق</Badge>
                ) : (
                  <Badge tone="amber">بانتظار التحصيل من الصندوق</Badge>
                )}
                <span>قبل الضريبة: {money(viewing.subtotal)}</span>
                {viewing.taxes.map((t) => (
                  <span key={t.id}>
                    {t.name} ({t.rate}%): {money(t.amount)}
                  </span>
                ))}
                {Number(viewing.discount_amount) > 0 && (
                  <span className="text-amber-700 dark:text-amber-400">
                    الخصم: {money(viewing.discount_amount)}
                  </span>
                )}
                <span className="text-emerald-700 dark:text-emerald-400">الإجمالي: {money(viewing.total)}</span>
                {Number(viewing.returned_total) > 0 && (
                  <span className="text-rose-700 dark:text-rose-400">
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
            taxRates={taxRates.data || []}
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
              // The invoice was already paid for more than it is now worth, so
              // money is owed back. Ask now — the obligation is easy to forget
              // once this screen closes, and it only ever showed up afterwards as
              // a negative balance on a statement nobody opens.
              if (ret.pending_credit_id) {
                setCreditDecision({
                  id: ret.pending_credit_id,
                  amount: ret.pending_credit_amount,
                  invoiceId: ret.invoice_id,
                });
              }
            }}
          />
        )}
      </Modal>

      <Modal
        open={!!creditDecision}
        title="مبلغ مستحقّ للعميل — كيف يُسوَّى؟"
        onClose={() => setCreditDecision(null)}
        guardUnsaved={false}
      >
        {creditDecision && (
          <CreditDecision
            credit={creditDecision}
            onDone={(message) => {
              setCreditDecision(null);
              setNotice(message);
              invoices.reload();
            }}
          />
        )}
      </Modal>
    </div>
  );
}
