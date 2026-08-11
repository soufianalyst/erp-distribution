// The application shell: navigation, the collapsible sidebar, the mobile drawer
// and the day/night switch. Navigation entries are filtered by permission, so
// each role only sees the modules it can actually use.
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { ROLE_LABELS, useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";

// Sidebar items gated by permission (null = every authenticated user).
const NAV_ITEMS = [
  { to: "/", label: "لوحة التحكم", icon: "📊", perm: null },
  { to: "/products", label: "الأصناف", icon: "📦", perm: "products.view" },
  { to: "/barcode-scan", label: "مسح الباركود", icon: "📷", perm: "products.view" },
  { to: "/warehouses", label: "المستودعات", icon: "🏬", perm: "warehouses.view" },
  { to: "/stock", label: "حركة المخزون", icon: "🔄", perm: "stock.view" },
  { to: "/expiry-worklist", label: "المهدد بالانتهاء", icon: "⏳", perm: "stock.view" },
  { to: "/markdown-plan", label: "خطة التصريف", icon: "🏷️", perm: "products.offers" },
  { to: "/customers", label: "العملاء", icon: "🧑‍💼", perm: "customers.view" },
  { to: "/collections", label: "متابعة التحصيل", icon: "📒", perm: "sales.collections" },
  { to: "/sales", label: "فواتير المبيعات", icon: "🧾", perm: "sales.view" },
  { to: "/field", label: "جولة المندوب", icon: "🚐", perm: "sales.field_sync" },
  { to: "/rounds", label: "تسوية الجولات", icon: "🧮", perm: "sales.round_settle" },
  { to: "/customer-requests", label: "طلبات العملاء", icon: "🛍️", perm: "sales.orders_review" },
  { to: "/cashier", label: "الصندوق", icon: "💰", perm: "cashier.view" },
  { to: "/delivery", label: "التوزيع والتسليم", icon: "🚛", perm: "delivery.view" },
  { to: "/suppliers", label: "الموردون", icon: "🚚", perm: "suppliers.view" },
  { to: "/purchases", label: "فواتير المشتريات", icon: "🛒", perm: "purchases.view" },
  { to: "/expenses", label: "المصاريف", icon: "💸", perm: "expenses.view" },
  { to: "/accounting", label: "الحسابات", icon: "📚", perm: "accounting.view" },
  { to: "/analytics", label: "التحليلات والتقارير", icon: "📈", perm: "analytics.view" },
  { to: "/settings", label: "الإعدادات", icon: "⚙️", perm: "settings.view" },
  { to: "/users", label: "المستخدمون", icon: "👥", perm: "users.manage" },
  { to: "/audit", label: "سجل التتبع", icon: "🕵️", perm: "audit.view" },
  { to: "/data-import", label: "استيراد البيانات", icon: "📥", perm: "data.import" },
];

const COLLAPSED_KEY = "erp-sidebar-collapsed";

/** Day/night switch. Shows the mode it will switch *to*, not the current one. */
function ThemeToggle({ compact = false }) {
  const { isDark, toggleTheme } = useTheme();
  const label = isDark ? "الوضع النهاري" : "الوضع الليلي";
  return (
    <button
      onClick={toggleTheme}
      title={label}
      aria-label={label}
      className={`flex items-center justify-center gap-2 rounded-lg bg-slate-800 px-3 py-2 text-xs font-bold text-slate-300 transition hover:bg-slate-700 ${
        compact ? "w-full" : "w-full"
      }`}
    >
      <span aria-hidden="true">{isDark ? "☀️" : "🌙"}</span>
      {!compact && label}
    </button>
  );
}

export default function Layout() {
  const { user, logout, can } = useAuth();
  const location = useLocation();
  // Desktop: remembered icon-only rail. Mobile: transient off-canvas drawer.
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(COLLAPSED_KEY) === "true"
  );
  const [drawerOpen, setDrawerOpen] = useState(false);

  const toggleCollapsed = () =>
    setCollapsed((current) => {
      localStorage.setItem(COLLAPSED_KEY, String(!current));
      return !current;
    });

  // Navigating on a phone should reveal the page, not leave the drawer over it.
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!drawerOpen) return undefined;
    const onKeyDown = (event) => {
      if (event.key === "Escape") setDrawerOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen]);

  const items = NAV_ITEMS.filter((item) => !item.perm || can(item.perm));
  // Collapsed only applies from lg up; the drawer is always full width.
  const railWidth = collapsed ? "lg:w-[4.5rem]" : "lg:w-60";

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      {/* Mobile/tablet top bar — the only place the drawer can be opened. */}
      <header className="flex items-center justify-between gap-3 bg-slate-900 px-4 py-3 text-slate-200 lg:hidden">
        <button
          onClick={() => setDrawerOpen(true)}
          aria-label="فتح القائمة"
          aria-expanded={drawerOpen}
          className="rounded-lg p-2 text-xl leading-none hover:bg-slate-800"
        >
          ☰
        </button>
        <div className="min-w-0 flex-1 truncate text-center text-sm font-extrabold text-white">
          نظام إدارة التوزيع
        </div>
        <div className="w-auto">
          <ThemeToggle compact />
        </div>
      </header>

      {/* Backdrop: only interactive while the drawer is open. */}
      {drawerOpen && (
        <div
          className="fixed inset-0 z-30 bg-slate-950/60 lg:hidden"
          onClick={() => setDrawerOpen(false)}
        />
      )}

      <aside
        className={`fixed inset-y-0 right-0 z-40 flex w-64 shrink-0 flex-col bg-slate-900 text-slate-200 transition-transform duration-200 lg:static lg:z-auto lg:w-60 lg:translate-x-0 lg:transition-[width] ${railWidth} ${
          drawerOpen ? "translate-x-0" : "translate-x-full lg:translate-x-0"
        }`}
      >
        <div
          className={`flex items-center gap-2 border-b border-slate-800 px-4 py-4 ${
            collapsed ? "lg:justify-center lg:px-2" : ""
          }`}
        >
          <div className={`min-w-0 flex-1 ${collapsed ? "lg:hidden" : ""}`}>
            <div className="truncate text-lg font-extrabold text-white">نظام إدارة التوزيع</div>
            <div className="mt-1 text-xs text-slate-400">المواد الغذائية بالجملة</div>
          </div>
          {/* Collapse is a desktop affordance; on mobile the same spot closes
              the drawer instead. */}
          <button
            onClick={toggleCollapsed}
            title={collapsed ? "توسيع القائمة" : "تصغير القائمة"}
            aria-label={collapsed ? "توسيع القائمة" : "تصغير القائمة"}
            className="hidden shrink-0 rounded-lg p-2 text-sm hover:bg-slate-800 lg:block"
          >
            {collapsed ? "»" : "«"}
          </button>
          <button
            onClick={() => setDrawerOpen(false)}
            aria-label="إغلاق القائمة"
            className="shrink-0 rounded-lg p-2 text-xl leading-none hover:bg-slate-800 lg:hidden"
          >
            ×
          </button>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto p-3">
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              // Title carries the name when the rail hides the label.
              title={item.label}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-bold transition ${
                  collapsed ? "lg:justify-center lg:px-2" : ""
                } ${isActive ? "bg-emerald-700 text-white" : "hover:bg-slate-800"}`
              }
            >
              <span aria-hidden="true">{item.icon}</span>
              <span className={collapsed ? "lg:hidden" : ""}>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className={`space-y-2 border-t border-slate-800 p-3 ${collapsed ? "lg:px-2" : ""}`}>
          <div className={collapsed ? "lg:hidden" : ""}>
            <div className="truncate text-sm font-bold text-white">{user.full_name}</div>
            <div className="text-xs text-slate-400">{ROLE_LABELS[user.role]}</div>
          </div>
          {/* The desktop rail keeps the theme switch; on mobile it lives in the
              top bar, where it is reachable without opening the drawer. */}
          <div className="hidden lg:block">
            <ThemeToggle compact={collapsed} />
          </div>
          <button
            onClick={logout}
            title="تسجيل الخروج"
            className="w-full rounded-lg bg-slate-800 px-3 py-2 text-xs font-bold text-slate-300 hover:bg-slate-700"
          >
            <span className={collapsed ? "hidden lg:inline" : "hidden"} aria-hidden="true">
              ⎋
            </span>
            <span className={collapsed ? "lg:hidden" : ""}>تسجيل الخروج</span>
          </button>
        </div>
      </aside>

      <main className="min-w-0 flex-1 p-4 sm:p-6">
        <Outlet />
      </main>
    </div>
  );
}
