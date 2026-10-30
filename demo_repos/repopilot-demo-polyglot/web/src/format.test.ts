import { describe, expect, it } from "vitest";
import { formatPrice } from "./format";

describe("formatPrice", () => {
  it("formats thousands", () => expect(formatPrice(1234.5)).toBe("1,234.50"));
  it("formats millions", () => expect(formatPrice(1234567.5)).toBe("1,234,567.50"));
});
