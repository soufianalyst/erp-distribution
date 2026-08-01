import { useNavigate, useParams } from "react-router-dom";
import { Button, Loading, money, qty } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api from "../services/api";

const STATUS_LABELS = {
  counting: "قيد الجرد",
  posted: "مُثبّت",
  cancelled: "ملغى",
};

/**
 * Printable count sheet (ورقة جرد). While the count is open it prints as a blank
 * sheet — expected quantities hidden — so whoever walks the aisles records what
 * they actually see rather than confirming the book figure. Once posted it prints
 * as the variance report, expected against counted.
 */
export default function PrintStocktakePage() {
  const { stocktakeId } = useParams();
  const navigate = useNavigate();
  const stocktake = useFetch(
    () => api.get(`/inventory/stocktakes/${stocktakeId}`),
    [stocktakeId]
  );
  const company = useFetch(() => api.get("/settings/company"));

  if (stocktake.loading || company.loading) return <Loading />;
  if (stocktake.error) {
    return (
      <div className="p-10 text-center font-bold text-rose-700">{stocktake.error}</div>
    );
  }

  const s = stocktake.data;
  const blank = s.status === "counting";
  const co = company.data ?? {};

  return (
    <div className="min-h-screen bg-slate-200 py-8 print:bg-white print:py-0">
      <div className="mx-auto mb-4 flex max-w-[210mm] justify-between gap-2 print:hidden">
        <Button variant="secondary" onClick={() => navigate("/stock")}>
          ← العودة لحركة المخزون
        </Button>
        <Button onClick={() => window.print()}>🖨️ طباعة</Button>
      </div>

      <div className="mx-auto max-w-[210mm] bg-white p-10 text-slate-900 shadow print:max-w-none print:p-0 print:shadow-none">
        <header className="flex items-start justify-between border-b-4 border-slate-800 pb-4">
          <div>
            <h1 className="text-2xl font-extrabold">{co.name ?? "الشركة"}</h1>
            {co.address && <div className="text-sm">{co.address}</div>}
            {co.phone && <div className="text-sm">هاتف: {co.phone}</div>}
          </div>
          <div className="text-left">
            <h2 className="text-xl font-extrabold">
              {blank ? "ورقة جرد مخزون" : "تقرير فروقات الجرد"}
            </h2>
            <div className="text-sm">رقم الجرد: {s.id}</div>
            <div className="text-sm">التاريخ: {s.count_date}</div>
            <div className="text-sm">الحالة: {STATUS_LABELS[s.status]}</div>
          </div>
        </header>

        <div className="mt-4 flex flex-wrap gap-6 text-sm font-bold">
          <span>المستودع: {s.warehouse_name}</span>
          <span>عدد التشغيلات: {s.line_count}</span>
          {!blank && <span>سطور بفروقات: {s.variance_line_count}</span>}
        </div>
        {s.notes && <p className="mt-2 text-sm">ملاحظات: {s.notes}</p>}

        {blank && (
          <p className="mt-3 text-xs font-bold">
            تُكتب الكميات الفعلية بخط اليد في العمود المخصص، ثم تُدخل في النظام
            وتُثبّت التسوية. الأرصدة الدفترية غير مطبوعة هنا عن قصد حتى يكون العدّ
            مستقلاً.
          </p>
        )}

        <table className="mt-5 w-full border-collapse text-sm">
          <thead>
            <tr className="bg-slate-100 text-right">
              <th className="border border-slate-300 p-2">#</th>
              <th className="border border-slate-300 p-2">الصنف</th>
              <th className="border border-slate-300 p-2">الرمز</th>
              <th className="border border-slate-300 p-2">التشغيلة</th>
              <th className="border border-slate-300 p-2">الانتهاء</th>
              {!blank && <th className="border border-slate-300 p-2">المتوقع دفترياً</th>}
              <th className="border border-slate-300 p-2">الكمية الفعلية</th>
              {!blank && (
                <>
                  <th className="border border-slate-300 p-2">الفرق</th>
                  <th className="border border-slate-300 p-2">قيمة الفرق</th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {s.lines.map((line, index) => (
              <tr key={line.id}>
                <td className="border border-slate-300 p-2">{index + 1}</td>
                <td className="border border-slate-300 p-2 font-bold">
                  {line.product_name}
                </td>
                <td className="border border-slate-300 p-2">{line.sku}</td>
                <td className="border border-slate-300 p-2">{line.batch_number}</td>
                <td className="border border-slate-300 p-2">{line.expiry_date}</td>
                {!blank && (
                  <td className="border border-slate-300 p-2">
                    {qty(line.expected_quantity)} {line.base_unit_name}
                  </td>
                )}
                {/* Left deliberately empty on a blank sheet: a box to write in. */}
                <td className="border border-slate-300 p-2">
                  {blank
                    ? ""
                    : line.counted_quantity == null
                      ? "لم يُجرد"
                      : qty(line.counted_quantity)}
                </td>
                {!blank && (
                  <>
                    <td className="border border-slate-300 p-2 font-bold">
                      {line.counted_quantity == null
                        ? "—"
                        : Number(line.variance) === 0
                          ? "مطابق"
                          : Number(line.variance) > 0
                            ? `+${qty(line.variance)}`
                            : qty(line.variance)}
                    </td>
                    <td className="border border-slate-300 p-2">
                      {line.counted_quantity == null || Number(line.unit_cost) === 0
                        ? "—"
                        : money(line.variance_value)}
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>

        {!blank && (
          <div className="mt-4 text-left text-base font-extrabold">
            صافي قيمة الفروقات: {money(s.net_value)}{" "}
            <span className="text-sm font-bold">
              ({Number(s.net_value) < 0 ? "عجز" : "زيادة"})
            </span>
          </div>
        )}

        <div className="mt-12 flex justify-between text-sm font-bold">
          <div>
            <div>القائم بالجرد</div>
            <div className="mt-10 border-t border-slate-400 pt-1">الاسم والتوقيع</div>
          </div>
          <div>
            <div>أمين المستودع</div>
            <div className="mt-10 border-t border-slate-400 pt-1">الاسم والتوقيع</div>
          </div>
          <div>
            <div>المدير المسؤول</div>
            <div className="mt-10 border-t border-slate-400 pt-1">الاسم والتوقيع</div>
          </div>
        </div>
      </div>
    </div>
  );
}
