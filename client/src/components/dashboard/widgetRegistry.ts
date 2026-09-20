/**
 * Personal dashboard widget registry (Skra issue #39).
 *
 * Small typed registry for the personal DashboardPage composition.
 * Layout persistence reuses the existing typed preferences contract
 * (`GET/PUT /api/preferences/{entity_type}`, PR #122) with the
 * per-user entity key `dashboard_layout_personal`.
 *
 * Rules enforced by `reconcileDashboardLayout`:
 * - Unknown widget IDs are ignored (backend accepts future IDs; only
 *   registered IDs render).
 * - New default widgets are appended (existing user order preserved).
 * - Malformed saved data falls back to defaults (never a blank page).
 */

export const PERSONAL_DASHBOARD_LAYOUT_KEY = "dashboard_layout_personal";

export const MAX_DASHBOARD_WIDGETS = 12;

export type DashboardWidgetId =
  | "recent-activity"
  | "favorites"
  | "quick-stats"
  | "expiring-soon";

export interface DashboardWidgetItem {
  id: string;
  visible: boolean;
}

export interface DashboardWidgetDefinition {
  id: DashboardWidgetId;
  title: string;
  description: string;
}

export const DASHBOARD_WIDGET_REGISTRY: Record<
  DashboardWidgetId,
  DashboardWidgetDefinition
> = {
  "recent-activity": {
    id: "recent-activity",
    title: "Recent activity",
    description: "Last viewed and edited items",
  },
  favorites: {
    id: "favorites",
    title: "Favorites",
    description: "Starred items across organizations",
  },
  "quick-stats": {
    id: "quick-stats",
    title: "Quick stats",
    description: "Counts by type across all organizations",
  },
  "expiring-soon": {
    id: "expiring-soon",
    title: "Expiring soon",
    description: "Upcoming expirations across organizations",
  },
};

/** Default layout: every registered widget, visible, in registry order. */
export const DEFAULT_DASHBOARD_LAYOUT: DashboardWidgetItem[] = [
  { id: "recent-activity", visible: true },
  { id: "favorites", visible: true },
  { id: "quick-stats", visible: true },
  { id: "expiring-soon", visible: true },
];

export function isKnownWidgetId(id: unknown): id is DashboardWidgetId {
  return (
    typeof id === "string" &&
    Object.prototype.hasOwnProperty.call(DASHBOARD_WIDGET_REGISTRY, id)
  );
}

function normalizeItem(item: unknown): DashboardWidgetItem | null {
  if (typeof item !== "object" || item === null) return null;
  const record = item as Record<string, unknown>;
  if (!isKnownWidgetId(record.id)) return null;
  return {
    id: record.id,
    visible: typeof record.visible === "boolean" ? record.visible : true,
  };
}

/**
 * Reconcile saved layout data against the registry.
 *
 * Accepts the raw `widgets` value from the preferences payload (or
 * anything malformed) and always returns a renderable, non-empty layout:
 * known IDs in saved order (deduplicated), then any new default widgets
 * appended, capped at MAX_DASHBOARD_WIDGETS.
 */
export function reconcileDashboardLayout(saved: unknown): DashboardWidgetItem[] {
  if (!Array.isArray(saved)) {
    return DEFAULT_DASHBOARD_LAYOUT.map((item) => ({ ...item }));
  }

  const seen = new Set<string>();
  const reconciled: DashboardWidgetItem[] = [];

  for (const entry of saved) {
    const normalized = normalizeItem(entry);
    if (normalized === null || seen.has(normalized.id)) continue;
    seen.add(normalized.id);
    reconciled.push(normalized);
  }

  for (const fallback of DEFAULT_DASHBOARD_LAYOUT) {
    if (!seen.has(fallback.id)) {
      seen.add(fallback.id);
      reconciled.push({ ...fallback });
    }
  }

  const capped = reconciled.slice(0, MAX_DASHBOARD_WIDGETS);
  return capped.length > 0
    ? capped
    : DEFAULT_DASHBOARD_LAYOUT.map((item) => ({ ...item }));
}

/** Serialize a layout for PUT — only known IDs, plain {id, visible} shape. */
export function toPersistedLayout(
  layout: DashboardWidgetItem[],
): DashboardWidgetItem[] {
  return reconcileDashboardLayout(layout);
}
