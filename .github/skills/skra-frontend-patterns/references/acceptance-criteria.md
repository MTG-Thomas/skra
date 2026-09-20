# Acceptance Criteria: skra-frontend-patterns

**Repository:** `MTG-Thomas/skra`  
**Purpose:** Validate React + TanStack Query patterns

---

## 1. Hook Patterns

### ✅ CORRECT: Query Keys Structure

```typescript
export const checklistKeys = {
  all: ["checklists"] as const,
  lists: (orgId: string) => [...checklistKeys.all, "list", orgId] as const,
  list: (orgId: string, filters: object) => 
    [...checklistKeys.lists(orgId), filters] as const,
  details: () => [...checklistKeys.all, "detail"] as const,
  detail: (orgId: string, id: string) => 
    [...checklistKeys.details(), orgId, id] as const,
};

// Usage
useQuery({
  queryKey: checklistKeys.detail(orgId, id),
  ...
});
```

### ❌ INCORRECT: Hardcoded Query Keys

```typescript
// WRONG: Hardcoded strings
tanstack query
useQuery({
  queryKey: ["checklist", id],  // WRONG: Inconsistent structure
  ...
});
```

### ✅ CORRECT: Cache Invalidation

```typescript
export function useCreateChecklist(orgId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data) => { ... },
    onSuccess: () => {
      // Invalidate list queries
      queryClient.invalidateQueries({ 
        queryKey: checklistKeys.lists(orgId) 
      });
      toast.success("Created");
    },
  });
}
```

### ❌ INCORRECT: Missing Invalidation

```typescript
export function useCreateChecklist(orgId: string) {
  return useMutation({
    mutationFn: async (data) => { ... },
    // WRONG: No onSuccess to invalidate cache!
  });
}
```

---

## 2. Component Patterns

### ✅ CORRECT: Org-Scoped URL

```typescript
<Link to={`/org/${orgId}/checklists/${checklist.id}`}>
  {checklist.name}
</Link>
```

### ❌ INCORRECT: Wrong URL Structure

```typescript
// WRONG: Missing org scope
<Link to={`/checklists/${checklist.id}`}>
  {checklist.name}
</Link>
```

### ✅ CORRECT: DataTable with Types

```typescript
const columns: ColumnDef<ChecklistRow>[] = [
  {
    accessorKey: "name",
    header: "Name",
    cell: ({ getValue }) => (
      <span className="font-medium">{getValue() as string}</span>
    ),
  },
];

<DataTable
  columns={columns}
  data={checklists}
  isLoading={isLoading}
  totalRows={total}
/>
```

### ❌ INCORRECT: Untyped Columns

```typescript
// WRONG: No proper typing
const columns = [
  { field: "name", title: "Name" },  // Wrong API
];
```

---

## 3. Form Patterns

### ✅ CORRECT: Zod Schema + React Hook Form

```typescript
const checklistSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  description: z.string().max(1000).optional(),
});

type ChecklistFormValues = z.infer<typeof checklistSchema>;

function ChecklistForm() {
  const form = useForm<ChecklistFormValues>({
    resolver: zodResolver(checklistSchema),
    defaultValues: {
      name: "",
      description: "",
    },
  });
  
  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)}>
        <FormField
          control={form.control}
          name="name"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Name</FormLabel>
              <Input {...field} />
              <FormMessage />
            </FormItem>
          )}
        />
      </form>
    </Form>
  );
}
```

### ❌ INCORRECT: No Validation

```typescript
// WRONG: No schema validation
function ChecklistForm() {
  const [name, setName] = useState("");
  
  return (
    <input value={name} onChange={e => setName(e.target.value)} />
    // No validation, no error handling!
  );
}
```

---

## 4. Import Patterns

### ✅ CORRECT: Path Aliases

```typescript
import { Button } from "@/components/ui/button";
import { useChecklists } from "@/hooks/useChecklists";
import { cn } from "@/lib/utils";
```

### ❌ INCORRECT: Relative Imports

```typescript
// WRONG: Hard to maintain relative paths
import { Button } from "../../../components/ui/button";
```

---

## 5. Error Handling

### ✅ CORRECT: Query Error State

```typescript
const { data, isLoading, error } = useChecklists(orgId);

if (error) {
  return <ErrorMessage message="Failed to load checklists" />;
}
```

### ❌ INCORRECT: Silent Errors

```typescript
const { data } = useChecklists(orgId);
// WRONG: No error handling!
```

---

## 6. Loading States

### ✅ CORRECT: Loading Skeleton

```typescript
const { data, isLoading } = useChecklists(orgId);

<DataTable
  columns={columns}
  data={data?.items || []}
  isLoading={isLoading}  // Shows skeleton rows
/>
```

### ❌ INCORRECT: No Loading State

```typescript
const { data } = useChecklists(orgId);

// WRONG: Shows empty table while loading
<DataTable data={data?.items || []} />
```

---

## 7. Inline Edit Pattern

### ✅ CORRECT: Toggle Edit Mode

```typescript
const [isEditing, setIsEditing] = useState(false);
const form = useForm<ChecklistFormValues>({
  resolver: zodResolver(checklistSchema),
});

{isEditing ? (
  <form onSubmit={form.handleSubmit(onSubmit)}>
    <Input {...form.register("name")} />
    <Button type="submit">Save</Button>
    <Button onClick={() => setIsEditing(false)}>Cancel</Button>
  </form>
) : (
  <div>
    <h1>{checklist.name}</h1>
    <Button onClick={() => setIsEditing(true)}>Edit</Button>
  </div>
)}
```

---

## 8. Common Mistakes Checklist

| Mistake | Why It's Wrong | Correct Approach |
|---------|---------------|------------------|
| Hardcoded query keys | Cache issues | Use structured query key factory |
| Missing invalidation | Stale data | Invalidate on mutations |
| Wrong URL structure | 404 errors | Use `/org/{orgId}/...` pattern |
| No TypeScript types | Bugs | Define ColumnDef<RowType> |
| No zod validation | Bad data | Always use zod schemas |
| Relative imports | Brittle code | Use `@/` path aliases |
| Silent errors | Poor UX | Handle error states |
| No loading state | Confusing UX | Pass `isLoading` to DataTable |
