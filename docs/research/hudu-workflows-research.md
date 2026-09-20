# Hudu-Compatible Workflows Research

> **Issue:** #18  
> **Date:** 2026-04-06  
> **Goal:** Identify high-value Hudu workflows for Skra parity

---

## Executive Summary

This research compares Skra's current capabilities with Hudu MSP documentation workflows to identify **selective parity targets** - features that materially improve technician efficiency without cloning Hudu wholesale.

**Key Finding:** Skra has strong foundation parity (entities, relationships, custom assets, search) but gaps exist in **technician quality-of-life features** that make daily work faster.

---

## 1. Hudu Feature Inventory

### 1.1 Core Documentation (Hudu Strengths)

| Feature | Hudu Implementation | MSP Value |
|---------|---------------------|-----------|
| **Standardized Layouts** | Every client follows same structure | Consistency, faster onboarding |
| **Flexible Assets** | Custom schemas per asset type | Domain-specific documentation |
| **Knowledge Base** | Internal + client-facing articles | Self-service support |
| **SOPs & Checklists** | Step-by-step procedures | Repeatable processes |
| **Document Templates** | Reusable formats | Faster doc creation |
| **Form Builder** | Drag-drop custom forms | Structured data entry |

### 1.2 Quick Access & Navigation

| Feature | Hudu Implementation | MSP Value |
|---------|---------------------|-----------|
| **Universal Search** | Global + filtered by record type | Find anything fast |
| **Favorites/Pins** | Starred items, personal pins | Quick access to frequent items |
| **Recent Activity** | Last viewed/edited items | Resume work quickly |
| **Homepage Dashboard** | Widgets: counts, alerts, recent | At-a-glance status |
| **Quick Create** | One-click from anywhere | Faster data entry |
| **Related Items** | Linked assets, passwords, KBs | Full context in one view |

### 1.3 Infrastructure & DCIM

| Feature | Hudu Implementation | MSP Value |
|---------|---------------------|-----------|
| **IPAM** | Network/subnet management | IP address tracking |
| **Rack Management** | Visual rack elevations | Physical planning |
| **Cable Tracing** | Port-to-port mapping | Troubleshooting |
| **Power Tracking** | Circuit load monitoring | Capacity planning |
| **Network Topology** | Auto-generated diagrams | Environment visualization |

### 1.4 Monitoring & Alerts

| Feature | Hudu Implementation | MSP Value |
|---------|---------------------|-----------|
| **Domain/SSL Tracking** | Expiration alerts | Prevent outages |
| **Warranty Tracking** | Asset warranty dates | Budget planning |
| **Contract Renewals** | Contract expiration alerts | Avoid lapses |
| **Website Monitoring** | Uptime + SSL status | Proactive monitoring |
| **Expiration Alerts** | Multi-channel notifications | Stay ahead of issues |

### 1.5 Security & Access

| Feature | Hudu Implementation | MSP Value |
|---------|---------------------|-----------|
| **Password Vault** | Company + personal vaults | Secure credential storage |
| **TOTP/MFA** | One-time passcode management | 2FA convenience |
| **Role-Based Access** | Granular permissions | Data security |
| **Audit Logs** | Full change history | Compliance, accountability |
| **Client Portals** | Controlled external access | Client self-service |

### 1.6 Integration & Automation

| Feature | Hudu Implementation | MSP Value |
|---------|---------------------|-----------|
| **PSA Integration** | ConnectWise, Autotask sync | Ticket context |
| **RMM Integration** | NinjaOne, Datto sync | Auto-discovery |
| **API** | Full CRUD API | Custom integrations |
| **Webhooks** | Event-driven automation | Real-time sync |
| **AI Assistant** | Auto-generate docs from data | Reduce manual work |

---

## 2. Skra Current State

### 2.1 ✅ Strong Parity (Production Ready)

| Feature | Status | Notes |
|---------|--------|-------|
| **Core Entities** | ✅ Complete | Organizations, Configs, Passwords, Documents, Locations |
| **Custom Asset Types** | ✅ Complete | Flexible schemas with field inference |
| **Relationships** | ✅ Complete | Linked items across entity types |
| **Search** | ✅ Complete | Vector + text search with pgvector |
| **Document Editor** | ✅ Complete | Rich text with Mermaid diagrams |
| **Attachments** | ✅ Complete | S3/MinIO storage |
| **Role-Based Access** | ✅ Complete | Owner/Admin/Contributor/Reader roles |
| **MFA/TOTP** | ✅ Complete | WebAuthn + TOTP support |
| **Audit Logs** | ✅ Complete | Full change tracking |
| **Column Pinning** | ✅ Complete | DataTable with pinned columns |
| **Recent/Frequent Access** | ✅ Complete | Tracking + API ready |
| **Migration Tool** | ✅ Complete | IT Glue import with parity |

### 2.2 ⚠️ Partial/Needs Enhancement

| Feature | Status | Gap | Priority |
|---------|--------|-----|----------|
| **Dashboard/Widgets** | ⚠️ Basic | Global page has counts but limited widgets | Medium |
| **Diagramming** | ⚠️ Partial | Mermaid works but no auto-generated topology | Medium |
| **IPAM** | ⚠️ Planned | DCIM plan exists but not implemented | Low |
| **Rack Management** | ⚠️ Planned | DCIM plan exists but not implemented | Low |
| **Quick Navigation** | ⚠️ Missing | No favorites/pins feature | **High** |
| **Homepage Personalization** | ⚠️ Missing | No user-specific homepage | Medium |
| **SOPs/Checklists** | ❌ Missing | No checklist entity type | **High** |
| **Expiration Tracking** | ❌ Missing | No warranty/SSL/contract alerts | Medium |
| **Client Portals** | ❌ Missing | No external access for clients | Low |
| **AI Assistant** | ⚠️ Partial | Document mutations exist but limited | Medium |

### 2.3 ❌ Not Planned (Out of Scope)

| Feature | Reason | Alternative |
|---------|--------|-------------|
| **RMM Integration** | Bifrost Integrations owns this | Use `MTG-Thomas/bifrost` sync |
| **Website Monitoring** | Specialized tools do this better | UptimeRobot, Pingdom |
| **PSA Ticketing** | PSA owns this | Use PSA integrations |
| **Network Discovery** | Specialized tools exist | Use Bifrost network discovery |
| **Self-Hosting Option** | Currently container-only | Docker Compose is the path |

---

## 3. Priority Gaps Analysis

### 3.1 High Priority (Immediate Technician Value)

#### 1. **Favorites/Pins** 
**Hudu Pattern:** Star items, appear in quick-access sidebar  
**Skra Gap:** No personal bookmarking system  
**Implementation:** Add `favorites` table (user_id + entity_type + entity_id)  
**Effort:** Small (2-4 hours)  
**Value:** High - technicians save 5-10 clicks per frequent item

#### 2. **SOPs / Checklists**
**Hudu Pattern:** Step-by-step procedures with checkboxes  
**Skra Gap:** Documents are static, no interactive checklists  
**Implementation:** Add `Checklist` entity type or checklist field type for custom assets  
**Effort:** Medium (6-10 hours)  
**Value:** High - repeatable processes, onboarding consistency

#### 3. **Quick Create**
**Hudu Pattern:** "+" button in nav for instant record creation  
**Skra Gap:** Must navigate to entity page first  
**Implementation:** Add quick-create modal to main nav  
**Effort:** Small (2-4 hours)  
**Value:** Medium - faster data entry

### 3.2 Medium Priority (Polish & Efficiency)

#### 4. **Homepage Widgets**
**Hudu Pattern:** Personalized dashboard with counts, alerts, recent  
**Skra Gap:** Global view exists but limited customization  
**Implementation:** Expand GlobalPage with configurable widgets  
**Effort:** Medium (4-8 hours)  
**Value:** Medium - at-a-glance status for managers

#### 5. **Expiration Alerts**
**Hudu Pattern:** Track domains, SSL, warranties with email alerts  
**Skra Gap:** No date-based alerting system  
**Implementation:** Add `expiration_date` field type + alert job  
**Effort:** Medium (6-10 hours)  
**Value:** Medium - prevent service lapses

#### 6. **Related Items Enhancement**
**Hudu Pattern:** Rich relationship browser with filtering  
**Skra Gap:** Relationships exist but navigation is basic  
**Implementation:** Add relationship explorer panel to entity views  
**Effort:** Medium (4-8 hours)  
**Value:** Medium - full context faster

### 3.3 Lower Priority (Nice to Have)

#### 7. **Document Templates**
**Hudu Pattern:** Pre-formatted documents for common scenarios  
**Workaround:** Use SOPs + documents  
**Effort:** Medium (6-10 hours)

#### 8. **Auto-Generated Diagrams**
**Hudu Pattern:** Network topology from live data  
**Workaround:** Manual Mermaid diagrams  
**Effort:** Large (10-20 hours) - needs DCIM entities first

#### 9. **Client Portals**
**Hudu Pattern:** Controlled external access  
**Workaround:** PDF exports for clients  
**Effort:** Large (15-25 hours) - needs auth overhaul

---

## 4. Implementation Recommendations

### Phase 1: Quick Wins (Immediate Value)

```
Sprint 1: Favorites/Pins + Quick Create
- Add favorites API (POST/GET/DELETE /me/favorites)
- Add favorites sidebar widget
- Add quick-create dropdown to nav

Sprint 2: SOPs/Checklists
- Add checklist field type to custom assets
- Implement checkbox rendering in forms
- Track completion state
```

### Phase 2: Polish Features (After Midtown)

```
Sprint 3: Homepage Enhancement
- Configurable widgets
- Alert summaries
- Personal quick links

Sprint 4: Expiration Tracking
- Date field with alert flag
- Background job for notifications
- Alert preferences per user
```

### Phase 3: Advanced (Future Roadmap)

```
Sprint 5+: DCIM Features
- IPAM entities
- Rack management
- Auto-diagram generation
```

---

## 5. Specific Implementation Notes

### 5.1 Favorites/Pins Database Schema

```sql
CREATE TABLE user_favorites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    entity_type VARCHAR(50) NOT NULL, -- 'password', 'configuration', etc.
    entity_id UUID NOT NULL,
    display_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, organization_id, entity_type, entity_id)
);

CREATE INDEX idx_favorites_user ON user_favorites(user_id);
```

### 5.2 Checklist Field Type

```typescript
// New field type for custom assets
interface FieldDefinition {
  name: string;
  field_type: 'text' | 'textbox' | 'number' | 'date' | 'checkbox' | 'select' | 'checklist';
  // ...
}

// Checklist value structure
interface ChecklistValue {
  items: {
    id: string;
    label: string;
    completed: boolean;
    completed_by?: string;
    completed_at?: string;
  }[];
}
```

### 5.3 Expiration Alert System

```python
# Background job (worker.py)
async def check_expiring_items():
    """Find items expiring in next 30/14/7 days"""
    # Query custom assets with date fields marked for alerts
    # Send notifications to relevant users
    pass

# Add to cron_jobs
cron(check_expiring_items, hour=8, minute=0)  # Daily at 8am
```

---

## 6. Competitive Positioning

### Against Hudu

| Differentiator | Skra Advantage |
|----------------|----------------------|
| **Open Source** | Self-hosted, no per-seat pricing |
| **Bifrost Integration** | Native sync with integration platform |
| **AI Features** | Document mutations, auto-generation |
| **IT Glue Migration** | Purpose-built migration tooling |
| **Vector Search** | Semantic search with embeddings |

### Gaps to Close

1. **Technician Speed:** Favorites, quick create, checklists
2. **Manager Visibility:** Better dashboards, expiration tracking
3. **Client Experience:** Limited client access options

---

## 7. Recommended Next Steps

1. **Create GitHub Issues:**
   - #XX Favorites/Pins feature
   - #XX SOPs/Checklists entity type
   - #XX Quick Create navigation
   - #XX Homepage widgets enhancement

2. **Start with Favorites:**
   - Smallest effort, highest daily value
   - Unblocks "quick navigation" epic requirement

3. **Defer DCIM:**
   - IPAM/Rack management is large effort
   - Current Mermaid diagrams are sufficient for now
   - Revisit after core technician UX is polished

---

## 8. Summary

**For Midtown (Immediate):**
- ✅ Strong foundation parity exists
- 🎯 Target favorites + checklists for technician adoption
- 📝 Document expiration tracking for operational safety

**For Hudu-Familiar MSPs:**
- Emphasize **open source + Bifrost integration** as differentiators
- Acknowledge gaps in technician UX but show roadmap
- Position as "docs-first, then expand" vs Hudu's "everything-in-one"

**Strategic Recommendation:**
Focus Phase 3 (Hudu parity) on **technician quality-of-life** features rather than cloning every Hudu module. The goal is **documentation workflow parity**, not feature parity.

---

**Related:**
- Epic #18 - Hudu-compatible documentation workflows
- Epic #22 - Diagramming and DCIM expansion  
- `docs/ROADMAP.md` Phase 3
- `docs/DCIM_DIAGRAMMING_PLAN.md` - Future DCIM work
