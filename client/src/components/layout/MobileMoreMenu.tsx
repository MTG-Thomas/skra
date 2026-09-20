import { MessageSquare, MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { RecentMenuContent } from "./RecentMenuContent";

interface MobileMoreMenuProps {
  onChatClick?: () => void;
}

/**
 * Compact overflow menu for small screens. Hosts the header actions that
 * don't fit below the sm breakpoint (Chat, Recent items) so hiding them
 * from the header bar never removes access to them.
 */
export function MobileMoreMenu({ onChatClick }: MobileMoreMenuProps) {
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
        <RecentMenuContent />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
