# FluxPricer CLI Reference (`flux`)

`flux` (`scripts/flux.py`) provides small, composable terminal diagnostic commands to inspect, drive, and test the entire dynamic pricing pipeline hop-by-hop without requiring a browser or web UI.

---

## 1. Quick Start

### Start Server in Offline Mock Mode
```bash
# Boots server on 127.0.0.1:8123 with MOCK_LLM=1, BUS_BACKEND=inproc, UI_REQUIRE_LOGIN=1
python scripts/flux.py serve
```

### Seed Test Database
```bash
python scripts/seed.py
```

---

## 2. CLI Verbs & Subcommands

### 🔐 Authentication (`flux auth`)
```bash
# Register a new account
python scripts/flux.py auth register --email user@example.com --password "Password123!"

# Log in (session is cached in ~/.fluxpricer/session.json)
python scripts/flux.py auth login --email admin@example.com --password "admin12345!"

# Check current session identity
python scripts/flux.py auth whoami
```

### 📦 Product Catalog (`flux catalog`)
```bash
# Upload a catalog CSV or JSON file
python scripts/flux.py catalog upload my_catalog.csv

# List all catalog items
python scripts/flux.py catalog list

# Show detailed SKU info
python scripts/flux.py catalog show LAPTOP-001

# Show portfolio pricing urgency summary and ranked priority
python scripts/flux.py catalog urgency
```

### 💬 Chat Interaction (`flux chat`)
```bash
# Send a pricing prompt and view pipeline trace (provider, tools used, token usage)
python scripts/flux.py chat send "What price should LAPTOP-001 be?"

# Send a prompt to an existing thread
python scripts/flux.py chat send "Apply the recommended margin" --thread 1

# Stream response via SSE
python scripts/flux.py chat send "Optimize LAPTOP-002" --stream
```

### ⚡ Direct Price Optimizer (`flux optimizer`)
```bash
# Run the autonomous price optimizer on a specific SKU
python scripts/flux.py optimizer run LAPTOP-001

# Run with a specific algorithm (rule_based, profit_maximization, volatility_adjusted)
python scripts/flux.py optimizer run LAPTOP-001 --algo profit_maximization
```

### 🕷️ Market Data Collector (`flux collector`)
```bash
# Trigger a data collection cycle across all inventory SKUs
python scripts/flux.py collector run

# Trigger collection for a specific SKU
python scripts/flux.py collector run LAPTOP-001
```

### 📊 Logged Price Proposals (`flux proposals`)
```bash
# List all recent price proposals
python scripts/flux.py proposals list

# Filter proposals by SKU
python scripts/flux.py proposals list LAPTOP-001

# Show details of a specific price proposal (ID or ID prefix)
python scripts/flux.py proposals show <id>

# Preview applying a price proposal to the live catalog (dry-run)
python scripts/flux.py proposals apply <id>

# Actually apply a price proposal to the live catalog
python scripts/flux.py proposals apply <id> --yes
```

### 🚨 Alerts & Incidents (`flux alerts`)
```bash
# List open alert incidents
python scripts/flux.py alerts incidents

# Acknowledge an incident
python scripts/flux.py alerts incidents ack 1

# Resolve an incident
python scripts/flux.py alerts incidents resolve 1
```

### 🤖 Daemon Agents Status (`flux agents`)
```bash
# Check daemon health, subscriptions, and uptime
python scripts/flux.py agents status
```

### 📜 Events Journal Tail (`flux events`)
```bash
# Show last 20 events from data/events.jsonl formatted single-line
python scripts/flux.py events tail -n 20

# Live follow event stream in real-time
python scripts/flux.py events tail --follow
```
