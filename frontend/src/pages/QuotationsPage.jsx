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

const EMPTY_LINE = { product_id: "", product_label: "", quantity: "", unit_price: "", product_name: "" };

const productLabel = (p) => `${p.sku} — ${p.name}`;

const STATUS_LABELS = {
  draft: "مسودة",
  sent: "مرسل",
  accepted: "مقبول",
  rejected: "مرفوض",
  converted: "تم التحويل",
};

const STATUS_TONES = {
  draft: "slate",
  sent: "blue",
  accepted: "green",
  rejected: "red",
  converted: "amber",
};

function QuotationForm({ customers, warehouses, products, onCreated }) {
  const [form, setForm] = useState({
    customer_id: "",
    warehouse_id: "",
    valid_until: "",
    notes: "",
  });
  const [lines, setLines] = useState([{ ...EMPTY_LINE }]);
  const [error, setError] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const setLine = (index, key, value) =>
    setLines(lines.map((l, i) => (i === index ? { ...l, [key]: value } : l)));

  const setProductLine = (index, value) => {
    const match = products.find((p) => productLabel(p) === value);
    setLines(
      lines.map((l, i) =>
        i === index
          ? {
              ...l,
              product_label: value,
              product_id: match ? String(match.id) : "",
              product_name: match?.name || "",
              unit_price: match?.wholesale_price || "",
            }
          : l
      )
    );
  };

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    if (lines.some((l) => l.product_label && !l.product_id)) {
      setError("اختر الصنف من قائمة البحث لكل سطر.");
      return;
    }
    const payload = {
      customer_id: form.customer_id,
      warehouse_id: form.warehouse_id,
      valid_until: form.valid_until || null,
      notes: form.notes || null,
      lines: lines
        .filter((l) => l.product_id && l.quantity)
        .map((l) => ({
          product_id: Number(l.product_id),
          product_name: l.product_name,
          quantity: l.quantity,
          unit_price: l.unit_price || "0",
        })),
    };
    if (!payload.lines.length) {
      setError("أدخل صنفاً واحداً على الأقل.");
      return;
    }
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
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Select label="العميل" value={form.customer_id} onChange={set("customer_id")} required>
          <option value="">— اختر العميل —</option>
          {customers.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
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
        <Input
          label="صالح حتى"
          type="date"
          value={form.valid_until}
          onChange={set("valid_until")}
        />
      </div>
      <Input label="ملاحظات" value={form.notes} onChange={set("notes")} />

      <datalist id="quotation-products">
        {products.map((p) => (
          <option key={p.id} value={productLabel(p)} />
        ))}
      </datalist>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-bold text-slate-600">أسطر العرض</span>
          <Button type="button" variant="secondary" onClick={() => setLines([...lines, { ...EMPTY_LINE }])}>
            + سطر
          </Button>
        </div>
        {lines.map((line, index) => {
          return (
            <div key={index} className="mb-2 grid grid-cols-12 items-end gap-2">
              <div className="col-span-5">
                <Input
                  label={index === 0 ? "الصنف (اكتب للبحث)" : undefined}
                  list="quotation-products"
                  placeholder="ابحث بالرمز أو الاسم..."
                  value={line.product_label ?? ""}
                  onChange={(e) => setProductLine(index, e.target.value)}
                  required
                />
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
                <Input
                  label={index === 0 ? "سعر الوحدة" : undefined}
                  type="number"
                  step="0.01"
                  min="0"
                  value={line.unit_price}
                  onChange={(e) => setLine(index, "unit_price", e.target.value)}
                  required
                />
              </div>
              <div className="col-span-2">
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

      <Button type="submit">إنشاء عرض الأسعار</Button>
    </form>
  );
}

export default function QuotationsPage() {
  const { can } = useAuth();
  const [tab, setTab] = useState("list");
  const [viewing, setViewing] = useState(null);
  const [notice, setNotice] = useState(null);
  const [convertModal, setConvertModal] = useState(null);

  const quotations = useFetch(() => api.get("/sales/quotations"));
  const customers = useFetch(() => api.get("/sales/customers"));
  const warehouses = useFetch(() => api.get("/inventory/warehouses"));
  const products = useFetch(() => api.get("/inventory/products", { params: { is_active: true } }));

  if (customers.loading || warehouses.loading || products.loading) return <Loading />;

  const canManage = can("sales.quotations");

  const TABS = [
    { id: "list", label: "القائمة" },
    ...(canManage ? [{ id: "new", label: "+ عرض جديد" }] : []),
  ];

  const updateStatus = async (quotationId, status) => {
    try {
      await api.patch(`/sales/quotations/${quotationId}/status`, null, { params: { status } });
      setNotice(`تم تحديث حالة العرض رقم ${quotationId} بنجاح.`);
      quotations.reload();
      setViewing(null);
    } catch (err) {
      alert(apiMessage(err));
    }
  };

  const convertToInvoice = async (paymentMethod) => {
    if (!convertModal) return;
    try {
      const { data } = await api.post(
        `/sales/quotations/${convertModal.id}/convert`,
        null,
        { params: { payment_method: paymentMethod } }
      );
      setNotice(`تم تحويل عرض الأسعار رقم ${convertModal.id} إلى فاتورة مبيعات رقم ${data.data.id}.`);
      setConvertModal(null);
      setViewing(null);
      quotations.reload();
    } catch (err) {
      alert(apiMessage(err));
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-extrabold">عروض الأسعار</h1>
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

      {tab === "new" && canManage && (
        <Card title="عرض أسعار جديد">
          <QuotationForm
            customers={customers.data}
            warehouses={warehouses.data}
            products={products.data}
            onCreated={(quotation) => {
              setViewing(quotation);
              setTab("list");
              setNotice(null);
              quotations.reload();
            }}
          />
        </Card>
      )}

      {tab === "list" && (
        <Card>
          <Alert>{quotations.error}</Alert>
          {quotations.loading ? (
            <Loading />
          ) : (
            <PaginatedTable
              columns={[
                { key: "id", label: "#" },
                { key: "quotation_date", label: "التاريخ" },
                {
                  key: "customer_id",
                  label: "العميل",
                  render: (r) => customers.data.find((c) => c.id === r.customer_id)?.name ?? r.customer_id,
                  searchable: (r) => customers.data.find((c) => c.id === r.customer_id)?.name ?? "",
                },
                {
                  key: "status",
                  label: "الحالة",
                  render: (r) => <Badge tone={STATUS_TONES[r.status]}>{STATUS_LABELS[r.status]}</Badge>,
                },
                { key: "total", label: "الإجمالي", render: (r) => <b>{money(r.total)}</b> },
                { key: "valid_until", label: "صالح حتى", render: (r) => r.valid_until || "—" },
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
              rows={quotations.data}
              empty="لا توجد عروض أسعار بعد."
              searchable
              searchPlaceholder="بحث بالعميل أو رقم العرض..."
              filterField="status"
              filterLabel="الحالة"
              filterOptions={[
                { value: "draft", label: "مسودة" },
                { value: "sent", label: "مرسلة" },
                { value: "accepted", label: "مقبولة" },
                { value: "rejected", label: "مرفوضة" },
                { value: "converted", label: "محولة" },
              ]}
              dateFromField="quotation_date"
              dateToField="quotation_date"
              amountField="total"
              amountLabel="الإجمالي"
            />
          )}
        </Card>
      )}

      <Modal
        open={!!viewing}
        title={viewing ? `عرض أسعار رقم ${viewing.id}` : ""}
        onClose={() => setViewing(null)}
        wide
      >
        {viewing && (
          <div className="space-y-4">
            <div className="flex gap-4 text-sm">
              <span>العميل: <b>{customers.data.find((c) => c.id === viewing.customer_id)?.name ?? viewing.customer_id}</b></span>
              <span>التاريخ: <b>{viewing.quotation_date}</b></span>
              {viewing.valid_until && <span>صالح حتى: <b>{viewing.valid_until}</b></span>}
              <Badge tone={STATUS_TONES[viewing.status]}>{STATUS_LABELS[viewing.status]}</Badge>
            </div>
            {viewing.notes && <p className="text-sm text-slate-500">{viewing.notes}</p>}
            <Table
              columns={[
                {
                  key: "product_id",
                  label: "الصنف",
                  render: (r) => r.product_name,
                },
                { key: "quantity", label: "الكمية", render: (r) => qty(r.quantity) },
                { key: "unit_price", label: "سعر الوحدة", render: (r) => money(r.unit_price) },
                { key: "line_total", label: "الإجمالي", render: (r) => money(r.line_total) },
              ]}
              rows={viewing.lines}
            />
            <div className="flex items-center justify-between border-t border-slate-200 pt-3">
              <div className="flex gap-2">
                {viewing.status === "draft" && (
                  <Button variant="secondary" onClick={() => updateStatus(viewing.id, "sent")}>
                    إرسال للعميل
                  </Button>
                )}
                {viewing.status === "sent" && (
                  <>
                    <Button variant="primary" onClick={() => updateStatus(viewing.id, "accepted")}>
                      قبول
                    </Button>
                    <Button variant="danger" onClick={() => updateStatus(viewing.id, "rejected")}>
                      رفض
                    </Button>
                  </>
                )}
                {viewing.status === "accepted" && (
                  <Button onClick={() => setConvertModal(viewing)}>
                    تحويل إلى فاتورة مبيعات
                  </Button>
                )}
                {viewing.status === "draft" && can("sales.delete") && (
                  <Button
                    variant="danger"
                    onClick={async () => {
                      if (!window.confirm(`حذف عرض الأسعار رقم ${viewing.id}؟`)) return;
                      try {
                        await api.delete(`/sales/quotations/${viewing.id}`);
                        setNotice(`تم حذف عرض الأسعار رقم ${viewing.id}.`);
                        setViewing(null);
                        quotations.reload();
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
                <span>قبل الضريبة: {money(viewing.subtotal)}</span>
                <span>الضريبة: {money(viewing.vat_amount)}</span>
                <span className="text-emerald-700">الإجمالي: {money(viewing.total)}</span>
              </div>
            </div>
          </div>
        )}
      </Modal>

      <Modal
        open={!!convertModal}
        title={convertModal ? `تحويل عرض رقم ${convertModal.id} إلى فاتورة` : ""}
        onClose={() => setConvertModal(null)}
      >
        {convertModal && (
          <div className="space-y-4">
            <p className="text-sm text-slate-600">
              سيتم خصم المخزون من المستودع حسب قاعدة FEFO. اختر طريقة الدفع:
            </p>
            <div className="flex gap-4">
              <Button onClick={() => convertToInvoice("cash")}>نقدي</Button>
              <Button variant="secondary" onClick={() => convertToInvoice("credit")}>آجل</Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
