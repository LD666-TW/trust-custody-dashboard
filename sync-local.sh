#!/bin/zsh
# 把 GitHub 上通過檢查的新月份資料同步到這台電腦。
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
repo_dir="$(cd -- "${0:A:h}" && pwd -P)"
cd "$repo_dir"
git pull --quiet --ff-only origin main
print "$(date '+%Y-%m-%d %H:%M:%S') 本機看板資料已同步；目前月份：$(python3 -c 'import json; print(json.load(open("public/data/index.json"))["latest"])')"
