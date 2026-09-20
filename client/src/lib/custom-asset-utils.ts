import type { CustomAssetType, CustomAsset } from "@/hooks/useCustomAssets";

/**
 * Get the display field key for an asset type.
 *
 * Falls back to:
 * 1. The explicit display_field_key if set
 * 2. First text/textbox field
 * 3. First non-header field
 * 4. null if no fields exist
 */
export function getDisplayFieldKey(assetType: CustomAssetType): string | null {
  if (assetType.display_field_key) {
    return assetType.display_field_key;
  }

  // Fall back to first text/textbox field
  const nonHeaderFields = assetType.fields.filter((f) => f.type !== "header");
  for (const field of nonHeaderFields) {
    if (field.type === "text" || field.type === "textbox") {
      return field.key;
    }
  }

  // Fall back to first scalar field (checklist and other structured values
  // don't render as names)
  for (const field of nonHeaderFields) {
    if (field.type !== "checklist") {
      return field.key;
    }
  }

  return null;
}

/**
 * Get the display value for an asset based on the display field key.
 */
export function getDisplayValue(
  asset: CustomAsset,
  displayFieldKey: string | null
): string {
  if (!displayFieldKey) return "Unnamed";
  const value = asset.values[displayFieldKey];
  if (value === undefined || value === null || value === "") return "Unnamed";
  // Structured values (e.g. checklist state objects) never render as names.
  if (typeof value === "object") return asset.id;
  return String(value);
}
