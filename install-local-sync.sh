#!/bin/zsh
# 為目前使用者安裝每小時一次的本機 GitHub 同步。
set -euo pipefail
repo_dir="${0:A:h}"
alias_dir="$HOME/.trust-dashboard"
agent_dir="$HOME/Library/LaunchAgents"
agent_file="$agent_dir/chatgpt.trust-dashboard.sync.plist"
log_file="$HOME/Library/Logs/trust-dashboard-sync.log"
mkdir -p "$agent_dir" "$HOME/Library/Logs"
ln -sfn "$repo_dir" "$alias_dir"
cat > "$agent_file" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>chatgpt.trust-dashboard.sync</string>
  <key>ProgramArguments</key><array><string>${alias_dir}/sync-local.sh</string></array>
  <key>StartInterval</key><integer>3600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>${log_file}</string>
  <key>StandardErrorPath</key><string>${log_file}</string>
</dict></plist>
EOF
chmod +x "$repo_dir/sync-local.sh"
launchctl bootout "gui/$(id -u)" "$agent_file" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$agent_file"
print "已安裝本機每小時同步。紀錄：$log_file"
