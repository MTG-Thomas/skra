/**
 * React Query hooks for expiration tracking (issue #40).
 *
 * Types are hand-written because `src/lib/v1.d.ts` is generated from a live
 * server (`generate:types`); re-run generation to pick up the endpoint and
 * remove the duplication. Field shapes mirror UpcomingExpirationPublic.
 */

import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api-client";

export interface UpcomingExpiration {
  organization_id: string;
  asset_id: string;
  asset_display: string | null;
  asset_type_id: string;
  asset_type_name: string;
  field_key: string;
  field_name: string;
  expires_on: string;
  days_until: number;
  window_days: number;
}

export interface UpcomingExpirationsResponse {
  items: UpcomingExpiration[];
  total: number;
  within_days: number;
}

/** Alert windows in days; 0 means already expired. */
export const EXPIRATION_WINDOWS = [30, 14, 7, 1] as const;

export function expirationLabel(daysUntil: number): string {
  if (daysUntil < 0) {
    return `Expired ${-daysUntil}d ago`;
  }
  if (daysUntil === 0) {
    return "Expires today";
  }
  return `Expires in ${daysUntil}d`;
}

export function useUpcomingExpirations(orgId: string, withinDays = 30) {
  return useQuery({
    queryKey: ["upcoming-expirations", orgId, withinDays],
    queryFn: async () => {
      const response = await api.get<UpcomingExpirationsResponse>(
        `/api/organizations/${orgId}/expirations/upcoming?within_days=${withinDays}`
      );
      return response.data;
    },
    enabled: !!orgId,
  });
}

/**
 * One flagged expiration with organization context (issue #39).
 *
 * Mirrors GlobalUpcomingExpirationPublic: the org-scoped shape plus the
 * organization name for the personal dashboard widget.
 */
export interface GlobalUpcomingExpiration extends UpcomingExpiration {
  organization_name: string;
}

export interface GlobalUpcomingExpirationsResponse {
  items: GlobalUpcomingExpiration[];
  total: number;
  within_days: number;
  limit: number;
  offset: number;
}

/**
 * Cross-organization expirations for the personal dashboard (issue #39).
 *
 * Single aggregation endpoint — no per-org fan-out from the client.
 */
export function useGlobalUpcomingExpirations(withinDays = 30, limit = 10) {
  return useQuery({
    queryKey: ["global-upcoming-expirations", withinDays, limit],
    queryFn: async () => {
      const response = await api.get<GlobalUpcomingExpirationsResponse>(
        `/api/global/expirations/upcoming?within_days=${withinDays}&limit=${limit}`
      );
      return response.data;
    },
  });
}
