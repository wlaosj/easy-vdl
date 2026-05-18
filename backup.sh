#!/bin/bash
# 强制切换到脚本所在目录 (确保备份的是项目而不是运行时的 CWD)
cd "$(dirname "$0")" || exit 1

# 设置备份存储目录 (存放在项目上一级，即 /mnt/user/appdata/xing/easy-vdl-backups/)
BACKUP_DIR="../easy-vdl-backups"
# 获取当前时间戳
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
# 固定项目名
PROJECT_NAME="easy-vdl"
# 自定义后缀（优先使用第1个参数；未提供时可交互输入）
CUSTOM_SUFFIX="$1"
if [ -z "$CUSTOM_SUFFIX" ] && [ -t 0 ]; then
    read -r -p "请输入备份后缀(可留空): " CUSTOM_SUFFIX
fi
# 文件名安全处理：支持中文，仅替换文件名非法字符
# 替换: / \ : * ? " < > | 以及换行
SAFE_SUFFIX=$(echo "$CUSTOM_SUFFIX" \
    | tr -d '\r\n' \
    | sed 's/[\/\\:*?"<>|]/_/g' \
    | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' \
    | tr ' ' '_')
SUFFIX_PART=""
if [ -n "$SAFE_SUFFIX" ]; then
    SUFFIX_PART="_${SAFE_SUFFIX}"
fi
# 压缩文件名
FILENAME="${PROJECT_NAME}_backup_${TIMESTAMP}${SUFFIX_PART}.tar.gz"

echo "🚀 开始全量备份项目: $PROJECT_NAME ..."

# 创建备份目录
mkdir -p "$BACKUP_DIR"

# 执行打包压缩
# 现在仅排除 downloads, logs, database 和备份目录本身
tar -czf "$BACKUP_DIR/$FILENAME" \
    --exclude="downloads" \
    --exclude="logs" \
    --exclude="database" \
    --exclude="easy-vdl-backups" \
    .

if [ $? -eq 0 ]; then
    echo "✅ 备份成功！"
    echo "📦 文件位置: $BACKUP_DIR/$FILENAME"
    echo "📏 文件大小: $(du -h "$BACKUP_DIR/$FILENAME" | cut -f1)"
else
    echo "❌ 备份失败，请检查硬盘空间或权限。"
    exit 1
fi
