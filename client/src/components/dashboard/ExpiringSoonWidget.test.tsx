import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";
import api from "@/lib/api-client";
import {
  ExpiringSoonList,
  ExpiringSoonWidget,
} from "@/components/dashboard/ExpiringSoonWidget";
import type { GlobalUpcomingExpiration } from "@/hooks/useExpirations";

vi.mock("@/lib/api-client", () => ({
  default: { get: vi.fn() },
}));

const getMock = api.get as unknown as Mock;

afterEach(cleanup);

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    </MemoryRouter>
  );
}

function item(
  overrides: Partial<GlobalUpcomingExpiration> = {},
): GlobalUpcomingExpiration {
  return {
    organization_id: "org-1",
    organization_name: "Acme",
    asset_id: "asset-1",
    asset_display: "Wildcard Cert",
    asset_type_id: "type-1",
    asset_type_name: "SSL Certificate",
    field_key: "expires_on",
    field_name: "Expires On",
    expires_on: "2026-09-26",
    days_until: 7,
    window_days: 7,
    ...overrides,
  };
}

describe("ExpiringSoonWidget", () => {
  beforeEach(() => {
    getMock.mockReset();
  });

  it("shows a loading state while fetching", () => {
    getMock.mockReturnValue(new Promise(() => {}));
    render(<ExpiringSoonWidget />, { wrapper });
    expect(screen.getByText("Loading expirations…")).toBeDefined();
    expect(getMock).toHaveBeenCalledWith(
      "/api/global/expirations/upcoming?within_days=30&limit=10",
    );
  });

  it("shows an empty state when nothing is expiring", async () => {
    getMock.mockResolvedValue({
      data: { items: [], total: 0, within_days: 30, limit: 10, offset: 0 },
    });
    render(<ExpiringSoonWidget />, { wrapper });
    await waitFor(() =>
      expect(
        screen.getByText("Nothing expiring in the next 30 days."),
      ).toBeDefined(),
    );
  });

  it("shows an error state when the request fails", async () => {
    getMock.mockRejectedValue(new Error("network down"));
    render(<ExpiringSoonWidget />, { wrapper });
    await waitFor(() =>
      expect(screen.getByText("Expirations unavailable.")).toBeDefined(),
    );
  });

  it("lists expirations with org context and detail links", async () => {
    getMock.mockResolvedValue({
      data: {
        items: [
          item({
            asset_id: "asset-2",
            asset_display: "Firewall Contract",
            asset_type_name: "Contract",
            field_name: "Renews On",
            organization_id: "org-2",
            organization_name: "Globex",
            days_until: 2,
          }),
          item({ days_until: 20 }),
        ],
        total: 2,
        within_days: 30,
        limit: 10,
        offset: 0,
      },
    });
    render(<ExpiringSoonWidget />, { wrapper });

    await waitFor(() =>
      expect(screen.getByText("Firewall Contract")).toBeDefined(),
    );
    // Org context is visible alongside the asset type and field.
    expect(screen.getByText(/Globex/)).toBeDefined();
    expect(screen.getByText(/Acme/)).toBeDefined();
    // Detail links land on the org asset detail route.
    const link = screen.getByText("Wildcard Cert").closest("a");
    expect(link?.getAttribute("href")).toBe(
      "/org/org-1/assets/type-1/asset-1",
    );
  });
});

describe("ExpiringSoonList", () => {
  it("orders by nearest expiry first", () => {
    render(
      <MemoryRouter>
        <ExpiringSoonList
          items={[
            item({
              asset_id: "asset-later",
              asset_display: "Later Cert",
              days_until: 20,
            }),
            item({
              asset_id: "asset-expired",
              asset_display: "Expired Cert",
              days_until: -1,
            }),
          ]}
        />
      </MemoryRouter>,
    );
    const links = screen.getAllByRole("link");
    expect(links[0].textContent).toBe("Expired Cert");
    // Expired badge labels the overdue item first.
    expect(screen.getByText("Expired 1d ago")).toBeDefined();
    expect(screen.getByText("Expires in 20d")).toBeDefined();
  });
});
