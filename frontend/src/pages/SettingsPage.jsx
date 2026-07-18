import { useEffect, useState } from "react";
import { Alert, Badge, Button, Card, Input, Modal, Table, money } from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const EMPTY_TAX_FORM = {
  name: "",
  code: "",
  rate: "",
  country: "",
  is_active: true,
  is_default: false,
};

function TaxRateForm({ onSaved, onClose }) {
  const [form, setForm] = useState(EMPTY_TAX_FORM);
  const [error, setError] = useState(null);
  const set = (key) => (e) =>
    setForm({
      ...form,
      [key]: e.target.type === "checkbox" ? e.target.checked : e.target.value,
    });

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      await api.post("/settings/tax-rates", {
        ...form,
        country: form.country || null,
      });
      onSaved();
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Alert>{error}</Alert>
      <Input label="اسم الضريبة" value={form.name} onChange={set("name")} required autoFocus />
      <Input
        label="الرمز (فريد، مثال: VAT، GST)"
        value={form.code}
        onChange={set("code")}
        required
      />
      <Input
        label="النسبة المئوية (مثال: 16 تعني 16%)"
        type="number"
        step="0.001"
        min="0"
        max="100"
        value={form.rate}
        onChange={set("rate")}
        required
      />
      <Input
        label="الدولة/المنطقة (اختياري)"
        value={form.country}
        onChange={set("country")}
      />
      <label className="flex items-center gap-2 text-sm font-bold text-slate-600">
        <input type="checkbox" checked={form.is_active} onChange={set("is_active")} />
        مفعّلة
      </label>
      <label className="flex items-center gap-2 text-sm font-bold text-slate-600">
        <input type="checkbox" checked={form.is_default} onChange={set("is_default")} />
        الضريبة الافتراضية المقترحة عند إصدار فاتورة جديدة
      </label>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onClose}>
          إلغاء
        </Button>
        <Button type="submit">حفظ الضريبة</Button>
      </div>
    </form>
  );
}

function TaxRatesSection({ canManage }) {
  const { data, loading, error, reload } = useFetch(() => api.get("/settings/tax-rates"));
  const [open, setOpen] = useState(false);
  const [notice, setNotice] = useState(null);

  const toggle = async (taxRate, field) => {
    try {
      await api.patch(`/settings/tax-rates/${taxRate.id}`, { [field]: !taxRate[field] });
      reload();
    } catch (err) {
      setNotice(apiMessage(err));
    }
  };

  const remove = async (taxRate) => {
    if (
      !window.confirm(
        `حذف الضريبة "${taxRate.name}"؟ الفواتير السابقة تحتفظ بقيمتها كما كانت.`
      )
    )
      return;
    try {
      await api.delete(`/settings/tax-rates/${taxRate.id}`);
      setNotice("تم حذف الضريبة بنجاح.");
      reload();
    } catch (err) {
      setNotice(apiMessage(err));
    }
  };

  return (
    <Card
      title="أنواع الضرائب"
      actions={canManage && <Button onClick={() => setOpen(true)}>+ ضريبة جديدة</Button>}
    >
      <Alert>{error}</Alert>
      <Alert tone="success">{notice}</Alert>
      {!loading && (
        <Table
          columns={[
            { key: "name", label: "اسم الضريبة" },
            { key: "code", label: "الرمز" },
            { key: "rate", label: "النسبة", render: (r) => `${r.rate}%` },
            { key: "country", label: "الدولة/المنطقة", render: (r) => r.country || "—" },
            {
              key: "is_default",
              label: "افتراضية",
              render: (r) =>
                canManage ? (
                  <button onClick={() => toggle(r, "is_default")}>
                    {r.is_default ? (
                      <Badge tone="green">نعم</Badge>
                    ) : (
                      <Badge tone="slate">لا</Badge>
                    )}
                  </button>
                ) : r.is_default ? (
                  <Badge tone="green">نعم</Badge>
                ) : (
                  <Badge tone="slate">لا</Badge>
                ),
            },
            {
              key: "is_active",
              label: "الحالة",
              render: (r) =>
                canManage ? (
                  <button onClick={() => toggle(r, "is_active")}>
                    {r.is_active ? (
                      <Badge tone="green">مفعّلة</Badge>
                    ) : (
                      <Badge tone="red">موقوفة</Badge>
                    )}
                  </button>
                ) : r.is_active ? (
                  <Badge tone="green">مفعّلة</Badge>
                ) : (
                  <Badge tone="red">موقوفة</Badge>
                ),
            },
            ...(canManage
              ? [
                  {
                    key: "actions",
                    label: "",
                    sortable: false,
                    render: (r) => (
                      <Button variant="danger" onClick={() => remove(r)}>
                        🗑️ حذف
                      </Button>
                    ),
                  },
                ]
              : []),
          ]}
          rows={data || []}
          searchPlaceholder="بحث في الضرائب..."
        />
      )}
      <Modal open={open} title="إضافة ضريبة جديدة" onClose={() => setOpen(false)}>
        <TaxRateForm
          onSaved={() => {
            setOpen(false);
            setNotice("تم إضافة الضريبة بنجاح.");
            reload();
          }}
          onClose={() => setOpen(false)}
        />
      </Modal>
    </Card>
  );
}

function CompanySection({ canManage }) {
  const { data, loading, error, reload } = useFetch(() => api.get("/settings/company"));
  const [form, setForm] = useState(null);
  const [notice, setNotice] = useState(null);
  const [saveError, setSaveError] = useState(null);

  useEffect(() => {
    if (data) setForm(data);
  }, [data]);

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const submit = async (event) => {
    event.preventDefault();
    setSaveError(null);
    setNotice(null);
    try {
      await api.put("/settings/company", form);
      setNotice("تم حفظ بيانات الشركة بنجاح.");
      reload();
    } catch (err) {
      setSaveError(apiMessage(err));
    }
  };

  if (loading || !form) return <Card title="بيانات الشركة">جارٍ التحميل...</Card>;

  return (
    <Card title="بيانات الشركة (تظهر في رأس المستندات المطبوعة)">
      <Alert>{error || saveError}</Alert>
      <Alert tone="success">{notice}</Alert>
      <fieldset disabled={!canManage} className="space-y-4">
        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Input label="اسم الشركة" value={form.name} onChange={set("name")} required />
            <Input
              label="الوصف المختصر (تحت الاسم)"
              value={form.tagline || ""}
              onChange={set("tagline")}
            />
            <Input label="العنوان" value={form.address || ""} onChange={set("address")} />
            <Input label="الهاتف" value={form.phone || ""} onChange={set("phone")} />
            <Input
              label="الرقم الضريبي"
              value={form.tax_number || ""}
              onChange={set("tax_number")}
            />
            <div className="grid grid-cols-2 gap-4">
              <Input
                label="رمز العملة (مثال: SAR)"
                value={form.currency_code}
                onChange={set("currency_code")}
                required
              />
              <Input
                label="رمز العملة المطبوع (مثال: ر.س)"
                value={form.currency_symbol}
                onChange={set("currency_symbol")}
                required
              />
            </div>
          </div>
          {canManage && (
            <div className="flex justify-end">
              <Button type="submit">حفظ بيانات الشركة</Button>
            </div>
          )}
        </form>
      </fieldset>
    </Card>
  );
}

export default function SettingsPage() {
  const { can } = useAuth();
  const canManage = can("settings.manage");

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold">الإعدادات</h1>
      {!canManage && (
        <Alert>لا تملك صلاحية التعديل على هذه الصفحة، يمكنك العرض فقط.</Alert>
      )}
      <TaxRatesSection canManage={canManage} />
      <CompanySection canManage={canManage} />
    </div>
  );
}
