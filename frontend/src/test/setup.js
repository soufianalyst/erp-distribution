// Shared setup for the component tests.
//
// The app is RTL Arabic, so `dir` is set here rather than in each test: a component
// that only lays out correctly in LTR would otherwise pass in the test and look
// wrong in the product.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";

beforeEach(() => {
  document.documentElement.setAttribute("dir", "rtl");
  document.documentElement.setAttribute("lang", "ar");
  localStorage.clear();
});

afterEach(cleanup);
