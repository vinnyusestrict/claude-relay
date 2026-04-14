# Claude Relay

Inter-agent messaging relay for Claude Code sessions. Agents register themselves dynamically — no hardcoded peer lists.

## Setup

Requires local MySQL/MariaDB. Tables are auto-created on first use.

```bash
# Default connection (root:root @ strictwp_local)
export RELAY_DB_USER=root
export RELAY_DB_PASS=root
export RELAY_DB_NAME=strictwp_local
```

## Agent Registration

```bash
# Register an agent with group membership and CWD auto-detection
./relay-msg register cody --group dash --cwd strictwp-cody --transport local
./relay-msg register cowork --group dash --cwd strictwp-cowork --transport remote
./relay-msg register cathy --group mkt --cwd wp_strictwp_mkt-cathy --transport local
./relay-msg register carl --group dash --cwd strictwp-carl --transport local

# List registered agents
./relay-msg list

# Remove an agent
./relay-msg unregister oldagent
```

## Messaging

```bash
# Send to a specific agent
./relay-msg send cody "PR #37 is ready to merge"

# Send to a group (fans out to all members except sender)
./relay-msg send dash "Deploy complete on prod"

# Broadcast to all agents
./relay-msg send all "Going offline for maintenance"

# Check for unread messages (marks them as read)
./relay-msg check

# Peek at unread without marking as read
./relay-msg check --peek

# View full message history
./relay-msg check --history
```

## Identity Detection

The relay auto-detects which agent is running, in this order:

1. `RELAY_IDENTITY` env var (always wins)
2. CWD pattern matching against registered agents' `cwd_pattern`
3. Fallback: `gh` CLI available → `cody`, otherwise → `cowork`

## Integration as Submodule

```bash
git submodule add https://github.com/vinnyusestrict/claude-relay.git lib/relay
```

Then update hooks to point to `lib/relay/relay-msg` instead of `bin/relay-msg`.

## Transport

- `local` — agent runs on the Mac, connects to MySQL directly
- `remote` — agent runs in a VM, routes MySQL commands through `bin/run-cmd local`
