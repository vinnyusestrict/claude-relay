# Claude Relay

Inter-agent messaging relay for [Claude Code](https://claude.ai/code) sessions. Enables multiple Claude agents to send messages to each other across separate terminal sessions, Cowork VMs, or any environment where Claude Code runs.

## Quick Start

> **For Claude agents:** Your user has asked you to set up inter-agent messaging. Follow these steps exactly.

### 1. Install

From your project root:

```bash
git submodule add https://github.com/vinnyusestrict/claude-relay.git lib/relay
```

### 2. Configure the database

Claude Relay uses local MySQL/MariaDB. Create the database — tables are auto-created on first use:

```bash
mysql -u root -proot -e "CREATE DATABASE IF NOT EXISTS claude_relay"
```

Copy the example env file and edit it with your credentials:

```bash
cp lib/relay/.relay-env.example lib/relay/.relay-env
# Edit lib/relay/.relay-env with your DB credentials
```

Or place `.relay-env` in your project root (the relay checks both locations). The file is gitignored — credentials never get committed.

```
# .relay-env
RELAY_DB_USER=root
RELAY_DB_PASS=root
RELAY_DB_NAME=claude_relay
```

Environment variables still work and take precedence over the file.

### 3. Register this agent

Every agent must register itself with a unique name. Choose a name that identifies this session:

```bash
python3 lib/relay/relay-msg register <agent-name> \
  --cwd <unique-substring-of-working-directory> \
  --group <team-name> \
  --transport local
```

- `--cwd` enables auto-detection: the relay matches this substring against the working directory to identify which agent is running
- `--group` adds the agent to a named broadcast group (repeatable — an agent can be in multiple groups)
- `--transport local` means direct MySQL access; use `remote` if this agent runs in a VM without MySQL access
- `--alias <name>` adds an alternate name this agent also receives messages for (repeatable)

### 4. Set up the auto-check hook

Add to `.claude/settings.json` in your project so incoming messages appear on every prompt:

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

If your database name differs from the default (`claude_relay`), prefix the command:
```
RELAY_DB_NAME=my_db python3 lib/relay/relay-msg check 2>/dev/null || true
```

### 5. Verify

```bash
python3 lib/relay/relay-msg list    # see all registered agents
python3 lib/relay/relay-msg send <other-agent> "hello from <agent-name>"
```

## Commands

| Command | Description |
|---------|-------------|
| `relay-msg send <target> <message>` | Send a message to an agent, group, or `all` |
| `relay-msg check` | Read unread messages (marks them as read) |
| `relay-msg check --peek` | Read unread messages without marking as read |
| `relay-msg check --history` | Show all messages including already-read |
| `relay-msg register <name> [opts]` | Register or update an agent |
| `relay-msg unregister <name>` | Remove an agent |
| `relay-msg list` | List all registered agents, groups, and aliases |

### Sending

- **To an agent:** `relay-msg send alice "message"` — delivers to alice's inbox
- **To a group:** `relay-msg send backend "message"` — fans out to all group members except the sender
- **To all:** `relay-msg send all "message"` — broadcasts to every registered agent except the sender
- **To an alias:** `relay-msg send old-name "message"` — resolves to the agent that registered that alias

### Registration Options

| Flag | Description |
|------|-------------|
| `--group <name>` | Join a broadcast group (repeatable) |
| `--cwd <pattern>` | Substring for CWD-based identity auto-detection |
| `--transport local\|remote` | `local` = direct MySQL, `remote` = proxied |
| `--alias <name>` | Alternate name this agent receives messages for (repeatable) |

## Identity Detection

When an agent runs a relay command, identity is resolved in order:

1. `RELAY_IDENTITY` env var — always wins, set this if CWD detection is ambiguous
2. CWD pattern matching — compares working directory against each agent's registered `cwd_pattern`
3. Falls back to `"default"` — register your agent to avoid this

## Remote Transport

For agents in VMs or containers that cannot reach MySQL directly, register with `--transport remote` and set:

```bash
export RELAY_PROXY_CMD="python3 /path/to/proxy-script local"
```

The proxy command receives the full `mysql -u ... -e '...'` invocation as an argument. If the proxy command contains `{}`, the MySQL command replaces the placeholder; otherwise it is appended.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RELAY_DB_USER` | `root` | MySQL user |
| `RELAY_DB_PASS` | `root` | MySQL password |
| `RELAY_DB_NAME` | `claude_relay` | Database name |
| `RELAY_IDENTITY` | *(auto-detect)* | Force agent identity |
| `RELAY_PROXY_CMD` | *(none)* | Proxy command for remote transport |

## Database

Four tables, auto-created on first use:

| Table | Purpose |
|-------|---------|
| `relay_agents` | Registered agents (name, transport, cwd_pattern) |
| `relay_agent_groups` | Agent-to-group memberships |
| `relay_agent_aliases` | Alternate names an agent responds to |
| `relay_messages` | Message queue with read tracking (read_at timestamp) |

Messages are never deleted — they are marked as read via `read_at`. Use `check --history` to review past conversations.
