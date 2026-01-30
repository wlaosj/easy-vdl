# easy-vdl 统一视频下载平台

**软件作者：bigv**  
**支持架构：x86设备**  
**电报交流群：** https://t.me/+7jcTMePlNVwwZjg1

---

## 简介

easy-vdl 是一款支持多平台的视频解析与下载可视化平台。内置视频订阅系统、直播订阅系统、批量下载、Emby/Jellyfin 元数据自动生成、核显硬件加速转码播放，界面美观，操作简单。

**支持平台：** 抖音、小红书、YouTube、Bilibili、TikTok、网易云、推特、ins等其他平台  
**支持订阅：** 博主订阅、合集订阅、点赞列表订阅（抖音）

---

## Docker 一键安装

```bash
docker run -d -p 888:80 \
  --memory=4g \
  --memory-swap=4g \
  --device=/dev/dri:/dev/dri \
  -v /mnt/easy-vdl/downloads:/app/downloads \
  -v /mnt/easy-vdl/logs:/app/logs \
  -v /mnt/easy-vdl/database:/app/database \
  -e EASY_VDL_PORT=80 \
  -e PUID=1000 \
  -e PGID=100 \
  -e EASY_VDL_ADMIN_USERNAME=admin \
  -e EASY_VDL_ADMIN_PASSWORD=admin123456 \
  qq918652593/easy-vdl:latest
```

**访问地址：** `http://服务器IP:888`

**环境变量说明：**
- `EASY_VDL_PORT`：容器内部端口，默认80
- `PUID`/`PGID`：用户权限，解决数据库权限问题（可选）
- `EASY_VDL_ADMIN_USERNAME`：管理员用户名（可选）
- `EASY_VDL_ADMIN_PASSWORD`：管理员密码（可选）
- `SNIFFER_LICENSE_KEY`：高级功能密钥（可选）

**目录挂载：**
- `/app/downloads` - 视频下载目录
- `/app/logs` - 日志目录
- `/app/database` - 数据库目录

> **内存建议：**
> - 轻量使用（订阅数量较少、偶尔解析下载）：可以将 `--memory` / `mem_limit` 调整为 `2g`。  
> - 中重度使用（约 50 个以上订阅、经常进行批量检测/批量同步）：推荐使用 `4g`，以保证浏览器嗅探和数据库在高负载场景下更稳定。

**硬件加速（可选）：**
- 添加 `--device=/dev/dri:/dev/dri` 启用 Intel 核显硬件加速
- 支持 Intel 第 6 代（Skylake）及更新的核显和 Intel Arc 系列
- 播放器会显示 `qsv`、`vaapi` 或 `cpu` 标识

### Docker Compose 部署

```yaml
version: '3.8'

services:
  easy-vdl:
    image: qq918652593/easy-vdl:latest
    container_name: easy-vdl
    ports:
      - "888:80"
    mem_limit: 4g
    memswap_limit: 4g
    devices:
      - /dev/dri:/dev/dri  # 硬件加速（可选）
    volumes:
      - /mnt/easy-vdl/downloads:/app/downloads
      - /mnt/easy-vdl/logs:/app/logs
      - /mnt/easy-vdl/database:/app/database
    environment:
      - EASY_VDL_PORT=80
      - PUID=1000
      - PGID=100
      - EASY_VDL_ADMIN_USERNAME=admin
      - EASY_VDL_ADMIN_PASSWORD=admin123456
      - TZ=Asia/Shanghai
    restart: unless-stopped
```

启动命令：在 `docker-compose.yml` 文件所在目录执行 `docker-compose up -d`

---

## 特色功能

### 多平台订阅
- 支持抖音、小红书、YouTube、Bilibili、TikTok 博主订阅
- 支持抖音、YouTube、Bilibili 合集订阅
- 支持抖音点赞列表订阅
- 自动检测新内容并下载

### API Token 认证
- 创建和管理 API Token，用于外部应用调用
- 支持过期时间、启用/禁用、重新生成
- 适用于浏览器插件、iOS 快捷指令、命令行工具等

### 浏览器插件
- 一键下载，无需手动输入 URL
- 自动识别平台（抖音、小红书、YouTube、Bilibili）
- 使用 API Token 安全认证
- 下载地址：https://github.com/wlaosj/easy-vdl/releases

### 其他功能
- 智能缓存系统，批量解析加速
- 自动生成 Emby/Jellyfin 元数据（NFO 文件）
- Intel 核显硬件加速转码播放
- 现代化 Web UI，支持移动端访问

---

## 快速使用

1. 启动容器后访问 `http://服务器IP:888`
2. 首次访问如未设置管理员账号，系统会引导设置
3. 输入视频链接一键解析下载，或在"订阅"页面添加博主自动下载
4. 在"设置" → "API Token 管理"中创建 Token，用于浏览器插件或 API 调用

**API 调用示例：**
```bash
curl -X POST "http://your-server:port/api/dyd/download" \
  -H "X-API-Token: your_token_here" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.douyin.com/video/xxx", "generate_nfo": true}'
```

**支持的 API：**
- 抖音：`POST /api/dyd/download`
- 小红书：`POST /api/xhs/download`
- YouTube/Bilibili：`POST /api/ytd/download`

---

## 技术支持

- **电报交流群：** https://t.me/+7jcTMePlNVwwZjg1
- **GitHub Releases：** https://github.com/wlaosj/easy-vdl/releases

---

快来体验 easy-vdl 带来的极致视频下载体验吧！
