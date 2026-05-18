#!/bin/bash
# 生产环境构建脚本

set -e

echo "🚀 开始构建 Easy-VDL Frontend v2..."

# 安装依赖
echo "📦 安装依赖..."
npm install

# 构建生产版本
echo "🔨 构建生产版本..."
npm run build

echo "✅ 构建完成！输出目录: dist/"
