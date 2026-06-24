#!/bin/bash
# 全量同步到 GitHub：更新天数 → 提交所有改动 → 推送
set -e

cd "$(dirname "$0")"

# 计算持续维护天数（自 2025-06-27）
FIRST_RELEASE_EPOCH=1750982400
NOW_EPOCH=$(date +%s)
DAYS=$(( (NOW_EPOCH - FIRST_RELEASE_EPOCH) / 86400 ))
echo "📅 已持续维护 $DAYS 天"

# 更新 README 中的天数占位符
sed -i "s/已持续维护-[0-9X]*天/已持续维护-${DAYS}天/" README.md

# 提交所有改动并推送
git add -A
git commit -m "chore: sync $(date '+%Y-%m-%d %H:%M')" 2>/dev/null || echo "ℹ️  无改动，跳过提交"
git push

echo "✅ 同步完成"
