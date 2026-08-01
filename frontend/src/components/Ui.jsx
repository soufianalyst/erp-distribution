// Shared UI primitives used across all pages (Arabic RTL, Tailwind).
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

const DISCARD_CONFIRM =
  "لديك بيانات غير محفوظة في هذا النموذج. هل تريد الخروج وإلغاء ما أدخلته؟";

// Serialise every form control inside a subtree, so a snapshot taken when the
// form opens can be compared against its current state to detect edits. Using
// the live DOM keeps this generic: no form has to report its own dirty state.
const snapshotFields = (root) => {
  if (!root) return null;
  return JSON.stringify(
    Array.from(root.querySelectorAll("input, select, textarea")).map((el) =>
      el.type === "checkbox" || el.type === "radio" ? String(el.checked) : el.value
    )
  );
};

// Lets a Cancel button inside a modal reuse the modal's own guarded close, so
// discarding a half-filled form always asks first, however it is dismissed.
const ModalCloseContext = createContext(null);

export const useModalClose = () => useContext(ModalCloseContext);

/**
 * Guards a form against losing unsaved input. Attach `ref` to the element
 * wrapping the fields; while `active`, leaving is only allowed if nothing
 * changed or the user confirms.
 *
 * Used by Modal for dialogs, and directly by the tab-hosted invoice forms,
 * which are not dialogs and so were previously abandoned without warning.
 */
export function useUnsavedGuard(active = true) {
  const ref = useRef(null);
  // Baseline of the fields as they first appeared; null until captured.
  const baselineRef = useRef(null);

  useEffect(() => {
    if (!active) {
      baselineRef.current = null;
      return undefined;
    }
    // Snapshot after the first paint so values pre-filled from an existing
    // record count as clean rather than as user input.
    const timer = setTimeout(() => {
      baselineRef.current = snapshotFields(ref.current);
    }, 0);
    return () => clearTimeout(timer);
  }, [active]);

  const isDirty = useCallback(() => {
    if (!active || baselineRef.current === null) return false;
    return snapshotFields(ref.current) !== baselineRef.current;
  }, [active]);

  /** True when it is safe to leave — either nothing changed or the user agreed. */
  const confirmLeave = useCallback(
    () => !isDirty() || window.confirm(DISCARD_CONFIRM),
    [isDirty]
  );

  /** Treat the current values as the new clean baseline (e.g. after saving). */
  const markClean = useCallback(() => {
    baselineRef.current = snapshotFields(ref.current);
  }, []);

  useEffect(() => {
    if (!active) return undefined;
    // Reloading or closing the tab mid-entry gets the browser's own warning.
    const onBeforeUnload = (event) => {
      if (!isDirty()) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [active, isDirty]);

  return { ref, isDirty, confirmLeave, markClean };
}

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

// Design principle: every table paginates at 15 rows/page, has a search box,
// and sorts by clicking any column header — avoids long pages and slow
// rendering, and is the standard for tables across the app. Built into this
// shared component so all callers get it automatically.
//
// Per-column overrides (all optional):
//   col.search(row)    -> string used for search matching (default: row[col.key])
//   col.sortValue(row) -> value used for sorting (default: row[col.key])
//   col.sortable = false to disable sorting for one column (columns with no
//   label — typically action/button columns — are non-sortable by default).
//
// keyField is a field name, or a function (row) -> key for rows whose identity
// spans several columns (e.g. stock levels are unique per product+warehouse,
// not per product alone).
export function Table({
  columns,
  rows,
  keyField = "id",
  empty = "لا توجد بيانات لعرضها.",
  pageSize = 15,
  searchable = true,
  searchPlaceholder = "بحث...",
}) {
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState({ key: null, dir: "asc" });
  useEffect(() => {
    setPage(1);
  }, [rows?.length, query]);

  if (!rows?.length) {
    return <div className="py-10 text-center text-sm text-slate-400">{empty}</div>;
  }

  const q = query.trim().toLowerCase();
  const filtered = q
    ? rows.filter((row) =>
        columns.some((col) => {
          const value = col.search ? col.search(row) : row[col.key];
          return String(value ?? "").toLowerCase().includes(q);
        })
      )
    : rows;

  let sorted = filtered;
  if (sort.key) {
    const col = columns.find((c) => c.key === sort.key);
    sorted = [...filtered].sort((a, b) => {
      const av = col?.sortValue ? col.sortValue(a) : a[sort.key];
      const bv = col?.sortValue ? col.sortValue(b) : b[sort.key];
      const an = Number(av);
      const bn = Number(bv);
      const bothNumeric = av !== "" && bv !== "" && av != null && bv != null && !Number.isNaN(an) && !Number.isNaN(bn);
      const cmp = bothNumeric ? an - bn : String(av ?? "").localeCompare(String(bv ?? ""), "ar");
      return sort.dir === "asc" ? cmp : -cmp;
    });
  }

  const toggleSort = (key) =>
    setSort((prev) => {
      if (prev.key !== key) return { key, dir: "asc" };
      if (prev.dir === "asc") return { key, dir: "desc" };
      return { key: null, dir: "asc" };
    });

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const pageRows = sorted.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  return (
    <div>
      {searchable && (
        <div className="mb-3">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={searchPlaceholder}
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-emerald-600 sm:w-64"
          />
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-right text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-xs font-bold text-slate-500">
              {columns.map((col) => {
                const isSortable = !!col.label && col.sortable !== false;
                return (
                  <th
                    key={col.key}
                    className={`px-3 py-2 ${isSortable ? "cursor-pointer select-none hover:text-slate-700" : ""}`}
                    onClick={isSortable ? () => toggleSort(col.key) : undefined}
                  >
                    <span className="inline-flex items-center gap-1">
                      {col.label}
                      {isSortable && sort.key === col.key && (
                        <span className="text-emerald-700">{sort.dir === "asc" ? "▲" : "▼"}</span>
                      )}
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>
          {pageRows.length > 0 ? (
            <tbody>
              {pageRows.map((row, index) => (
                <tr
                  key={(typeof keyField === "function" ? keyField(row) : row[keyField]) ?? index}
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
          ) : (
            <tbody>
              <tr>
                <td colSpan={columns.length} className="py-8 text-center text-sm text-slate-400">
                  لا توجد نتائج مطابقة لبحثك.
                </td>
              </tr>
            </tbody>
          )}
        </table>
      </div>
      {totalPages > 1 && (
        <div className="mt-3 flex items-center justify-between text-xs font-bold text-slate-500">
          <span>إجمالي {sorted.length} عنصر</span>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              disabled={currentPage === 1}
              onClick={() => setPage(currentPage - 1)}
            >
              السابق
            </Button>
            <span>
              صفحة {currentPage} من {totalPages}
            </span>
            <Button
              variant="secondary"
              disabled={currentPage === totalPages}
              onClick={() => setPage(currentPage + 1)}
            >
              التالي
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

export function Modal({
  open,
  title,
  onClose,
  children,
  wide = false,
  // Confirmation dialogs hold no record to preserve, so they opt out of the
  // unsaved-changes prompt that data-entry dialogs get.
  guardUnsaved = true,
}) {
  const { ref: contentRef, confirmLeave } = useUnsavedGuard(open && guardUnsaved);

  // Every dismissal route funnels through here: backdrop, ×, Escape, Cancel.
  const requestClose = useCallback(() => {
    if (!confirmLeave()) return;
    onClose();
  }, [confirmLeave, onClose]);

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        requestClose();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, requestClose]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/50 p-4 pt-14"
      onClick={requestClose}
    >
      <div
        ref={contentRef}
        className={`w-full ${wide ? "max-w-4xl" : "max-w-lg"} rounded-xl bg-white p-6 shadow-xl`}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-extrabold">{title}</h3>
          <button onClick={requestClose} className="text-2xl leading-none text-slate-400 hover:text-slate-600">
            ×
          </button>
        </header>
        <ModalCloseContext.Provider value={requestClose}>{children}</ModalCloseContext.Provider>
      </div>
    </div>
  );
}

/** Cancel button for a form inside a Modal — confirms first if data was entered. */
export function CancelButton({ onClose, children = "إلغاء", ...props }) {
  const guardedClose = useModalClose();
  return (
    <Button
      type="button"
      variant="secondary"
      onClick={guardedClose ?? onClose}
      {...props}
    >
      {children}
    </Button>
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
