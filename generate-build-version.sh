#!/bin/bash
# 生成构建版本信息
BUILD_TIME="${BUILD_TIME:-$(date '+%Y-%m-%d %H:%M:%S')}"
BUILD_VERSION="${BUILD_VERSION:-v$(date '+%Y%m%d.%H%M%S')}"

# 确保data目录存在
mkdir -p data

cat > data/build-version.json << EOF
{
    "version": "$BUILD_VERSION",
    "build_time": "$BUILD_TIME"
}
EOF

echo "Generated build version: $BUILD_VERSION at $BUILD_TIME"
