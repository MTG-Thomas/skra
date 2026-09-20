import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import {
  expirationLabel,
  useGlobalUpcomingExpirations,
  type GlobalUpcomingExpiration,
} from "@/hooks/useExpirations";

function severityVariant(daysUntil: number) {
  if (daysUntil <= 1) return "destructive" as const;
  if (daysUntil <= 7) return "default" as const;
  return "secondary" as const;
}

export function ExpiringSoonList({
  items,
}: {
  items: GlobalUpcomingExpiration[];
}) {
  const sorted = [...items].sort((a, b) => a.days_until - b.days_until);
  return (
    <ul className="space-y-1">
      {sorted.map((item) => (
        <li
          key={`${item.organization_id}-${item.asset_id}-${item.field_key}`}
          className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 hover:bg-muted"
        >
          <div className="min-w-0 flex-1">
            <Link
              to={`/org/${item.organization_id}/assets/${item.asset_type_id}/${item.asset_id}`}
              className="block truncate text-sm hover:underline"
            >
              {item.asset_display || item.asset_type_name}
            </Link>
            <p className="truncate text-xs text-muted-foreground">
              {item.asset_type_name} · {item.field_name} ·{" "}
              {item.organization_name}
            </p>
          </div>
          <Badge
            variant={severityVariant(item.days_until)}
            className="shrink-0"
          >
            {expirationLabel(item.days_until)}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

/**
 * Personal dashboard "Expiring soon" widget (issue #39).
 *
 * Nearest expirations across all readable organizations with org context
 * and detail links, backed by the single global aggregation endpoint.
 */
export function ExpiringSoonWidget() {
  const { data, isLoading, isError } = useGlobalUpcomingExpirations(30, 10);

  if (isLoading) {
    return (
      <p className="text-sm text-muted-foreground">Loading expirations…</p>
    );
  }

  if (isError || !data) {
    return (
      <p className="text-sm text-muted-foreground">Expirations unavailable.</p>
    );
  }

  if (data.items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Nothing expiring in the next 30 days.
      </p>
    );
  }

  return <ExpiringSoonList items={data.items} />;
}
