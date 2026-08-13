// Stock movements: balances, transfers between warehouses, write-offs of
// damaged or expired goods, physical stocktakes, and the near-expiry watchlist.
//
// Receiving lives in purchasing rather than here, so goods always arrive against
// a supplier document.
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  Card,
  Input,
  Loading,
  Select,
  Table,
  money,
  qty,
} from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import ProductPicker from "../components/ProductPicker";
import useFetch from "../hooks/useFetch";
import useProductCatalog from "../hooks/useProductCatalog";
import api, { apiMessage } from "../services/api";

const ADJUSTMENT_REASON_LABELS = {
  expired: "منتهي الصلاحية",
  damaged: "تالف",
  spoiled: "فاسد",
  count_shortfall: "نقص عند الجرد",
  other: "أخرى",
};

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

function TransferForm({ products, onProductQuery, productsLoading = false, warehouses, onDone }) {
  const [form, setForm] = useState({
    product_id: "",
    product_label: "",
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
        <ProductPicker
          listId="transfer-products"
          products={products}
          value={form.product_label}
          loading={productsLoading}
          onQuery={onProductQuery}
          onSelect={(match, text) =>
            setForm((f) => ({
              ...f,
              product_label: text,
              product_id: match ? String(match.id) : "",
              unit_id: "",
            }))
          }
          required
        />
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

function AdjustmentForm({ products, onProductQuery, productsLoading = false, warehouses, onDone }) {
  const [reason, setReason] = useState("damaged");
  const [productLabelText, setProductLabelText] = useState("");
  const [notes, setNotes] = useState("");
  const [productId, setProductId] = useState("");
  const [batches, setBatches] = useState([]);
  const [batchesLoading, setBatchesLoading] = useState(false);
  const [quantities, setQuantities] = useState({});
  const [error, setError] = useState(null);

  const selectProduct = async (pid) => {
    setProductId(pid);
    setQuantities({});
    setBatches([]);
    if (!pid) return;
    setBatchesLoading(true);
    try {
      const { data } = await api.get(`/inventory/products/${pid}/batches`);
      setBatches(data.data);
    } finally {
      setBatchesLoading(false);
    }
  };

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    const lines = Object.entries(quantities)
      .filter(([, quantity]) => Number(quantity) > 0)
      .map(([batch_id, quantity]) => ({ batch_id: Number(batch_id), quantity }));
    if (!lines.length) {
      setError("أدخل كمية الإتلاف لتشغيلة واحدة على الأقل.");
      return;
    }
    try {
      const { data } = await api.post("/inventory/stock/adjustments", {
        reason,
        notes: notes || null,
        lines,
      });
      setNotes("");
      setQuantities({});
      onDone(data.message);
      selectProduct(productId);
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Alert>{error}</Alert>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Select label="السبب" value={reason} onChange={(e) => setReason(e.target.value)}>
          {Object.entries(ADJUSTMENT_REASON_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>
        <ProductPicker
          listId="adjustment-products"
          products={products}
          value={productLabelText}
          loading={productsLoading}
          onQuery={onProductQuery}
          onSelect={(match, text) => {
            setProductLabelText(text);
            // Only a resolved product has batches to count; a half-typed name clears
            // the list rather than leaving last product's batches on screen.
            selectProduct(match ? String(match.id) : "");
          }}
          required
        />
      </div>
      <Input label="ملاحظات (اختياري)" value={notes} onChange={(e) => setNotes(e.target.value)} />

      {batchesLoading && <Loading />}
      {!batchesLoading && productId && batches.length === 0 && (
        <p className="text-sm text-slate-400 dark:text-slate-500">لا توجد تشغيلات متوفرة لهذا الصنف.</p>
      )}
      {batches.map((b) => (
        <div key={b.id} className="grid grid-cols-2 items-end gap-4">
          <div className="text-sm font-bold">
            {b.batch_number}{" "}
            {/* A batch is warehouse-specific, and the same product may sit in
                several warehouses — show which one is being written off. */}
            <Badge tone="blue">
              {warehouses.find((w) => w.id === b.warehouse_id)?.name ?? "مستودع غير معروف"}
            </Badge>
            <div className="text-xs font-normal text-slate-500 dark:text-slate-400">
              المتوفر: {qty(b.quantity)} — الانتهاء: {b.expiry_date}
            </div>
          </div>
          <Input
            label="الكمية المُتلَفة"
            type="number"
            step="any"
            min="0"
            max={b.quantity}
            value={quantities[b.id] ?? ""}
            onChange={(e) => setQuantities({ ...quantities, [b.id]: e.target.value })}
          />
        </div>
      ))}
      <Button type="submit" variant="danger">
        تسجيل تعديل المخزون
      </Button>
    </form>
  );
}

const STOCKTAKE_STATUS_LABELS = {
  counting: "قيد الجرد",
  posted: "مُثبّت",
  cancelled: "ملغى",
};
const STOCKTAKE_STATUS_TONE = { counting: "amber", posted: "green", cancelled: "red" };

/**
 * Variance display, shared by the live count sheet and the posted review.
 * `variance` is null for a line nobody has counted yet — which is not a
 * shortfall, and must not read like one.
 */
function Variance({ variance }) {
  if (variance == null) {
    return <span className="text-slate-400 dark:text-slate-500">لم يُجرد</span>;
  }
  if (Number(variance) === 0) return <Badge tone="green">مطابق</Badge>;
  const short = Number(variance) < 0;
  return (
    <b className={short ? "text-rose-700 dark:text-rose-400" : "text-sky-700 dark:text-sky-400"}>
      {short ? qty(variance) : `+${qty(variance)}`}
    </b>
  );
}

/**
 * The count sheet: expected quantities on the left, a box per line for what was
 * actually found. Counts save in one call, so a long count can be saved in
 * passes without losing anything, and Enter jumps to the next line so the whole
 * sheet can be keyed without the mouse.
 */
function StocktakeSheet({ stocktake, onSaved, onPosted }) {
  const editable = stocktake.status === "counting";
  const [counts, setCounts] = useState(() =>
    Object.fromEntries(
      stocktake.lines.map((l) => [
        l.id,
        l.counted_quantity == null ? "" : String(l.counted_quantity),
      ])
    )
  );
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setError(null);
    const entered = Object.entries(counts)
      .filter(([, value]) => value !== "")
      .map(([lineId, value]) => ({ line_id: Number(lineId), counted_quantity: value }));
    if (!entered.length) {
      setError("أدخل الكمية الفعلية لسطر واحد على الأقل.");
      return null;
    }
    setBusy(true);
    try {
      const { data } = await api.put(
        `/inventory/stocktakes/${stocktake.id}/counts`,
        { counts: entered }
      );
      onSaved(data.data);
      return data.data;
    } catch (err) {
      setError(apiMessage(err));
      return null;
    } finally {
      setBusy(false);
    }
  };

  const post = async () => {
    // Save first: posting settles what the server holds, not what is on screen.
    const saved = await save();
    if (!saved) return;
    if (
      !window.confirm(
        `تثبيت الجرد رقم ${stocktake.id}؟ ستُسوّى فروقات النقص والزيادة على المخزون ولا يمكن التراجع.`
      )
    )
      return;
    setBusy(true);
    try {
      const { data } = await api.post(`/inventory/stocktakes/${stocktake.id}/post`);
      onPosted(data.data);
    } catch (err) {
      setError(apiMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const varianceOf = (line) => {
    const raw = counts[line.id];
    return raw === "" || raw == null
      ? null
      : Number(raw) - Number(line.expected_quantity);
  };

  // Live preview so the counter sees the impact before committing.
  const preview = stocktake.lines.reduce(
    (acc, line) => {
      const raw = counts[line.id];
      if (raw === "" || raw == null) return acc;
      const variance = Number(raw) - Number(line.expected_quantity);
      const value = variance * Number(line.unit_cost);
      return {
        counted: acc.counted + 1,
        differing: acc.differing + (variance === 0 ? 0 : 1),
        net: acc.net + value,
      };
    },
    { counted: 0, differing: 0, net: 0 }
  );

  return (
    <div className="space-y-4">
      <Alert>{error}</Alert>
      {/* A counting sheet is still a list: a full-warehouse stocktake runs to a
          couple of thousand batches, and this was rendering every one of them.
          Typed counts live in `counts`, keyed by line id, so they survive paging —
          and Enter still walks down the visible page. */}
      <Table
        columns={[
          {
            key: "product_name",
            label: "الصنف",
            render: (line) => (
              <span className="font-bold">
                {line.product_name}
                <div className="text-xs font-normal text-slate-500 dark:text-slate-400">
                  {line.sku}
                </div>
              </span>
            ),
            search: (line) => `${line.product_name} ${line.sku}`,
          },
          { key: "batch_number", label: "التشغيلة" },
          { key: "expiry_date", label: "الانتهاء" },
          {
            key: "expected_quantity",
            label: "المتوقع دفترياً",
            render: (line) => `${qty(line.expected_quantity)} ${line.base_unit_name}`,
            sortValue: (line) => Number(line.expected_quantity),
          },
          {
            key: "counted_quantity",
            label: "الكمية الفعلية",
            sortable: false,
            render: (line) =>
              editable ? (
                <Input
                  type="number"
                  step="any"
                  min="0"
                  data-count-input
                  value={counts[line.id] ?? ""}
                  onChange={(e) => setCounts({ ...counts, [line.id]: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key !== "Enter") return;
                    // Enter walks down the sheet instead of submitting the form.
                    e.preventDefault();
                    const boxes = [...document.querySelectorAll("input[data-count-input]")];
                    boxes[boxes.indexOf(e.target) + 1]?.focus();
                  }}
                />
              ) : line.counted_quantity == null ? (
                // Never counted — showing 0 here would read as "found none".
                <span className="text-slate-400 dark:text-slate-500">—</span>
              ) : (
                qty(line.counted_quantity)
              ),
          },
          {
            key: "variance",
            label: "الفرق",
            render: (line) => <Variance variance={varianceOf(line)} />,
            sortValue: (line) => varianceOf(line) ?? 0,
          },
          {
            key: "variance_value",
            label: "قيمة الفرق",
            render: (line) => {
              const variance = varianceOf(line);
              return variance == null || Number(line.unit_cost) === 0
                ? "—"
                : money(variance * Number(line.unit_cost));
            },
            sortValue: (line) => (varianceOf(line) ?? 0) * Number(line.unit_cost || 0),
          },
        ]}
        rows={stocktake.lines}
        searchPlaceholder="بحث بالصنف أو الرمز أو التشغيلة..."
      />

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-slate-50 p-3 text-sm font-bold dark:bg-slate-800/60">
        <span>
          تم جرد {preview.counted} من {stocktake.lines.length} سطر — بفروقات في{" "}
          {preview.differing}
        </span>
        <span className={preview.net < 0 ? "text-rose-700 dark:text-rose-400" : "text-emerald-700 dark:text-emerald-400"}>
          صافي قيمة الفروقات: {money(preview.net)}
        </span>
      </div>

      {editable && (
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={save} disabled={busy}>
            حفظ الكميات دون تثبيت
          </Button>
          <Button onClick={post} disabled={busy}>
            تثبيت الجرد وتسوية الفروقات
          </Button>
        </div>
      )}
    </div>
  );
}

export default function StockPage() {
  const { can } = useAuth();
  const canTransfer = can("stock.transfer");
  const canAdjust = can("stock.adjust");
  const canCancelAdjust = can("stock.adjust_cancel");
  const canCount = can("stock.stocktake");
  const navigate = useNavigate();
  const [tab, setTab] = useState("levels");
  const [notice, setNotice] = useState(null);
  // The count sheet currently open for entry or review; null shows the list.
  const [sheet, setSheet] = useState(null);
  const [newCountWarehouse, setNewCountWarehouse] = useState("");

  // Searched rather than downloaded; see useProductCatalog.
  const catalog = useProductCatalog();
  const warehouses = useFetch(() => api.get("/inventory/warehouses"));
  const levels = useFetch(() => api.get("/inventory/stock/levels"));
  const nearExpiry = useFetch(() => api.get("/inventory/stock/near-expiry", { params: { days: 60 } }));
  const adjustments = useFetch(() => api.get("/inventory/stock/adjustments"));
  const stocktakes = useFetch(() => api.get("/inventory/stocktakes"));

  const reloadAll = () => {
    levels.reload();
    nearExpiry.reload();
  };

  const cancelAdjustment = async (adjustment) => {
    const reason = window.prompt(
      `إلغاء سجل الإتلاف رقم ${adjustment.id}؟ ستعود الكمية للمخزون.\nسبب الإلغاء (اختياري):`
    );
    // prompt returns null on Cancel, "" when confirmed with no text typed.
    if (reason === null) return;
    try {
      const { data } = await api.post(
        `/inventory/stock/adjustments/${adjustment.id}/cancel`,
        { cancel_reason: reason || null }
      );
      setNotice(data.message);
      reloadAll();
      adjustments.reload();
    } catch (err) {
      alert(apiMessage(err));
    }
  };

  const openStocktake = async () => {
    if (!newCountWarehouse) return;
    try {
      const { data } = await api.post("/inventory/stocktakes", {
        warehouse_id: Number(newCountWarehouse),
      });
      setNotice(data.message);
      setSheet(data.data);
      stocktakes.reload();
    } catch (err) {
      alert(apiMessage(err));
    }
  };

  const cancelStocktake = async (stocktake) => {
    const reason = window.prompt(
      `إلغاء الجرد رقم ${stocktake.id}؟ لن يتأثر المخزون لأن الجرد لم يُثبّت.\nسبب الإلغاء (اختياري):`
    );
    if (reason === null) return;
    try {
      const { data } = await api.post(
        `/inventory/stocktakes/${stocktake.id}/cancel`,
        { cancel_reason: reason || null }
      );
      setNotice(data.message);
      if (sheet?.id === stocktake.id) setSheet(null);
      stocktakes.reload();
    } catch (err) {
      alert(apiMessage(err));
    }
  };

  const TABS = [
    { id: "levels", label: "الأرصدة" },
    ...(canTransfer ? [{ id: "transfer", label: "تحويل بين المستودعات" }] : []),
    ...(canAdjust ? [{ id: "adjust", label: "تعديل/إتلاف المخزون" }] : []),
    ...(canCount ? [{ id: "stocktake", label: "الجرد" }] : []),
    { id: "expiry", label: "قرب الانتهاء" },
  ];

  if (warehouses.loading) return <Loading />;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold">حركة المخزون</h1>
      <div className="flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`rounded-lg px-4 py-2 text-sm font-bold ${
              tab === t.id ? "bg-emerald-700 text-white" : "bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-50"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <Alert tone="success">{notice}</Alert>

      {tab === "levels" && (
        <Card title="أرصدة المخزون حسب الصنف والمستودع">
          <Alert>{levels.error}</Alert>
          {levels.loading ? (
            <Loading />
          ) : (
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
              keyField={(r) => `${r.product_id}-${r.warehouse_id}`}
            />
          )}
        </Card>
      )}

      {tab === "transfer" && canTransfer && (
        <Card title="تحويل بضاعة — يتم اختيار التشغيلات الأقرب انتهاءً أولاً (FEFO)">
          <TransferForm
              products={catalog.products}
              onProductQuery={catalog.setQuery}
              productsLoading={catalog.loading}
              warehouses={warehouses.data}
              onDone={reloadAll}
            />
        </Card>
      )}

      {tab === "adjust" && canAdjust && (
        <div className="space-y-6">
          <Card title="تعديل/إتلاف المخزون — يخرج نهائياً من المخزون خارج أي عملية بيع">
            <AdjustmentForm
              products={catalog.products}
              onProductQuery={catalog.setQuery}
              productsLoading={catalog.loading}
              warehouses={warehouses.data}
              onDone={(message) => {
                setNotice(message);
                reloadAll();
                adjustments.reload();
              }}
            />
          </Card>
          <Card title="سجل تعديلات/إتلاف المخزون">
            <Alert>{adjustments.error}</Alert>
            {adjustments.loading ? (
              <Loading />
            ) : (
              <Table
                columns={[
                  { key: "id", label: "#" },
                  {
                    key: "reason",
                    label: "السبب",
                    render: (r) => <Badge tone="red">{ADJUSTMENT_REASON_LABELS[r.reason]}</Badge>,
                  },
                  {
                    key: "lines",
                    label: "عدد الأصناف",
                    render: (r) => r.lines.length,
                  },
                  {
                    key: "total_quantity",
                    label: "الكمية المُتلَفة",
                    render: (r) => (
                      <span>
                        {qty(r.total_quantity)}
                        <div className="text-xs font-normal text-slate-500 dark:text-slate-400">
                          {r.lines
                            .map((l) => `${l.product_name} (${qty(l.quantity)} ${l.base_unit_name})`)
                            .join("، ")}
                        </div>
                      </span>
                    ),
                  },
                  {
                    key: "total_cost",
                    label: "قيمة الخسارة",
                    // A 0.00 with no known batch cost means "unknown", not "worthless".
                    render: (r) =>
                      r.cost_known ? (
                        money(r.total_cost)
                      ) : (
                        <span className="text-xs text-amber-700 dark:text-amber-400">لا توجد تكلفة مسجلة</span>
                      ),
                  },
                  {
                    key: "status",
                    label: "الحالة",
                    render: (r) =>
                      r.status === "cancelled" ? (
                        <Badge tone="slate">ملغى</Badge>
                      ) : (
                        <Badge tone="green">مُثبّت</Badge>
                      ),
                  },
                  { key: "notes", label: "ملاحظات", render: (r) => r.notes || "—" },
                  { key: "created_at", label: "التاريخ", render: (r) => r.created_at?.slice(0, 10) },
                  {
                    key: "actions",
                    label: "",
                    render: (r) => (
                      <div className="flex flex-wrap gap-2">
                        <Button
                          variant="secondary"
                          onClick={() => navigate(`/print/adjustment/${r.id}`)}
                        >
                          🖨️ طباعة
                        </Button>
                        {r.status !== "cancelled" && canCancelAdjust && (
                          <Button variant="danger" onClick={() => cancelAdjustment(r)}>
                            إلغاء
                          </Button>
                        )}
                      </div>
                    ),
                  },
                ]}
                rows={adjustments.data}
                empty="لا توجد تعديلات مخزون بعد."
              />
            )}
          </Card>
        </div>
      )}

      {tab === "stocktake" && canCount && (
        <div className="space-y-6">
          {sheet ? (
            <Card
              title={`ورقة الجرد رقم ${sheet.id} — مستودع (${sheet.warehouse_name})`}
              actions={
                <>
                  <Button
                    variant="secondary"
                    onClick={() => navigate(`/print/stocktake/${sheet.id}`)}
                  >
                    🖨️ طباعة
                  </Button>
                  <Button variant="secondary" onClick={() => setSheet(null)}>
                    رجوع للقائمة
                  </Button>
                </>
              }
            >
              {sheet.status === "counting" ? (
                <p className="mb-3 text-xs font-bold text-slate-600 dark:text-slate-400">
                  أدخل ما وُجد فعلياً على الرف لكل تشغيلة. الحقول الفارغة تعني «لم
                  يُجرد» ولا تُحسب نقصاً. اضغط Enter للانتقال للسطر التالي.
                </p>
              ) : (
                <div className="mb-3 flex flex-wrap items-center gap-3 text-sm font-bold">
                  <Badge tone={STOCKTAKE_STATUS_TONE[sheet.status]}>
                    {STOCKTAKE_STATUS_LABELS[sheet.status]}
                  </Badge>
                  {sheet.posted_at && <span>تاريخ التثبيت: {sheet.posted_at.slice(0, 10)}</span>}
                  <span
                    className={
                      Number(sheet.net_value) < 0
                        ? "text-rose-700 dark:text-rose-400"
                        : "text-emerald-700 dark:text-emerald-400"
                    }
                  >
                    صافي قيمة الفروقات المُسوّاة: {money(sheet.net_value)}
                  </span>
                </div>
              )}
              <StocktakeSheet
                key={`${sheet.id}-${sheet.status}`}
                stocktake={sheet}
                onSaved={(updated) => {
                  setSheet(updated);
                  setNotice("تم حفظ الكميات المُدخلة.");
                  stocktakes.reload();
                }}
                onPosted={(updated) => {
                  setSheet(updated);
                  setNotice(
                    `تم تثبيت الجرد رقم ${updated.id} وتسوية الفروقات على المخزون.`
                  );
                  stocktakes.reload();
                  reloadAll();
                }}
              />
            </Card>
          ) : (
            <Card
              title="جرد المستودعات — تُسوّى فروقات النقص والزيادة عند التثبيت"
              actions={
                <div className="flex flex-wrap items-end gap-2">
                  <Select
                    value={newCountWarehouse}
                    onChange={(e) => setNewCountWarehouse(e.target.value)}
                  >
                    <option value="">— اختر المستودع —</option>
                    {warehouses.data.map((w) => (
                      <option key={w.id} value={w.id}>
                        {w.name}
                      </option>
                    ))}
                  </Select>
                  <Button onClick={openStocktake} disabled={!newCountWarehouse}>
                    + بدء جرد
                  </Button>
                </div>
              }
            >
              <Alert>{stocktakes.error}</Alert>
              {stocktakes.loading ? (
                <Loading />
              ) : (
                <Table
                  columns={[
                    { key: "id", label: "#" },
                    { key: "count_date", label: "تاريخ الجرد" },
                    { key: "warehouse_name", label: "المستودع" },
                    {
                      key: "status",
                      label: "الحالة",
                      render: (r) => (
                        <Badge tone={STOCKTAKE_STATUS_TONE[r.status]}>
                          {STOCKTAKE_STATUS_LABELS[r.status]}
                        </Badge>
                      ),
                    },
                    {
                      key: "counted_line_count",
                      label: "المجرود",
                      render: (r) => `${r.counted_line_count} / ${r.line_count}`,
                    },
                    {
                      key: "variance_line_count",
                      label: "سطور بفروقات",
                      render: (r) =>
                        r.variance_line_count > 0 ? (
                          <b className="text-amber-700 dark:text-amber-400">
                            {r.variance_line_count}
                          </b>
                        ) : (
                          "0"
                        ),
                    },
                    {
                      key: "net_value",
                      label: "صافي الفروقات",
                      render: (r) =>
                        r.status === "posted" ? (
                          <b
                            className={
                              Number(r.net_value) < 0
                                ? "text-rose-700 dark:text-rose-400"
                                : "text-emerald-700 dark:text-emerald-400"
                            }
                          >
                            {money(r.net_value)}
                          </b>
                        ) : (
                          "—"
                        ),
                    },
                    {
                      key: "actions",
                      label: "",
                      render: (r) => (
                        <div className="flex flex-wrap gap-1">
                          <Button variant="secondary" onClick={() => setSheet(r)}>
                            {r.status === "counting" ? "متابعة الجرد" : "عرض"}
                          </Button>
                          {r.status === "counting" && (
                            <Button variant="danger" onClick={() => cancelStocktake(r)}>
                              إلغاء
                            </Button>
                          )}
                        </div>
                      ),
                    },
                  ]}
                  rows={stocktakes.data}
                  empty="لا توجد عمليات جرد بعد."
                />
              )}
            </Card>
          )}
        </div>
      )}

      {tab === "expiry" && (
        <Card title="التشغيلات القريبة من الانتهاء (60 يوم)">
          {nearExpiry.loading ? (
            <Loading />
          ) : (
            <Table
              columns={[
                { key: "product_name", label: "الصنف" },
                { key: "warehouse_name", label: "المستودع" },
                { key: "batch_number", label: "التشغيلة" },
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
            />
          )}
        </Card>
      )}
    </div>
  );
}
