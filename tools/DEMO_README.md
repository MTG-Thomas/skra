# Quick Demo Setup

Generate realistic MSP data for your Skra demo in under 2 minutes.

## Quick Start (Bash Script)

### Prerequisites
1. Skra running locally (`docker compose up -d`)
2. Logged in to the web UI (create first user at http://localhost:8080)
3. JWT token from browser (Dev Tools > Application > Local Storage > `skra-auth`)

### Run the Demo Script

```bash
# From the tools directory
cd tools

# Get your token first (see below), then run:
./quick_demo.sh http://localhost:8080 <your-jwt-token>
```

**What it creates:**
- 3 sample organizations (Acme Manufacturing, TechStart, Summit Financial)
- ~30 configurations (firewalls, switches, servers, APs, workstations)
- 15 passwords (6 with TOTP secrets for live code generation)
- 9 documents (SOPs, network diagrams with mermaid)

## Get Your JWT Token

### Chrome/Edge:
1. Open http://localhost:8080 and login
2. Press `F12` → Application tab
3. Local Storage → http://localhost:8080
4. Copy value of `skra-auth`

### Firefox:
1. Open http://localhost:8080 and login
2. Press `F12` → Storage tab
3. Local Storage → http://localhost:8080
4. Copy value of `skra-auth`

## Demo Highlights

After running the script, show your manager:

### 1. Migration Dashboard (`/admin/migration`)
```
Shows: 3 organizations, 30 configurations, 15 passwords, 9 documents
Visual progress bars and feature comparison with IT Glue
```

### 2. TOTP Code Generation (`/passwords`)
```
1. Go to Passwords page
2. Find "Domain Admin - Primary" password
3. Click "Reveal"
4. Show the live 6-digit TOTP code with countdown
5. "No more pulling out phones for 2FA codes"
```

### 3. AI-Powered Search (Press `Cmd+K`)
```
Try these searches:
- "Find the firewall at Acme"
- "Server IP addresses"
- "Emergency contact"
```

### 4. Network Diagrams
```
1. Go to Documents
2. Open "/Infrastructure/Network Topology"
3. Show the Mermaid diagram rendering live
4. Zoom and export as SVG/PNG
```

### 5. Global View (`/global`)
```
1. See all devices across all 3 companies
2. Filter by organization
3. "One view for our entire MSP"
```

## Demo Talking Points

**Cost Savings:**
- "IT Glue costs us $X/month per tech. This is free."
- "Self-hosted, no per-seat pricing"

**Better Features:**
- "Built-in TOTP generation - IT Glue can't do this"
- "Auto-generated network diagrams from live data"
- "AI search across all documentation"
- "Full audit logging"

**Security:**
- "Data stays in our infrastructure"
- "End-to-end encryption"
- "Passkey/WebAuthn support"

**Customization:**
- "Open source - we can modify anything"
- "API for integrations"
- "NinjaOne/Meraki auto-discovery built-in"

## Troubleshooting

### Script fails with "No token provided"
Make sure you're logged in to the web UI and copied the token correctly.

### "401 Unauthorized"
Token expired. Get a fresh token from the browser (login again if needed).

### "Connection refused"
Make sure Docker containers are running:
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml ps
```

## Alternative: Python Script

For more control over generated data:

```bash
# Install dependencies
pip install httpx

# Run Python generator
python generate_demo_data.py --api-url http://localhost:8080 --token <jwt-token>
```

## Cleanup

To remove demo data:
```bash
# Option 1: Reset database (fastest)
docker compose down -v
docker compose up -d

# Option 2: Manual deletion via UI
# Go to each organization → Settings → Delete Organization
```

## Sample Data Details

### Organizations
1. **Acme Manufacturing** - 50-100 employees, Detroit, MI
2. **TechStart Solutions** - 10-50 employees, Austin, TX  
3. **Summit Financial Group** - 100-500 employees, Denver, CO

### Sample Passwords (with TOTP)
- Domain Admin - Primary (TOTP: `JBSWY3DPEHPK3PXP`)
- Office 365 Global Admin (TOTP: `K3VPU6J2LFGVOWBX`)
- Server Root Access (TOTP: `LFLFMU2SOVDFE23K`)
- FortiGate Admin (no TOTP)
- Wi-Fi Admin (no TOTP)

**Note:** TOTP secrets are sample data only - they won't work with real authenticators but will show the UI functionality.

### Network Topology
Each org gets a realistic network:
- FortiGate/Cisco firewall
- Cisco Catalyst switches
- Dell PowerEdge servers
- Ubiquiti access points
- Multiple VLANs
- Documented in mermaid diagrams

## Next Steps

After successful demo:
1. Pilot with one small client
2. Import real IT Glue export
3. Train team on new interface
4. Document internal procedures

---

**Need help?** Check the main README or open an issue on GitHub.
