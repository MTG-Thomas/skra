import { describe, expect, it } from "vitest";
import {
  DEFAULT_DASHBOARD_LAYOUT,
  isKnownWidgetId,
  reconcileDashboardLayout,
  toPersistedLayout,
} from "@/components/dashboard/widgetRegistry";

describe("reconcileDashboardLayout", () => {
  it("falls back to defaults for malformed payloads", () => {
    for (const malformed of [
      undefined,
      null,
      "widgets",
      42,
      { widgets: [] },
      [],
    ]) {
      expect(reconcileDashboardLayout(malformed)).toEqual(
        DEFAULT_DASHBOARD_LAYOUT,
      );
    }
  });

  it("ignores unknown widget ids and deduplicates", () => {
    const layout = reconcileDashboardLayout([
      { id: "favorites", visible: false },
      { id: "future-widget", visible: true },
      { id: "favorites", visible: true },
      { id: 42, visible: true },
    ]);
    expect(layout).toEqual([
      { id: "favorites", visible: false },
      { id: "recent-activity", visible: true },
      { id: "quick-stats", visible: true },
      { id: "expiring-soon", visible: true },
    ]);
  });

  it("preserves saved order and appends new defaults", () => {
    const layout = reconcileDashboardLayout([
      { id: "quick-stats", visible: true },
    ]);
    expect(layout.map((item) => item.id)).toEqual([
      "quick-stats",
      "recent-activity",
      "favorites",
      "expiring-soon",
    ]);
  });

  it("appends expiring-soon to previously saved layouts", () => {
    const layout = reconcileDashboardLayout([
      { id: "recent-activity", visible: true },
      { id: "favorites", visible: true },
      { id: "quick-stats", visible: true },
    ]);
    expect(layout).toEqual([
      { id: "recent-activity", visible: true },
      { id: "favorites", visible: true },
      { id: "quick-stats", visible: true },
      { id: "expiring-soon", visible: true },
    ]);
  });

  it("defaults visible to true when the flag is missing", () => {
    const layout = reconcileDashboardLayout([{ id: "favorites" }]);
    expect(layout[0]).toEqual({ id: "favorites", visible: true });
  });
});

describe("toPersistedLayout", () => {
  it("round-trips through reconcile so only known ids persist", () => {
    expect(
      toPersistedLayout([
        { id: "favorites", visible: false },
        { id: "unknown", visible: true },
      ]),
    ).toEqual([
      { id: "favorites", visible: false },
      { id: "recent-activity", visible: true },
      { id: "quick-stats", visible: true },
      { id: "expiring-soon", visible: true },
    ]);
  });
});

describe("isKnownWidgetId", () => {
  it("accepts registered ids and rejects everything else", () => {
    expect(isKnownWidgetId("favorites")).toBe(true);
    expect(isKnownWidgetId("future-widget")).toBe(false);
    expect(isKnownWidgetId(undefined)).toBe(false);
    expect(isKnownWidgetId(42)).toBe(false);
  });
});
