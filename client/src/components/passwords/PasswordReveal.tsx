import { useState, useCallback } from "react";
import { Eye, EyeOff, Copy, Check, Loader2 } from "lucide-react";
import api from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { useTimedReveal } from "@/hooks/useTimedReveal";

interface PasswordRevealProps {
  orgId: string;
  passwordId: string;
}

interface PasswordRevealResponse {
  password: string;
}

export function PasswordReveal({ orgId, passwordId }: PasswordRevealProps) {
  // Store secret in local state only - no React Query caching for secrets
  const [password, setPassword] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  // Clear secret from state when hiding
  const handleClearSecret = useCallback(() => {
    setPassword(null);
  }, []);

  const { revealed, reveal, hide } = useTimedReveal({
    onHide: handleClearSecret,
  });

  // Always fetch fresh - no caching
  const fetchPassword = async (): Promise<string | null> => {
    setIsLoading(true);
    try {
      const response = await api.get<PasswordRevealResponse>(
        `/api/organizations/${orgId}/passwords/${passwordId}/reveal`
      );
      const pw = response.data.password;
      setPassword(pw);
      return pw;
    } catch {
      toast.error("Failed to reveal password");
      return null;
    } finally {
      setIsLoading(false);
    }
  };

  const handleToggleReveal = async () => {
    if (revealed) {
      hide();
    } else {
      await fetchPassword();
      reveal();
    }
  };

  const handleCopy = async () => {
    let pw = password;

    // Fetch if we don't have it (but don't reveal visually)
    if (!pw) {
      pw = await fetchPassword();
    }

    if (pw) {
      await navigator.clipboard.writeText(pw);
      setCopied(true);
      toast.success("Password copied to clipboard");
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="flex-1 font-mono text-sm bg-muted px-3 py-2 rounded-md overflow-hidden whitespace-nowrap">
        {isLoading ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : revealed && password ? (
          <span className="truncate">{password}</span>
        ) : (
          <span className="tracking-widest">************</span>
        )}
      </div>
      <Button
        variant="outline"
        size="icon"
        onClick={handleToggleReveal}
        disabled={isLoading}
        aria-label={revealed ? "Hide password" : "Reveal password"}
      >
        {revealed ? (
          <EyeOff className="h-4 w-4" />
        ) : (
          <Eye className="h-4 w-4" />
        )}
      </Button>
      <Button
        variant="outline"
        size="icon"
        onClick={handleCopy}
        disabled={isLoading}
        aria-label="Copy password"
      >
        {copied ? (
          <Check className="h-4 w-4 text-green-500" />
        ) : (
          <Copy className="h-4 w-4" />
        )}
      </Button>
    </div>
  );
}
