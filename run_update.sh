#!/bin/zsh
set -euo pipefail
export NVM_DIR="$HOME/.nvm"
if [ -s "$NVM_DIR/nvm.sh" ]; then
  . "$NVM_DIR/nvm.sh"
  nvm use 22.12.0 >/dev/null || true
fi
export PATH="/Users/guoxl/.nvm/versions/node/v22.12.0/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export OPENCLAW_NODE="/Users/guoxl/.nvm/versions/node/v22.12.0/bin/node"
export OPENCLAW_BIN="/Users/guoxl/.nvm/versions/node/v22.12.0/bin/openclaw"
cd /Users/guoxl/.openclaw/war_timeline
/usr/bin/python3 /Users/guoxl/.openclaw/war_timeline/update_timeline.py --push >> /Users/guoxl/.openclaw/war_timeline/logs/cron.log 2>&1
