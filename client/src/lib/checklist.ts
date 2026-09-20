/**
 * Checklist/SOP value helpers (pure, UI-framework free).
 *
 * API shape per field key: { items: [{ id, completed, completed_by?, completed_at? }] }
 */

export interface ChecklistItemState {
  id: string;
  completed: boolean;
  completed_by?: string | null;
  completed_at?: string | null;
}

export function parseChecklistItems(value: unknown): ChecklistItemState[] {
  if (typeof value !== "object" || value === null) return [];
  const items = (value as { items?: unknown }).items;
  if (!Array.isArray(items)) return [];
  return items.filter(
    (e): e is ChecklistItemState =>
      typeof e === "object" &&
      e !== null &&
      typeof (e as { id?: unknown }).id === "string" &&
      typeof (e as { completed?: unknown }).completed === "boolean"
  );
}

export function checklistProgress(
  definitions: { id?: string | null }[] | null | undefined,
  states: ChecklistItemState[]
): { done: number; total: number; percent: number } {
  const total = definitions?.length ?? 0;
  if (total === 0) return { done: 0, total: 0, percent: 0 };
  const byId = new Map(states.map((s) => [s.id, s]));
  const done = (definitions ?? []).filter((d) => d.id && byId.get(d.id)?.completed).length;
  return { done, total, percent: Math.round((done / total) * 100) };
}

/**
 * Compact completion summary for table/list cells, e.g. "75% (3/4)".
 */
export function formatChecklistListValue(
  definitions: { id?: string | null }[] | null | undefined,
  value: unknown
): string {
  const { done, total, percent } = checklistProgress(definitions, parseChecklistItems(value));
  if (total === 0) return "-";
  return `${percent}% (${done}/${total})`;
}
