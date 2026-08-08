// The frame a shop owner sees. Deliberately not the ERP shell.
//
// No sidebar of modules, no permission-gated menu, nothing that hints at an
// internal system — a customer should never be able to tell how much of one is
// behind this. Five destinations along the bottom, thumb-height, because this is
// opened on a phone behind a counter far more often than on a desk.
import { NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import { Loading } from "../components/Ui";
import { usePortalAuth } from "../context/PortalAuthContext";

const TABS = [
  { to: "/portal", end: true, label: "حسابي", icon: "🏠" },
  { to: "/portal/catalog", label: "الأصناف", icon: "🧺" },
  { to: "/portal/orders", label: "طلباتي", icon: "📋" },
  { to: "/portal/invoices", label: "الفواتير", icon: "🧾" },
  { to: "/portal/statement", label: "كشف الحساب", icon: "📄" },
];

export default function PortalShell() {
  const { customer, loading, logout } = usePortalAuth();
  const location = useLocation();

  if (loading) return <Loading />;
  if (!customer) return <Navigate to="/portal/login" replace />;
  // The office issues a temporary password by phone; until it is replaced the
  // server refuses every data route, so sending them anywhere else would only
  // produce a screen full of errors.
  if (customer.must_change_password && location.pathname !== "/portal/password") {
    return <Navigate to="/portal/password" replace />;
  }

  return (
    <div dir="rtl" className="min-h-screen bg-slate-50 pb-20 dark:bg-slate-900">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/95 backdrop-blur dark:border-slate-700 dark:bg-slate-800/95">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-3 px-4 py-3">
          <div className="min-w-0">
            <p className="truncate text-base font-bold text-slate-800 dark:text-slate-100">
              {customer.name}
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">بوابة العملاء</p>
          </div>
          <button
            onClick={logout}
            className="shrink-0 rounded-lg px-3 py-2 text-sm font-bold text-slate-600 transition hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            خروج
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-4">
        <Outlet />
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-10 border-t border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800">
        <div className="mx-auto flex max-w-3xl">
          {TABS.map((tab) => (
            <NavLink
              key={tab.to}
              to={tab.to}
              end={tab.end}
              className={({ isActive }) =>
                `flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-bold transition ${
                  isActive
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-slate-500 dark:text-slate-400"
                }`
              }
            >
              <span className="text-lg leading-none">{tab.icon}</span>
              {tab.label}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}
