/**
 * Passkeys Service
 *
 * API methods for WebAuthn passkey operations.
 * Provides passwordless authentication via biometrics (Face ID, Touch ID, etc.)
 */

import {
  startRegistration,
  startAuthentication,
  browserSupportsWebAuthn,
  browserSupportsWebAuthnAutofill,
} from "@simplewebauthn/browser";
import type {
  PublicKeyCredentialCreationOptionsJSON,
  PublicKeyCredentialRequestOptionsJSON,
} from "@simplewebauthn/browser";
import api from "@/lib/api-client";

// =============================================================================
// Types
// =============================================================================

export interface SetupPasskeyOptionsResponse {
  registration_token: string;
  options: PublicKeyCredentialCreationOptionsJSON;
  expires_in: number;
}

export interface SetupPasskeyVerifyResponse {
  user_id: string;
  email: string;
  access_token: string;
  refresh_token: string;
}

export interface SetupStatusResponse {
  needs_setup: boolean;
}

export interface PasskeyAuthOptionsResponse {
  challenge_id: string;
  options: PublicKeyCredentialRequestOptionsJSON;
}

export interface PasskeyAuthVerifyResponse {
  access_token: string;
  refresh_token: string;
  token_type?: string;
}

// =============================================================================
// Feature Detection
// =============================================================================

/**
 * Check if the browser supports WebAuthn passkeys
 */
export function supportsPasskeys(): boolean {
  return browserSupportsWebAuthn();
}

/**
 * Check if the browser supports WebAuthn conditional UI (autofill)
 * This enables passkey authentication to be triggered automatically
 */
export async function supportsConditionalUI(): Promise<boolean> {
  return browserSupportsWebAuthnAutofill();
}

// =============================================================================
// Setup Flow (First-Time Registration)
// =============================================================================

/**
 * Check if the platform needs first-time setup
 */
export async function checkSetupStatus(): Promise<SetupStatusResponse> {
  const response = await api.get<SetupStatusResponse>("/auth/setup/status");
  return response.data;
}

/**
 * Register with a passkey during first-time platform setup.
 * This is for NEW users when no users exist in the system.
 *
 * Flow:
 * 1. Get registration options with email/name
 * 2. Trigger browser passkey creation (Face ID, Touch ID, etc.)
 * 3. Verify credential and create user + passkey atomically
 * 4. Receive JWT tokens (user is immediately logged in)
 *
 * @param email - Email address for the new account
 * @param name - Optional display name
 * @param bootstrapToken - One-time production bootstrap authorization
 * @param deviceName - Optional friendly name for the passkey
 * @returns JWT tokens and user info on success
 */
export async function setupWithPasskey(
  email: string,
  name?: string,
  bootstrapToken?: string,
  deviceName?: string
): Promise<SetupPasskeyVerifyResponse> {
  // Step 1: Get registration options from server (auth at root level, no /api)
  const optionsResponse = await api.post<SetupPasskeyOptionsResponse>(
    "/auth/setup/passkey/options",
    { email, name, bootstrap_token: bootstrapToken }
  );

  const { registration_token, options } = optionsResponse.data;

  // Step 2: Trigger browser passkey creation
  let credential;
  try {
    console.log("[Passkey] Starting registration with options:", options);
    credential = await startRegistration({
      optionsJSON: options,
    });
    console.log("[Passkey] Registration successful");
  } catch (error) {
    // Log the full error for debugging
    console.error("[Passkey] Registration failed:", error);

    // Handle specific WebAuthn errors
    if (error instanceof Error) {
      console.error("[Passkey] Error name:", error.name, "Message:", error.message);

      if (error.name === "NotAllowedError") {
        throw new Error("Passkey creation was cancelled or not allowed. Please try again.");
      }
      if (error.name === "InvalidStateError") {
        throw new Error("This passkey is already registered on this device");
      }
      if (error.name === "NotSupportedError") {
        throw new Error("Your browser or device does not support passkeys");
      }
      if (error.name === "AbortError") {
        throw new Error("Passkey creation was aborted. Please try again.");
      }
      if (error.name === "SecurityError") {
        throw new Error("Security error: The page origin may not match the relying party ID");
      }
      // For unknown errors, include the original message
      throw new Error(`Passkey creation failed: ${error.message}`);
    }
    throw error;
  }

  // Step 3: Send credential to server for verification and user creation
  const verifyResponse = await api.post<SetupPasskeyVerifyResponse>(
    "/auth/setup/passkey/verify",
    {
      registration_token,
      credential,
      device_name: deviceName,
      bootstrap_token: bootstrapToken,
    }
  );

  return verifyResponse.data;
}

// =============================================================================
// Authentication Flow (Login with Passkey)
// =============================================================================

/**
 * Authenticate with a passkey (passwordless login).
 *
 * Flow:
 * 1. Get authentication challenge from server
 * 2. Trigger browser passkey authentication (Face ID, Touch ID, etc.)
 * 3. Verify credential and receive JWT tokens
 *
 * @param email - Optional email to target specific user's credentials.
 *                If omitted, uses discoverable credentials (passkey autofill).
 * @returns JWT tokens on success
 */
export async function authenticateWithPasskey(
  email?: string
): Promise<PasskeyAuthVerifyResponse> {
  // Step 1: Get authentication options from server
  const optionsResponse = await api.post<PasskeyAuthOptionsResponse>(
    "/auth/passkeys/authenticate/options",
    { email }
  );

  const { challenge_id, options } = optionsResponse.data;

  // Step 2: Trigger browser passkey authentication
  let credential;
  try {
    console.log("[Passkey] Starting authentication with options:", options);
    credential = await startAuthentication({
      optionsJSON: options,
    });
    console.log("[Passkey] Authentication successful");
  } catch (error) {
    console.error("[Passkey] Authentication failed:", error);

    if (error instanceof Error) {
      console.error(
        "[Passkey] Error name:",
        error.name,
        "Message:",
        error.message
      );

      if (error.name === "NotAllowedError") {
        throw new Error(
          "Passkey authentication was cancelled or not allowed. Please try again."
        );
      }
      if (error.name === "SecurityError") {
        throw new Error(
          "Security error: The page origin may not match the relying party ID"
        );
      }
      if (error.name === "AbortError") {
        throw new Error("Passkey authentication was aborted. Please try again.");
      }
      throw new Error(`Passkey authentication failed: ${error.message}`);
    }
    throw error;
  }

  // Step 3: Send credential to server for verification
  const verifyResponse = await api.post<PasskeyAuthVerifyResponse>(
    "/auth/passkeys/authenticate/verify",
    {
      challenge_id,
      credential,
    }
  );

  return verifyResponse.data;
}

/**
 * Start conditional passkey authentication (autofill).
 * This pre-fills the credential selection UI when the user interacts with
 * an input field with autocomplete="webauthn".
 *
 * @returns Promise that resolves when authentication completes
 */
export async function startConditionalAuthentication(): Promise<PasskeyAuthVerifyResponse> {
  // Step 1: Get authentication options from server (no email = discoverable)
  const optionsResponse = await api.post<PasskeyAuthOptionsResponse>(
    "/auth/passkeys/authenticate/options",
    {}
  );

  const { challenge_id, options } = optionsResponse.data;

  // Step 2: Start conditional (autofill) authentication
  let credential;
  try {
    console.log("[Passkey] Starting conditional authentication");
    credential = await startAuthentication({
      optionsJSON: options,
      useBrowserAutofill: true,
    });
    console.log("[Passkey] Conditional authentication successful");
  } catch (error) {
    // If aborted, just rethrow
    if (error instanceof Error && error.name === "AbortError") {
      throw error;
    }

    console.error("[Passkey] Conditional authentication failed:", error);

    if (error instanceof Error) {
      if (error.name === "NotAllowedError") {
        throw new Error(
          "Passkey authentication was cancelled or not allowed."
        );
      }
      throw new Error(`Passkey authentication failed: ${error.message}`);
    }
    throw error;
  }

  // Step 3: Send credential to server for verification
  const verifyResponse = await api.post<PasskeyAuthVerifyResponse>(
    "/auth/passkeys/authenticate/verify",
    {
      challenge_id,
      credential,
    }
  );

  return verifyResponse.data;
}
