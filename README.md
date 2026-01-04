# easy-vdl 统一视频下载平台<br>
<br>
**软件作者：bigv 支持x86设备**<br>
**电报交流群：https://t.me/+7jcTMePlNVwwZjg1    #反馈使用问题，交流更新日志 **<br>
<br>
---<br>
<br>
## 简介<br>
<br>
easy-vdl 是一款支持多平台的视频解析与下载可视化平台。内置订阅系统、批量下载、Emby/Jellyfin 元数据自动生成、核显硬件加速转码播放，界面美观，操作简单。<br><br>
支持平台：抖音、小红书、YouTube、Bilibili、TikTok、其他平台<br>
支持订阅：博主订阅、合集订阅、点赞列表订阅（抖音）<br>
<br>
---<br>
<br>
## Docker 一键安装<br>
<br>
<pre>
docker run -d -p 888:80 \<br>
  --memory=2g \<br>
  --memory-swap=2g \<br>
  --device=/dev/dri:/dev/dri \<br>
  -v /mnt/easy-vdl/downloads:/app/downloads \<br>
  -v /mnt/easy-vdl/logs:/app/logs \<br>
  -v /mnt/easy-vdl/database:/app/database \<br>
  -e EASY_VDL_PORT=80 \<br>
  -e PUID=1000 \<br>
  -e PGID=100 \<br>
  -e EASY_VDL_ADMIN_USERNAME=admin \<br>
  -e EASY_VDL_ADMIN_PASSWORD=admin123456 \<br>
  qq918652593/easy-vdl:latest<br>
</pre>
<br>
**访问地址**：`http://服务器IP:888`<br>
<br>
**环境变量说明**：<br>
- `EASY_VDL_PORT`：容器内部端口，默认80<br>
- `PUID`/`PGID`：用户权限，解决数据库权限问题（可选）<br>
- `EASY_VDL_ADMIN_USERNAME`：管理员用户名（可选）<br>
- `EASY_VDL_ADMIN_PASSWORD`：管理员密码（可选）<br>
- `COMMUNITY_API_KEY`：社区功能密钥（可选）<br>
- `SNIFFER_LICENSE_KEY`：高级功能密钥（可选）<br>
<br>
**目录挂载**：<br>
- `/app/downloads` - 视频下载目录<br>
- `/app/logs` - 日志目录<br>
- `/app/database` - 数据库目录<br>
<br>
**硬件加速**（可选）：<br>
- 添加 `--device=/dev/dri:/dev/dri` 启用 Intel 核显硬件加速<br>
- 支持 Intel 第 6 代（Skylake）及更新的核显和 Intel Arc 系列<br>
- 播放器会显示 `qsv`、`vaapi` 或 `cpu` 标识<br>
<br>
### Docker Compose 部署<br>
<br>
<pre>
version: '3.8'<br>
<br>
services:<br>
  easy-vdl:<br>
    image: qq918652593/easy-vdl:latest<br>
    container_name: easy-vdl<br>
    ports:<br>
      - "888:80"<br>
    mem_limit: 2g<br>
    memswap_limit: 2g<br>
    devices:<br>
      - /dev/dri:/dev/dri  # 硬件加速（可选）<br>
    volumes:<br>
      - /mnt/easy-vdl/downloads:/app/downloads<br>
      - /mnt/easy-vdl/logs:/app/logs<br>
      - /mnt/easy-vdl/database:/app/database<br>
    environment:<br>
      - EASY_VDL_PORT=80<br>
      - PUID=1000<br>
      - PGID=100<br>
      - EASY_VDL_ADMIN_USERNAME=admin<br>
      - EASY_VDL_ADMIN_PASSWORD=admin123456<br>
      - COMMUNITY_API_KEY=社区功能密钥（可选）<br>
      - SNIFFER_LICENSE_KEY=高级功能密钥（可选）<br>
      - TZ=Asia/Shanghai<br>
    restart: unless-stopped<br>
</pre>
<br>
启动命令：在 `docker-compose.yml` 文件所在目录执行 `docker-compose up -d`<br>
<br>
---<br>
<br>
## 特色功能<br>
<br>
### 多平台订阅<br>
- ✅ 支持抖音、小红书、YouTube、Bilibili、TikTok 博主订阅<br>
- ✅ 支持抖音、YouTube、Bilibili 合集订阅<br>
- ✅ 支持抖音点赞列表订阅<br>
- ✅ 自动检测新内容并下载<br>
<br>
### API Token 认证<br>
- ✅ 创建和管理 API Token，用于外部应用调用<br>
- ✅ 支持过期时间、启用/禁用、重新生成<br>
- ✅ 适用于浏览器插件、iOS 快捷指令、命令行工具等<br>
<br>
### 浏览器插件<br>
- ✅ 一键下载，无需手动输入 URL<br>
- ✅ 自动识别平台（抖音、小红书、YouTube、Bilibili）<br>
- ✅ 使用 API Token 安全认证<br>
- 📥 下载地址：https://github.com/wlaosj/easy-vdl/releases<br>
<br>
### 其他功能<br>
- ✅ 智能缓存系统，批量解析加速<br>
- ✅ 自动生成 Emby/Jellyfin 元数据（NFO 文件）<br>
- ✅ 支持多格式选择、字幕、封面下载<br>
- ✅ Intel 核显硬件加速转码播放<br>
- ✅ 现代化 Web UI，支持移动端访问<br>
<br>
---<br>
<br>
## 快速使用<br>
<br>
1. 启动容器后访问 `http://服务器IP:888`<br>
2. 首次访问如未设置管理员账号，系统会引导设置<br>
3. 输入视频链接一键解析下载，或在"订阅"页面添加博主自动下载<br>
4. 在"设置" → "API Token 管理"中创建 Token，用于浏览器插件或 API 调用<br>
<br>
**API 调用示例**：<br>
```bash<br>
curl -X POST "http://your-server:port/api/dyd/download" \<br>
  -H "X-API-Token: your_token_here" \<br>
  -H "Content-Type: application/json" \<br>
  -d '{"url": "https://www.douyin.com/video/xxx", "generate_nfo": true}'<br>
```<br>
<br>
**支持的 API**：<br>
- 抖音：`POST /api/dyd/download`<br>
- 小红书：`POST /api/xhs/download`<br>
- YouTube/Bilibili：`POST /api/ytd/download`<br>
<br>
---<br>
<br>
## 技术支持<br>
<br>
- **电报交流群**：https://t.me/+7jcTMePlNVwwZjg1<br>
- **GitHub Releases**：https://github.com/wlaosj/easy-vdl/releases<br>
<br>
---<br>
<br>
快来体验 easy-vdl 带来的极致视频下载体验吧！
