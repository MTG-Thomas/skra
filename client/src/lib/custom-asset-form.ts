import { z } from "zod";

import type { FieldDefinition } from "@/hooks/useCustomAssets";

export type AssetFormMode = "create" | "edit";

export function buildAssetValuesSchema(
  fields: FieldDefinition[],
  mode: AssetFormMode,
) {
  const fieldSchemas: Record<string, z.ZodTypeAny> = {};

  for (const field of fields) {
    if (field.type === "header") continue;

    let fieldSchema: z.ZodTypeAny;
    switch (field.type) {
      case "text":
      case "textbox":
        fieldSchema = z.string();
        if (field.required) {
          fieldSchema = (fieldSchema as z.ZodString).min(1, `${field.name} is required`);
        }
        break;
      case "password":
      case "totp":
        fieldSchema = z.string();
        if (field.required && mode === "create") {
          fieldSchema = (fieldSchema as z.ZodString).min(1, `${field.name} is required`);
        }
        break;
      case "number":
        fieldSchema = field.required
          ? z.number({ message: `${field.name} is required` })
          : z.union([z.number(), z.null()]);
        break;
      case "date":
        fieldSchema = z.string();
        if (field.required) {
          fieldSchema = (fieldSchema as z.ZodString).min(1, `${field.name} is required`);
        }
        break;
      case "checkbox":
        fieldSchema = z.boolean();
        break;
      case "select":
        fieldSchema = z.string();
        if (field.required) {
          fieldSchema = (fieldSchema as z.ZodString).min(1, `${field.name} is required`);
        }
        break;
      case "checklist":
        fieldSchema = z.object({ items: z.array(z.unknown()) }).passthrough();
        break;
      default:
        fieldSchema = z.string();
    }

    fieldSchemas[field.key] = fieldSchema;
  }

  return z.object({ values: z.object(fieldSchemas) });
}

export function cleanEditableAssetValues(
  fields: FieldDefinition[],
  values: Record<string, unknown>,
): Record<string, unknown> {
  const cleanedValues: Record<string, unknown> = {};
  for (const field of fields) {
    if (field.type === "header" || field.type === "checklist") continue;
    const value = values[field.key];
    if (value !== undefined && value !== "" && value !== null) {
      cleanedValues[field.key] = value;
    }
  }
  return cleanedValues;
}
