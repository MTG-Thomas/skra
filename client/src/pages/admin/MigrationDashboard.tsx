import { useQuery } from "@tanstack/react-query";
import {
  Building2,
  Network,
  Server,
  FileText,
  Key,
  MapPin,
  FolderTree,
  Activity,
  TrendingUp,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import api from "@/lib/api-client";

type ListResponse = {
  total?: number;
  items?: unknown[];
};

function getListTotal(data: ListResponse | unknown[]): number {
  if (Array.isArray(data)) {
    return data.length;
  }

  return data.total ?? data.items?.length ?? 0;
}

interface MigrationStats {
  organizations: number;
  configurations: number;
  passwords: number;
  documents: number;
  locations: number;
  customAssets: number;
  totalEntities: number;
  lastMigration: string | null;
}

export function MigrationDashboard() {
  // Fetch all stats
  const { data: orgs } = useQuery({
    queryKey: ["dashboard-orgs"],
    queryFn: async () => {
      const response = await api.get<ListResponse | unknown[]>("/api/organizations", {
        params: { limit: 1 },
      });
      return getListTotal(response.data);
    },
  });

  const { data: configs } = useQuery({
    queryKey: ["dashboard-configs"],
    queryFn: async () => {
      const response = await api.get<ListResponse>("/api/organizations/{org_id}/configurations", {
        params: { limit: 1 },
      });
      return getListTotal(response.data);
    },
  });

  const { data: passwords } = useQuery({
    queryKey: ["dashboard-passwords"],
    queryFn: async () => {
      const response = await api.get<ListResponse>("/api/organizations/{org_id}/passwords", {
        params: { limit: 1 },
      });
      return getListTotal(response.data);
    },
  });

  const { data: documents } = useQuery({
    queryKey: ["dashboard-docs"],
    queryFn: async () => {
      const response = await api.get<ListResponse>("/api/organizations/{org_id}/documents", {
        params: { limit: 1 },
      });
      return getListTotal(response.data);
    },
  });

  const stats: MigrationStats = {
    organizations: orgs || 0,
    configurations: configs || 0,
    passwords: passwords || 0,
    documents: documents || 0,
    locations: 0, // Would need separate call
    customAssets: 0, // Would need separate call
    totalEntities: (orgs || 0) + (configs || 0) + (passwords || 0) + (documents || 0),
    lastMigration: null,
  };

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Migration Dashboard</h1>
          <p className="text-muted-foreground">
            Overview of your IT Glue migration to Skra
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => window.open("/api/docs", "_blank")}>
            API Docs
          </Button>
          <Button onClick={() => window.location.href = "/global"}>
            <Activity className="h-4 w-4 mr-2" />
            Global View
          </Button>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Organizations</CardTitle>
            <Building2 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.organizations}</div>
            <p className="text-xs text-muted-foreground">Client companies</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Configurations</CardTitle>
            <Server className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.configurations}</div>
            <p className="text-xs text-muted-foreground">Devices & assets</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Passwords</CardTitle>
            <Key className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.passwords}</div>
            <p className="text-xs text-muted-foreground">Credentials stored</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Documents</CardTitle>
            <FileText className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.documents}</div>
            <p className="text-xs text-muted-foreground">KB articles & docs</p>
          </CardContent>
        </Card>
      </div>

      {/* Migration Status */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-5 w-5" />
              Migration Progress
            </CardTitle>
            <CardDescription>
              Estimated completion based on entity counts
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span>Total Entities Migrated</span>
                <span className="font-medium">{stats.totalEntities.toLocaleString()}</span>
              </div>
              <Progress value={Math.min(stats.totalEntities / 1000 * 100, 100)} />
              <p className="text-xs text-muted-foreground">
                {stats.totalEntities > 0 
                  ? "✓ Migration in progress - entities importing successfully" 
                  : "Ready to begin migration"}
              </p>
            </div>

            <div className="grid grid-cols-2 gap-4 pt-4">
              <div className="space-y-1">
                <p className="text-sm font-medium">Locations</p>
                <div className="flex items-center gap-2">
                  <MapPin className="h-4 w-4 text-blue-500" />
                  <span className="text-2xl font-bold">{stats.locations}</span>
                </div>
              </div>
              <div className="space-y-1">
                <p className="text-sm font-medium">Custom Assets</p>
                <div className="flex items-center gap-2">
                  <FolderTree className="h-4 w-4 text-purple-500" />
                  <span className="text-2xl font-bold">{stats.customAssets}</span>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Network className="h-5 w-5" />
              New Features Available
            </CardTitle>
            <CardDescription>
              Capabilities not available in IT Glue
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-3">
              <div className="flex items-start gap-3">
                <div className="mt-0.5 h-2 w-2 rounded-full bg-green-500" />
                <div>
                  <p className="text-sm font-medium">AI-Powered Search</p>
                  <p className="text-xs text-muted-foreground">
                    Natural language queries across all documentation
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="mt-0.5 h-2 w-2 rounded-full bg-green-500" />
                <div>
                  <p className="text-sm font-medium">TOTP/OTP Support</p>
                  <p className="text-xs text-muted-foreground">
                    Generate 2FA codes directly in the platform
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="mt-0.5 h-2 w-2 rounded-full bg-green-500" />
                <div>
                  <p className="text-sm font-medium">Auto-Generated Diagrams</p>
                  <p className="text-xs text-muted-foreground">
                    Network topology from live NinjaOne/Meraki data
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="mt-0.5 h-2 w-2 rounded-full bg-green-500" />
                <div>
                  <p className="text-sm font-medium">Rack Elevations</p>
                  <p className="text-xs text-muted-foreground">
                    Visual DCIM with power tracking
                  </p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Quick Actions */}
      <Card>
        <CardHeader>
          <CardTitle>Quick Actions</CardTitle>
          <CardDescription>Common tasks after migration</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Button
              variant="outline"
              className="h-auto py-4 flex flex-col items-center gap-2"
              onClick={() => window.location.href = "/organizations"}
            >
              <Building2 className="h-6 w-6" />
              <span className="text-sm font-medium">View Organizations</span>
              <span className="text-xs text-muted-foreground text-center">
                Browse all migrated companies
              </span>
            </Button>

            <Button
              variant="outline"
              className="h-auto py-4 flex flex-col items-center gap-2"
              onClick={() => window.location.href = "/passwords"}
            >
              <Key className="h-6 w-6" />
              <span className="text-sm font-medium">Check Passwords</span>
              <span className="text-xs text-muted-foreground text-center">
                Verify credentials imported
              </span>
            </Button>

            <Button
              variant="outline"
              className="h-auto py-4 flex flex-col items-center gap-2"
              onClick={() => window.location.href = "/search"}
            >
              <Activity className="h-6 w-6" />
              <span className="text-sm font-medium">Test Search</span>
              <span className="text-xs text-muted-foreground text-center">
                Try AI-powered search
              </span>
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Migration Log */}
      <Card className="bg-muted/50">
        <CardHeader>
          <CardTitle className="text-base">Migration CLI Reference</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm font-mono">
          <p className="text-muted-foreground"># Run migration (dry-run first)</p>
          <p>itglue-migrate itglue run --export-path /path/to/export --org "Company Name" --dry-run</p>
          <br />
          <p className="text-muted-foreground"># Full migration with sync</p>
          <p>itglue-migrate itglue sync --export-path /path/to/export --org "Company Name"</p>
          <br />
          <p className="text-muted-foreground"># Quick sync (faster, skip attachments)</p>
          <p>itglue-migrate itglue sync --export-path /path/to/export --org "Company Name" --skip-attachments</p>
        </CardContent>
      </Card>
    </div>
  );
}
