import { useState } from "react";
import DOMPurify from "dompurify";
import { Check, X, Eye, EyeOff, Copy, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { TOTPDisplay } from "@/components/ui/totp-display";
import { toast } from "sonner";
import { useTimedReveal } from "@/hooks/useTimedReveal";
import type { FieldDefinition } from "@/hooks/useCustomAssets";
import { ChecklistField } from "./ChecklistField";

interface CustomFieldRendererProps {
  field: FieldDefinition;
  value: unknown;
  revealedValue?: unknown;
  onReveal?: () => void;
  onClear?: () => void;
  isRevealing?: boolean;
  onChecklistToggle?: (itemId: string, completed: boolean) => void;
  onChecklistReset?: () => void;
  checklistDisabled?: boolean;
}

export function CustomFieldRenderer({
  field,
  value,
  revealedValue,
  onReveal,
  onClear,
  isRevealing,
  onChecklistToggle,
  onChecklistReset,
  checklistDisabled,
}: CustomFieldRendererProps) {
  // Checklist fields render the interactive/read-only step list, with the
  // standard field-name wrapper below.
  const isChecklist = field.type === "checklist";

  // Header fields are just section dividers
  if (field.type === "header") {
    return (
      <div className="border-b pb-2 pt-4">
        <h4 className="font-semibold text-sm text-muted-foreground uppercase tracking-wide">
          {field.name}
        </h4>
      </div>
    );
  }

  const renderValue = () => {
    // Handle password/totp FIRST - they're excluded from public API response
    // and should always show reveal UI regardless of whether value is defined
    if (field.type === "password") {
      return (
        <InlinePasswordReveal
          value={revealedValue !== undefined ? String(revealedValue) : undefined}
          onReveal={onReveal}
          onClear={onClear}
          isRevealing={isRevealing}
        />
      );
    }

    if (field.type === "totp") {
      return (
        <InlineTOTPReveal
          value={revealedValue !== undefined ? String(revealedValue) : undefined}
          onReveal={onReveal}
          onClear={onClear}
          isRevealing={isRevealing}
        />
      );
    }

    // For all other field types, show "Not set" if empty (checklists render
    // their step list even without stored state so steps can be completed).
    if (!isChecklist && (value === undefined || value === null || value === "")) {
      return <span className="text-muted-foreground italic">Not set</span>;
    }

    switch (field.type) {
      case "text":
        return <span className="break-words">{String(value)}</span>;

      case "textbox":
        // Render HTML content for multiline text fields
        return (
          <div
            className="prose prose-sm dark:prose-invert max-w-none break-words"
            dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(String(value)) }}
          />
        );

      case "number":
        return (
          <span className="font-mono">
            {typeof value === "number" ? value.toLocaleString() : String(value)}
          </span>
        );

      case "date":
        try {
          const date = new Date(String(value));
          return (
            <span>
              {date.toLocaleDateString(undefined, {
                year: "numeric",
                month: "long",
                day: "numeric",
              })}
            </span>
          );
        } catch {
          return <span>{String(value)}</span>;
        }

      case "checkbox":
        return value === true || value === "true" ? (
          <div className="flex items-center gap-1.5 text-green-600 dark:text-green-500">
            <Check className="h-4 w-4" />
            <span>Yes</span>
          </div>
        ) : (
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <X className="h-4 w-4" />
            <span>No</span>
          </div>
        );

      case "select":
        return <span>{String(value)}</span>;

      case "checklist":
        return (
          <ChecklistField
            field={field}
            value={value}
            onToggle={onChecklistToggle}
            onReset={onChecklistReset}
            disabled={checklistDisabled}
          />
        );

      default:
        return <span>{String(value)}</span>;
    }
  };

  return (
    <div className="flex flex-col gap-1">
      <dt className="text-sm font-medium text-muted-foreground flex items-center gap-2">
        {field.name}
        {field.required && (
          <span className="text-xs text-destructive">*</span>
        )}
      </dt>
      <dd className="text-sm">{renderValue()}</dd>
      {field.hint && (
        <p className="text-xs text-muted-foreground">{field.hint}</p>
      )}
    </div>
  );
}

// Inline password reveal component for custom asset fields
interface InlinePasswordRevealProps {
  value?: string;
  onReveal?: () => void;
  onClear?: () => void;
  isRevealing?: boolean;
}

function InlinePasswordReveal({ value, onReveal, onClear, isRevealing }: InlinePasswordRevealProps) {
  const [copied, setCopied] = useState(false);

  const { revealed, reveal, hide } = useTimedReveal({
    onHide: onClear,
  });

  const handleToggleReveal = () => {
    if (revealed) {
      hide();
    } else {
      // Fetch if we don't have the value
      if (!value && onReveal) {
        onReveal();
      }
      reveal();
    }
  };

  const handleCopy = async () => {
    // Fetch if we don't have the value
    if (!value && onReveal) {
      onReveal();
      reveal();
      return;
    }
    if (value) {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      toast.success("Password copied to clipboard");
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 font-mono text-sm bg-muted px-3 py-2 rounded-md">
        {isRevealing ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : revealed && value ? (
          value
        ) : (
          <span className="tracking-widest">************</span>
        )}
      </div>
      <Button
        variant="outline"
        size="icon"
        onClick={handleToggleReveal}
        disabled={isRevealing}
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
        disabled={isRevealing}
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

// Inline TOTP reveal component for custom asset fields
interface InlineTOTPRevealProps {
  value?: string;
  onReveal?: () => void;
  onClear?: () => void;
  isRevealing?: boolean;
}

function InlineTOTPReveal({ value, onReveal, onClear, isRevealing }: InlineTOTPRevealProps) {
  const { revealed, reveal, hide } = useTimedReveal({
    onHide: onClear,
  });

  const handleToggleReveal = () => {
    if (revealed) {
      hide();
    } else {
      // Fetch if we don't have the value
      if (!value && onReveal) {
        onReveal();
      }
      reveal();
    }
  };

  // When not revealed, show masked placeholder with reveal button
  if (!revealed) {
    return (
      <div className="flex items-center gap-2">
        <div className="flex-1 font-mono text-sm bg-muted px-3 py-2 rounded-md">
          {isRevealing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <span className="tracking-widest">************</span>
          )}
        </div>
        <Button
          variant="outline"
          size="icon"
          onClick={handleToggleReveal}
          disabled={isRevealing}
        >
          <Eye className="h-4 w-4" />
        </Button>
      </div>
    );
  }

  // When revealed and we have the secret, show the TOTP display
  if (value) {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <TOTPDisplay secret={value} className="flex-1" />
          <Button
            variant="outline"
            size="icon"
            onClick={handleToggleReveal}
          >
            <EyeOff className="h-4 w-4" />
          </Button>
        </div>
      </div>
    );
  }

  // Revealed but no value yet (still loading)
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 font-mono text-sm bg-muted px-3 py-2 rounded-md">
        <Loader2 className="h-4 w-4 animate-spin" />
      </div>
      <Button
        variant="outline"
        size="icon"
        onClick={handleToggleReveal}
      >
        <EyeOff className="h-4 w-4" />
      </Button>
    </div>
  );
}

interface CustomFieldListProps {
  fields: FieldDefinition[];
  values: Record<string, unknown>;
  revealedValues?: Record<string, unknown>;
  onReveal?: () => void;
  onClear?: () => void;
  isRevealing?: boolean;
  onChecklistToggle?: (fieldKey: string, itemId: string, completed: boolean) => void;
  onChecklistReset?: (fieldKey: string) => void;
  checklistDisabled?: boolean;
}

export function CustomFieldList({
  fields,
  values,
  revealedValues,
  onReveal,
  onClear,
  isRevealing,
  onChecklistToggle,
  onChecklistReset,
  checklistDisabled,
}: CustomFieldListProps) {
  const hasSecretFields = fields.some((f) => f.type === "password" || f.type === "totp");

  return (
    <dl className="grid gap-4">
      {fields.map((field) => (
        <CustomFieldRenderer
          key={field.key}
          field={field}
          value={values[field.key]}
          revealedValue={revealedValues?.[field.key]}
          onReveal={hasSecretFields ? onReveal : undefined}
          onClear={hasSecretFields ? onClear : undefined}
          isRevealing={isRevealing}
          onChecklistToggle={
            onChecklistToggle ? (itemId, completed) => onChecklistToggle(field.key, itemId, completed) : undefined
          }
          onChecklistReset={onChecklistReset ? () => onChecklistReset(field.key) : undefined}
          checklistDisabled={checklistDisabled}
        />
      ))}
    </dl>
  );
}
