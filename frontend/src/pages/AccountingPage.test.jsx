// The journal, wired to a paged endpoint.
//
// The Table's own tests prove it calls `onPageChange(2)`. What they cannot prove is
// the part that lives here: that page 2 turns into `offset=15` on the wire, and that
// a new search returns to page 1. Both are small mappings, and both fail silently —
// a wrong offset shows plausible rows from the wrong place, and a search left on
// page 40 shows an empty table that reads as "nothing found".
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AccountingPage from "./AccountingPage";
import api from "../services/api";

vi.mock("../services/api", () => ({
  default: { get: vi.fn(), post: vi.fn() },
  apiMessage: (error) => error?.response?.data?.message ?? "خطأ",
}));

const entry = (id) => ({
  id,
  entry_date: "2026-08-08",
  description: `قيد رقم ${id}`,
  reference_type: "sales_invoice",
  reference_id: id,
  items: [
    { account: { code: "1010", name: "الصندوق" }, debit: "10.00", credit: "0.00" },
    { account: { code: "4010", name: "المبيعات" }, debit: "0.00", credit: "10.00" },
  ],
});

// Enough entries for a second page to exist.
const TOTAL = 3408;

function journalCalls() {
  return api.get.mock.calls.filter(([url]) => url === "/accounting/journal-entries");
}

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockImplementation((url, config) => {
    if (url === "/accounting/journal-entries") {
      const offset = config?.params?.offset ?? 0;
      return Promise.resolve({
        data: {
          data: {
            items: [entry(TOTAL - offset), entry(TOTAL - offset - 1)],
            total: TOTAL,
            limit: config?.params?.limit ?? 15,
            offset,
          },
        },
      });
    }
    // Everything else on the page: an empty list or object is enough, since these
    // tests never leave the journal tab.
    return Promise.resolve({ data: { data: [] } });
  });
});

describe("the journal asks the server for one page at a time", () => {
  it("requests the first fifteen on load, not the whole ledger", async () => {
    render(<AccountingPage />);

    await waitFor(() => expect(journalCalls().length).toBeGreaterThan(0));
    expect(journalCalls()[0][1].params).toMatchObject({ limit: 15, offset: 0 });
  });

  it("turns page two into offset fifteen", async () => {
    render(<AccountingPage />);
    await screen.findByText(/إجمالي 3408 عنصر/);

    await userEvent.click(screen.getByRole("button", { name: "التالي" }));

    await waitFor(() => {
      const offsets = journalCalls().map(([, c]) => c.params.offset);
      expect(offsets).toContain(15);
    });
  });

  it("sends the search to the server rather than filtering the page", async () => {
    render(<AccountingPage />);
    await screen.findByText(/إجمالي 3408 عنصر/);

    await userEvent.type(
      screen.getByPlaceholderText("بحث بالبيان أو التاريخ..."), "سند قبض"
    );

    await waitFor(() => {
      const searched = journalCalls().map(([, c]) => c.params.search);
      expect(searched).toContain("سند قبض");
    }, { timeout: 2000 });
  });

  it("returns to page one when a new search is typed", async () => {
    // Without this, searching from page 40 asks the server for rows 585-600 of a
    // result set with three matches, and the screen says the search found nothing.
    render(<AccountingPage />);
    await screen.findByText(/إجمالي 3408 عنصر/);

    await userEvent.click(screen.getByRole("button", { name: "التالي" }));
    await waitFor(() =>
      expect(journalCalls().map(([, c]) => c.params.offset)).toContain(15)
    );

    await userEvent.type(
      screen.getByPlaceholderText("بحث بالبيان أو التاريخ..."), "قبض"
    );

    await waitFor(() => {
      const searchCall = journalCalls().find(([, c]) => c.params.search === "قبض");
      expect(searchCall).toBeDefined();
      expect(searchCall[1].params.offset).toBe(0);
    }, { timeout: 2000 });
  });
});
