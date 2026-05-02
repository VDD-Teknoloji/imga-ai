#!/usr/bin/env bash
#
# Bootstrap Claude Code agent configuration for the imga deploy server.
#
# Idempotent — safe to re-run after pulling repo updates.
#
# Installs:
#   1. /opt/imga/.claude/settings.local.json     (gitignored, server-local)
#       - allow:   docker compose build/up/ps/logs/restart/exec on prod & staging
#       - deny:    down/stop/rm/kill on prod, prune, volume rm, rm -rf /opt|/var|/etc
#       - ask:     git push, git reset --hard, staging down/stop
#       - autoMode classifier rules pre-authorizing routine deploys, hard-stopping destructive ops
#       - PreToolUse hook auditing every Bash command
#   2. .gitignore entry for .claude/settings.local.json
#   3. /var/log/claude-agent/ writable by the deploy user (audit log destination)
#
# After running, settings take effect on the next prompt; hooks need a session
# restart or one-time `/hooks` open to register with the file watcher.

set -euo pipefail

REPO_DIR="/opt/imga"
CLAUDE_DIR="$REPO_DIR/.claude"
SETTINGS="$CLAUDE_DIR/settings.local.json"
AUDIT_DIR="/var/log/claude-agent"
AUDIT_LOG="$AUDIT_DIR/bash.log"
GITIGNORE="$REPO_DIR/.gitignore"
RUN_USER="${SUDO_USER:-${USER:-$(id -un)}}"

# --- Sanity: only run on the deploy server ---
if [[ ! -f "$REPO_DIR/infra/imga/production/docker-compose.yml" ]]; then
  echo "ERROR: $REPO_DIR/infra/imga/production/docker-compose.yml missing." >&2
  echo "       This script is for the imga deploy server only." >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq not found. Install it first: sudo apt-get install -y jq" >&2
  exit 1
fi

mkdir -p "$CLAUDE_DIR"

# --- 1) Write settings.local.json atomically ---
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

cat > "$TMP" <<'JSON'
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "permissions": {
    "allow": [
      "Bash(sudo docker compose -f /opt/imga/infra/imga/production/docker-compose.yml build:*)",
      "Bash(sudo docker compose -f /opt/imga/infra/imga/production/docker-compose.yml up:*)",
      "Bash(sudo docker compose -f /opt/imga/infra/imga/production/docker-compose.yml restart:*)",
      "Bash(sudo docker compose -f /opt/imga/infra/imga/production/docker-compose.yml ps:*)",
      "Bash(sudo docker compose -f /opt/imga/infra/imga/production/docker-compose.yml logs:*)",
      "Bash(sudo docker compose -f /opt/imga/infra/imga/production/docker-compose.yml top:*)",
      "Bash(sudo docker compose -f /opt/imga/infra/imga/production/docker-compose.yml config:*)",
      "Bash(sudo docker compose -f /opt/imga/infra/imga/production/docker-compose.yml exec:*)",
      "Bash(sudo docker compose -f /opt/imga/infra/imga/staging/docker-compose.yml build:*)",
      "Bash(sudo docker compose -f /opt/imga/infra/imga/staging/docker-compose.yml up:*)",
      "Bash(sudo docker compose -f /opt/imga/infra/imga/staging/docker-compose.yml restart:*)",
      "Bash(sudo docker compose -f /opt/imga/infra/imga/staging/docker-compose.yml ps:*)",
      "Bash(sudo docker compose -f /opt/imga/infra/imga/staging/docker-compose.yml logs:*)",
      "Bash(sudo docker compose -f /opt/imga/infra/imga/staging/docker-compose.yml top:*)",
      "Bash(sudo docker compose -f /opt/imga/infra/imga/staging/docker-compose.yml config:*)",
      "Bash(sudo docker compose -f /opt/imga/infra/imga/staging/docker-compose.yml exec:*)",
      "Bash(sudo docker ps:*)",
      "Bash(sudo docker images:*)",
      "Bash(sudo docker logs:*)",
      "Bash(sudo docker inspect:*)",
      "Bash(sudo docker stats:*)",
      "Bash(git pull:*)",
      "Bash(git fetch:*)",
      "Bash(git status:*)",
      "Bash(git log:*)",
      "Bash(git diff:*)",
      "Bash(git show:*)"
    ],
    "deny": [
      "Bash(sudo docker compose -f /opt/imga/infra/imga/production/docker-compose.yml down:*)",
      "Bash(sudo docker compose -f /opt/imga/infra/imga/production/docker-compose.yml stop:*)",
      "Bash(sudo docker compose -f /opt/imga/infra/imga/production/docker-compose.yml rm:*)",
      "Bash(sudo docker compose -f /opt/imga/infra/imga/production/docker-compose.yml kill:*)",
      "Bash(sudo docker system prune:*)",
      "Bash(sudo docker volume rm:*)",
      "Bash(sudo docker volume prune:*)",
      "Bash(sudo docker network rm:*)",
      "Bash(rm -rf /opt/imga:*)",
      "Bash(sudo rm -rf /opt/imga:*)",
      "Bash(sudo rm -rf /var:*)",
      "Bash(sudo rm -rf /etc:*)",
      "Bash(sudo rm -rf /home:*)",
      "Bash(git push --force:*)",
      "Bash(git push -f:*)"
    ],
    "ask": [
      "Bash(git push:*)",
      "Bash(git reset --hard:*)",
      "Bash(git clean -fd:*)",
      "Bash(sudo docker compose -f /opt/imga/infra/imga/staging/docker-compose.yml down:*)",
      "Bash(sudo docker compose -f /opt/imga/infra/imga/staging/docker-compose.yml stop:*)"
    ]
  },
  "autoMode": {
    "allow": [
      "$defaults",
      "On this host (the imga deploy server, /opt/imga), the routine deploy workflow is: `git pull origin main` followed by `sudo docker compose -f /opt/imga/infra/imga/{production,staging}/docker-compose.yml {build,up -d,ps,logs,restart,exec,top,config}` against the production and staging stacks. These compose subcommands on the imga prod and staging stacks are pre-authorized routine operations on this dedicated single-host deploy server — do not flag them as production deploys requiring re-authorization. The user has explicitly added them to the Bash permission allowlist."
    ],
    "soft_deny": [
      "$defaults",
      "Destructive subcommands on the imga PRODUCTION stack (down, stop, rm, kill) always require fresh user confirmation — even if Bash permission rules would permit them. The same applies to docker system prune, docker volume rm/prune, docker network rm, and any rm -rf under /opt/imga, /var, /etc, /home."
    ]
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "jq -r '\"[\\(now | strftime(\"%Y-%m-%dT%H:%M:%SZ\"))] [\\(.session_id // \"unknown\")] \\(.tool_input.command)\"' >> /var/log/claude-agent/bash.log 2>/dev/null || true"
          }
        ]
      }
    ]
  }
}
JSON

if ! jq empty "$TMP" 2>/dev/null; then
  echo "ERROR: generated settings JSON failed validation" >&2
  exit 1
fi

mv "$TMP" "$SETTINGS"
trap - EXIT
chmod 0644 "$SETTINGS"
echo "[1/3] Wrote $SETTINGS"

# --- 2) Update .gitignore ---
if [[ -f "$GITIGNORE" ]] && ! grep -qxF '.claude/settings.local.json' "$GITIGNORE"; then
  printf '\n# Claude Code per-server config (deploy-server-specific permissions)\n.claude/settings.local.json\n' >> "$GITIGNORE"
  echo "[2/3] Added .claude/settings.local.json to .gitignore"
else
  echo "[2/3] .gitignore already excludes .claude/settings.local.json (no change)"
fi

# --- 3) Audit log directory ---
if [[ ! -d "$AUDIT_DIR" ]]; then
  sudo mkdir -p "$AUDIT_DIR"
  sudo chown "$RUN_USER:$RUN_USER" "$AUDIT_DIR"
  sudo chmod 0750 "$AUDIT_DIR"
  echo "[3/3] Created $AUDIT_DIR (owner=$RUN_USER, mode=0750)"
else
  echo "[3/3] $AUDIT_DIR already exists (no change)"
fi

cat <<EOF

Done.

Effects:
  - Permission rules:  active on the next prompt.
                       (the settings watcher only registers .claude/ when a
                       settings file existed at session start).

Audit log:  $AUDIT_LOG
            tail -f "$AUDIT_LOG"

To uninstall: rm $SETTINGS  (rules disappear next session)
EOF
