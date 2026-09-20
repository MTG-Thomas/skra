import { useNavigate } from "react-router-dom";
import {
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { useRecentlyAccessed } from "@/hooks/useRecentlyAccessed";
import { entityIconFor, getEntityPath } from "./recent-utils";

/**
 * Shared "Recently Accessed" section rendered inside both the desktop
 * Recent dropdown and the mobile overflow menu, so the list markup and
 * navigation behavior exist in exactly one place.
 */
export function RecentMenuContent() {
  const navigate = useNavigate();
  const { data: recentItems, isLoading } = useRecentlyAccessed(10);

  return (
    <>
      <DropdownMenuLabel>Recently Accessed</DropdownMenuLabel>
      <DropdownMenuSeparator />
      {isLoading ? (
        <div className="p-2 space-y-2">
          {[...Array(3)].map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : recentItems && recentItems.length > 0 ? (
        recentItems.map((item) => {
          const Icon = entityIconFor(item.entity_type);
          return (
            <DropdownMenuItem
              key={`${item.entity_type}-${item.entity_id}`}
              onClick={() => navigate(getEntityPath(item))}
              className="cursor-pointer"
            >
              <Icon className="h-4 w-4 mr-3 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium truncate">{item.name}</p>
                {item.org_name && item.entity_type !== "organization" && (
                  <p className="text-xs text-muted-foreground truncate">
                    {item.org_name}
                  </p>
                )}
              </div>
            </DropdownMenuItem>
          );
        })
      ) : (
        <div className="p-4 text-center text-sm text-muted-foreground">
          No recent activity
        </div>
      )}
    </>
  );
}
