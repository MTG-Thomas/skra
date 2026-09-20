import { RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import type { FieldDefinition } from "@/hooks/useCustomAssets";
import {
  checklistProgress,
  parseChecklistItems,
  type ChecklistItemState,
} from "@/lib/checklist";

interface ChecklistFieldProps {
  field: FieldDefinition;
  /** Current value in API shape: { items: ChecklistItemState[] } */
  value: unknown;
  /** When provided, the list is interactive (detail view). */
  onToggle?: (itemId: string, completed: boolean) => void;
  onReset?: () => void;
  disabled?: boolean;
}

function formatStamp(item: ChecklistItemState): string | null {
  if (!item.completed) return null;
  const parts: string[] = [];
  if (item.completed_at) {
    const date = new Date(item.completed_at);
    if (!Number.isNaN(date.getTime())) {
      parts.push(date.toLocaleString());
    }
  }
  if (item.completed_by) {
    parts.push(`by ${item.completed_by.slice(0, 8)}`);
  }
  return parts.length > 0 ? parts.join(" ") : null;
}

/**
 * Checklist/SOP field: ordered steps with completion state, progress, and
 * reset. Interactive when onToggle is provided, read-only otherwise.
 */
export function ChecklistField({ field, value, onToggle, onReset, disabled }: ChecklistFieldProps) {
  const definitions = field.checklist_items ?? [];
  const states = parseChecklistItems(value);
  const byId = new Map(states.map((s) => [s.id, s]));
  const { done, total, percent } = checklistProgress(definitions, states);
  const interactive = typeof onToggle === "function";

  if (definitions.length === 0) {
    return <span className="text-muted-foreground italic">No steps defined</span>;
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <Progress value={percent} className="flex-1" aria-label={`Checklist progress ${percent}%`} />
        <span className="text-xs text-muted-foreground whitespace-nowrap">
          {percent}% ({done}/{total})
        </span>
        {interactive && onReset && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled || done === 0}
            onClick={onReset}
            aria-label="Reset checklist"
          >
            <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
            Reset
          </Button>
        )}
      </div>
      <ul className="space-y-1.5">
        {definitions.map((item, index) => {
          const itemId = item.id ?? "";
          const state = byId.get(itemId);
          const completed = state?.completed ?? false;
          const stamp = state ? formatStamp(state) : null;
          return (
            <li key={itemId || index} className="flex items-start gap-2.5">
              {interactive ? (
                <Checkbox
                  id={`${field.key}-${itemId}`}
                  checked={completed}
                  disabled={disabled}
                  onCheckedChange={(checked) => onToggle(itemId, checked === true)}
                  className="mt-0.5"
                  aria-label={item.label ?? itemId}
                />
              ) : (
                <span
                  className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${completed ? "bg-green-600" : "bg-muted-foreground/30"}`}
                  aria-hidden
                />
              )}
              <div className="flex-1 min-w-0">
                <label
                  htmlFor={interactive ? `${field.key}-${itemId}` : undefined}
                  className={`text-sm ${completed ? "line-through text-muted-foreground" : ""} ${interactive ? "cursor-pointer" : ""}`}
                >
                  <span className="text-xs text-muted-foreground mr-1.5">{index + 1}.</span>
                  {item.label}
                </label>
                <div className="flex items-center gap-2 mt-0.5">
                  {item.required && (
                    <Badge variant="secondary" className="text-xs">
                      Required
                    </Badge>
                  )}
                  {stamp && (
                    <span className="text-xs text-muted-foreground" title={state?.completed_at ?? undefined}>
                      {stamp}
                    </span>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
