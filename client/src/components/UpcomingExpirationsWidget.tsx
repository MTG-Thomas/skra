import { Link } from "react-router-dom";
import { CalendarClock } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  expirationLabel,
  type UpcomingExpiration,
} from "@/hooks/useExpirations";

function severityVariant(daysUntil: number) {
  if (daysUntil <= 1) return "destructive" as const;
  if (daysUntil <= 7) return "default" as const;
  return "secondary" as const;
}

interface UpcomingExpirationsWidgetProps {
  orgId: string;
  items: UpcomingExpiration[];
}

export function UpcomingExpirationsWidget({ orgId, items }: UpcomingExpirationsWidgetProps) {
  if (items.length === 0) {
    return null;
  }

  const sorted = [...items].sort((a, b) => a.days_until - b.days_until);

  return (
    <div data-testid="upcoming-expirations-widget">
      <h2 className="text-lg font-semibold mb-4">Upcoming Expirations</h2>
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <CalendarClock className="h-4 w-4 text-muted-foreground" />
            {items.length} asset{items.length === 1 ? "" : "s"} expiring soon
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="divide-y">
            {sorted.map((item) => (
              <li
                key={`${item.asset_id}-${item.field_key}`}
                className="flex items-center justify-between gap-3 py-2.5 first:pt-0 last:pb-0"
              >
                <div className="min-w-0">
                  <Link
                    to={`/org/${orgId}/assets/${item.asset_type_id}/${item.asset_id}`}
                    className="font-medium hover:underline truncate block"
                  >
                    {item.asset_display || item.asset_type_name}
                  </Link>
                  <p className="text-sm text-muted-foreground truncate">
                    {item.asset_type_name} · {item.field_name} · {item.expires_on}
                  </p>
                </div>
                <Badge variant={severityVariant(item.days_until)}>
                  {expirationLabel(item.days_until)}
                </Badge>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
