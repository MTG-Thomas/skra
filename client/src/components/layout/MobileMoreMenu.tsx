import { MessageSquare, MoreHorizontal } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { useRecentlyAccessed } from "@/hooks/useRecentlyAccessed";
import { entityIconFor, getEntityPath } from "./recent-utils";

interface MobileMoreMenuProps {
  onChatClick?: () => void;
}

/**
 * Compact overflow menu for small screens. Hosts the header actions that
 * don't fit below the sm breakpoint (Chat, Recent items) so hiding them
 * from the header bar never removes access to them.
 */
export function MobileMoreMenu({ onChatClick }: MobileMoreMenuProps) {
  const navigate = useNavigate();
  const { data: recentItems, isLoading } = useRecentlyAccessed(10);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-9 w-9 sm:hidden"
          aria-label="More actions"
        >
          <MoreHorizontal className="h-5 w-5" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuItem
          onClick={() => onChatClick?.()}
          className="cursor-pointer"
        >
          <MessageSquare className="h-4 w-4 mr-3 text-muted-foreground" />
          <span className="text-sm font-medium">Chat</span>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>Recently Accessed</DropdownMenuLabel>
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
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
