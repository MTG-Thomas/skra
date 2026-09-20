/**
 * Shared entity deep-links for personal dashboard widgets.
 * Route shapes mirror RecentEntityCard so widget links land on the same pages.
 */

export function entityPath(
  entityType: string,
  organizationId: string | null,
  entityId: string,
): string | null {
  if (entityType === "organization") return `/org/${entityId}`;
  if (!organizationId) return null;
  switch (entityType) {
    case "password":
      return `/org/${organizationId}/passwords/${entityId}`;
    case "configuration":
      return `/org/${organizationId}/configurations/${entityId}`;
    case "location":
      return `/org/${organizationId}/locations/${entityId}`;
    case "document":
      return `/org/${organizationId}/documents/${entityId}`;
    case "custom_asset":
      // No typeId is available on recent/favorite payloads, so link to the
      // org asset-type list instead of guessing a detail route.
      return `/org/${organizationId}/assets`;
    default:
      return null;
  }
}

export function entityLabel(entityType: string): string {
  switch (entityType) {
    case "password":
      return "Password";
    case "configuration":
      return "Configuration";
    case "location":
      return "Location";
    case "document":
      return "Document";
    case "custom_asset":
      return "Asset";
    case "organization":
      return "Organization";
    default:
      return entityType;
  }
}
