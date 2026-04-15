# Claude Relay

Inter-agent messaging relay for [Claude Code](https://claude.ai/code) sessions. Agents register themselves dynamically — no hardcoded peer lists.

## Setup

Requires local MySQL/MariaDB. Tables are auto-created on first use.

```bash
# Default connection (override with env vars)
export RELAY_DB_USER=root
export RELAY_DB_PASS=root
export RELAY_DB_NAME=claude_relay   # default database name
```

Create the database if it doesn't exist:
```bash
mysql -u root -proot -e "CREATE DATABASE IF NOT EXISTS claude_relay"
```

## Agent Registration

```bash
# Register an agent with group membership, CWD auto-detection, and aliases
./relay-msg register alice --group backend --cwd my-project-alice --transport local
./relay-msg register bob --group backend --cwd my-project-bob --transport remote --alias robert
./relay-msg register carol --group frontend --cwd my-project-carol --transport local

# List registered agents
./relay-msg list

# Remove an agent
./relay-msg unregister oldagent
```

### Options

| Flag | Description |
|------|-------------|
| `--group <name>` | Add agent to a named group (repeatable) |
| `--cwd <pattern>` | Substring matched against CWD for auto-detection |
| `--transport local\|remote` | `local` = direct MySQL, `remote` = proxied via `RELAY_PROXY_CMD` |
| `--alias <name>` | Legacy or alternate name this agent also receives messages for (repeatable) |

## Messaging

```bash
# Send to a specific agent
./relay-msg send alice "PR #37 is ready to merge"

# Send to a group (fans out to all members except sender)
./relay-msg send backend "Deploy complete"

# Broadcast to all registered agents
./relay-msg send all "Going offline for maintenance"

# Check for unread messages (marks them as read)
./relay-msg check

# Peek at unread without marking as read
./relay-msg check --peek

# View full message history
./relay-msg check --history
```

## Identity Detection

The relay auto-detects which agent is running, in priority order:

1. `RELAY_IDENTITY` env var (always wins)
2. CWD pattern matching against registered agents' `cwd_pattern`
3. Falls back to `"default"`

## Integration

### As a Git submodule

```bash
git submodule add https://github.com/vinnyusestrict/claude-relay.git lib/relay
```

### Claude Code hook (auto-check on every prompt)

Add to your project's `.claude/settings.json`:

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

## Remote Transport

For agents running in VMs or containers that can't reach MySQL directly, set `--transport remote` during registration and configure a proxy command:

```bash
export RELAY_PROXY_CMD="python3 /path/to/run-cmd local"
```

The proxy command receives the full `mysql ...` invocation as an argument. If it contains `{}`, the MySQL command replaces the placeholder; otherwise it's appended.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RELAY_DB_USER` | `root` | MySQL user |
| `RELAY_DB_PASS` | `root` | MySQL password |
| `RELAY_DB_NAME` | `claude_relay` | Database name |
| `RELAY_IDENTITY` | (auto) | Force agent identity |
| `RELAY_PROXY_CMD` | (none) | Command to proxy MySQL for remote agents |

## Database Schema

Auto-created on first use:

- `relay_agents` — registered agents (name, transport, cwd_pattern)
- `relay_agent_groups` — agent-to-group memberships
- `relay_agent_aliases` — alternate names an agent responds to
- `relay_messages` — message queue with read tracking
