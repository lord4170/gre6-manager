#!/usr/bin/env bash
set -Eeuo pipefail
if (( EUID != 0 )); then
  echo 'ERROR: Run sudo bash install.sh' >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo 'ERROR: python3 not installed. Install: apt update && apt install python3' >&2
  exit 1
fi
if ! command -v ip >/dev/null 2>&1; then
  echo 'ERROR: iproute2 not installed. Install: apt update && apt install iproute2' >&2
  exit 1
fi
if ! command -v systemctl >/dev/null 2>&1; then
  echo 'ERROR: systemd is required' >&2
  exit 1
fi
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/gre6ctl" install
