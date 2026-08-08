// Portal catalog: what's for sale, and how much is on hand — quantities only,
// deliberately no prices anywhere. Out-of-stock products stay listed but greyed
// out, so the customer knows the product exists and is temporarily unavailable.
// Products with stock in a warehouse show one row per warehouse; the customer
// picks a quantity and drops it in the cart (a unit is always the base unit).
import { useState } from "react";
import { Alert, Button, Card, Input, Loading, qty } from "../components/Ui";
import { useCart } from "../components/PortalLayout";
import useFetch from "../hooks/useFetch";
import api from "../services/api";

export default function PortalCatalog() {
  const { data, loading, error, reload } = useFetch(() => api.get("/portal/catalog"));
  const { cart, setQuantity } = useCart();

  // Group the per-warehouse rows under their product so each product shows as
  // one card listing the warehouses that hold it.
  const products = (data || []).reduce((acc, item) => {
    const group = acc.get(item.product_id) || {
      productId: item.product_id,
      name: item.product_name,
      sku: item.sku,
      unit: item.base_unit_name,
      inStock: false,
      warehouses: [],
    };
    if (item.in_stock) group.inStock = true;
    group.warehouses.push(item);
    acc.set(item.product_id, group);
    return acc;
  }, new Map());

  const [added, setAdded] = useState(null);
  const flash = (productId) => {
    setAdded(productId);
    setTimeout(() => setAdded(null), 1500);
  };

  const inCart = (productId) => Number(cart[productId]) || 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold">كتالوج الأصناف</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            الأرصدة محدثة لحظة بلحظة حسب المخزون الفعلي.
          </p>
        </div>
        <Button variant="secondary" onClick={reload}>
          تحديث الأرصدة
        </Button>
      </div>

      <Alert>{error}</Alert>

      {loading ? (
        <Loading />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[...products.values()].map((product) => {
            const available = product.inStock;
            return (
              <Card
                key={product.productId}
                className={!available ? "opacity-60" : ""}
                actions={
                  !available ? (
                    <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-bold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                      غير متوفر حالياً
                    </span>
                  ) : (
                    <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-bold text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200">
                      متوفر
                    </span>
                  )
                }
              >
                <div className="mb-1 font-extrabold">{product.name}</div>
                <div className="mb-3 text-xs text-slate-500 dark:text-slate-400">
                  {product.sku} · الوحدة: {product.unit}
                </div>

                {product.warehouses.length > 0 ? (
                  <ul className="mb-3 space-y-1">
                    {product.warehouses.map((item) => (
                      <li
                        key={`${item.warehouse_id}-${item.product_id}`}
                        className="flex items-center justify-between text-sm"
                      >
                        <span className="text-slate-600 dark:text-slate-300">
                          {item.warehouse_name || "مخزن غير محدد"}
                        </span>
                        <span className="font-bold">{qty(item.available_quantity)}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="mb-3 text-sm text-slate-400">لا يوجد رصيد في أي مخزن.</div>
                )}

                {available && (
                  <div className="flex items-center gap-2">
                    <Input
                      type="number"
                      min="0"
                      step="1"
                      value={inCart(product.id)}
                      onChange={(e) => setQuantity(product.id, Number(e.target.value))}
                      placeholder="الكمية"
                      className="!w-24"
                    />
                    <Button
                      variant={added === product.id ? "secondary" : "primary"}
                      disabled={!inCart(product.id)}
                      onClick={() => flash(product.id)}
                    >
                      {added === product.id ? "✓ أُضيف" : "إضافة للطلب"}
                    </Button>
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}