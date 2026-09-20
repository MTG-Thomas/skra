import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useAuthStore } from "@/stores/auth.store";
import { useFavorites } from "@/hooks/useFavorites";
import { useGlobalSidebarData } from "@/hooks/useGlobalData";
import { useRecentlyAccessed } from "@/hooks/useRecentlyAccessed";
import { useDashboardLayout } from "@/hooks/useDashboardLayout";
import {
  DASHBOARD_WIDGET_REGISTRY,
  type DashboardWidgetId,
} from "@/components/dashboard/widgetRegistry";
import { entityLabel, entityPath } from "@/components/dashboard/entityLinks";
import { ExpiringSoonWidget } from "@/components/dashboard/ExpiringSoonWidget";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

// =============================================================================
// Widget shell with keyboard-accessible layout controls
// =============================================================================

function WidgetShell({
  title,
  description,
  disableUp,
  disableDown,
  onMoveUp,
  onMoveDown,
  onHide,
  children,
}: {
  title: string;
  description: string;
  disableUp: boolean;
  disableDown: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onHide: () => void;
  children: ReactNode;
}) {
  return (
    <section aria-label={title}>
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
          <div className="flex flex-wrap gap-1 pt-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={onMoveUp}
              disabled={disableUp}
              aria-label={`Move ${title} up`}
            >
              Move up
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={onMoveDown}
              disabled={disableDown}
              aria-label={`Move ${title} down`}
            >
              Move down
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={onHide}
              aria-label={`Hide ${title}`}
            >
              Hide
            </Button>
          </div>
        </CardHeader>
        <CardContent>{children}</CardContent>
      </Card>
    </section>
  );
}

// =============================================================================
// Recent activity widget
// =============================================================================

function RecentActivityWidget() {
  const { data, isLoading } = useRecentlyAccessed(8);

  if (isLoading) {
    return (
      <p className="text-sm text-muted-foreground">Loading recent activity…</p>
    );
  }

  const items = data ?? [];
  if (items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Nothing viewed yet. Open an item and it will show up here.
      </p>
    );
  }

  return (
    <ul className="space-y-1">
      {items.map((item) => {
        const href = entityPath(
          item.entity_type,
          item.organization_id,
          item.entity_id,
        );
        return (
          <li
            key={`${item.entity_type}-${item.entity_id}`}
            className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 hover:bg-muted"
          >
            {href ? (
              <Link
                to={href}
                className="min-w-0 flex-1 truncate text-sm hover:underline"
              >
                {item.name}
              </Link>
            ) : (
              <span className="min-w-0 flex-1 truncate text-sm">
                {item.name}
              </span>
            )}
            <span className="shrink-0 text-xs text-muted-foreground">
              {entityLabel(item.entity_type)}
              {item.org_name ? ` · ${item.org_name}` : ""}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

// =============================================================================
// Favorites widget
// =============================================================================

function FavoritesWidget() {
  const { data, isLoading } = useFavorites(8);

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading favorites…</p>;
  }

  const items = data?.items ?? [];
  if (items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No favorites yet. Star items to add them here.
      </p>
    );
  }

  return (
    <ul className="space-y-1">
      {items.map((favorite) => {
        const href = entityPath(
          favorite.entity_type,
          favorite.organization_id,
          favorite.entity_id,
        );
        const label =
          favorite.custom_label ||
          `${entityLabel(favorite.entity_type)} ${favorite.entity_id.slice(0, 8)}`;
        return (
          <li
            key={favorite.id}
            className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 hover:bg-muted"
          >
            {href ? (
              <Link
                to={href}
                className="min-w-0 flex-1 truncate text-sm hover:underline"
              >
                {label}
              </Link>
            ) : (
              <span className="min-w-0 flex-1 truncate text-sm">{label}</span>
            )}
            <span className="shrink-0 text-xs text-muted-foreground">
              {entityLabel(favorite.entity_type)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

// =============================================================================
// Quick stats widget
// =============================================================================

function QuickStatsWidget() {
  const { data, isLoading } = useGlobalSidebarData();

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading stats…</p>;
  }

  if (!data) {
    return (
      <p className="text-sm text-muted-foreground">Stats unavailable.</p>
    );
  }

  const stats = [
    { label: "Passwords", value: data.passwords_count },
    { label: "Configurations", value: data.configurations_count },
    { label: "Locations", value: data.locations_count },
    { label: "Documents", value: data.documents_count },
    {
      label: "Custom assets",
      value: data.custom_asset_types.reduce((sum, t) => sum + t.count, 0),
    },
  ];

  return (
    <dl className="grid grid-cols-2 gap-2">
      {stats.map((stat) => (
        <div key={stat.label} className="rounded-md border p-3">
          <dt className="text-xs text-muted-foreground">{stat.label}</dt>
          <dd className="text-2xl font-semibold">{stat.value}</dd>
        </div>
      ))}
    </dl>
  );
}

// =============================================================================
// Page
// =============================================================================

function renderWidget(id: DashboardWidgetId) {
  switch (id) {
    case "recent-activity":
      return <RecentActivityWidget />;
    case "favorites":
      return <FavoritesWidget />;
    case "quick-stats":
      return <QuickStatsWidget />;
    case "expiring-soon":
      return <ExpiringSoonWidget />;
    default:
      return null;
  }
}

export function DashboardPage() {
  const { user } = useAuthStore();
  const {
    layout,
    isLoading,
    isSaving,
    moveWidget,
    setWidgetVisible,
    resetLayout,
  } = useDashboardLayout();

  const visible = layout.filter((item) => item.visible);
  const hidden = layout.filter((item) => !item.visible);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
          <p className="mt-1 text-muted-foreground">
            Welcome to Skra, {user?.name || "User"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isSaving && (
            <span className="text-xs text-muted-foreground" role="status">
              Saving…
            </span>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={resetLayout}
            disabled={isLoading}
          >
            Reset layout
          </Button>
        </div>
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading dashboard…</p>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {visible.map((item, index) => {
            const def =
              DASHBOARD_WIDGET_REGISTRY[item.id as DashboardWidgetId];
            if (!def) return null;
            return (
              <WidgetShell
                key={item.id}
                title={def.title}
                description={def.description}
                disableUp={index === 0}
                disableDown={index === visible.length - 1}
                onMoveUp={() => moveWidget(item.id, "up")}
                onMoveDown={() => moveWidget(item.id, "down")}
                onHide={() => setWidgetVisible(item.id, false)}
              >
                {renderWidget(def.id)}
              </WidgetShell>
            );
          })}
        </div>
      )}

      {hidden.length > 0 && (
        <div>
          <h2 className="mb-2 text-sm font-medium text-muted-foreground">
            Hidden widgets
          </h2>
          <div className="flex flex-wrap gap-2">
            {hidden.map((item) => {
              const def =
                DASHBOARD_WIDGET_REGISTRY[item.id as DashboardWidgetId];
              if (!def) return null;
              return (
                <Button
                  key={item.id}
                  variant="outline"
                  size="sm"
                  onClick={() => setWidgetVisible(item.id, true)}
                  aria-label={`Show ${def.title}`}
                >
                  Show {def.title}
                </Button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
