// The shop's ordering screen.
//
// The first test here exists because of a bug I wrote and caught by luck. Moving the
// catalogue search from the browser to the server shrank `items` from the whole range
// to one page of results — and the basket was reading product names out of `items`.
// Add rice, search for chicken, and the rice line in the review panel went blank: the
// customer would have confirmed an order showing a nameless row.
//
// `vite build` passed throughout. Nothing but a test that actually searches twice
// would have caught it, which is the argument for this file existing at all.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PortalCatalog from "./PortalCatalog";
import portalApi from "../services/portalApi";

vi.mock("../services/portalApi", () => ({
  default: { get: vi.fn(), post: vi.fn() },
  portalMessage: (error) => error?.response?.data?.message ?? "خطأ",
}));

const RICE = { product_id: 1, name: "أرز بسمتي", unit: "كيس", availability: "available" };
const CHICKEN = { product_id: 2, name: "دجاج مجمد", unit: "كيلو", availability: "limited" };

// The server filters; the mock mimics that rather than returning everything, because
// returning everything is exactly the behaviour that hid the bug.
const respondToSearch = () => {
  portalApi.get.mockImplementation((_path, config) => {
    const term = config?.params?.search;
    const all = [RICE, CHICKEN];
    const data = term ? all.filter((i) => i.name.includes(term)) : all;
    return Promise.resolve({ data: { data } });
  });
};

const renderCatalog = () =>
  render(
    <MemoryRouter>
      <PortalCatalog />
    </MemoryRouter>
  );

describe("the basket survives a second search", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    respondToSearch();
  });

  it("keeps the name of an item added before the search changed", async () => {
    const user = userEvent.setup();
    renderCatalog();
    await screen.findByText("أرز بسمتي");

    // Add rice.
    const quantities = screen.getAllByPlaceholderText("0");
    await user.type(quantities[0], "5");

    // Now search for something else entirely; rice leaves the result set.
    await user.type(screen.getByLabelText("ابحث عن صنف"), "دجاج");
    await waitFor(() => expect(screen.queryByText("أرز بسمتي")).not.toBeInTheDocument());

    // The basket must still know what it holds.
    await user.click(screen.getByText(/مراجعة الطلب/));
    expect(await screen.findByText("أرز بسمتي")).toBeInTheDocument();
    expect(screen.getByText(/5\s*كيس/)).toBeInTheDocument();
  });

  it("submits the quantity that was actually entered", async () => {
    const user = userEvent.setup();
    portalApi.post.mockResolvedValue({ data: { data: { id: 1 } } });
    renderCatalog();
    await screen.findByText("أرز بسمتي");

    await user.type(screen.getAllByPlaceholderText("0")[0], "7");
    await user.click(screen.getByText(/مراجعة الطلب/));
    await user.click(screen.getByText("إرسال الطلب"));

    await waitFor(() => expect(portalApi.post).toHaveBeenCalled());
    const [path, body] = portalApi.post.mock.calls[0];
    expect(path).toBe("/portal/orders");
    expect(body.lines).toEqual([{ product_id: 1, quantity: "7" }]);
  });
});

describe("what the catalogue may show", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    respondToSearch();
  });

  it("shows no price anywhere, and says why", async () => {
    renderCatalog();
    await screen.findByText("أرز بسمتي");

    // The rule the whole ordering design rests on. Checked against the rendered text
    // rather than the schema, because a price could arrive through any of these.
    const rendered = document.body.textContent ?? "";
    for (const forbidden of ["ريال", "السعر", "price", "التكلفة"]) {
      expect(rendered).not.toContain(forbidden);
    }
    expect(rendered).toContain("الأسعار تُحتسب عند تأكيد الطلب");
  });

  it("renders availability as a band, never a quantity", async () => {
    renderCatalog();
    expect(await screen.findByText("متوفر")).toBeInTheDocument();
    expect(screen.getByText("كمية محدودة")).toBeInTheDocument();
  });

  it("stops a customer ordering something unavailable", async () => {
    portalApi.get.mockResolvedValue({
      data: { data: [{ ...RICE, availability: "unavailable" }] },
    });
    renderCatalog();
    await screen.findByText("أرز بسمتي");
    expect(screen.getByPlaceholderText("0")).toBeDisabled();
  });
});
