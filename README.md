# easy-vdl 统一视频下载平台<br>
<br>
**软件作者：bigv **<br>
**支持x86设备（推荐），arm设备也编译了镜像，但是我没有设备测试，你们自行测试吧，不保证100%能用 **<br>
**电报交流群：https://t.me/+7jcTMePlNVwwZjg1 #反馈使用问题，交流更新日志 **<br>
<br>
---<br>
<br>
## 简介<br>
<br>
easy-vdl 是一款支持多平台（某音、某书、B某、YouTube、更多平台、多平台博主订阅功能、批量下载、文件管理）的视频解析与下载的可视化平台。内置智能缓存、批量下载、Emby/Jellyfin 元数据自动刮削生成、核显硬件加速转码播放，界面美观，操作简单，适合个人和媒体库用户。<br>
<br>
---<br>
<br>
## Docker 一键安装指令<br>
<br>
**桥接模式示例：**<br>
<pre>
docker run -d -p 888:80 \<br>
  --device=/dev/dri:/dev/dri \<br>
  -v /mnt/easy-vdl/downloads:/app/downloads \<br>
  -v /mnt/easy-vdl/logs:/app/logs \<br>
  -v /mnt/easy-vdl/database:/app/database \<br>
  -e EASY_VDL_PORT=80 \<br>
  -e PUID=1000 \<br>
  -e PGID=100 \<br>
  -e EASY_VDL_ADMIN_USERNAME=admin \<br>
  -e EASY_VDL_ADMIN_PASSWORD=admin123456 \<br>
  -e COMMUNITY_API_KEY=社区功能特权密匙 \<br>
  -e SNIFFER_LICENSE_KEY=内测功能特权密匙 \<br>
  qq918652593/easy-vdl:latest<br>
</pre>
<br>
**Host模式示例：**<br>
<pre>
docker run -d --network host \<br>
  --device=/dev/dri:/dev/dri \<br>
  -v /mnt/easy-vdl/downloads:/app/downloads \<br>
  -v /mnt/easy-vdl/logs:/app/logs \<br>
  -v /mnt/easy-vdl/database:/app/database \<br>
  -e EASY_VDL_PORT=888 \<br>
  -e PUID=1000 \<br>
  -e PGID=100 \<br>
  -e EASY_VDL_ADMIN_USERNAME=admin \<br>
  -e EASY_VDL_ADMIN_PASSWORD=admin123456 \<br>
  -e COMMUNITY_API_KEY=社区功能特权密匙 \<br>
  -e SNIFFER_LICENSE_KEY=内测功能特权密匙 \<br>
  qq918652593/easy-vdl:latest<br>
</pre>
<br>
<br>
**环境变量说明：**<br>
- `EASY_VDL_PORT`：容器内部UI端口，默认80，Host模式时指定访问端口<br>
- `PUID`：用户ID，可选，解决数据库权限问题，避免PostgreSQL启动失败<br>
- `PGID`：组ID，可选，配合PUID使用，确保文件权限正确<br>
- `EASY_VDL_ADMIN_USERNAME`：管理员用户名，可选，不设置时首次进入UI可图形化设置<br>
- `EASY_VDL_ADMIN_PASSWORD`：管理员密码，可选，不设置时首次进入UI可图形化设置<br>
- `COMMUNITY_API_KEY`：社区功能特权密匙，可选，用于获取社区功能<br>
- `SNIFFER_LICENSE_KEY`：内测功能特权密匙，可选，用于获取内测功能<br>
- 常见PUID/PGID值（来自网络，具体请自测）：Unraid(1000:100)、飞牛(1000:1001)、群晖(1026:100)、威联通(1000:1000)<br>
- 具体可通过 `id 用户名` 命令查看当前用户的UID和GID<br>
- 不设置PUID/PGID时使用系统默认用户ID，适合大部分用户<br>
- 在遇到数据库权限问题时可按需要设置PUID/PGID<br>
<br>
**目录挂载说明：**<br>
- `/app/downloads`：视频下载及管理目录，存储所有下载的视频文件<br>
- `/app/logs`：日志目录，包含应用运行日志，便于排查问题<br>
- `/app/database`：数据库目录，包含PostgreSQL数据库文件和Chrome用户数据<br>
- 建议将所有目录挂载到本地，确保数据持久化和便于管理<br>
<br>
**硬件加速说明（x86 架构）：**<br>
- `--device=/dev/dri:/dev/dri`：启用核显硬件加速（可选，仅 x86 架构支持）<br>
- **Intel 核显**：✅ 明确支持，支持 Intel 第 6 代（Skylake）及更新的核显（HD 500/600/700/UHD 系列）和 Intel Arc 系列独立显卡<br>
- **AMD 核显**：⚠️ 可能支持但未测试，镜像已包含 `mesa-va-drivers` 和 AMD DRM 库，理论上支持较新的 AMD APU（如 Radeon 600/700 系列），但未经过实际测试验证，如有 AMD 设备可自行测试<br>
- ARM 架构不支持标准 VA-API 硬件加速，无需添加此参数<br>
- **使用说明**：硬件加速仅在随机的播放视频器中生效，可在播放器的右上角切换画质；画质选择器会实时显示当前使用的转码技术标识：`qsv`（Intel Quick Sync Video 硬件加速）、`vaapi`（VA-API 硬件加速）或 `cpu`（CPU 软件转码），方便确认硬件加速是否生效<br>
- **验证方法**：在播放器中切换画质时，如果硬件加速正常工作，画质选项后会显示 `qsv` 或 `vaapi` 标识（如"720p (qsv)"），且 CPU 占用会明显降低；如果显示 `cpu` 则表示使用软件转码<br>
<br>

---<br>
<br>
## Docker Compose 部署示例<br>
<br>
<pre>
version: '3.8'<br>
<br>
services:<br>
  easy-vdl:<br>
    image: qq918652593/easy-vdl<br>
    container_name: easy-vdl<br>
    ports:<br>
      - "888:80"  # 主服务端口<br>
    devices:<br>
      - /dev/dri:/dev/dri  # Intel 核显硬件加速（x86 架构，可选）<br>
    volumes:<br>
      - /mnt/easy-vdl/easy-vdl:/app/downloads  # 下载文件目录<br>
      - /mnt/easy-vdl/easy-vdl/logs:/app/logs  # 日志目录<br>
      - /mnt/easy-vdl/easy-vdl/database:/app/database  # 数据库目录<br>
    environment:<br>
      # UI端口配置<br>
      - EASY_VDL_PORT=80  # 容器内部UI端口<br>
      # 用户权限配置（可选，仅在遇到数据库权限问题时需要设置）<br>
      - PUID=1000  # 用户ID，对应宿主机用户<br>
      - PGID=100   # 组ID，对应宿主机用户组<br>
      # 管理员账号配置（可选，不设置时首次进入UI可图形化设置）<br>
      - EASY_VDL_ADMIN_USERNAME=admin  # 管理员用户名<br>
      - EASY_VDL_ADMIN_PASSWORD=admin123456  # 管理员密码<br>
      # 社区功能配置<br>
      - COMMUNITY_API_KEY=加群获取key  #社区功能特权密匙<br>
      # 内测功能特权配置<br>
      - SNIFFER_LICENSE_KEY=发电用户可以获取密匙  #内测功能特权密匙 <br>
      - TZ=Asia/Shanghai<br>
    restart: unless-stopped<br>
</pre>
<br>
- 可根据实际需求修改端口和挂载目录<br>
- 启动命令：在 `docker-compose.yml` 文件所在目录执行 `docker-compose up -d` 即可<br>
<br>
<br>
---<br>
<br>
## 主要特性<br>
<br>
- 支持某音、某书、YouTube、B某等主流平台视频解析与下载<br>
- 智能缓存系统，批量解析加速<br>
- 自动生成 Emby/Jellyfin 元数据，下载即用<br>
- 支持多格式选择、字幕、封面下载<br>
- 简洁美观的 Web UI，支持移动端访问<br>
<br>
---<br>
<br>
## 使用说明<br>
<br>
1. 启动容器后，访问 `http://服务器IP:888` 进入 Web UI<br>
2. 首次访问时，如未设置管理员账号，系统会引导进行图形化账号设置<br>
3. 按提示输入视频链接，一键解析下载<br>
4. 支持批量任务、缓存加速、媒体库自动识别<br>
5. 所有配置和下载内容、日志、数据库均保存在挂载目录下，便于管理和数据持久化<br>
<br>
---<br>
<br>
快来体验 easy-vdl 带来的极致视频下载体验吧！

