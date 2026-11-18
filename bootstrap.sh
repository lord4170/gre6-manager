#!/usr/bin/env bash
set -Eeuo pipefail

# Example: curl -fsSL https://raw.githubusercontent.com/USER/gre6-manager/main/bootstrap.sh | sudo bash
REPO="${GRE6_REPO:-lord4170/gre6-manager}"
REF="${GRE6_REF:-main}"
if [[ ! "$REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] ||
   [[ ! "$REF" =~ ^[A-Za-z0-9._/-]+$ ]] ||
   [[ "$REF" == *..* ]]; then
  echo "ERROR: Invalid GRE6_REPO or GRE6_REF." >&2
  exit 1
fi
if (( EUID != 0 )); then
  echo "ERROR: Run with sudo (e.g. curl ... | sudo bash)." >&2
  exit 1
fi
for tool in curl python3 ip systemctl mktemp; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "ERROR: Missing $tool. Install prerequisites: python3 iproute2 curl systemd" >&2
    exit 1
  fi
done

WORKDIR="$(mktemp -d)"
trap 'rm -rf -- "$WORKDIR"' EXIT
BASE="https://raw.githubusercontent.com/${REPO}/${REF}"
echo "Downloading GRE6 Manager from ${REPO} (${REF})..."
curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
  --retry 3 --connect-timeout 15 --max-time 120 \
  "${BASE}/gre6ctl" -o "${WORKDIR}/gre6ctl"
curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
  --retry 3 --connect-timeout 15 --max-time 120 \
  "${BASE}/install.sh" -o "${WORKDIR}/install.sh"

python3 -m py_compile "${WORKDIR}/gre6ctl"
echo "Installing..."
(cd "$WORKDIR" && bash ./install.sh)
echo "Opening management menu..."
gre6ctl menu
