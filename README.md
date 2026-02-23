# Easy-vdl 综合直播视频订阅解析下载器

**软件作者：bigv**  
**支持架构：x86设备**  
**电报交流群：** https://t.me/+7jcTMePlNVwwZjg1

---

## 简介

easy-vdl 是一款支持多平台的视频解析下载、视频订阅、直播订阅的可视化平台。内置博主订阅系统、直播订阅系统、批量下载、Emby/Jellyfin 元数据自动生成、核显硬件加速转码播放，界面美观，操作简单。

**支持平台：** 抖音、小红书、YouTube、Bilibili、TikTok、网易云、推特、ins等其他平台  

**支持视频订阅：**
- 抖音：博主、合集、点赞列表
- YouTube：博主、播放列表、Shorts短视频
- Bilibili：UP主、合集
- TikTok：博主
- 小红书：博主

**支持直播订阅：** 抖音直播、B站直播、小红书直播、虎牙直播等，更多平台陆续增加中

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
- `PUID`/`PGID`：用户权限，解决数据库权限问题（可选，默认1000/100）
- `EASY_VDL_ADMIN_USERNAME`：管理员用户名（可选）
- `EASY_VDL_ADMIN_PASSWORD`：管理员密码（可选）
- `SNIFFER_LICENSE_KEY`：高级功能密钥（可选）
- `TZ`：时区设置（可选，如 `Asia/Shanghai`）

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
- **抖音**：博主订阅、合集订阅、点赞列表订阅
- **YouTube**：频道订阅、播放列表订阅、Shorts短视频订阅
- **Bilibili**：UP主订阅、合集订阅
- **TikTok**：博主订阅
- **小红书**：博主订阅
- 自动检测新内容并下载，支持批量同步历史视频

### API Token 认证
- 创建和管理 API Token，用于外部应用调用
- 支持过期时间、启用/禁用、重新生成
- 适用于浏览器插件、iOS 快捷指令、命令行工具等
- **注意**：部分接口仅支持 JWT 认证，部分接口需要系统授权（高级版功能）

### 浏览器插件
- 一键下载，无需手动输入 URL
- 自动识别平台（抖音、小红书、YouTube、Bilibili）
- 使用 API Token 安全认证
- 下载地址：https://github.com/wlaosj/easy-vdl/releases

### Telegram Bot 支持
- 通过 Telegram Bot 远程管理订阅和下载
- 支持直接发送链接下载视频
- 支持直接发送视频/图片到 Bot 自动转存到本地
- 支持添加订阅、查看订阅列表、查看直播列表
- 支持系统状态查询、服务重启等管理功能
- 转存功能需要**高级版授权**，且仅允许 `Chat ID` 白名单用户使用
- 转存为静默模式：仅落盘，不进入下载任务列表
- 转存大小限制：内置 Telethon MTProto 代理直连底层，已永久突破 20MB 枷锁，最高支持转存 **2GB (2000MB)** 以内的大文件
- 转存目录：`/app/downloads/telegram-inbox/YYYYMMDD/<chat_id>/`
- 命名规则：优先使用消息 caption（视频下方标题），回退到 Telegram `file_unique_id`
- 在"设置" → "Telegram Bot"中配置 Bot Token 和 Chat ID

### 直播录制
- 支持多平台直播自动录制
- 实时监控直播间状态，开播自动开始录制
- 支持录制质量设置和存储管理
- 自动检测直播结束并保存录制文件

### 其他功能
- **智能缓存系统**：批量解析加速，减少重复请求
- **数据备份**：支持订阅数据、配置数据一键备份和恢复
- **Cookie 管理**：统一管理各平台 Cookie，支持自动刷新
- **通知系统**：支持多种通知方式，及时了解下载和订阅状态
- **WebSocket 实时推送**：实时获取下载进度和系统状态
- **自动生成元数据**：Emby/Jellyfin 元数据（NFO 文件）自动生成
- **硬件加速**：Intel 核显硬件加速转码播放
- **现代化 Web UI**：美观界面，支持移动端访问

---

## 快速使用

1. **启动容器**后访问 `http://服务器IP:888`
2. **首次访问**如未设置管理员账号，系统会引导设置（或通过环境变量 `EASY_VDL_ADMIN_USERNAME` 和 `EASY_VDL_ADMIN_PASSWORD` 预设）
3. **下载视频**：在首页输入视频链接一键解析下载
4. **添加订阅**：在"订阅"页面添加博主或合集，系统会自动检测新内容并下载
5. **配置 API Token**：在"设置" → "API Token 管理"中创建 Token，用于浏览器插件或 API 调用
6. **配置 Telegram Bot**（可选）：在"设置" → "Telegram Bot"中配置 Bot Token 和 Chat ID，实现远程管理
   - 可直接给 Bot 发送视频/图片进行转存（需高级授权 + 白名单 Chat ID）
   - 转存已由核心层的 MTProto 引擎接管，最高支持约 **2GB** 超大媒体文件（突破传统 Bot 的 20MB 枷锁）
7. **添加直播订阅**：在"直播"页面添加直播间，系统会自动监控并录制

**API 调用示例：**

使用 API Token 认证（推荐用于外部应用）：
```bash
curl -X POST "http://your-server:port/api/dyd/download" \
  -H "X-API-Token: your_token_here" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.douyin.com/video/xxx", "generate_nfo": true}'
```

> **提示**：推荐使用浏览器插件进行一键下载，无需手动调用 API。如需集成到其他应用，可在"设置" → "API Token 管理"中创建 Token 后使用。

---

## 技术支持

- **电报交流群：** https://t.me/+7jcTMePlNVwwZjg1
- **GitHub Releases：** https://github.com/wlaosj/easy-vdl/releases

---

快来体验 easy-vdl 带来的极致视频下载体验吧！
