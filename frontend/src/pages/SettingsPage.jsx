// The control panel: company identity used on printed documents, the country the
// business trades in, and the tax rates available when invoicing.
//
// A tax with no country applies everywhere; one tagged with a country is only
// offered when it matches the company's own, so a foreign rate can be prepared
// in advance without appearing on today's invoices.
import { useEffect, useState } from "react";
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
} from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const EMPTY_TAX_FORM = {
  name: "",
  code: "",
  rate: "",
  country_code: "",
  is_active: true,
  is_default: false,
};

/** Reference list backing every country picker on this page. */
const useCountries = () => useFetch(() => api.get("/settings/countries"));
const useTimezones = () => useFetch(() => api.get("/settings/timezones"));

// The company's working day starts at midnight in this zone. It is not cosmetic:
// the cashier's closing report and every "by day" figure are cut on this boundary,
// which is why the offset is shown next to each city.
function TimezoneSelect({ value, onChange, timezones }) {
  return (
    <Select
      label="توقيت الشركة — عليه يبدأ يوم العمل وتُقفل عليه حسابات الصندوق"
      value={value || "UTC"}
      onChange={onChange}
    >
      {timezones.map((tz) => (
        <option key={tz.name} value={tz.name}>
          {tz.label} ({tz.utc_offset})
        </option>
      ))}
    </Select>
  );
}

function CountrySelect({ label, value, onChange, countries, universalLabel }) {
  return (
    <Select label={label} value={value || ""} onChange={onChange}>
      <option value="">{universalLabel}</option>
      {countries.map((c) => (
        <option key={c.code} value={c.code}>
          {c.name}
        </option>
      ))}
    </Select>
  );
}

function TaxRateForm({ onSaved, onClose, countries }) {
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
        country_code: form.country_code || null,
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
      <CountrySelect
        label="الدولة التي تنطبق فيها هذه الضريبة"
        value={form.country_code}
        onChange={set("country_code")}
        countries={countries}
        universalLabel="— تنطبق في كل الدول —"
      />
      <p className="-mt-2 text-xs font-bold text-slate-500 dark:text-slate-400">
        الضريبة المرتبطة بدولة لا تُعرض عند إصدار الفواتير إلا إذا كانت هي دولة
        الشركة؛ اترك الحقل فارغاً لضريبة تنطبق دائماً.
      </p>
      <label className="flex items-center gap-2 text-sm font-bold text-slate-600 dark:text-slate-400">
        <input type="checkbox" checked={form.is_active} onChange={set("is_active")} />
        مفعّلة
      </label>
      <label className="flex items-center gap-2 text-sm font-bold text-slate-600 dark:text-slate-400">
        <input type="checkbox" checked={form.is_default} onChange={set("is_default")} />
        الضريبة الافتراضية المقترحة عند إصدار فاتورة جديدة
      </label>
      <div className="flex justify-end gap-2">
        <CancelButton onClose={onClose} />
        <Button type="submit">حفظ الضريبة</Button>
      </div>
    </form>
  );
}

function TaxRatesSection({ canManage, countries, companyCountry }) {
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
            {
              key: "country_code",
              label: "الدولة",
              // A rate for another country is configured but never offered while
              // the company operates elsewhere — worth showing plainly.
              render: (r) =>
                !r.country_code ? (
                  <Badge tone="blue">كل الدول</Badge>
                ) : companyCountry && r.country_code !== companyCountry ? (
                  <span className="flex flex-wrap items-center gap-1">
                    {r.country_name}
                    <Badge tone="slate">خارج نطاق الشركة</Badge>
                  </span>
                ) : (
                  r.country_name
                ),
              search: (r) => r.country_name ?? "كل الدول",
              sortValue: (r) => r.country_name ?? "",
            },
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
          countries={countries}
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

function CompanySection({ canManage, countries, timezones, onCountrySaved }) {
  const { data, loading, error, reload } = useFetch(() => api.get("/settings/company"));
  const [form, setForm] = useState(null);
  const [notice, setNotice] = useState(null);
  const [saveError, setSaveError] = useState(null);

  useEffect(() => {
    if (data) setForm(data);
  }, [data]);

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  // Choosing a country fills in its usual currency, but only when the currency
  // has not been customised — never silently overwrite a deliberate choice.
  const setCountry = (e) => {
    const code = e.target.value;
    const country = countries.find((c) => c.code === code);
    setForm((current) => {
      const previous = countries.find((c) => c.code === current.country_code);
      // The currency counts as untouched when it is empty, still matches the
      // country picked before, or no country had been chosen at all — in which
      // case it is only the install default and safe to replace.
      const currencyIsSuggestion =
        !current.currency_code ||
        !current.country_code ||
        current.currency_code === previous?.currency_code;
      return {
        ...current,
        country_code: code,
        ...(country && currencyIsSuggestion
          ? {
              currency_code: country.currency_code,
              currency_symbol: country.currency_symbol,
            }
          : {}),
      };
    });
  };

  const submit = async (event) => {
    event.preventDefault();
    setSaveError(null);
    setNotice(null);
    try {
      await api.put("/settings/company", { ...form, country_code: form.country_code || null });
      setNotice("تم حفظ بيانات الشركة بنجاح.");
      reload();
      // Tax scoping depends on this, so the tax table has to re-read it.
      onCountrySaved();
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
            <CountrySelect
              label="دولة العمل — تحدد الضرائب المتاحة عند إصدار الفواتير"
              value={form.country_code}
              onChange={setCountry}
              countries={countries}
              universalLabel="— لم تُحدد —"
            />
            <TimezoneSelect
              value={form.timezone}
              onChange={set("timezone")}
              timezones={timezones}
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

          {/* Four numbers that decide what the system orders and how deep it
              discounts. They existed in the API from the day the reorder point and
              the clearance plan were built, and no screen could change them — which
              meant the only way to set company policy was a curl command. */}
          <div className="space-y-3 rounded-lg border border-slate-200 p-4 dark:border-slate-700">
            <div>
              <h3 className="text-sm font-bold text-slate-800 dark:text-slate-100">
                سياسة الشراء والتصريف
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                تُستخدم في حساب نقطة إعادة الطلب وفي عمق الخصم المقترح على المخزون
                القريب من الانتهاء.
              </p>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Input
                label="مهلة التوريد الافتراضية (يوم)"
                type="number"
                min="1"
                max="180"
                value={form.default_lead_time_days}
                onChange={set("default_lead_time_days")}
              />
              <Input
                label="مخزون الأمان (يوم تغطية)"
                type="number"
                min="0"
                max="180"
                value={form.safety_stock_days}
                onChange={set("safety_stock_days")}
              />
              <Input
                label="دورية مراجعة الطلبات (يوم)"
                type="number"
                min="1"
                max="180"
                value={form.reorder_review_days}
                onChange={set("reorder_review_days")}
              />
              <Input
                label="إيقاف البيع الآجل بعد (يوم) — صفر يعطّله"
                type="number"
                min="0"
                max="730"
                value={form.credit_block_after_days}
                onChange={set("credit_block_after_days")}
              />
              <Input
                label="أقصى خصم تصريف مسموح %"
                type="number"
                min="1"
                max="90"
                step="0.01"
                value={form.markdown_max_discount_percent}
                onChange={set("markdown_max_discount_percent")}
              />
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              إيقاف البيع الآجل يقيس <span className="font-bold">عمر</span> الدين لا
              حجمه؛ الحد الائتماني وحده يمرّر عميلاً متأخراً سنة ما دام تحت سقفه.
              يبقى للمدير تجاوزه بالموافقة على الفاتورة.
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              سقف الخصم حدٌّ أعلى وليس هدفاً: لن يقترح النظام أعمق منه، وتستطيع شاشة
              خطة التصريف أن تختار أقل منه في أي وقت.
            </p>
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
  const countries = useCountries();
  const timezones = useTimezones();
  const company = useFetch(() => api.get("/settings/company"));
  // Bumping this re-mounts the tax table so its "out of scope" markers follow a
  // change to the company's country.
  const [scopeVersion, setScopeVersion] = useState(0);

  if (countries.loading || company.loading) return <Loading />;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold">لوحة الإعدادات</h1>
      <Alert>{countries.error}</Alert>
      {!canManage && (
        <Alert>لا تملك صلاحية التعديل على هذه الصفحة، يمكنك العرض فقط.</Alert>
      )}
      <CompanySection
        canManage={canManage}
        countries={countries.data || []}
        timezones={timezones.data || []}
        onCountrySaved={() => {
          company.reload();
          setScopeVersion((v) => v + 1);
        }}
      />
      <TaxRatesSection
        key={scopeVersion}
        canManage={canManage}
        countries={countries.data || []}
        companyCountry={company.data?.country_code ?? null}
      />
    </div>
  );
}
