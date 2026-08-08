// Drives the field app's connection to the server: caches what the round needs,
// queues what it produces, and drains that queue whenever a signal returns.
//
// The queue is never cleared optimistically. A document leaves it only once the
// server has confirmed it — as created, or as a duplicate it already holds. That
// is what makes losing the response mid-sync safe: the app simply sends it
// again, and the server recognises the identifier.

import { useCallback, useEffect, useState } from "react";
import api, { apiMessage } from "../services/api";
import {
  dequeue,
  markFailed,
  queued,
  readSnapshot,
  saveSnapshot,
} from "../services/offlineStore";

const SNAPSHOT_KEYS = {
  customers: "customers",
  products: "products",
  van: "van",
  taxRates: "tax_rates",
};

export default function useFieldSync() {
  const [online, setOnline] = useState(navigator.onLine);
  const [pending, setPending] = useState([]);
  const [snapshot, setSnapshot] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [lastResult, setLastResult] = useState(null);
  const [error, setError] = useState(null);
  // Whether this browser lets us keep a local copy at all. False means the app
  // is usable, but only while there is a signal.
  const [cacheAvailable, setCacheAvailable] = useState(true);

  const refreshPending = useCallback(async () => {
    try {
      setPending(await queued());
    } catch {
      setCacheAvailable(false);
    }
  }, []);

  /** Pull everything the round needs, so the app keeps working once signal drops. */
  const refreshSnapshot = useCallback(async () => {
    if (!navigator.onLine) return;
    try {
      const [customers, products, van, taxRates] = await Promise.all([
        api.get("/sales/customers"),
        api.get("/inventory/products"),
        api.get("/sales/field/van").catch(() => null),
        api.get("/settings/tax-rates", {
          params: { active_only: true, in_scope_only: true },
        }),
      ]);
      const fresh = {
        customers: customers.data.data,
        products: products.data.data.filter((p) => p.is_active),
        // A salesman with no vehicle can still take orders, so this is optional.
        van: van?.data?.data ?? null,
        taxRates: taxRates.data.data,
      };
      // Show it before caching it. Writing to IndexedDB can fail — private
      // browsing, a full quota, storage switched off — and that must not cost
      // the salesman a screen whose data has already arrived. The round then
      // works online only, which the "no cached copy" notice makes plain.
      setSnapshot({ ...fresh, saved_at: new Date().toISOString() });
      setError(null);
      try {
        await Promise.all(
          Object.entries(SNAPSHOT_KEYS).map(([key, storeKey]) =>
            saveSnapshot(storeKey, fresh[key])
          )
        );
      } catch {
        setCacheAvailable(false);
      }
    } catch (err) {
      setError(apiMessage(err));
    }
  }, []);

  /** Load the cached copy first so the screen is usable before any request. */
  const loadCached = useCallback(async () => {
    let entries;
    try {
      entries = await Promise.all(
        Object.entries(SNAPSHOT_KEYS).map(async ([key, storeKey]) => [
          key,
          await readSnapshot(storeKey),
        ])
      );
    } catch {
      // No local store to read from; the live fetch below is the only source.
      setCacheAvailable(false);
      return;
    }
    const cached = Object.fromEntries(
      entries.map(([key, row]) => [key, row?.value ?? null])
    );
    if (cached.customers || cached.products) {
      const savedAt = entries.map(([, row]) => row?.saved_at).filter(Boolean)[0];
      setSnapshot({ ...cached, saved_at: savedAt ?? null });
    }
  }, []);

  const sync = useCallback(async () => {
    if (!navigator.onLine || syncing) return null;
    const documents = await queued();
    if (!documents.length) {
      setLastResult(null);
      return null;
    }
    setSyncing(true);
    setError(null);
    try {
      // Customers travel in their own list so the server can create them before
      // the sales that name them.
      const payload = {
        customers: documents
          .filter((d) => d.kind === "customer")
          .map(({ kind, last_error, attempts, ...rest }) => rest),
        documents: documents
          .filter((d) => d.kind !== "customer")
          .map(({ last_error, attempts, provisional_reference, ...rest }) => rest),
      };
      const { data } = await api.post("/sales/field/sync", payload);
      const result = data.data;

      for (const item of result.results) {
        if (item.status === "failed") {
          // Kept queued with the reason, so the round is never silently lost.
          await markFailed(item.client_uuid, item.message);
        } else {
          await dequeue(item.client_uuid);
        }
      }
      setLastResult(result);
      await refreshPending();
      // Stock and balances moved on the server; pull a fresh picture.
      await refreshSnapshot();
      return result;
    } catch (err) {
      setError(apiMessage(err));
      return null;
    } finally {
      setSyncing(false);
    }
  }, [syncing, refreshPending, refreshSnapshot]);

  useEffect(() => {
    loadCached();
    refreshPending();
    refreshSnapshot();
  }, [loadCached, refreshPending, refreshSnapshot]);

  // Reopening the app is as much a reconnection as the `online` event: a phone
  // that died mid-round comes back with work still queued, and the salesman
  // should not have to notice and press anything.
  useEffect(() => {
    if (navigator.onLine) sync();
    // Deliberately once on mount: `sync` changes identity while it runs, and
    // depending on it here would re-fire the moment a sync completes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reconnecting is the natural moment to flush the round.
  useEffect(() => {
    const goOnline = () => {
      setOnline(true);
      sync();
    };
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, [sync]);

  return {
    online,
    cacheAvailable,
    snapshot,
    pending,
    syncing,
    lastResult,
    error,
    sync,
    refreshPending,
    refreshSnapshot,
  };
}
