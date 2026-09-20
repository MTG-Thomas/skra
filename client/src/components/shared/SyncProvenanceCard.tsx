import { Clock3, Database, ExternalLink, Fingerprint, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDateTime, formatRelativeTime } from "@/lib/date-utils";
import { isSafeExternalUrl } from "@/lib/external-url";

export interface SyncMetadata {
  source_system: string;
  source_tenant_id: string;
  external_id: string;
  last_synced_at: string;
  sync_status: string;
  sync_hash: string;
  source_url?: string | null;
}

interface SyncProvenanceCardProps {
  syncMetadata?: SyncMetadata | null;
}

function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\w\S*/g, (word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase());
}

function DetailRow({
  icon: Icon,
  label,
  value,
  mono = false,
}: {
  icon: typeof Database;
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex gap-3">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0">
        <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
        <dd className={mono ? "truncate font-mono text-xs" : "truncate text-sm"} title={value}>
          {value}
        </dd>
      </div>
    </div>
  );
}

export function SyncProvenanceCard({ syncMetadata }: SyncProvenanceCardProps) {
  if (!syncMetadata) {
    return null;
  }

  const sourceName = titleCase(syncMetadata.source_system);
  const statusLabel = titleCase(syncMetadata.sync_status);
  const lastSynced = formatDateTime(syncMetadata.last_synced_at);
  const freshness = formatRelativeTime(syncMetadata.last_synced_at);

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between gap-3 text-base">
          <span className="flex min-w-0 items-center gap-2">
            <RefreshCw className="h-4 w-4 shrink-0" />
            <span className="truncate">Sync Provenance</span>
          </span>
          <Badge variant="secondary" className="capitalize">
            {statusLabel}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="space-y-4">
          <DetailRow icon={Database} label="Source" value={sourceName} />
          <DetailRow icon={Fingerprint} label="External ID" value={syncMetadata.external_id} mono />
          <DetailRow icon={Clock3} label="Last sync" value={`${freshness} (${lastSynced})`} />
          <DetailRow icon={Fingerprint} label="Tenant" value={syncMetadata.source_tenant_id} mono />
        </dl>
        {isSafeExternalUrl(syncMetadata.source_url) && (
          <a
            href={syncMetadata.source_url as string}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-primary hover:underline"
          >
            Open source record
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        )}
      </CardContent>
    </Card>
  );
}
