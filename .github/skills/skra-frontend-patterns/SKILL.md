---
name: skra-frontend-patterns
description: |
  React + TanStack Query patterns for Skra frontend (skra repo).
  Use when adding new pages, hooks, DataTables, forms, or UI components.
  Triggers: "add hook", "create page", "DataTable", "inline edit",
  "add sidebar", "entity detail page", "form component", "React Query".
---

# Skra Frontend Patterns

Reusable patterns for Skra frontend (MTG-Thomas/skra repo) using React, TypeScript, TanStack Query, and shadcn/ui.

## Quick Start: Add New Entity Page

Example: Adding a "Checklists" entity page

```bash
# 1. Create Hook
# src/hooks/useChecklists.ts

# 2. Create List Page  
# src/pages/checklists/ChecklistsPage.tsx

# 3. Create Detail Page
# src/pages/checklists/ChecklistDetailPage.tsx

# 4. Add to Sidebar
# src/components/layout/Sidebar.tsx

# 5. Add Routes
# src/App.tsx
```

## Architecture Principles

| Principle | Implementation |
|-----------|----------------|
| **TanStack Query** | All server state via useQuery/useMutation |
| **Optimistic UI** | Update cache before API confirms |
| **Type safety** | Strict TypeScript, generated API types |
| **shadcn/ui** | Use existing component library |
| **Org-scoped URLs** | `/org/{orgId}/entity/{id}` |
| **Inline edit** | Edit on detail pages where possible |

## Hook Template

```typescript
// src/hooks/useChecklists.ts

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api-client";
import { toast } from "sonner";

// =============================================================================
// Types
// =============================================================================

export interface Checklist {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
  updated_by_user_id: string | null;
}

export interface ChecklistCreate {
  name: string;
  description?: string | null;
}

export interface ChecklistUpdate {
  name?: string;
  description?: string | null;
  is_enabled?: boolean;
}

export interface ChecklistListResponse {
  items: Checklist[];
  total: number;
  limit: number;
  offset: number;
}

// =============================================================================
// Query Keys
// =============================================================================

export const checklistKeys = {
  all: ["checklists"] as const,
  lists: (orgId: string) => [...checklistKeys.all, "list", orgId] as const,
  list: (orgId: string, filters: object) => [...checklistKeys.lists(orgId), filters] as const,
  details: () => [...checklistKeys.all, "detail"] as const,
  detail: (orgId: string, id: string) => [...checklistKeys.details(), orgId, id] as const,
};

// =============================================================================
// List Hook
// =============================================================================

export function useChecklists(
  orgId: string,
  options: {
    search?: string;
    is_enabled?: boolean;
    limit?: number;
    offset?: number;
  } = {}
) {
  const { search, is_enabled = true, limit = 100, offset = 0 } = options;

  return useQuery({
    queryKey: checklistKeys.list(orgId, { search, is_enabled, limit, offset }),
    queryFn: async () => {
      const response = await api.get<ChecklistListResponse>(
        `/api/organizations/${orgId}/checklists`,
        {
          params: { search, is_enabled, limit, offset },
        }
      );
      return response.data;
    },
    staleTime: 30 * 1000, // 30 seconds
    enabled: !!orgId,
  });
}

// =============================================================================
// Detail Hook
// =============================================================================

export function useChecklist(orgId: string, checklistId: string) {
  return useQuery({
    queryKey: checklistKeys.detail(orgId, checklistId),
    queryFn: async () => {
      const response = await api.get<Checklist>(
        `/api/organizations/${orgId}/checklists/${checklistId}`
      );
      return response.data;
    },
    staleTime: 30 * 1000,
    enabled: !!orgId && !!checklistId,
  });
}

// =============================================================================
// Create Hook
// =============================================================================

export function useCreateChecklist(orgId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: ChecklistCreate) => {
      const response = await api.post<Checklist>(
        `/api/organizations/${orgId}/checklists`,
        data
      );
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: checklistKeys.lists(orgId) });
      toast.success("Checklist created");
    },
    onError: () => {
      toast.error("Failed to create checklist");
    },
  });
}

// =============================================================================
// Update Hook
// =============================================================================

export function useUpdateChecklist(orgId: string, checklistId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: ChecklistUpdate) => {
      const response = await api.put<Checklist>(
        `/api/organizations/${orgId}/checklists/${checklistId}`,
        data
      );
      return response.data;
    },
    onSuccess: (updated) => {
      // Optimistic update
      queryClient.setQueryData(checklistKeys.detail(orgId, checklistId), updated);
      queryClient.invalidateQueries({ queryKey: checklistKeys.lists(orgId) });
      toast.success("Checklist updated");
    },
    onError: () => {
      toast.error("Failed to update checklist");
    },
  });
}

// =============================================================================
// Delete Hook (Soft Delete)
// =============================================================================

export function useDeleteChecklist(orgId: string, onSuccess?: () => void) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (checklistId: string) => {
      await api.delete(
        `/api/organizations/${orgId}/checklists/${checklistId}`
      );
    },
    onSuccess: (_, checklistId) => {
      queryClient.removeQueries({ queryKey: checklistKeys.detail(orgId, checklistId) });
      queryClient.invalidateQueries({ queryKey: checklistKeys.lists(orgId) });
      toast.success("Checklist deleted");
      onSuccess?.();
    },
    onError: () => {
      toast.error("Failed to delete checklist");
    },
  });
}
```

## DataTable List Page Template

```typescript
// src/pages/checklists/ChecklistsPage.tsx

import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { Plus, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DataTable } from "@/components/ui/data-table";
import { useChecklists, checklistKeys } from "@/hooks/useChecklists";
import { usePermissions } from "@/hooks/usePermissions";
import type { ColumnDef } from "@tanstack/react-table";

// =============================================================================
// Types
// =============================================================================

interface ChecklistRow {
  id: string;
  name: string;
  description: string | null;
  is_enabled: boolean;
  created_at: string;
}

// =============================================================================
// Columns
// =============================================================================

const columns: ColumnDef<ChecklistRow>[] = [
  {
    accessorKey: "name",
    header: "Name",
    cell: ({ row, getValue }) => {
      const orgId = row.original.organization_id;
      return (
        <Link
          to={`/org/${orgId}/checklists/${row.original.id}`}
          className="font-medium hover:underline"
        >
          {getValue() as string}
        </Link>
      );
    },
  },
  {
    accessorKey: "description",
    header: "Description",
    cell: ({ getValue }) => (
      <span className="text-muted-foreground truncate max-w-md">
        {(getValue() as string) || "—"}
      </span>
    ),
  },
  {
    accessorKey: "is_enabled",
    header: "Status",
    cell: ({ getValue }) => (
      <span className={getValue() ? "text-green-600" : "text-muted-foreground"}>
        {getValue() ? "Active" : "Disabled"}
      </span>
    ),
  },
  {
    accessorKey: "created_at",
    header: "Created",
    cell: ({ getValue }) => new Date(getValue() as string).toLocaleDateString(),
  },
];

// Columns to pin to the left
const pinnedColumns = ["select", "name"];

// =============================================================================
// Component
// =============================================================================

export function ChecklistsPage() {
  const { orgId } = useParams<{ orgId: string }>();
  const { canEdit } = usePermissions();
  const [search, setSearch] = useState("");
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 25 });

  const { data, isLoading, error } = useChecklists(orgId!, {
    search: search || undefined,
    limit: pagination.pageSize,
    offset: pagination.pageIndex * pagination.pageSize,
  });

  const checklists = data?.items || [];
  const total = data?.total || 0;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Checklists</h1>
          <p className="text-muted-foreground">
            Manage checklists and procedures
          </p>
        </div>
        {canEdit && (
          <Button asChild>
            <Link to={`/org/${orgId}/checklists/new`}>
              <Plus className="mr-2 h-4 w-4" />
              New Checklist
            </Link>
          </Button>
        )}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search checklists..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8"
          />
        </div>
      </div>

      {/* DataTable */}
      <DataTable
        columns={columns}
        data={checklists}
        isLoading={isLoading}
        error={error}
        totalRows={total}
        pinnedColumns={pinnedColumns}
        pagination={pagination}
        onPaginationChange={setPagination}
        enableRowSelection={canEdit}
      />
    </div>
  );
}
```

## Detail Page with Inline Edit Template

```typescript
// src/pages/checklists/ChecklistDetailPage.tsx

import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { ArrowLeft, Trash2, Edit2 } from "lucide-react";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useForm, Controller } from "react-hook-form";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { ConfirmDialog } from "@/components/shared";
import { RelatedItemsSidebar } from "@/components/relationships";
import { FavoriteButton } from "@/components/favorites";

import { useChecklist, useUpdateChecklist, useDeleteChecklist } from "@/hooks/useChecklists";
import { usePermissions } from "@/hooks/usePermissions";
import { toast } from "sonner";

// =============================================================================
// Schema
// =============================================================================

const checklistSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  description: z.string().max(1000).optional(),
  is_enabled: z.boolean(),
});

type ChecklistFormValues = z.infer<typeof checklistSchema>;

// =============================================================================
// Component
// =============================================================================

export function ChecklistDetailPage() {
  const { orgId, id } = useParams<{ orgId: string; id: string }>();
  const navigate = useNavigate();
  const { canEdit } = usePermissions();
  const [isEditing, setIsEditing] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);

  const { data: checklist, isLoading } = useChecklist(orgId!, id!);
  const updateChecklist = useUpdateChecklist(orgId!, id!);
  const deleteChecklist = useDeleteChecklist(orgId!, () => {
    navigate(`/org/${orgId}/checklists`);
  });

  const form = useForm<ChecklistFormValues>({
    resolver: zodResolver(checklistSchema),
    defaultValues: {
      name: checklist?.name || "",
      description: checklist?.description || "",
      is_enabled: checklist?.is_enabled ?? true,
    },
  });

  const onSubmit = async (values: ChecklistFormValues) => {
    await updateChecklist.mutateAsync(values);
    setIsEditing(false);
  };

  if (isLoading) {
    return <div>Loading...</div>;
  }

  if (!checklist) {
    return <div>Checklist not found</div>;
  }

  return (
    <div className="flex gap-6">
      <div className="flex-1 space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
              <Link to={`/org/${orgId}/checklists`}>Checklists</Link>
              <span>/</span>
              <span>{checklist.name}</span>
            </div>
            
            {isEditing ? (
              <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
                <Controller
                  control={form.control}
                  name="name"
                  render={({ field, fieldState }) => (
                    <div>
                      <Input {...field} className="text-2xl font-bold" />
                      {fieldState.error && (
                        <p className="text-sm text-destructive mt-1">
                          {fieldState.error.message}
                        </p>
                      )}
                    </div>
                  )}
                />
                
                <Controller
                  control={form.control}
                  name="description"
                  render={({ field }) => (
                    <Textarea {...field} placeholder="Description" rows={3} />
                  )}
                />

                <div className="flex items-center gap-2">
                  <Controller
                    control={form.control}
                    name="is_enabled"
                    render={({ field }) => (
                      <Switch
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    )}
                  />
                  <span>Active</span>
                </div>

                <div className="flex gap-2">
                  <Button type="submit" disabled={updateChecklist.isPending}>
                    Save
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setIsEditing(false)}
                  >
                    Cancel
                  </Button>
                </div>
              </form>
            ) : (
              <>
                <div className="flex items-center gap-3">
                  <h1 className="text-2xl font-bold">{checklist.name}</h1>
                  <FavoriteButton
                    organizationId={orgId!}
                    entityType="checklist"
                    entityId={id!}
                    entityName={checklist.name}
                  />
                </div>
                <p className="text-muted-foreground">
                  {checklist.description || "No description"}
                </p>
              </>
            )}
          </div>

          {!isEditing && canEdit && (
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setIsEditing(true)}>
                <Edit2 className="mr-2 h-4 w-4" />
                Edit
              </Button>
              <Button
                variant="destructive"
                onClick={() => setShowDeleteDialog(true)}
              >
                <Trash2 className="mr-2 h-4 w-4" />
                Delete
              </Button>
            </div>
          )}
        </div>

        {/* Content sections here */}
      </div>

      {/* Sidebar */}
      <aside className="w-80 shrink-0 hidden lg:block space-y-4">
        <RelatedItemsSidebar
          orgId={orgId!}
          entityType="checklist"
          entityId={id!}
        />
      </aside>

      {/* Delete Dialog */}
      <ConfirmDialog
        open={showDeleteDialog}
        onOpenChange={setShowDeleteDialog}
        title="Delete Checklist"
        description={`Are you sure you want to delete "${checklist.name}"?`}
        onConfirm={() => deleteChecklist.mutate(id!)}
        isLoading={deleteChecklist.isPending}
      />
    </div>
  );
}
```

## Adding to Sidebar

```typescript
// In src/components/layout/Sidebar.tsx

import { FavoritesList } from "@/components/favorites";

// Add favorites widget after Home link
<NavItem name="Home" href={`/org/${orgId}`} icon={Home} />

{!isCollapsed && (
  <div className="px-2">
    <FavoritesList maxItems={5} />
  </div>
)}
```

## Adding Routes

```typescript
// In src/App.tsx

import { ChecklistsPage } from "@/pages/checklists/ChecklistsPage";
import { ChecklistDetailPage } from "@/pages/checklists/ChecklistDetailPage";

// Add routes
<Route path="/org/:orgId/checklists" element={<ChecklistsPage />} />
<Route path="/org/:orgId/checklists/:id" element={<ChecklistDetailPage />} />
```

## Reference Files

| File | Contents |
|------|----------|
| [references/acceptance-criteria.md](references/acceptance-criteria.md) | Correct/incorrect patterns |
| [references/hook-patterns.md](references/hook-patterns.md) | TanStack Query best practices |
| [references/component-patterns.md](references/component-patterns.md) | React component patterns |

## Related

- Repo: `MTG-Thomas/skra`
- Stack: React, TypeScript, TanStack Query, shadcn/ui, TailwindCSS
