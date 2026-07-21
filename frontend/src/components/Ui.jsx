// Shared UI primitives used across all pages (Arabic RTL, Tailwind).
import React from "react";

export const money = (value) =>
  Number(value ?? 0).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

export const qty = (value) => {
  const n = Number(value ?? 0);
  return Number.isInteger(n) ? n.toLocaleString("en-US") : n.toLocaleString("en-US", { maximumFractionDigits: 3 });
};

const BUTTON_VARIANTS = {
  primary: "bg-emerald-700 text-white hover:bg-emerald-800",
  secondary: "bg-white text-slate-700 border border-slate-300 hover:bg-slate-50",
  danger: "bg-rose-600 text-white hover:bg-rose-700",
};

export function Button({ variant = "primary", className = "", ...props }) {
  return (
    <button
      className={`rounded-lg px-4 py-2 text-sm font-bold transition disabled:cursor-not-allowed disabled:opacity-50 ${BUTTON_VARIANTS[variant]} ${className}`}
      {...props}
    />
  );
}

export function Field({ label, children }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-bold text-slate-600">{label}</span>
      {children}
    </label>
  );
}

const CONTROL =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-emerald-600";

export function Input({ label, ...props }) {
  const input = <input className={CONTROL} {...props} />;
  return label ? <Field label={label}>{input}</Field> : input;
}

export function Select({ label, children, ...props }) {
  const select = (
    <select className={CONTROL} {...props}>
      {children}
    </select>
  );
  return label ? <Field label={label}>{select}</Field> : select;
}

export function Card({ title, actions, children, className = "" }) {
  return (
    <section className={`rounded-xl bg-white p-5 shadow-sm ${className}`}>
      {(title || actions) && (
        <header className="mb-4 flex items-center justify-between gap-2">
          <h2 className="text-lg font-extrabold text-slate-800">{title}</h2>
          <div className="flex gap-2">{actions}</div>
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint, tone = "emerald" }) {
  return (
    <div className="rounded-xl bg-white p-5 shadow-sm">
      <div className="text-sm font-bold text-slate-500">{label}</div>
      <div className={`mt-1 text-3xl font-extrabold text-${tone}-700`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-400">{hint}</div>}
    </div>
  );
}

export function Table({ columns, rows, keyField = "id", empty = "لا توجد بيانات لعرضها." }) {
  if (!rows?.length) {
    return <div className="py-10 text-center text-sm text-slate-400">{empty}</div>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-right text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-xs font-bold text-slate-500">
            {columns.map((col) => (
              <th key={col.key} className="px-3 py-2">
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={row[keyField] ?? index}
              className="border-b border-slate-100 last:border-0 hover:bg-slate-50"
            >
              {columns.map((col) => (
                <td key={col.key} className="px-3 py-2.5">
                  {col.render ? col.render(row) : row[col.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Modal({ open, title, onClose, children, wide = false }) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/50 p-4 pt-14"
      onClick={onClose}
    >
      <div
        className={`w-full ${wide ? "max-w-4xl" : "max-w-lg"} rounded-xl bg-white p-6 shadow-xl`}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-extrabold">{title}</h3>
          <button onClick={onClose} className="text-2xl leading-none text-slate-400 hover:text-slate-600">
            ×
          </button>
        </header>
        {children}
      </div>
    </div>
  );
}

export function Badge({ tone = "slate", children }) {
  const tones = {
    slate: "bg-slate-100 text-slate-700",
    green: "bg-emerald-100 text-emerald-800",
    red: "bg-rose-100 text-rose-800",
    amber: "bg-amber-100 text-amber-800",
    blue: "bg-sky-100 text-sky-800",
  };
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-bold ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function Alert({ tone = "error", children }) {
  if (!children) return null;
  const tones = {
    error: "bg-rose-50 text-rose-800 border-rose-200",
    success: "bg-emerald-50 text-emerald-800 border-emerald-200",
  };
  return <div className={`mb-4 rounded-lg border px-4 py-3 text-sm font-bold ${tones[tone]}`}>{children}</div>;
}

export function Loading() {
  return <div className="py-10 text-center text-sm text-slate-400">جارٍ التحميل...</div>;
}

const PAGE_SIZE = 15;

export function PaginatedTable({
  columns,
  rows,
  keyField = "id",
  empty = "لا توجد بيانات لعرضها.",
  searchable = false,
  searchPlaceholder = "بحث...",
  filterField,
  filterLabel,
  filterOptions = [],
  dateFromField,
  dateFromLabel = "من تاريخ",
  dateToField,
  dateToLabel = "إلى تاريخ",
  amountField,
  amountLabel = "المبلغ",
}) {
  const [page, setPage] = React.useState(0);
  const [term, setTerm] = React.useState("");
  const [filterVal, setFilterVal] = React.useState("");
  const [dateFrom, setDateFrom] = React.useState("");
  const [dateTo, setDateTo] = React.useState("");
  const [amountFrom, setAmountFrom] = React.useState("");
  const [amountTo, setAmountTo] = React.useState("");
  const [sortKey, setSortKey] = React.useState(null);
  const [sortDir, setSortDir] = React.useState("asc");

  React.useEffect(() => { setPage(0); }, [term, filterVal, dateFrom, dateTo, amountFrom, amountTo]);

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  // Stable ref to columns so the filter fn never goes stale.
  const columnsRef = React.useRef(columns);
  columnsRef.current = columns;

  const filtered = React.useMemo(() => {
    let result = rows || [];
    const cols = columnsRef.current;
    if (searchable && term.trim()) {
      const t = term.trim().toLowerCase();
      result = result.filter((row) => {
        // Search all raw field values
        for (const val of Object.values(row)) {
          if (val != null && String(val).toLowerCase().includes(t)) return true;
        }
        // Also search via column extractors
        for (const col of cols) {
          if (col.searchable === false) continue;
          if (typeof col.searchable === "function") {
            try {
              const s = col.searchable(row);
              if (s && String(s).toLowerCase().includes(t)) return true;
            } catch (_) { /* skip */ }
          }
        }
        return false;
      });
    }
    if (filterField && filterVal) {
      result = result.filter((row) => String(row[filterField]) === String(filterVal));
    }
    if (dateFromField && dateFrom) {
      result = result.filter((row) => row[dateFromField] >= dateFrom);
    }
    if (dateToField && dateTo) {
      result = result.filter((row) => row[dateToField] <= dateTo);
    }
    if (amountField && amountFrom) {
      result = result.filter((row) => Number(row[amountField]) >= Number(amountFrom));
    }
    if (amountField && amountTo) {
      result = result.filter((row) => Number(row[amountField]) <= Number(amountTo));
    }
    if (sortKey) {
      result = [...result].sort((a, b) => {
        const av = a[sortKey], bv = b[sortKey];
        if (av == null && bv == null) return 0;
        if (av == null) return 1;
        if (bv == null) return -1;
        const cmp = typeof av === "number" ? av - bv : String(av).localeCompare(String(bv), "ar");
        return sortDir === "asc" ? cmp : -cmp;
      });
    }
    return result;
  }, [rows, term, filterVal, dateFrom, dateTo, amountFrom, amountTo, sortKey, sortDir, searchable, filterField, dateFromField, dateToField, amountField]);

  const hasFilters = searchable || filterField || dateFromField || dateToField || amountField;
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages - 1);
  const pageRows = filtered.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE);

  const SORT_ARROW = (key) => {
    if (sortKey !== key) return <span className="mr-1 text-slate-300">⇅</span>;
    return <span className="mr-1 text-emerald-600">{sortDir === "asc" ? "↑" : "↓"}</span>;
  };

  return (
    <div>
      {hasFilters && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {searchable && (
            <input
              className="w-full max-w-xs rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-emerald-600"
              placeholder={searchPlaceholder}
              value={term}
              onChange={(e) => setTerm(e.target.value)}
            />
          )}
          {filterField && (
            <select
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-emerald-600"
              value={filterVal}
              onChange={(e) => setFilterVal(e.target.value)}
            >
              <option value="">{filterLabel || "الكل"}</option>
              {filterOptions.map((opt) => (
                <option key={opt.value ?? opt} value={opt.value ?? opt}>
                  {opt.label ?? opt}
                </option>
              ))}
            </select>
          )}
          {dateFromField && (
            <input type="date" className="rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} placeholder={dateFromLabel} />
          )}
          {dateToField && (
            <input type="date" className="rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm" value={dateTo} onChange={(e) => setDateTo(e.target.value)} placeholder={dateToLabel} />
          )}
          {amountField && (
            <>
              <input type="number" className="w-28 rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm" placeholder={`${amountLabel} من`} value={amountFrom} onChange={(e) => setAmountFrom(e.target.value)} />
              <input type="number" className="w-28 rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm" placeholder={`${amountLabel} إلى`} value={amountTo} onChange={(e) => setAmountTo(e.target.value)} />
            </>
          )}
        </div>
      )}
      <div className="overflow-x-auto">
        {filtered.length === 0 ? (
          <div className="py-10 text-center text-sm text-slate-400">{empty}</div>
        ) : (
          <table className="w-full text-right text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs font-bold text-slate-500">
                {columns.map((col) => (
                  <th
                    key={col.key}
                    className="cursor-pointer select-none px-3 py-2 hover:text-emerald-700"
                    onClick={() => handleSort(col.key)}
                  >
                    {col.label}{SORT_ARROW(col.key)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pageRows.map((row, index) => (
                <tr
                  key={row[keyField] ?? index}
                  className="border-b border-slate-100 last:border-0 hover:bg-slate-50"
                >
                  {columns.map((col) => (
                    <td key={col.key} className="px-3 py-2.5">
                      {col.render ? col.render(row) : row[col.key]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {filtered.length > PAGE_SIZE && (
        <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
          <span>
            عرض {safePage * PAGE_SIZE + 1}–{Math.min((safePage + 1) * PAGE_SIZE, filtered.length)}{" "}
            من {filtered.length}
          </span>
          <div className="flex gap-1">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={safePage === 0}
              className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-50 disabled:opacity-40"
            >
              ← التالي
            </button>
            {Array.from({ length: totalPages }, (_, i) => i)
              .filter((i) => i === 0 || i === totalPages - 1 || Math.abs(i - safePage) <= 2)
              .reduce((acc, i, idx, arr) => {
                if (idx > 0 && i - arr[idx - 1] > 1) acc.push("...");
                acc.push(i);
                return acc;
              }, [])
              .map((item, idx) =>
                item === "..." ? (
                  <span key={`e${idx}`} className="px-1 py-1">...</span>
                ) : (
                  <button
                    key={item}
                    onClick={() => setPage(item)}
                    className={`rounded border px-2 py-1 ${
                      item === safePage
                        ? "border-emerald-600 bg-emerald-700 text-white"
                        : "border-slate-300 hover:bg-slate-50"
                    }`}
                  >
                    {item + 1}
                  </button>
                )
              )}
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={safePage >= totalPages - 1}
              className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-50 disabled:opacity-40"
            >
              السابق →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
