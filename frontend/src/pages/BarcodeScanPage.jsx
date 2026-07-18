import { useEffect, useRef, useState } from "react";
import { BrowserMultiFormatReader } from "@zxing/browser";
import { Alert, Button, Card, Input, Loading, money, qty } from "../components/Ui";
import api, { apiMessage } from "../services/api";

export default function BarcodeScanPage() {
  const [barcode, setBarcode] = useState("");
  const [product, setProduct] = useState(null);
  const [stockLevels, setStockLevels] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const videoRef = useRef(null);
  const controlsRef = useRef(null);

  useEffect(() => {
    // Stop the camera stream if the user navigates away mid-scan.
    return () => controlsRef.current?.stop();
  }, []);

  const lookup = async (code) => {
    const value = (code ?? barcode).trim();
    if (!value) return;
    setLoading(true);
    setError(null);
    setProduct(null);
    setStockLevels([]);
    try {
      const { data } = await api.get(`/inventory/products/barcode/${encodeURIComponent(value)}`);
      setProduct(data.data);
      const levels = await api.get("/inventory/stock/levels", {
        params: { product_id: data.data.id },
      });
      setStockLevels(levels.data.data);
    } catch (err) {
      setError(apiMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const submit = (event) => {
    event.preventDefault();
    lookup();
  };

  const startCamera = async () => {
    setError(null);
    setScanning(true);
    try {
      const reader = new BrowserMultiFormatReader();
      const controls = await reader.decodeFromVideoDevice(
        undefined,
        videoRef.current,
        (result) => {
          if (result) {
            const text = result.getText();
            controlsRef.current?.stop();
            setScanning(false);
            setBarcode(text);
            lookup(text);
          }
        }
      );
      controlsRef.current = controls;
    } catch {
      setError("تعذّر تشغيل الكاميرا، تأكد من منح الإذن بالوصول إليها.");
      setScanning(false);
    }
  };

  const stopCamera = () => {
    controlsRef.current?.stop();
    setScanning(false);
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold">مسح الباركود — بحث سريع عن صنف</h1>

      <Card title="البحث عن صنف">
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <div className="min-w-[220px] flex-1">
            <Input
              label="الباركود"
              value={barcode}
              onChange={(e) => setBarcode(e.target.value)}
              autoFocus
              placeholder="امسح بجهاز الباركود أو اكتب الرقم يدوياً..."
            />
          </div>
          <Button type="submit">بحث</Button>
          {!scanning ? (
            <Button type="button" variant="secondary" onClick={startCamera}>
              📷 مسح بالكاميرا
            </Button>
          ) : (
            <Button type="button" variant="danger" onClick={stopCamera}>
              إيقاف الكاميرا
            </Button>
          )}
        </form>

        {scanning && (
          <div className="mt-4 max-w-sm overflow-hidden rounded-lg border border-slate-300">
            {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
            <video ref={videoRef} className="w-full" muted playsInline />
          </div>
        )}
      </Card>

      <Alert>{error}</Alert>
      {loading && <Loading />}

      {product && (
        <Card title={`الصنف: ${product.name}`}>
          <div className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            <div>
              <div className="text-slate-500">الرمز (SKU)</div>
              <div className="font-bold">{product.sku}</div>
            </div>
            <div>
              <div className="text-slate-500">الباركود</div>
              <div className="font-bold">{product.barcode || "—"}</div>
            </div>
            <div>
              <div className="text-slate-500">سعر الجملة</div>
              <div className="font-bold">{money(product.wholesale_price)}</div>
            </div>
            <div>
              <div className="text-slate-500">سعر التجزئة</div>
              <div className="font-bold">{money(product.retail_price)}</div>
            </div>
          </div>
          <div className="mt-4">
            <div className="mb-2 text-sm font-bold text-slate-600">الرصيد الحالي</div>
            {stockLevels.length ? (
              <ul className="space-y-1 text-sm">
                {stockLevels.map((lvl) => (
                  <li
                    key={lvl.warehouse_id}
                    className="flex justify-between rounded bg-slate-50 px-3 py-2"
                  >
                    <span>{lvl.warehouse_name}</span>
                    <span className="font-bold">
                      {qty(lvl.total_quantity)} {lvl.base_unit_name}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-400">لا يوجد رصيد في أي مستودع.</p>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
