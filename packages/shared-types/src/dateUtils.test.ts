import { describe, expect, it } from "vitest";
import { deriveFirstName, deriveLastName, formatDateMMDDYYYY, parseDateMMDDYYYY } from "./dateUtils";

describe("formatDateMMDDYYYY", () => {
  it("formats ISO date to MM/DD/YYYY", () => {
    expect(formatDateMMDDYYYY("2024-03-15")).toBe("03/15/2024");
  });

  it("handles ISO datetime strings", () => {
    expect(formatDateMMDDYYYY("2024-03-15T10:30:00Z")).toBe("03/15/2024");
  });

  it("returns null for null/undefined/empty", () => {
    expect(formatDateMMDDYYYY(null)).toBeNull();
    expect(formatDateMMDDYYYY(undefined)).toBeNull();
    expect(formatDateMMDDYYYY("")).toBeNull();
  });

  it("returns null for non-ISO strings", () => {
    expect(formatDateMMDDYYYY("March 15, 2024")).toBeNull();
  });
});

describe("parseDateMMDDYYYY", () => {
  it("parses MM/DD/YYYY to ISO YYYY-MM-DD", () => {
    expect(parseDateMMDDYYYY("03/15/2024")).toBe("2024-03-15");
  });

  it("pads single-digit month and day", () => {
    expect(parseDateMMDDYYYY("3/5/2024")).toBe("2024-03-05");
  });

  it("returns null for null/undefined/empty", () => {
    expect(parseDateMMDDYYYY(null)).toBeNull();
    expect(parseDateMMDDYYYY(undefined)).toBeNull();
    expect(parseDateMMDDYYYY("")).toBeNull();
  });

  it("returns null for non-MM/DD/YYYY strings", () => {
    expect(parseDateMMDDYYYY("2024-03-15")).toBeNull();
  });

  it("round-trips with formatDateMMDDYYYY", () => {
    const iso = "2024-06-01";
    expect(parseDateMMDDYYYY(formatDateMMDDYYYY(iso)!)).toBe(iso);
  });
});

describe("deriveFirstName", () => {
  it("extracts first token from full name", () => {
    expect(deriveFirstName("Grace Hopper")).toBe("Grace");
  });

  it("handles single name", () => {
    expect(deriveFirstName("Cher")).toBe("Cher");
  });

  it("handles multi-word name", () => {
    expect(deriveFirstName("Mary Ann Smith")).toBe("Mary");
  });
});

describe("deriveLastName", () => {
  it("extracts everything after first token", () => {
    expect(deriveLastName("Grace Hopper")).toBe("Hopper");
  });

  it("returns empty string for single name", () => {
    expect(deriveLastName("Cher")).toBe("");
  });

  it("handles multi-word last name", () => {
    expect(deriveLastName("Mary Ann Smith")).toBe("Ann Smith");
  });
});
