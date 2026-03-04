#!/bin/zsh
set -euo pipefail
PLIST_SRC="/Users/guoxl/.openclaw/war_timeline/com.guoxl.war.timeline.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.guoxl.war.timeline.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST_SRC" "$PLIST_DST"
launchctl bootout gui/$(id -u) com.guoxl.war.timeline >/dev/null 2>&1 || true
launchctl bootstrap gui/$(id -u) "$PLIST_DST"
launchctl enable gui/$(id -u)/com.guoxl.war.timeline
launchctl kickstart -k gui/$(id -u)/com.guoxl.war.timeline
echo "installed: $PLIST_DST"
launchctl print gui/$(id -u)/com.guoxl.war.timeline | sed -n '1,80p'
