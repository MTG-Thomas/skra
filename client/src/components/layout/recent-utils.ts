import {
  Building2,
  FileText,
  Key,
  MapPin,
  Package,
  Server,
} from "lucide-react";
import type { RecentItem } from "@/hooks/useRecentlyAccessed";

export const entityIcons: Record<
  string,
  React.ComponentType<{ className?: string }>
> = {
  password: Key,
  configuration: Server,
  location: MapPin,
  document: FileText,
  custom_asset: Package,
  organization: Building2,
};

export function entityIconFor(
  entityType: string
): React.ComponentType<{ className?: string }> {
  return entityIcons[entityType] || Package;
}

export function getEntityPath(item: RecentItem): string {
  if (item.entity_type === "organization") {
    return `/org/${item.entity_id}`;
  }
  return `/org/${item.organization_id}/${item.entity_type}s/${item.entity_id}`;
}
