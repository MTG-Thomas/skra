import { describe, expect, it } from "vitest";
import { entityLabel, entityPath } from "@/components/dashboard/entityLinks";

describe("entityPath", () => {
  it("builds org-scoped detail routes", () => {
    expect(entityPath("password", "org-1", "pw-1")).toBe(
      "/org/org-1/passwords/pw-1",
    );
    expect(entityPath("configuration", "org-1", "cfg-1")).toBe(
      "/org/org-1/configurations/cfg-1",
    );
    expect(entityPath("location", "org-1", "loc-1")).toBe(
      "/org/org-1/locations/loc-1",
    );
    expect(entityPath("document", "org-1", "doc-1")).toBe(
      "/org/org-1/documents/doc-1",
    );
  });

  it("links organizations without an org scope", () => {
    expect(entityPath("organization", null, "org-1")).toBe("/org/org-1");
  });

  it("links custom assets to the org asset list without a type id", () => {
    expect(entityPath("custom_asset", "org-1", "asset-1")).toBe(
      "/org/org-1/assets",
    );
  });

  it("returns null when no route exists", () => {
    expect(entityPath("password", null, "pw-1")).toBeNull();
    expect(entityPath("unknown-type", "org-1", "id-1")).toBeNull();
  });
});

describe("entityLabel", () => {
  it("labels known types and passes unknown types through", () => {
    expect(entityLabel("password")).toBe("Password");
    expect(entityLabel("organization")).toBe("Organization");
    expect(entityLabel("something-new")).toBe("something-new");
  });
});
