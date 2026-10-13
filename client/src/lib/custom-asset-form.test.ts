import { describe, expect, it } from "vitest";

import type { FieldDefinition } from "@/hooks/useCustomAssets";
import { buildAssetValuesSchema, cleanEditableAssetValues } from "./custom-asset-form";

const fields = [
  { key: "name", name: "Name", type: "text", required: true },
  { key: "steps", name: "Steps", type: "checklist", required: false },
] as FieldDefinition[];

describe("custom asset form checklist handling", () => {
  it("accepts API checklist objects during edit validation", () => {
    const schema = buildAssetValuesSchema(fields, "edit");

    expect(
      schema.safeParse({
        values: {
          name: "Router rollout",
          steps: { items: [{ id: "rack", completed: true }] },
        },
      }).success,
    ).toBe(true);
  });

  it("excludes checklist snapshots from whole-form updates", () => {
    expect(
      cleanEditableAssetValues(fields, {
        name: "Router rollout",
        steps: { items: [{ id: "rack", completed: true }] },
      }),
    ).toEqual({ name: "Router rollout" });
  });
});
