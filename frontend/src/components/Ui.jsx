// Shared UI primitives used across all pages (Arabic RTL, Tailwind).
import { Fragment, createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

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

/**
 * Today, as the user's calendar sees it — "YYYY-MM-DD" in local time.
 *
 * Deliberately not `new Date().toISOString().slice(0, 10)`, which returns the
 * *UTC* day and is therefore the wrong day for part of every 24 hours. That
 * matters most in exactly the screens that use it: end-of-day closes. It was
 * caught on the round-settlement screen, where a van sale posted minutes earlier
 * — dated by the server's own local today — did not appear at all, because the
 * screen had defaulted to asking about yesterday.
 */
export const todayStr = () => {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
};

const BUTTON_VARIANTS = {
  primary: "bg-emerald-700 text-white hover:bg-emerald-800 dark:bg-emerald-600 dark:hover:bg-emerald-500",
  secondary:
    "bg-white text-slate-700 border border-slate-300 hover:bg-slate-50 dark:bg-slate-800 dark:text-slate-200 dark:border-slate-600 dark:hover:bg-slate-700",
  danger: "bg-rose-600 text-white hover:bg-rose-700 dark:bg-rose-700 dark:hover:bg-rose-600",
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
      {/* `field-label` lets repeated line-item labels hide on wider screens
          while staying visible on stacked mobile rows (see index.css). */}
      <span className="field-label mb-1 block font-bold text-slate-600 dark:text-slate-400">
        {label}
      </span>
      {children}
    </label>
  );
}

const CONTROL =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-emerald-600 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:placeholder:text-slate-500";

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
    <section
      className={`rounded-xl bg-white p-4 shadow-sm sm:p-5 dark:bg-slate-900 dark:ring-1 dark:ring-slate-800 ${className}`}
    >
      {(title || actions) && (
        // Wraps on narrow screens so a long title never squashes its buttons.
        <header className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-extrabold text-slate-800 sm:text-lg dark:text-slate-100">
            {title}
          </h2>
          <div className="flex flex-wrap gap-2">{actions}</div>
        </header>
      )}
      {children}
    </section>
  );
}

// Spelled out rather than interpolated: Tailwind only ships classes it can see
// as literal strings, so a `text-${tone}-700` template would rely on the colour
// happening to be used elsewhere in the app.
const STAT_TONES = {
  emerald: "text-emerald-700 dark:text-emerald-400",
  rose: "text-rose-700 dark:text-rose-400",
  amber: "text-amber-700 dark:text-amber-400",
  sky: "text-sky-700 dark:text-sky-400",
  slate: "text-slate-700 dark:text-slate-300",
};

export function Stat({ label, value, hint, tone = "emerald" }) {
  return (
    <div className="rounded-xl bg-white p-4 shadow-sm sm:p-5 dark:bg-slate-900 dark:ring-1 dark:ring-slate-800">
      <div className="text-sm font-bold text-slate-500 dark:text-slate-400">{label}</div>
      <div
        className={`mt-1 text-2xl font-extrabold sm:text-3xl ${STAT_TONES[tone] ?? STAT_TONES.emerald}`}
      >
        {value}
      </div>
      {hint && <div className="mt-1 text-xs text-slate-400 dark:text-slate-500">{hint}</div>}
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
  // Optional per-row detail panel, opened from a toggle in the last column. Added
  // for the journal, where each entry has its own debit/credit lines: rendering all
  // of them as stacked cards meant the list could not be paginated at all, and a
  // thousand entries arrived on one page. A row that can expand keeps the
  // double-entry detail an accountant needs while the list stays 15 to a page.
  renderDetail,
}) {
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState({ key: null, dir: "asc" });
  const [expanded, setExpanded] = useState(() => new Set());
  useEffect(() => {
    setPage(1);
  }, [rows?.length, query]);

  if (!rows?.length) {
    return (
      <div className="py-10 text-center text-sm text-slate-400 dark:text-slate-500">{empty}</div>
    );
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

  const rowKey = (row, index) =>
    (typeof keyField === "function" ? keyField(row) : row[keyField]) ?? index;

  const toggleExpanded = (key) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

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
            className={`${CONTROL} sm:w-64`}
          />
        </div>
      )}
      {/* Data tables carry too many columns for a phone, so the table keeps a
          readable minimum width and scrolls sideways inside this box rather
          than crushing its columns or widening the whole page. */}
      <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        <table className="w-full min-w-[44rem] text-right text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-xs font-bold text-slate-500 dark:border-slate-700 dark:text-slate-400">
              {columns.map((col) => {
                const isSortable = !!col.label && col.sortable !== false;
                return (
                  <th
                    key={col.key}
                    className={`px-3 py-2 ${isSortable ? "cursor-pointer select-none hover:text-slate-700 dark:hover:text-slate-200" : ""}`}
                    onClick={isSortable ? () => toggleSort(col.key) : undefined}
                  >
                    <span className="inline-flex items-center gap-1">
                      {col.label}
                      {isSortable && sort.key === col.key && (
                        <span className="text-emerald-700 dark:text-emerald-400">
                          {sort.dir === "asc" ? "▲" : "▼"}
                        </span>
                      )}
                    </span>
                  </th>
                );
              })}
              {renderDetail && <th className="w-10 px-3 py-2" />}
            </tr>
          </thead>
          {pageRows.length > 0 ? (
            <tbody>
              {pageRows.map((row, index) => {
                const key = rowKey(row, index);
                const isOpen = expanded.has(key);
                return (
                  <Fragment key={key}>
                    <tr className="border-b border-slate-100 last:border-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/60">
                      {columns.map((col) => (
                        <td key={col.key} className="px-3 py-2.5">
                          {col.render ? col.render(row) : row[col.key]}
                        </td>
                      ))}
                      {renderDetail && (
                        <td className="px-3 py-2.5">
                          <button
                            type="button"
                            onClick={() => toggleExpanded(key)}
                            aria-expanded={isOpen}
                            title={isOpen ? "إخفاء التفاصيل" : "عرض التفاصيل"}
                            className="rounded-lg px-2 py-1 text-xs font-bold text-emerald-700 hover:bg-emerald-50 dark:text-emerald-400 dark:hover:bg-emerald-900/30"
                          >
                            {isOpen ? "▲ إخفاء" : "▼ التفاصيل"}
                          </button>
                        </td>
                      )}
                    </tr>
                    {renderDetail && isOpen && (
                      <tr className="border-b border-slate-100 dark:border-slate-800">
                        <td
                          colSpan={columns.length + 1}
                          className="bg-slate-50 px-3 py-3 dark:bg-slate-800/40"
                        >
                          {renderDetail(row)}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          ) : (
            <tbody>
              <tr>
                <td
                  colSpan={columns.length + (renderDetail ? 1 : 0)}
                  className="py-8 text-center text-sm text-slate-400 dark:text-slate-500"
                >
                  لا توجد نتائج مطابقة لبحثك.
                </td>
              </tr>
            </tbody>
          )}
        </table>
      </div>
      {totalPages > 1 && (
        <div className="mt-3 flex flex-col items-center justify-between gap-2 text-xs font-bold text-slate-500 sm:flex-row dark:text-slate-400">
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
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/50 p-3 pt-6 sm:p-4 sm:pt-14 dark:bg-slate-950/70"
      onClick={requestClose}
    >
      <div
        ref={contentRef}
        className={`w-full ${wide ? "max-w-4xl" : "max-w-lg"} rounded-xl bg-white p-4 shadow-xl sm:p-6 dark:bg-slate-900 dark:ring-1 dark:ring-slate-700`}
        onClick={(event) => event.stopPropagation()}
      >
        {/* Sticky header keeps the title and × reachable while a long form
            scrolls underneath on short screens. */}
        <header className="sticky -top-4 z-10 mb-4 flex items-start justify-between gap-3 bg-white pb-2 pt-1 sm:-top-6 sm:pt-2 dark:bg-slate-900">
          <h3 className="text-base font-extrabold sm:text-lg dark:text-slate-100">{title}</h3>
          <button
            onClick={requestClose}
            aria-label="إغلاق"
            className="shrink-0 text-2xl leading-none text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
          >
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
  // Light background + dark text of the same hue, mirrored in dark mode as a
  // dark translucent background + light text — never white on a pale fill.
  const tones = {
    slate: "bg-slate-100 text-slate-700 dark:bg-slate-700/50 dark:text-slate-200",
    green: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200",
    red: "bg-rose-100 text-rose-800 dark:bg-rose-900/50 dark:text-rose-200",
    amber: "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200",
    blue: "bg-sky-100 text-sky-800 dark:bg-sky-900/50 dark:text-sky-200",
  };
  return (
    <span
      className={`inline-block whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-bold ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

export function Alert({ tone = "error", children }) {
  if (!children) return null;
  const tones = {
    error:
      "bg-rose-50 text-rose-800 border-rose-200 dark:bg-rose-950/50 dark:text-rose-200 dark:border-rose-900",
    success:
      "bg-emerald-50 text-emerald-800 border-emerald-200 dark:bg-emerald-950/50 dark:text-emerald-200 dark:border-emerald-900",
  };
  return <div className={`mb-4 rounded-lg border px-4 py-3 text-sm font-bold ${tones[tone]}`}>{children}</div>;
}

export function Loading() {
  return (
    <div className="py-10 text-center text-sm text-slate-400 dark:text-slate-500">
      جارٍ التحميل...
    </div>
  );
}
