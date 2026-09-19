import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { User, UserRole } from "@/lib/api-client";

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  needsSetup: boolean | null; // null = not checked yet
  login: (user: User) => void;
  logout: () => void;
  setUser: (user: User) => void;
  setNeedsSetup: (needsSetup: boolean) => void;
  // Permission helpers
  isAdmin: () => boolean;
  isOwner: () => boolean;
  hasRole: (role: UserRole) => boolean;
}

/** Legacy token keys from the pre-cookie session (issue #90). Purged once. */
const LEGACY_TOKEN_KEYS = [
  "access_token",
  "refresh_token",
  "bifrost-docs-auth",
] as const;

function purgeLegacyTokenStorage(): void {
  for (const key of LEGACY_TOKEN_KEYS) {
    localStorage.removeItem(key);
  }
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      isAuthenticated: false,
      needsSetup: null,

      login: (user) => {
        // Session lives in HttpOnly cookies set by the API on login.
        // Never persist Bearer [REDACTED] in readable browser storage.
        purgeLegacyTokenStorage();
        set({
          user,
          isAuthenticated: true,
          needsSetup: false, // Once logged in, setup is complete
        });
      },

      logout: () => {
        purgeLegacyTokenStorage();
        set({
          user: null,
          isAuthenticated: false,
        });
      },

      setUser: (user) => {
        set({ user });
      },

      setNeedsSetup: (needsSetup) => {
        set({ needsSetup });
      },

      // Permission helpers
      isAdmin: () => {
        const user = get().user;
        return user?.role === 'owner' || user?.role === 'administrator';
      },

      isOwner: () => {
        const user = get().user;
        return user?.role === 'owner';
      },

      hasRole: (role: UserRole) => {
        const user = get().user;
        return user?.role === role;
      },
    }),
    {
      name: "bifrost-docs-auth",
      storage: createJSONStorage(() => localStorage),
      // Version 1 drops persisted Bearer tokens (issue #90). The migrate
      // step purges any pre-cookie state so stale tokens cannot linger.
      version: 1,
      migrate: (persistedState) => {
        purgeLegacyTokenStorage();
        const state = (persistedState ?? {}) as Record<string, unknown>;
        return {
          user: (state.user ?? null) as AuthState["user"],
          isAuthenticated: (state.isAuthenticated ?? false) as boolean,
          needsSetup: (state.needsSetup ?? null) as AuthState["needsSetup"],
        };
      },
      partialize: (state) => ({
        user: state.user,
        isAuthenticated: state.isAuthenticated,
        needsSetup: state.needsSetup,
      }),
    }
  )
);
