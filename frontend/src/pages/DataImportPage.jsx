// Loading a legacy system into this one. Admin only.
//
// The screen is built around one idea: check before you commit. The default button
// only validates, the destructive one is deliberately harder to reach, and the
// reconciliation table at the end is what tells the admin whether the migration
// actually worked — a row count never could.
import { useState } from "react";
import { Alert, Badge, Button, Card, Loading, Table, money } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

/** Fetch a protected file and hand it to the browser as a download. */
async function download(path, filename) {
  const response = await api.get(path, { responseType: "blob" });
  const url = URL.createObjectURL(response.data);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function Rules({ rules }) {
  return (
    <ul className="space-y-2 text-sm text-slate-700 dark:text-slate-300">
      {rules.map((rule) => (
        <li key={rule} className="flex gap-2">
          <span className="text-emerald-700 dark:text-emerald-400">◂</span>
          <span>{rule}</span>
        </li>
      ))}
    </ul>
  );
}

function SheetReference({ sheets }) {
  const [open, setOpen] = useState(null);
  return (
    <div className="space-y-2">
      {sheets.map((sheet, index) => (
        <div
          key={sheet.name}
          className="rounded-lg border border-slate-200 dark:border-slate-700"
        >
          <button
            type="button"
            onClick={() => setOpen(open === sheet.name ? null : sheet.name)}
            className="flex w-full items-center justify-between gap-3 px-4 py-3 text-right"
          >
            <span className="text-xs font-bold text-slate-400">
              {open === sheet.name ? "▲" : "▼"}
            </span>
            <span className="flex-1">
              <span className="font-bold">
                {index + 1}. {sheet.title}
              </span>
              <span className="mr-2 font-mono text-xs text-slate-400">{sheet.name}</span>
              <span className="mt-1 block text-xs text-slate-500 dark:text-slate-400">
                {sheet.purpose}
              </span>
            </span>
          </button>
          {open === sheet.name && (
            <div className="border-t border-slate-200 px-4 py-3 dark:border-slate-700">
              <Table
                columns={[
                  { key: "name", label: "العمود", render: (r) => (
                      <span className="font-mono text-xs">{r.name}</span>
                    ) },
                  { key: "label", label: "الوصف" },
                  {
                    key: "required",
                    label: "إلزامي",
                    render: (r) =>
                      r.required ? <Badge tone="amber">إلزامي</Badge> : "—",
                  },
                  {
                    key: "kind",
                    label: "النوع",
                    render: (r) =>
                      r.choices.length ? r.choices.join(" / ") : r.kind,
                  },
                  { key: "note", label: "ملاحظات" },
                ]}
                rows={sheet.columns}
                keyField="name"
                searchable={false}
              />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export default function DataImportPage() {
  const guide = useFetch(() => api.get("/imports/guide"));
  const [files, setFiles] = useState([]);
  const [report, setReport] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const send = async (commit) => {
    setBusy(true);
    setError(null);
    // The previous report is cleared first: leaving a green "check passed" on
    // screen while a new run is in flight invites someone to press the commit
    // button on the strength of a result that no longer describes the files.
    setReport(null);
    try {
      const body = new FormData();
      files.forEach((file) => body.append("files", file));
      const { data } = await api.post("/imports/run", body, {
        params: { dry_run: !commit },
      });
      setReport(data.data);
    } catch (err) {
      setError(apiMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const checked = report && report.error_count === 0 && !report.applied;

  if (guide.loading) return <Loading />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold">استيراد البيانات من النظام القديم</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          رفع الأصناف والمخزون والعملاء والفواتير وسندات القبض دفعة واحدة. متاح للمدير فقط.
        </p>
      </div>

      <Card title="١ — نزّل القالب">
        <p className="mb-4 text-sm text-slate-600 dark:text-slate-400">
          القالب يحتوي على ورقة لكل نوع بيانات، وورقة «دليل الاستخدام» تشرح كل عمود،
          وورقة «أمثلة» توضّح الشكل المطلوب. أوراق البيانات فارغة عمداً حتى لا تُرفع
          أمثلة بالخطأ إلى نظامك.
        </p>
        <div className="flex flex-wrap gap-3">
          <Button
            onClick={() => download("/imports/template.xlsx", "erp-import-template.xlsx")}
          >
            ⬇ تنزيل قالب Excel
          </Button>
          <Button
            variant="secondary"
            onClick={() =>
              download("/imports/template.zip", "erp-import-template-csv.zip")
            }
          >
            ⬇ تنزيل قوالب CSV (مضغوطة)
          </Button>
        </div>
      </Card>

      <Card title="٢ — اقرأ القواعد قبل التعبئة">
        <Rules rules={guide.data?.rules || []} />
      </Card>

      <Card title="٣ — ارفع الملفات">
        <Alert>{error}</Alert>
        <input
          type="file"
          multiple
          accept=".xlsx,.csv"
          onChange={(event) => {
            setFiles(Array.from(event.target.files || []));
            setReport(null);
          }}
          className="block w-full rounded-lg border border-slate-300 bg-white p-2 text-sm dark:border-slate-600 dark:bg-slate-800"
        />
        {files.length > 0 && (
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
            {files.length} ملف: {files.map((f) => f.name).join("، ")}
          </p>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button disabled={!files.length || busy} onClick={() => send(false)}>
            {busy ? "جارٍ الفحص…" : "🔍 فحص فقط (بدون حفظ)"}
          </Button>
          {/* Only offered once a clean check has actually run against these files.
              Choosing the files again clears the report, so the button cannot be
              reached on the strength of a check of something else. */}
          <Button
            variant="danger"
            disabled={!checked || busy}
            onClick={() => {
              if (
                window.confirm(
                  "سيتم حفظ البيانات في النظام وترحيلها محاسبياً. هل تريد المتابعة؟"
                )
              ) {
                send(true);
              }
            }}
          >
            ⬆ تنفيذ الاستيراد
          </Button>
          {!checked && files.length > 0 && !busy && (
            <span className="text-xs font-bold text-slate-500 dark:text-slate-400">
              ابدأ بالفحص — زر التنفيذ يُفعّل بعد فحص ناجح.
            </span>
          )}
        </div>
      </Card>

      {report && <ImportReport report={report} />}

      <Card title="مرجع الأعمدة">
        <SheetReference sheets={guide.data?.sheets || []} />
      </Card>
    </div>
  );
}

function ImportReport({ report }) {
  const failed = report.error_count > 0;
  return (
    <Card title="النتيجة">
      <div
        className={`mb-4 rounded-lg p-4 text-sm font-bold ${
          failed
            ? "bg-rose-100 text-rose-800 dark:bg-rose-900/50 dark:text-rose-200"
            : report.applied
              ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200"
              : "bg-sky-100 text-sky-800 dark:bg-sky-900/50 dark:text-sky-200"
        }`}
      >
        {report.message}
      </div>

      {report.sheets.length > 0 && (
        <div className="mb-5 flex flex-wrap gap-2">
          {report.sheets.map((sheet) => (
            <Badge key={sheet.sheet} tone="slate">
              {sheet.title}: {sheet.rows}
            </Badge>
          ))}
        </div>
      )}

      {failed && (
        <div className="mb-6">
          <h3 className="mb-2 font-bold text-rose-700 dark:text-rose-400">
            الأخطاء ({report.error_count}
            {report.errors.length < report.error_count
              ? ` — تُعرض أول ${report.errors.length}`
              : ""}
            )
          </h3>
          <Table
            columns={[
              { key: "sheet_title", label: "الورقة" },
              { key: "row", label: "السطر", render: (r) => r.row ?? "—" },
              {
                key: "column",
                label: "العمود",
                render: (r) =>
                  r.column ? (
                    <span className="font-mono text-xs">{r.column}</span>
                  ) : (
                    "—"
                  ),
              },
              { key: "message", label: "الخطأ" },
            ]}
            rows={report.errors.map((e, i) => ({ ...e, _i: i }))}
            keyField="_i"
            empty="لا توجد أخطاء."
          />
        </div>
      )}

      {report.reconciliation.length > 0 && (
        <div>
          <h3 className="mb-1 font-bold">مطابقة أرصدة العملاء</h3>
          <p className="mb-3 text-xs text-slate-500 dark:text-slate-400">
            مقارنة الرصيد الذي حسبه النظام بعد الاستيراد مع الرصيد الذي أدخلته من
            النظام القديم. أي اختلاف هنا يعني أن شيئاً في الملف ناقص أو محسوب مرتين.
          </p>
          <Table
            columns={[
              { key: "customer_name", label: "العميل" },
              {
                key: "expected_balance",
                label: "حسب النظام القديم",
                render: (r) => money(r.expected_balance),
              },
              {
                key: "actual_balance",
                label: "حسب النظام الجديد",
                render: (r) => money(r.actual_balance),
              },
              {
                key: "difference",
                label: "الفرق",
                render: (r) => money(r.difference),
              },
              {
                key: "matches",
                label: "الحالة",
                render: (r) =>
                  r.matches ? (
                    <Badge tone="green">مطابق</Badge>
                  ) : (
                    <Badge tone="red">مختلف</Badge>
                  ),
              },
            ]}
            rows={report.reconciliation}
            keyField="customer_name"
            empty="لا توجد أرصدة للمطابقة."
          />
        </div>
      )}
    </Card>
  );
}
