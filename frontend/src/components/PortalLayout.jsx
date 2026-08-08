// Customer portal shell: a purpose-built layout with its own navigation, so the
// customer only ever sees the portal pages, never the staff system. The cart
// lives here too — it is shared by the catalog (add) and the order form (review).
import { createContext, useContext, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";
import { Badge } from "./Ui";

const NAV_ITEMS = [
  { to: "/portal", label: "الرئيسية", icon: "🏠", end: true },
  { to: "/portal/catalog", label: "الكتالوج", icon: "📦", end: false },
  { to: "/portal/orders", label: "طلباتي", icon: "🛒", end: false },
  { to: "/portal/statement", label: "كشف الحساب والفواتير", icon: "🧾", end: false },
];

// Cart: quantity per product id, persisted so a reload never loses a draft.
const CartContext = createContext(null);
export const useCart = () => useContext(CartContext);

const CART_KEY = "erp-portal-cart";
const readCart = () => {
  try {
    return JSON.parse(localStorage.getItem(CART_KEY)) || {};
  } catch {
    return {};
  }
};

export function CartProvider({ children }) {
  const [cart, setCart] = useState(readCart);

  const setQuantity = (id, quantity) =>
    setCart((current) => {
      const next = { ...current };
      if (quantity > 0) next[id] = quantity;
      else delete next[id];
      localStorage.setItem(CART_KEY, JSON.stringify(next));
      return next;
    });

  const clear = () => {
    localStorage.removeItem(CART_KEY);
    setCart({});
  };

  const count = Object.values(cart).reduce((sum, q) => sum + q, 0);

  return (
    <CartContext.Provider value={{ cart, setQuantity, clear, count }}>
      {children}
    </CartContext.Provider>
  );
}

export default function PortalLayout() {
  const { user, logout } = useAuth();
  const { isDark, toggleTheme } = useTheme();
  const location = useLocation();
  const { count } = useCart();
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  return (
    <div className="flex min-h-screen flex-col bg-slate-100 dark:bg-slate-950">
      <header className="sticky top-0 z-40 bg-slate-900 text-slate-200 shadow-lg">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setDrawerOpen(true)}
              aria-label="فتح القائمة"
              className="rounded-lg p-2 text-xl leading-none hover:bg-slate-800 lg:hidden"
            >
              ☰
            </button>
            <NavLink to="/portal" className="text-base font-extrabold text-white sm:text-lg">
              بوابة العملاء
            </NavLink>
          </div>
          <div className="flex items-center gap-2">
            <NavLink
              to="/portal/catalog"
              title="الطلب من الكتالوج"
              className="relative flex items-center gap-2 rounded-lg bg-emerald-700 px-3 py-2 text-xs font-bold text-white hover:bg-emerald-600"
            >
              <span aria-hidden="true">🛒</span>
              <span className="hidden sm:inline">الطلب الآن</span>
              {count > 0 && (
                <Badge tone="red">{count}</Badge>
              )}
            </NavLink>
            <button
              onClick={toggleTheme}
              title={isDark ? "الوضع النهاري" : "الوضع الليلي"}
              className="rounded-lg px-2 py-2 text-sm hover:bg-slate-800"
            >
              {isDark ? "☀️" : "🌙"}
            </button>
          </div>
        </div>

        {/* Desktop navigation row. */}
        <nav className="hidden border-t border-slate-800 lg:block">
          <div className="mx-auto flex max-w-6xl gap-1 px-4">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `flex items-center gap-2 px-3 py-2.5 text-sm font-bold transition ${
                    isActive ? "text-emerald-400" : "text-slate-300 hover:text-white"
                  }`
                }
              >
                <span aria-hidden="true">{item.icon}</span>
                {item.label}
              </NavLink>
            ))}
          </div>
        </nav>

        {/* Mobile drawer. */}
        {drawerOpen && (
          <div className="fixed inset-0 z-40 bg-slate-950/60 lg:hidden" onClick={() => setDrawerOpen(false)} />
        )}
        {drawerOpen && (
          <div className="fixed inset-y-0 right-0 z-50 flex w-64 flex-col bg-slate-900 p-3 lg:hidden">
            <div className="mb-4 flex items-center justify-between px-1 pt-1">
              <span className="text-base font-extrabold text-white">بوابة العملاء</span>
              <button
                onClick={() => setDrawerOpen(false)}
                aria-label="إغلاق القائمة"
                className="rounded-lg p-1 text-xl leading-none hover:bg-slate-800"
              >
                ×
              </button>
            </div>
            <nav className="flex-1 space-y-1">
              {NAV_ITEMS.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-bold ${
                      isActive ? "bg-emerald-700 text-white" : "text-slate-300 hover:bg-slate-800"
                    }`
                  }
                >
                  <span aria-hidden="true">{item.icon}</span>
                  {item.label}
                </NavLink>
              ))}
            </nav>
            <div className="space-y-2 border-t border-slate-800 pt-3">
              <div className="px-1 text-sm font-bold text-white">{user.full_name}</div>
              <button
                onClick={logout}
                className="w-full rounded-lg bg-slate-800 px-3 py-2 text-xs font-bold text-slate-300 hover:bg-slate-700"
              >
                تسجيل الخروج
              </button>
            </div>
          </div>
        )}
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 p-4 sm:p-6">
        <Outlet />
      </main>
    </div>
  );
}