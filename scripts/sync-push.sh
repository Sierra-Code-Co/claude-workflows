#!/usr/bin/env bash
# sync-push.sh — apply repo dotfiles INTO ~/.claude/* on this machine.
#
# Run this after `git pull` to update ~/.claude/* from the latest repo state.
# Idempotent — safe to run repeatedly.
#
# This is a thin wrapper around new-machine.sh that just reapplies symlinks.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/new-machine.sh"
