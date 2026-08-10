// Holds a value back until it stops changing, so a search box that now asks the
// server does not fire one request per keystroke. Typing "فاتورة" would otherwise
// be seven queries, six of them already stale by the time they answer — and the
// last one to arrive is not necessarily the last one sent, so the results could
// settle on a prefix of what the user typed.
import { useEffect, useState } from "react";

export default function useDebouncedValue(value, delay = 300) {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return settled;
}
