# Agent Relay

Lightweight inter-agent messaging for AI coding agents. Enables multiple agents to send messages to each other across separate terminal sessions, VMs, containers, or any environment where agents run.

Works with any AI agent that can execute shell commands — Claude Code, Cursor, Windsurf, Cline, Aider, custom agents, or plain scripts.

## Quick Start

### 1. Install

```bash
git submodule add https://github.com/vinnyusestrict/agent-relay.git lib/relay
```

Or clone directly:
```bash
git clone https://github.com/vinnyusestrict/agent-relay.git
```

### 2. Configure the database

Agent Relay uses local MySQL/MariaDB for message storage. Tables are auto-created on first use.

```bash
mysql -u root -proot -e "CREATE DATABASE IF NOT EXISTS agent_relay"
```

Create a `.relay-env` file in the relay directory (or your project root) with your credentials:

```bash
cp lib/relay/.relay-env.example lib/relay/.relay-env
```

```
# .relay-env
RELAY_DB_USER=root
RELAY_DB_PASS=root
RELAY_DB_NAME=agent_relay
```

This file is gitignored — credentials never get committed.

### 3. Register agents

Every agent registers itself with a unique name:

```bash
python3 lib/relay/relay-msg register alice \
  --cwd /path/to/alice-workspace \
  --group backend \
  --transport local
```

| Flag | Description |
|------|-------------|
| `--group <name>` | Join a broadcast group (repeatable) |
| `--cwd <pattern>` | Substring matched against working directory for auto-detection |
| `--transport local\|remote` | `local` = direct MySQL, `remote` = proxied (see below) |
| `--alias <name>` | Alternate name this agent also receives messages for (repeatable) |

### 4. Send and receive

```bash
# Send to a specific agent
./relay-msg send alice "PR #37 is ready to merge"

# Send to a group
./relay-msg send backend "Deploy complete"

# Broadcast to all
./relay-msg send all "Going offline for maintenance"

# Check for unread messages (marks as read)
./relay-msg check

# Peek without marking as read
./relay-msg check --peek

# View full history
./relay-msg check --history
```

### 5. Set up auto-check (optional)

For agents that support hooks or startup scripts, auto-check on every prompt so incoming messages appear automatically.

**Claude Code** — add to `.claude/settings.json`:
```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 lib/relay/relay-msg check 2>/dev/null || true"
          }
        ]
      }
    ]
  }
}
```

**Cron / polling** — check every N seconds:
```bash
# In a crontab or background loop
* * * * * python3 /path/to/relay-msg check 2>/dev/null
```

**Custom agents** — call from your agent's message loop:
```python
import subprocess
result = subprocess.run(
    ["python3", "lib/relay/relay-msg", "check"],
    capture_output=True, text=True
)
if result.stdout.strip():
    # Feed messages into the agent's context
    print(result.stdout)
```

## Commands

| Command | Description |
|---------|-------------|
| `relay-msg send <target> <message>` | Send to an agent, group, or `all` |
| `relay-msg check` | Read unread messages (marks as read) |
| `relay-msg check --peek` | Read without marking as read |
| `relay-msg check --history` | Show all messages including read |
| `relay-msg register <name> [opts]` | Register or update an agent |
| `relay-msg unregister <name>` | Remove an agent |
| `relay-msg list` | List all agents, groups, and aliases |

## Identity Detection

When an agent runs a command, identity is resolved in order:

1. `RELAY_IDENTITY` env var — always wins
2. CWD pattern matching against registered agents' `cwd_pattern`
3. Falls back to `"default"`

## Remote Transport

For agents in VMs or containers without direct MySQL access, register with `--transport remote` and configure a proxy:

```
# In .relay-env
RELAY_TRANSPORT=remote
RELAY_PROXY_CMD=ssh myhost mysql
```

The proxy command receives the full `mysql -u ... -e '...'` invocation. If it contains `{}`, the MySQL command replaces the placeholder; otherwise it's appended.

## Environment Variables

All configurable via `.relay-env` file or environment variables (env vars take precedence).

| Variable | Default | Description |
|----------|---------|-------------|
| `RELAY_DB_USER` | `root` | MySQL user |
| `RELAY_DB_PASS` | `root` | MySQL password |
| `RELAY_DB_NAME` | `agent_relay` | Database name |
| `RELAY_IDENTITY` | *(auto-detect)* | Force agent identity |
| `RELAY_TRANSPORT` | `local` | `local` or `remote` |
| `RELAY_PROXY_CMD` | *(none)* | Proxy command for remote transport |

## Database

Four tables, auto-created on first use:

| Table | Purpose |
|-------|---------|
| `relay_agents` | Registered agents (name, transport, cwd_pattern) |
| `relay_agent_groups` | Agent-to-group memberships |
| `relay_agent_aliases` | Alternate names an agent responds to |
| `relay_messages` | Message queue with read tracking |

Messages are never deleted — marked as read via `read_at` timestamp.

## Requirements

- Python 3.8+
- MySQL or MariaDB (local or accessible via proxy)
- `mysql` CLI client (for local transport)
