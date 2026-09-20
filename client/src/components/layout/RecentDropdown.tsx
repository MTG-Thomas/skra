import { Clock } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { RecentMenuContent } from "./RecentMenuContent";

export function RecentDropdown() {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="h-9 w-9">
          <Clock className="h-4 w-4" />
          <span className="sr-only">Recent items</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <RecentMenuContent />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
