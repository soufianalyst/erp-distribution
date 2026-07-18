import { NavLink, Outlet } from "react-router-dom";
import { ROLE_LABELS, useAuth } from "../context/AuthContext";

// Sidebar items gated by permission (null = every authenticated user).
const NAV_ITEMS = [
  { to: "/", label: "لوحة التحكم", icon: "📊", perm: null },
  { to: "/products", label: "الأصناف", icon: "📦", perm: "products.view" },
  { to: "/barcode-scan", label: "مسح الباركود", icon: "📷", perm: "products.view" },
  { to: "/warehouses", label: "المستودعات", icon: "🏬", perm: "warehouses.view" },
  { to: "/stock", label: "حركة المخزون", icon: "🔄", perm: "stock.view" },
  { to: "/customers", label: "العملاء", icon: "🧑‍💼", perm: "customers.view" },
  { to: "/sales", label: "فواتير المبيعات", icon: "🧾", perm: "sales.view" },
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
];

export default function Layout() {
  const { user, logout, can } = useAuth();

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-60 shrink-0 flex-col bg-slate-900 text-slate-200">
        <div className="border-b border-slate-800 px-5 py-5">
          <div className="text-lg font-extrabold text-white">نظام إدارة التوزيع</div>
          <div className="mt-1 text-xs text-slate-400">المواد الغذائية بالجملة</div>
        </div>
        <nav className="flex-1 space-y-1 p-3">
          {NAV_ITEMS.filter((item) => !item.perm || can(item.perm)).map(
            (item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-bold transition ${
                    isActive ? "bg-emerald-700 text-white" : "hover:bg-slate-800"
                  }`
                }
              >
                <span>{item.icon}</span>
                {item.label}
              </NavLink>
            )
          )}
        </nav>
        <div className="border-t border-slate-800 p-4">
          <div className="text-sm font-bold text-white">{user.full_name}</div>
          <div className="mb-3 text-xs text-slate-400">{ROLE_LABELS[user.role]}</div>
          <button
            onClick={logout}
            className="w-full rounded-lg bg-slate-800 px-3 py-2 text-xs font-bold text-slate-300 hover:bg-slate-700"
          >
            تسجيل الخروج
          </button>
        </div>
      </aside>
      <main className="flex-1 p-6">
        <Outlet />
      </main>
    </div>
  );
}
