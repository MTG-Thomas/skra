#!/bin/bash
#
# Quick Demo Data Generator for Skra
# 
# Creates sample organizations, configurations, passwords, and documents
# using the API directly with curl.
#
# Usage:
#   ./quick_demo.sh http://localhost:8080 <jwt_token>
#   
# Or if you're already logged in to the web UI, grab the token from
# browser dev tools (Application > Local Storage > skra-auth)

set -e

API_URL="${1:-http://localhost:8080}"
TOKEN="${2:-}"

if [ -z "$TOKEN" ]; then
    echo "⚠️  No token provided. Trying to use demo mode (requires manual login first)"
    echo "Usage: $0 <api_url> <jwt_token>"
    echo ""
    echo "To get your token:"
    echo "  1. Login to the web UI at $API_URL"
    echo "  2. Open browser dev tools (F12)"
    echo "  3. Go to Application > Local Storage"
    echo "  4. Copy the 'skra-auth' value"
    exit 1
fi

echo "🚀 Generating demo data at $API_URL..."
echo ""

# Helper function for API calls
api_call() {
    local method="$1"
    local endpoint="$2"
    local data="${3:-}"
    
    if [ -n "$data" ]; then
        curl -s -X "$method" \
            -H "Authorization: Bearer $TOKEN" \
            -H "Content-Type: application/json" \
            -d "$data" \
            "${API_URL}${endpoint}" | jq -r '.id // empty'
    else
        curl -s -X "$method" \
            -H "Authorization: Bearer $TOKEN" \
            "${API_URL}${endpoint}" | jq -r '.id // empty'
    fi
}

# Create organizations
echo "📦 Creating organizations..."

ORG1=$(api_call POST "/api/organizations" '{
    "name": "Acme Manufacturing",
    "metadata": {"industry": "Manufacturing", "size": "50-100 employees", "city": "Detroit", "state": "MI"}
}')

ORG2=$(api_call POST "/api/organizations" '{
    "name": "TechStart Solutions",
    "metadata": {"industry": "Technology", "size": "10-50 employees", "city": "Austin", "state": "TX"}
}')

ORG3=$(api_call POST "/api/organizations" '{
    "name": "Summit Financial Group",
    "metadata": {"industry": "Finance", "size": "100-500 employees", "city": "Denver", "state": "CO"}
}')

echo "  ✓ Created Acme Manufacturing (ID: ${ORG1:0:8}...)"
echo "  ✓ Created TechStart Solutions (ID: ${ORG2:0:8}...)"
echo "  ✓ Created Summit Financial (ID: ${ORG3:0:8}...)"

# Create configurations (infrastructure) for each org
create_configs() {
    local org_id="$1"
    local org_name="$2"
    
    echo "  🔧 Creating configurations for $org_name..."
    
    # Firewall
    api_call POST "/api/organizations/$org_id/configurations" '{
        "name": "FW-01",
        "configuration_type": "firewall",
        "manufacturer": "Fortinet",
        "model": "FortiGate 100F",
        "serial_number": "FG100FTK12345678",
        "ip_address": "10.1.1.1",
        "mac_address": "00:0C:29:A1:B2:C3",
        "operating_system": "FortiOS 7.0",
        "notes": "Primary firewall for HQ. WAN: 203.0.113.10",
        "status": "active"
    }' > /dev/null
    
    # Core Switch
    api_call POST "/api/organizations/$org_id/configurations" '{
        "name": "SW-CORE-01",
        "configuration_type": "switch",
        "manufacturer": "Cisco",
        "model": "Catalyst 9300",
        "serial_number": "FCW1234A1B2",
        "ip_address": "10.1.1.2",
        "mac_address": "00:5E:00:53:01:01",
        "operating_system": "IOS-XE 17.6",
        "notes": "Core switch with 48 ports. VLANs: 10(Server), 20(Workstation), 30(VoIP)",
        "status": "active"
    }' > /dev/null
    
    # Domain Controller
    api_call POST "/api/organizations/$org_id/configurations" '{
        "name": "DC01",
        "configuration_type": "server",
        "manufacturer": "Dell",
        "model": "PowerEdge R740",
        "serial_number": "2WXYZ1234A01",
        "ip_address": "10.1.10.10",
        "mac_address": "00:0C:29:D4:E5:F6",
        "operating_system": "Windows Server 2022",
        "notes": "Primary domain controller. Runs AD, DNS, DHCP.",
        "status": "active"
    }' > /dev/null
    
    # File Server
    api_call POST "/api/organizations/$org_id/configurations" '{
        "name": "FS01",
        "configuration_type": "server",
        "manufacturer": "Dell",
        "model": "PowerEdge R640",
        "serial_number": "2WXYZ5678B02",
        "ip_address": "10.1.10.11",
        "mac_address": "00:0C:29:A7:B8:C9",
        "operating_system": "Windows Server 2022",
        "notes": "File server with 10TB storage. RAID 10.",
        "status": "active"
    }' > /dev/null
    
    # Access Points
    for i in 1 2 3; do
        api_call POST "/api/organizations/$org_id/configurations" "{
            \"name\": \"AP-0$i\",
            \"configuration_type\": \"ap\",
            \"manufacturer\": \"Ubiquiti\",
            \"model\": \"UAP-AC-Pro\",
            \"serial_number\": \"E0123456789${i}\",
            \"ip_address\": \"10.1.40.1$i\",
            \"mac_address\": \"80:2A:A8:00:00:0$i\",
            \"notes\": \"Ceiling mount in ${i}F conference area\",
            \"status\": \"active\"
        }" > /dev/null
    done
    
    # Workstations
    for i in 1 2 3 4 5; do
        api_call POST "/api/organizations/$org_id/configurations" "{
            \"name\": \"WS-$(printf "%02d" $i)\",
            \"configuration_type\": \"workstation\",
            \"manufacturer\": \"Dell\",
            \"model\": \"OptiPlex 7090\",
            \"serial_number\": \"ABC$(printf "%05d" $i)\",
            \"ip_address\": \"10.1.20.$(printf "%02d" $i)\",
            \"mac_address\": \"00:1C:C0:00:$(printf "%02x" $i):00\",
            \"operating_system\": \"Windows 11 Pro\",
            \"status\": \"active\"
        }" > /dev/null
    done
    
    echo "    ✓ Created firewall, switches, servers, APs, workstations"
}

# Create passwords
create_passwords() {
    local org_id="$1"
    local org_name="$2"
    
    echo "  🔐 Creating passwords for $org_name..."
    
    # Domain Admin with TOTP
    api_call POST "/api/organizations/$org_id/passwords" '{
        "name": "Domain Admin - Primary",
        "username": "administrator",
        "password": "Secur3P@ss2024!",
        "totp_secret": "JBSWY3DPEHPK3PXP",
        "notes": "Domain admin account with MFA. Last rotated: 2024-01-15",
        "url": null
    }' > /dev/null
    
    # Office 365 with TOTP
    api_call POST "/api/organizations/$org_id/passwords" '{
        "name": "Office 365 Global Admin",
        "username": "admin@acmemfg.onmicrosoft.com",
        "password": "O365_Secure_2024!",
        "totp_secret": "K3VPU6J2LFGVOWBX",
        "notes": "Global admin for M365 tenant",
        "url": "https://admin.microsoft.com"
    }' > /dev/null
    
    # Firewall
    api_call POST "/api/organizations/$org_id/passwords" '{
        "name": "FortiGate Admin",
        "username": "admin",
        "password": "FGT@dm1n_2024!",
        "notes": "FortiGate admin password. Enable MFA in settings.",
        "url": "https://10.1.1.1"
    }' > /dev/null
    
    # Server root
    api_call POST "/api/organizations/$org_id/passwords" '{
        "name": "Server Root Access",
        "username": "root",
        "password": "L1nux_R00t_2024!",
        "totp_secret": "LFLFMU2SOVDFE23K",
        "notes": "Emergency root access to Linux servers",
        "url": null
    }' > /dev/null
    
    # Wi-Fi
    api_call POST "/api/organizations/$org_id/passwords" '{
        "name": "Wi-Fi Admin",
        "username": "ubnt",
        "password": "Un1f1_Admin2024!",
        "notes": "UniFi controller admin. Controller at 10.1.1.10:8443",
        "url": "https://10.1.1.10:8443"
    }' > /dev/null
    
    echo "    ✓ Created 5 passwords (2 with TOTP)"
}

# Create documents
create_documents() {
    local org_id="$1"
    local org_name="$2"
    
    echo "  📄 Creating documents for $org_name..."
    
    # Network diagram document
    api_call POST "/api/organizations/$org_id/documents" '{
        "name": "Network Topology",
        "path": "/Infrastructure",
        "content": "# Network Topology\n\n```mermaid\nflowchart LR\n    Internet[Internet] --> FW[Firewall\\n10.1.1.1]\n    FW --> SW[Core Switch\\n10.1.1.2]\n    SW --> Servers[Server VLAN\\n10.1.10.x]\n    SW --> Workstations[Workstation VLAN\\n10.1.20.x]\n    SW --> APs[Wi-Fi VLAN\\n10.1.40.x]\n    \n    classDef up fill:#90EE90,stroke:#228B22\n    class FW,SW,Servers,Workstations,APs up\n```\n\n## Network Segments\n\n| VLAN | Purpose | Subnet | Gateway |\n|------|---------|--------|---------|\n| 1 | Management | 10.1.1.0/24 | 10.1.1.1 |\n| 10 | Servers | 10.1.10.0/24 | 10.1.10.1 |\n| 20 | Workstations | 10.1.20.0/24 | 10.1.20.1 |\n| 40 | Wi-Fi | 10.1.40.0/24 | 10.1.40.1 |\n\n_Last updated: 2024-01-15_"
    }' > /dev/null
    
    # SOP Document
    api_call POST "/api/organizations/$org_id/documents" '{
        "name": "New Employee Onboarding - IT Checklist",
        "path": "/SOPs",
        "content": "# New Employee Onboarding - IT Checklist\n\n## Pre-Arrival (Day -1)\n- [ ] Create AD account in OU=Users\n- [ ] Assign Office 365 license (E3)\n- [ ] Prepare laptop from inventory\n- [ ] Create email signature template\n- [ ] Add to distribution lists:\n  - All Staff\n  - Department specific\n  - Location specific\n\n## Day 1 Tasks\n- [ ] Deliver hardware to desk\n- [ ] Setup dual monitors\n- [ ] Initial login and forced password reset\n- [ ] Microsoft Authenticator setup\n- [ ] 15-minute security briefing\n\n## Week 1\n- [ ] File share access (\\\\FS01\\shares)\n- [ ] VPN certificate issued\n- [ ] Printer mapping (FollowMe Print)\n- [ ] Application installs:\n  - Office 365\n  - Adobe Reader\n  - Company VPN\n  - Slack/Teams\n\n## Emergency Contacts\n| Role | Name | Phone |\n|------|------|-------|\n| IT Manager | John Smith | 555-0100 |\n| Network Admin | Jane Doe | 555-0101 |\n| MSP Hotline | 24/7 Support | 1-800-555-0199 |\n\n---\n**Document Version:** 2.1\n**Last Updated:** January 2024"
    }' > /dev/null
    
    # Emergency procedures
    api_call POST "/api/organizations/$org_id/documents" '{
        "name": "After-Hours Emergency Procedure",
        "path": "/SOPs",
        "content": "# After-Hours Emergency Procedure\n\n## Priority 1 - Immediate Response (24/7)\nCall immediately for these issues:\n- 🔴 Email server down (all users affected)\n- 🔴 Complete internet outage\n- 🔴 Security breach / Ransomware\n- 🔴 Core server failure (DC, FS, SQL)\n\n## Priority 2 - Within 2 Hours\nSubmit ticket, page on-call:\n- 🟡 Single workstation failure\n- 🟡 Printer issues\n- 🟡 Non-critical application down\n- 🟡 Slow network performance\n\n## Escalation Path\n1. **Self-Service:** https://helpdesk.company.com\n2. **MSP Hotline:** 1-800-555-0199 (24/7)\n3. **Text IT Manager:** For Priority 1 only\n   - John Smith: 555-0100\n4. **Call CTO:** If MSP unavailable\n   - Emergency: 555-0001\n\n## Quick Troubleshooting\n\n### Internet Down\n1. Check firewall power (10.1.1.1)\n2. Check ISP modem status lights\n3. Call ISP: 1-800-ISP-HELP\n\n### Server Unreachable\n1. Check iDRAC/iLO: 10.1.1.100 (DC01)\n2. Verify power at rack\n3. Check switch port status\n\n### Ransomware Detected\n1. **DISCONNECT** affected machine from network\n2. Call MSP immediately\n3. Do NOT pay ransom\n4. Document affected systems\n\n---\n**Document Version:** 1.5\n**Last Review:** December 2023"
    }' > /dev/null
    
    echo "    ✓ Created 3 documents (including mermaid diagram)"
}

# Create data for each organization
echo ""
echo "🏢 Populating organizations..."

for org_id in $ORG1 $ORG2 $ORG3; do
    org_name=$(curl -s -H "Authorization: Bearer $TOKEN" "${API_URL}/api/organizations/${org_id}" | jq -r '.name')
    create_configs "$org_id" "$org_name"
    create_passwords "$org_id" "$org_name"
    create_documents "$org_id" "$org_name"
    echo ""
done

echo ""
echo "✅ Demo data generation complete!"
echo ""
echo "📊 Summary:"
echo "   Organizations: 3"
echo "   Configurations: ~30 (firewalls, switches, servers, APs, workstations)"
echo "   Passwords: 15 (including 6 with TOTP)"
echo "   Documents: 9 (SOPs, network diagrams)"
echo ""
echo "🌐 Access your demo:"
echo "   Dashboard: ${API_URL}/admin/migration"
echo "   Global View: ${API_URL}/global"
echo "   Search: Press Cmd+K (or Ctrl+K)"
echo ""
echo "💡 Demo Highlights:"
echo "   - TOTP codes: View any password with TOTP to see live 6-digit code"
echo "   - Network diagrams: Check /Infrastructure/Network Topology documents"
echo "   - AI search: Try 'find the firewall at Acme'"
echo "   - Global view: See all devices across all 3 companies"
