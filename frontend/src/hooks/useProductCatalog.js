// Products on demand, instead of the whole catalogue up front.
//
// Every line-item form used to open by downloading all 1,060 products — 237 KB on the
// sales screen, the purchases screen and the stock screen, on every visit, growing with
// the catalogue. The forms only ever look at two kinds of product: the handful matching
// what the user is typing, and the ones they have already picked.
//
// So this holds exactly those two, and returns them in the same shape the forms already
// expect: a flat `products` array they can call `.find()` on. That was the deliberate
// design choice — a typeahead that handed back a different shape would have meant
// rewriting fifteen call sites across the three most business-critical forms in the
// system, and each rewrite is a chance to break invoice pricing.
//
// `ensure(ids)` covers the one case searching cannot: opening an existing invoice for
// edit, where the lines name products nobody has searched for in this session.
import { useCallback, useEffect, useRef, useState } from "react";

import useDebouncedValue from "./useDebouncedValue";
import api from "../services/api";

// Enough matches to choose from, few enough to stay a list rather than a page.
const LIMIT = 20;

export default function useProductCatalog() {
  const [query, setQuery] = useState("");
  const debounced = useDebouncedValue(query, 250);
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  // Everything seen so far, keyed by id. Never evicted during a form's life: a line
  // added five minutes ago must still be able to price itself.
  const [known, setKnown] = useState(() => new Map());
  const inflight = useRef(new Set());

  const remember = useCallback((rows) => {
    setKnown((current) => {
      const next = new Map(current);
      for (const row of rows) next.set(row.id, row);
      return next;
    });
  }, []);

  useEffect(() => {
    const term = debounced.trim();
    if (!term) {
      setResults([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api
      .get("/inventory/products", { params: { search: term, limit: LIMIT } })
      .then(({ data }) => {
        if (cancelled) return;
        // Only sellable products are offered for a new line; a discontinued one can
        // still be *resolved* by id, because old invoices contain it.
        const rows = (data.data.items ?? []).filter((p) => p.is_active);
        setResults(rows);
        remember(rows);
      })
      .catch(() => {
        if (!cancelled) setResults([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debounced, remember]);

  // Fetch products named by id — the lines of an invoice being edited. Requests are
  // de-duplicated because several lines commonly share a product and React may run
  // this twice before the first response lands.
  const ensure = useCallback(
    async (ids) => {
      const wanted = [...new Set(ids)].filter(
        (id) => id && !known.has(id) && !inflight.current.has(id)
      );
      if (!wanted.length) return;
      wanted.forEach((id) => inflight.current.add(id));
      try {
        const rows = await Promise.all(
          wanted.map((id) =>
            api
              .get(`/inventory/products/${id}`)
              .then(({ data }) => data.data)
              .catch(() => null)
          )
        );
        remember(rows.filter(Boolean));
      } finally {
        wanted.forEach((id) => inflight.current.delete(id));
      }
    },
    [known, remember]
  );

  // Search hits first so the list the user is reading stays at the top, then every
  // other product already known — which is what makes `.find()` keep working.
  const seen = new Set(results.map((p) => p.id));
  const products = [...results, ...[...known.values()].filter((p) => !seen.has(p.id))];

  return { products, query, setQuery, loading, ensure, remember };
}
