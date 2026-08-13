// One way to choose a product, backed by a server search.
//
// There were two ways before. The sales invoice form had a type-to-search input over a
// datalist; the purchase and stock forms had a `<select>` listing the entire catalogue —
// 1,060 options in a dropdown, which is unusable long before it is slow, and which is
// why both screens had to download every product to open a form.
//
// This is the sales pattern, extracted: an ordinary text input whose suggestions come
// from whatever the server matched on the last few keystrokes. It keeps the input a
// text box on purpose. A storekeeper entering twenty lines works by typing and tabbing,
// and a custom dropdown that traps focus or swallows Enter would cost more than the
// bytes it saved — which is the whole reason `<datalist>` is still the right primitive
// here despite being unfashionable.
import { useEffect } from "react";

import { Input } from "./Ui";

// "P-1001 — أرز بسمتي 5 كجم". The label is the value the input holds, so it must be
// unambiguous: two products with the same name are told apart by the SKU in front.
export const productLabel = (product) =>
  product ? `${product.sku} — ${product.name}` : "";

export default function ProductPicker({
  label = "الصنف (اكتب للبحث)",
  listId,
  products,
  value,
  onQuery,
  onSelect,
  loading = false,
  disabled = false,
  required = false,
  autoFocus = false,
}) {
  // A bare SKU or a bare name counts as a hit, not only the full "SKU — name" label.
  // Borrowed from the analytics slicer, which had it first and was right: warehouse
  // staff type codes from memory, and making them reproduce " — " to be understood
  // would be pointless ceremony.
  const resolve = (text) => {
    const key = text.trim().toLowerCase();
    if (!key) return null;
    return (
      products.find((p) => productLabel(p).toLowerCase() === key) ||
      products.find((p) => (p.sku || "").toLowerCase() === key) ||
      products.find((p) => (p.name || "").toLowerCase() === key) ||
      null
    );
  };

  // Resolve again when results land, not only on a keystroke.
  //
  // Found by using it: typing a full SKU quickly means the search answers *after* the
  // last character, so there is no further keystroke to match against — the suggestion
  // sat in the dropdown while the line stayed unresolved, and tabbing away left it
  // blank. Clicking the suggestion worked, which is exactly why it was easy to miss.
  useEffect(() => {
    const text = (value ?? "").trim();
    if (!text) return;
    const match = resolve(text);
    if (match) onSelect(match, value);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [products, value]);

  const handle = (text) => {
    // Both, every time: the query drives the suggestions, and text that matches one
    // of them is a selection. Typing commits nothing until it resolves — which is
    // what lets someone tab away from a half-typed line and come back to it.
    onQuery(text);
    onSelect(resolve(text), text);
  };

  return (
    <>
      <Input
        label={loading ? `${label} — جارٍ البحث…` : label}
        list={listId}
        placeholder="ابحث بالرمز أو الاسم..."
        value={value ?? ""}
        onChange={(e) => handle(e.target.value)}
        disabled={disabled}
        required={required}
        autoFocus={autoFocus}
        autoComplete="off"
      />
      <datalist id={listId}>
        {products.map((product) => (
          <option key={product.id} value={productLabel(product)}>
            {product.name}
          </option>
        ))}
      </datalist>
    </>
  );
}
