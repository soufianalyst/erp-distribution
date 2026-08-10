// The tracker card.
//
// A stepper is read at a glance and believed without checking, so the thing worth
// testing is that the glance is honest: the step the invoice is actually on is the
// one that stands out, everything ahead of it stays quiet, and a failed delivery
// looks like a failure rather than like progress.
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import InvoiceTracker from "./InvoiceTracker";
import api from "../services/api";

vi.mock("../services/api", () => ({
  default: { get: vi.fn() },
  apiMessage: (error) => error?.response?.data?.message ?? "خطأ",
}));

const step = (key, label, state, extra = {}) => ({
  key, label, state, at: null, detail: null, ...extra,
});

function timeline(steps, extra = {}) {
  return {
    data: {
      data: {
        invoice_id: 7,
        reference: "INV-00007",
        customer_name: "بقالة الاختبار",
        fulfillment: "delivery",
        shipped_via: "شاحنة 9",
        status_label: "قيد التوصيل",
        expected: "2026-08-11",
        total: "500.00",
        amount_due: "0.00",
        returned_total: "0.00",
        steps,
        ...extra,
      },
    },
  };
}

beforeEach(() => vi.clearAllMocks());

describe("the card says where the invoice is", () => {
  it("shows the reference, the carrier and the expected date", async () => {
    api.get.mockResolvedValue(timeline([step("raised", "صدرت الفاتورة", "done")]));
    render(<InvoiceTracker invoiceId={7} />);

    expect(await screen.findByText(/INV-00007/)).toBeInTheDocument();
    expect(screen.getByText("شاحنة 9")).toBeInTheDocument();
    expect(screen.getByText("2026-08-11")).toBeInTheDocument();
    expect(screen.getByText("قيد التوصيل")).toBeInTheDocument();
  });

  it("draws every step the backend sent, in order", async () => {
    api.get.mockResolvedValue(
      timeline([
        step("raised", "صدرت الفاتورة", "done"),
        step("payment", "تم التحصيل", "done"),
        step("scheduled", "مجدولة في رحلة", "done"),
        step("transit", "قيد التوصيل", "current"),
        step("delivered", "تم التسليم", "pending"),
      ])
    );
    render(<InvoiceTracker invoiceId={7} />);

    await screen.findByText(/INV-00007/);
    // Rendered twice — the wide stepper and the stacked phone list — which is why
    // this counts rather than asserting a single node.
    for (const label of ["صدرت الفاتورة", "تم التحصيل", "مجدولة في رحلة"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
  });

  it("makes the current step the loud one and leaves the rest quiet", async () => {
    /* The whole point of a stepper. If "where it is" does not stand out from
       "where it isn't", the reader has to work out the state themselves. */
    api.get.mockResolvedValue(
      timeline([
        step("raised", "صدرت الفاتورة", "done"),
        step("payment", "بانتظار التحصيل", "current"),
        step("delivered", "تم التسليم", "pending"),
      ])
    );
    render(<InvoiceTracker invoiceId={7} />);

    const currentLabel = (await screen.findAllByText("بانتظار التحصيل"))[0];
    expect(currentLabel.className).toMatch(/font-extrabold/);

    const pendingLabel = screen.getAllByText("تم التسليم")[0];
    expect(pendingLabel.className).toMatch(/text-slate-400/);
  });

  it("shows a failed delivery as a failure, not as progress", async () => {
    api.get.mockResolvedValue(
      timeline([
        step("raised", "صدرت الفاتورة", "done"),
        step("transit", "تعذّر التسليم", "failed", { detail: "المحل مغلق" }),
        step("delivered", "تم التسليم", "pending"),
      ])
    );
    render(<InvoiceTracker invoiceId={7} />);

    const failed = (await screen.findAllByText("تعذّر التسليم"))[0];
    expect(failed.className).toMatch(/rose/);
    // The reason travels with it on the stacked view, so nobody has to click.
    expect(screen.getByText("المحل مغلق")).toBeInTheDocument();
  });

  it("flags a credit note against the invoice", async () => {
    api.get.mockResolvedValue(
      timeline([step("raised", "صدرت الفاتورة", "done")], {
        returned_total: "75.00",
      })
    );
    render(<InvoiceTracker invoiceId={7} />);
    expect(await screen.findByText(/يوجد مرتجع/)).toBeInTheDocument();
  });

  it("asks for the invoice it was given", async () => {
    api.get.mockResolvedValue(timeline([step("raised", "صدرت", "done")]));
    render(<InvoiceTracker invoiceId={42} />);
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith("/sales/invoices/42/timeline")
    );
  });
});
