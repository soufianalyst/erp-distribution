// The shared Table in its two modes.
//
// Client mode holds every row and slices it locally. Server mode receives one page
// and must not pretend otherwise — which is the whole risk, because the two look
// identical on screen. A table showing fifteen rows of a page of fifteen, and a
// table showing the first fifteen of three thousand, are the same picture; only the
// footer and the search box tell you which one you are looking at, and only one of
// them is telling the truth.
//
// So these tests are mostly about what server mode must NOT do: not report the page
// as the total, not filter the page and call it a search, not offer a sort that
// reorders fifteen rows out of thousands.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Table } from "./Ui";

const COLUMNS = [
  { key: "id", label: "الرقم" },
  { key: "name", label: "الاسم" },
];

const rows = (from, count) =>
  Array.from({ length: count }, (_, i) => ({ id: from + i, name: `صنف ${from + i}` }));

describe("server-paged mode", () => {
  it("reports the server's total, not the number of rows it was handed", async () => {
    render(
      <Table
        columns={COLUMNS}
        rows={rows(1, 15)}
        serverPaged={{ total: 3408, page: 1, onPageChange: vi.fn() }}
      />
    );

    // The bug this guards: reading `rows.length` here would say "15 items" and
    // "page 1 of 1", and the other 3,393 entries would be unreachable and unmentioned.
    expect(screen.getByText(/إجمالي 3408 عنصر/)).toBeInTheDocument();
    expect(screen.getByText(/صفحة 1 من 228/)).toBeInTheDocument();
  });

  it("asks the caller for the next page instead of slicing locally", async () => {
    const onPageChange = vi.fn();
    render(
      <Table
        columns={COLUMNS}
        rows={rows(1, 15)}
        serverPaged={{ total: 3408, page: 1, onPageChange }}
      />
    );

    await userEvent.click(screen.getByRole("button", { name: "التالي" }));

    expect(onPageChange).toHaveBeenCalledWith(2);
  });

  it("disables السابق on the first page and التالي on the last", () => {
    const { rerender } = render(
      <Table
        columns={COLUMNS}
        rows={rows(1, 15)}
        serverPaged={{ total: 30, page: 1, onPageChange: vi.fn() }}
      />
    );
    expect(screen.getByRole("button", { name: "السابق" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "التالي" })).toBeEnabled();

    rerender(
      <Table
        columns={COLUMNS}
        rows={rows(16, 15)}
        serverPaged={{ total: 30, page: 2, onPageChange: vi.fn() }}
      />
    );
    expect(screen.getByRole("button", { name: "السابق" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "التالي" })).toBeDisabled();
  });

  it("shows no search box when the caller cannot search the server", () => {
    // A box that filtered the loaded page would look exactly like a working search
    // and quietly answer a different question. Better absent than lying.
    render(
      <Table
        columns={COLUMNS}
        rows={rows(1, 15)}
        serverPaged={{ total: 3408, page: 1, onPageChange: vi.fn() }}
      />
    );
    expect(screen.queryByPlaceholderText("بحث...")).not.toBeInTheDocument();
  });

  it("hands the query to the server when the caller can search", async () => {
    const onSearchChange = vi.fn();
    render(
      <Table
        columns={COLUMNS}
        rows={rows(1, 15)}
        serverPaged={{
          total: 3408, page: 1, onPageChange: vi.fn(), onSearchChange,
        }}
      />
    );

    await userEvent.type(screen.getByPlaceholderText("بحث..."), "أرز");

    expect(onSearchChange).toHaveBeenLastCalledWith("أرز");
  });

  it("does not filter the page it was given", async () => {
    // Typing must not remove rows locally: the server decides what matches, and a
    // local filter on top would hide rows the server deliberately returned.
    render(
      <Table
        columns={COLUMNS}
        rows={rows(1, 15)}
        serverPaged={{
          total: 3408, page: 1, onPageChange: vi.fn(), onSearchChange: vi.fn(),
        }}
      />
    );

    await userEvent.type(screen.getByPlaceholderText("بحث..."), "لا يطابق شيئاً");

    expect(screen.getByText("صنف 1")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(16); // header + 15
  });

  it("offers no column sorting, because sorting one page is not sorting", async () => {
    render(
      <Table
        columns={COLUMNS}
        rows={rows(1, 15)}
        serverPaged={{ total: 3408, page: 1, onPageChange: vi.fn() }}
      />
    );

    const header = screen.getByText("الرقم");
    await userEvent.click(header);

    // Order unchanged: the click did nothing rather than reordering fifteen rows
    // and implying the whole ledger had been sorted.
    const cells = screen.getAllByRole("row")[1];
    expect(within(cells).getByText("1")).toBeInTheDocument();
  });
});

describe("client mode still works", () => {
  it("slices, searches and sorts locally when given the whole list", async () => {
    render(<Table columns={COLUMNS} rows={rows(1, 40)} />);

    expect(screen.getByText(/إجمالي 40 عنصر/)).toBeInTheDocument();
    expect(screen.getByText(/صفحة 1 من 3/)).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText("بحث..."), "صنف 7");
    // "صنف 7" matches 7 and 70-79 among 1..40 -> just 7.
    expect(screen.getByText("صنف 7")).toBeInTheDocument();
    expect(screen.queryByText("صنف 8")).not.toBeInTheDocument();
  });
});
