#!/bin/bash
# 构建之前手动执行，就能保持arm和x86版本号一致，生成发布版本环境文件。x86/arm64 构建时读取同一个文件即可保持版本一致。

set -e

cd "$(dirname "$0")"

VERSION_FILE="${VERSION_FILE:-build-version.env}"
BUILD_TIME="${BUILD_TIME:-$(date '+%Y-%m-%d %H:%M:%S')}"
BUILD_VERSION="${BUILD_VERSION:-v$(date '+%Y%m%d.%H%M%S')}"

cat > "$VERSION_FILE" << EOF
BUILD_VERSION=$BUILD_VERSION
BUILD_TIME="$BUILD_TIME"
EOF

echo "Generated release version file: $VERSION_FILE"
echo "BUILD_VERSION=$BUILD_VERSION"
echo "BUILD_TIME=$BUILD_TIME"
