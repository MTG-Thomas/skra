import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";
import api from "@/lib/api-client";
import { useDashboardLayout } from "@/hooks/useDashboardLayout";
import {
  DEFAULT_DASHBOARD_LAYOUT,
  PERSONAL_DASHBOARD_LAYOUT_KEY,
  type DashboardWidgetItem,
} from "@/components/dashboard/widgetRegistry";

vi.mock("@/lib/api-client", () => ({
  default: { get: vi.fn(), put: vi.fn() },
}));

const getMock = api.get as unknown as Mock;
const putMock = api.put as unknown as Mock;

interface PutBody {
  preferences: { widgets: DashboardWidgetItem[] };
}

interface Gate {
  promise: Promise<unknown>;
  resolve: (value: unknown) => void;
  reject: (reason: unknown) => void;
}

function echo(widgets: DashboardWidgetItem[]) {
  return {
    entity_type: PERSONAL_DASHBOARD_LAYOUT_KEY,
    preferences: { widgets },
  };
}

function putWidgets(callIndex: number): DashboardWidgetItem[] {
  return (putMock.mock.calls[callIndex]?.[1] as PutBody).preferences.widgets;
}

function hidden(...ids: string[]): DashboardWidgetItem[] {
  return DEFAULT_DASHBOARD_LAYOUT.map((item) =>
    ids.includes(item.id) ? { ...item, visible: false } : { ...item },
  );
}

describe("useDashboardLayout save flow", () => {
  let queryClient: QueryClient;
  let gates: Gate[];

  function wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    );
  }

  async function renderReadyHook() {
    getMock.mockResolvedValue({ data: echo(DEFAULT_DASHBOARD_LAYOUT) });
    const hook = renderHook(() => useDashboardLayout(), { wrapper });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(hook.result.current.isLoading).toBe(false);
    return hook;
  }

  beforeEach(() => {
    // Only the debounce timers are faked; queueMicrotask stays real so
    // TanStack Query observer notifications flush with normal awaits.
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    gates = [];
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    getMock.mockReset();
    putMock.mockReset();
    putMock.mockImplementation(() => {
      let resolve!: (value: unknown) => void;
      let reject!: (reason: unknown) => void;
      const promise = new Promise<unknown>((res, rej) => {
        resolve = res;
        reject = rej;
      });
      const gate: Gate = { promise, resolve, reject };
      gates.push(gate);
      return gate.promise;
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("coalesces rapid changes into a single PUT with the latest layout", async () => {
    const hook = await renderReadyHook();

    // Sequential changes inside one debounce window. Advancing partway
    // pumps the async queues so the second change builds on the first
    // optimistic update, like separate user events.
    act(() => {
      hook.result.current.setWidgetVisible("favorites", false);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    act(() => {
      hook.result.current.setWidgetVisible("quick-stats", false);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    expect(putMock).toHaveBeenCalledTimes(1);
    expect(putWidgets(0)).toEqual(hidden("favorites", "quick-stats"));
  });

  it("serializes PUTs in order and never lets a stale success overwrite newer state", async () => {
    const hook = await renderReadyHook();
    const layoutA = hidden("favorites");
    const layoutB = hidden("favorites", "quick-stats");

    // First change starts PUT #1 (held in flight).
    act(() => {
      hook.result.current.setWidgetVisible("favorites", false);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(putMock).toHaveBeenCalledTimes(1);
    expect(putWidgets(0)).toEqual(layoutA);

    // Second change while PUT #1 is in flight stays queued.
    act(() => {
      hook.result.current.setWidgetVisible("quick-stats", false);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(putMock).toHaveBeenCalledTimes(1);

    // Stale success for PUT #1 must not clobber the newer optimistic layout,
    // and the queued latest layout is sent next, in order.
    await act(async () => {
      gates[0]?.resolve({ data: echo(layoutA) });
    });
    expect(putMock).toHaveBeenCalledTimes(2);
    expect(putWidgets(1)).toEqual(layoutB);
    expect(hook.result.current.layout).toEqual(layoutB);

    await act(async () => {
      gates[1]?.resolve({ data: echo(layoutB) });
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(hook.result.current.layout).toEqual(layoutB);
    expect(hook.result.current.isSaving).toBe(false);
  });

  it("keeps the queued latest layout when a PUT fails", async () => {
    const hook = await renderReadyHook();
    const layoutB = hidden("favorites", "quick-stats");

    act(() => {
      hook.result.current.setWidgetVisible("favorites", false);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(putMock).toHaveBeenCalledTimes(1);

    act(() => {
      hook.result.current.setWidgetVisible("quick-stats", false);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    // Failed PUT #1 must not roll back to a refetch while newer state is
    // queued; the latest layout is retried instead.
    await act(async () => {
      gates[0]?.reject(new Error("network down"));
    });
    expect(putMock).toHaveBeenCalledTimes(2);
    expect(putWidgets(1)).toEqual(layoutB);
    expect(hook.result.current.layout).toEqual(layoutB);

    await act(async () => {
      gates[1]?.resolve({ data: echo(layoutB) });
    });
    expect(hook.result.current.layout).toEqual(layoutB);
  });
});
