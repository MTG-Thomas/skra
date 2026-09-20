import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef } from "react";
import api from "@/lib/api-client";
import {
  DEFAULT_DASHBOARD_LAYOUT,
  PERSONAL_DASHBOARD_LAYOUT_KEY,
  reconcileDashboardLayout,
  type DashboardWidgetItem,
} from "@/components/dashboard/widgetRegistry";

// =============================================================================
// Types
// =============================================================================

interface DashboardPreferencesResponse {
  entity_type: string;
  preferences: {
    widgets?: DashboardWidgetItem[] | null;
  };
}

// =============================================================================
// Hook
// =============================================================================

/**
 * Per-user personal dashboard layout, persisted via the existing
 * `GET/PUT /api/preferences/{entity_type}` contract using the
 * `dashboard_layout_personal` key (widgets contract from PR #122).
 *
 * Saved data is always reconciled against the widget registry, so unknown
 * IDs are ignored, new default widgets are appended, and malformed payloads
 * fall back to defaults instead of rendering a blank page.
 */
export function useDashboardLayout() {
  const queryClient = useQueryClient();
  const queryKey = useMemo(
    () => ["preferences", PERSONAL_DASHBOARD_LAYOUT_KEY],
    [],
  );

  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn: async () => {
      const response = await api.get<DashboardPreferencesResponse>(
        `/api/preferences/${PERSONAL_DASHBOARD_LAYOUT_KEY}`,
      );
      return response.data;
    },
    // A missing layout is a normal first-run state, not an error.
    retry: false,
  });

  // Serialized saves: rapid persist() calls debounce into one queued layout,
  // and at most one PUT runs at a time. When a request settles, the latest
  // queued layout (if any) is sent next, so the server always converges to
  // the newest state and can never persist a stale order. A failed request
  // rolls back the optimistic cache only when nothing newer is queued.
  // Unmount flushes a debounced-but-unsent layout instead of dropping it.
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingWidgetsRef = useRef<DashboardWidgetItem[] | null>(null);
  const saveInFlightRef = useRef(false);
  const unmountedRef = useRef(false);
  const flushSaveRef = useRef<() => void>(() => {});

  const saveMutation = useMutation({
    mutationFn: async (widgets: DashboardWidgetItem[]) => {
      const response = await api.put<DashboardPreferencesResponse>(
        `/api/preferences/${PERSONAL_DASHBOARD_LAYOUT_KEY}`,
        { preferences: { widgets } },
      );
      return response.data;
    },
    onSuccess: (data) => {
      // Adopt the server echo only when nothing newer is queued; otherwise
      // the queued flush will persist the newer state and refresh the cache.
      // After unmount the cache update is skipped so a stale response can
      // never overwrite newer optimistic state.
      if (!unmountedRef.current && pendingWidgetsRef.current === null) {
        queryClient.setQueryData(queryKey, data);
      }
    },
    onError: () => {
      // A queued layout supersedes the failed request, so roll back only
      // when there is nothing newer to send. After unmount the rollback is
      // skipped for the same staleness reason as onSuccess.
      if (!unmountedRef.current && pendingWidgetsRef.current === null) {
        queryClient.invalidateQueries({ queryKey });
      }
    },
    onSettled: () => {
      saveInFlightRef.current = false;
      flushSaveRef.current();
    },
  });

  const flushSave = useCallback(() => {
    if (saveInFlightRef.current) return;
    const pending = pendingWidgetsRef.current;
    if (pending === null) return;
    pendingWidgetsRef.current = null;
    saveInFlightRef.current = true;
    saveMutation.mutate(pending);
  }, [saveMutation]);

  useEffect(() => {
    flushSaveRef.current = flushSave;
  });

  // A debounced-but-unsent layout is flushed on unmount with a fire-and-
  // forget PUT so navigating right after a Hide/Move never loses the action.
  // When a PUT is already in flight, the queued latest layout stays queued
  // and the onSettled chain sends it; either way no cache writes happen
  // after unmount (see onSuccess/onError).
  useEffect(() => {
    return () => {
      unmountedRef.current = true;
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
        saveTimeoutRef.current = null;
      }
      if (saveInFlightRef.current) return;
      const pending = pendingWidgetsRef.current;
      pendingWidgetsRef.current = null;
      if (pending !== null) {
        // Fire-and-forget: the request outlives the component. Rejections
        // are ignored; the layout stays visible and resyncs on next visit.
        void api
          .put<DashboardPreferencesResponse>(
            `/api/preferences/${PERSONAL_DASHBOARD_LAYOUT_KEY}`,
            { preferences: { widgets: pending } },
          )
          .catch(() => undefined);
      }
    };
  }, []);

  const layout = useMemo(
    () => reconcileDashboardLayout(data?.preferences?.widgets),
    [data?.preferences?.widgets],
  );

  const persist = useCallback(
    (next: DashboardWidgetItem[]) => {
      const reconciled = reconcileDashboardLayout(next);
      queryClient.setQueryData(queryKey, {
        entity_type: PERSONAL_DASHBOARD_LAYOUT_KEY,
        preferences: { widgets: reconciled },
      });
      pendingWidgetsRef.current = reconciled;
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }
      saveTimeoutRef.current = setTimeout(() => {
        saveTimeoutRef.current = null;
        // Serialize through flushSave: if a PUT is in flight the pending
        // (latest) layout stays queued and is sent when it settles, so the
        // server always converges to the newest state in order.
        flushSaveRef.current();
      }, 300);
    },
    [queryClient, queryKey],
  );

  const moveWidget = useCallback(
    (id: string, direction: "up" | "down") => {
      const index = layout.findIndex((item) => item.id === id);
      if (index === -1) return;
      const moving = layout[index];
      // Only visible widgets are movable; hidden entries stay in place.
      if (moving === undefined || !moving.visible) return;
      const delta = direction === "up" ? -1 : 1;
      // Skip over hidden entries to the nearest visible neighbor.
      let target = index + delta;
      while (
        target >= 0 &&
        target < layout.length &&
        !layout[target]?.visible
      ) {
        target += delta;
      }
      if (target < 0 || target >= layout.length) return;
      const targetItem = layout[target];
      if (targetItem === undefined) return;
      const next = [...layout];
      next[index] = targetItem;
      next[target] = moving;
      persist(next);
    },
    [layout, persist],
  );

  const setWidgetVisible = useCallback(
    (id: string, visible: boolean) => {
      if (!layout.some((item) => item.id === id)) return;
      persist(
        layout.map((item) => (item.id === id ? { ...item, visible } : item)),
      );
    },
    [layout, persist],
  );

  const resetLayout = useCallback(() => {
    persist(DEFAULT_DASHBOARD_LAYOUT.map((item) => ({ ...item })));
  }, [persist]);

  return {
    layout,
    isLoading,
    error,
    isSaving: saveMutation.isPending,
    moveWidget,
    setWidgetVisible,
    resetLayout,
  };
}
