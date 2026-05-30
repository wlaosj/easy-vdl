# 🚀 Easy-VDL 综合直播视频订阅解析下载器

![Docker Pulls](https://img.shields.io/docker/pulls/qq918652593/easy-vdl?style=flat-square&color=orange)
![Platform Support](https://img.shields.io/badge/Platform-x86_64%20%7C%20ARM64-blue?style=flat-square)
[![Telegram Group](https://img.shields.io/badge/Telegram-Group-blue?logo=telegram&style=flat-square)](https://t.me/+7jcTMePlNVwwZjg1)

**一款集视频订阅、直播监控、自动录制、弹幕录制、无缝时间轴播放、GPU硬件加速转码与AI智能高光剪辑及媒体服务器联动的全能型可视化下载平台。**

[功能特点](#-功能特色) • [极速部署](#-极速部署) • [上手指南](#-三步上手指南) • [加入社区](#-加入社区)

---

## 🌟 功能特色

* **🎬 多平台视频订阅**：支持 **抖音**（博主/合集/点赞）、**YouTube**（频道/播放列表/Shorts）、**B站**（UP主/合集）、**小红书**、**TikTok**、**Instagram**、**X** 等平台自动检测更新并批量下载。
* **🔴 直播自动监控录制**：实时监控 **抖音**、**B站**、**小红书**、**虎牙** 等直播间状态，开播静默录制，停播自动转码保存。
* **🤖 AI 智能高光切片**：直播结束后基于弹幕热度与情感分析**自动截取高光片段**，接入大语言模型（如 DeepSeek）自动生成高能标题与剧情摘要，打包一键导出二剪素材。
* **🔔 智能通知推送**：支持 微信机器人、Telegram Bot、Server酱³、Bark (iOS)、电子邮件及 WebSocket 实时交互通知。
* **✈️ 突破枷锁的 Telegram 集成**：内置 MTProto 底层代理直连，**突破 Telegram 传统的 20MB 下载限制**，支持直接向 Bot 发送最大 **2GB** 媒体文件静默转存至本地。
* **🍿 完美联动 Emby/Jellyfin**：自动生成符合 Emby/Jellyfin 标准的 NFO 元数据与精美海报墙。
* **⚡ 硬件加速解码**：完美支持 Intel/AMD 核显（QSV/VAAPI）与 NVIDIA 显卡硬件加速，在网页端畅享丝滑转码与流畅播放。

---

## ⚡ 极速部署

支持 **x86_64** 与 **ARM64** 架构设备（如 Apple Silicon Mac、各类群晖/威联通/Unraid NAS 硬件）。

### 推荐：使用 Docker Compose 一键部署

在您存放数据的目录下创建 `docker-compose.yml`，复制以下内容并运行 `docker-compose up -d`：

```yaml
version: '3.8'

services:
  easy-vdl:
    # x86_64 设备使用 latest，ARM64 设备请改为 arm64 标签
    image: qq918652593/easy-vdl:latest
    container_name: easy-vdl
    ports:
      - "888:80"                      # 888 为外部访问端口，可按需修改
    mem_limit: 4g                     # 推荐 4G，小规模订阅可降为 2G
    mem_limit_swap: 4g
    # 【x86硬件加速，ARM设备请删除 devices/cap_add 块】
    devices:
      - /dev/dri:/dev/dri             # Intel/AMD 核显硬件加速映射
    cap_add:
      - PERFMON                       # GPU 仪表盘监控负载支持
    volumes:
      - ./downloads:/app/downloads    # 视频与媒体下载保存路径
      - ./logs:/app/logs              # 程序运行日志
      - ./database:/app/database      # 数据库与全局配置路径
    environment:
      - EASY_VDL_PORT=80
      - PUID=1000                     # 推荐修改为您宿主机用户的 UID/GID，防止出现 Permission denied 错误
      - PGID=100
      - EASY_VDL_ADMIN_USERNAME=admin # 预设管理员用户名
      - EASY_VDL_ADMIN_PASSWORD=admin123456 # 预设管理员密码
      - TZ=Asia/Shanghai
    restart: unless-stopped
```

#### 💡 传统的 Docker Run 部署指令

```bash
# x86_64（支持 Intel/AMD 硬件加速与 GPU 监控）
docker run -d --name easy-vdl -p 888:80 \
  --memory=4g --memory-swap=4g \
  --device=/dev/dri:/dev/dri \
  --cap-add PERFMON \
  -v $(pwd)/downloads:/app/downloads \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/database:/app/database \
  -e EASY_VDL_PORT=80 -e PUID=1000 -e PGID=100 -e TZ=Asia/Shanghai \
  -e EASY_VDL_ADMIN_USERNAME=admin -e EASY_VDL_ADMIN_PASSWORD=admin123456 \
  --restart always \
  qq918652593/easy-vdl:latest

# ARM64 设备（如群晖 ARM 架构、Mac M1/M2 系列）
docker run -d --name easy-vdl -p 888:80 \
  --memory=4g --memory-swap=4g \
  -v $(pwd)/downloads:/app/downloads \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/database:/app/database \
  -e EASY_VDL_PORT=80 -e PUID=1000 -e PGID=100 -e TZ=Asia/Shanghai \
  -e EASY_VDL_ADMIN_USERNAME=admin -e EASY_VDL_ADMIN_PASSWORD=admin123456 \
  --restart always \
  qq918652593/easy-vdl:arm64
```
---

## ⚙️ 环境变量与挂载参数说明

### 常用环境变量
| 变量名 | 说明 | 默认值 | 推荐/必选 |
| :--- | :--- | :--- | :--- |
| `EASY_VDL_PORT` | 容器内部的服务端口 | `80` | 保持 `80` |
| `PUID` / `PGID` | 读写挂载目录的用户 UID/GID | `1000` / `100` | 推荐匹配您宿主机用户的实际 ID |
| `EASY_VDL_ADMIN_USERNAME` | 默认管理员账号 | `admin` | 必选 |
| `EASY_VDL_ADMIN_PASSWORD` | 默认管理员密码 | `admin123456` | 必选（建议修改） |
| `SNIFFER_LICENSE_KEY` | 高级功能授权密钥 | 无 | 可选（亦支持启动后在网页端直接粘贴激活） |
| `TZ` | 系统时区 | `Asia/Shanghai` | 推荐 |

### 目录挂载推荐
* `/app/downloads` ➔ 挂载到您的机械硬盘或 NAS 共享存储空间（用于存放下载的庞大视频文件）。
* `/app/database` ➔ 挂载到您的 SSD 固态硬盘（PostgreSQL 数据库高频读写，固态硬盘能显著提高并发同步流畅度）。

---

## 📖 三步上手指南

### 1️⃣ 第一步：登录控制台
部署完成后，在浏览器中访问 `http://服务器IP:888`，使用您在环境变量中预设的管理员账户密码进行登录。

### 2️⃣ 第二步：激活高级功能 (免重启)
如果您拥有高级版授权，进入 **“系统设置” ➔ “授权设置”** 选项卡。直接在**“图形化授权配置”**框中粘贴您的激活密钥，点击 **“保存并验证”**。
系统会实时秒级激活高级版功能（订阅系统、直播监控录制、AI 高光等），**完全不需要重启容器。**

### 3️⃣ 第三步：开始解析与订阅
* **单链解析**：在首页输入框直接粘贴任何平台的视频链接，秒级解析并一键下载。
* **博主订阅**：在“订阅”页面输入创作者主页链接，配置检测间隔，系统此后将默默为您守护，自动下载每一条新视频。
* **直播订阅**：在“直播”页面添加您喜爱的直播间地址，系统会全天候自动值守，开播即录，录毕即存。

---

## 🔌 浏览器一键下载插件

我们为 **Chrome / Edge** 等浏览器提供了专属的网页快捷下载插件：
* 自动识别您当前浏览的视频网页（支持抖音、B站、YouTube等）。
* 使用生成的 **API Token**（在设置页中一键创建）安全认证，在网页端点击即可将下载任务一键直达推送至您的 Easy-VDL 容器。
* 📥 [点此下载最新浏览器插件](https://github.com/wlaosj/easy-vdl/releases)

---

## 👥 加入社区

* **电报交流群（官方唯一）**：[https://t.me/+7jcTMePlNVwwZjg1](https://t.me/+7jcTMePlNVwwZjg1)
* **GitHub 镜像与发布站**：[https://github.com/wlaosj/easy-vdl](https://github.com/wlaosj/easy-vdl)

---


*软件作者：bigv | 用心服务，带给您极致而优雅的视频下载与流式录制体验*
