import os
import asyncio
import logging
import time
import json
import base64
import subprocess
import shutil
from typing import Optional, Dict, List
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks, Depends
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sys
from urllib.parse import urlparse, unquote, parse_qsl
import aiohttp
from routers.auth import get_current_user, require_license_api
from sql.models import User
import yt_dlp
import urllib.parse
from datetime import datetime
from sql.database_postgresql import get_db
from sql.models import Task, TaskStatus
import uuid
import tempfile
import concurrent.futures
from sqlalchemy.orm import Session

# 创建APIRouter实例
router = APIRouter(prefix="/api/universal")

# 取消标志字典.
wnxt_cancel_flags = {}

class WnxtRequest(BaseModel):
    url: str
    cookie: str = ""
    platform: str = "auto"
    parse_method: str = "ytdlp"  # 修改默认值为ytdlp

class WnxtResponse(BaseModel):
    success: bool
    media_list: List[Dict] = []
    error: Optional[str] = None

def get_domain_from_url(url: str) -> str:
    """从URL中提取域名，并进行规范化处理"""
    try:
        parsed = urlparse(url)
        # 提取主域名
        domain = parsed.netloc
        # 如果是www开头，去掉www
        if domain.startswith('www.'):
            domain = domain[4:]
        # 确保域名以点开始
        if not domain.startswith('.'):
            domain = f".{domain}"
        return domain
    except Exception as e:
        logging.error(f"域名解析失败: {str(e)}")
        return None

def normalize_cookie_domain(domain: str, target_domain: str) -> str:
    """规范化Cookie域名"""
    try:
        # 确保域名以点开始
        if not domain.startswith('.'):
            domain = f".{domain}"
        
        # 移除www前缀
        if domain.startswith('.www.'):
            domain = domain[4:]
            
        # 验证域名是否匹配目标域名
        target_domain = target_domain.lstrip('.')
        domain = domain.lstrip('.')
        
        # 如果域名完全相同或是目标域名的子域名
        if domain == target_domain or target_domain.endswith(f".{domain}"):
            return f".{domain}"
            
        # 如果域名不匹配，使用目标域名
        return f".{target_domain}"
        
    except Exception as e:
        logging.warning(f"Cookie域名规范化失败: {str(e)}")
        return None

def parse_cookies(cookie_string: str, target_url: str) -> List[Dict]:
    """解析Cookie字符串，支持Netscape Cookie文件格式和普通Cookie字符串"""
    if not cookie_string.strip():
        return []
    
    cookies = []
    try:
        # 获取目标域名
        target_domain = get_domain_from_url(target_url)
        if not target_domain:
            logging.error("无法获取目标域名，Cookie解析失败")
            return []

        # 处理每一行
        lines = cookie_string.strip().split('\n')
        for line in lines:
            line = line.strip()
            # 跳过注释和空行
            if not line or line.startswith('#'):
                continue
                
            # 尝试解析Netscape格式
            if '\t' in line:
                try:
                    parts = line.split('\t')
                    if len(parts) >= 7:
                        domain_str = parts[0]
                        path = parts[2]
                        secure = parts[3].lower() == 'true'
                        expiry = parts[4]
                        name = parts[5]
                        value = parts[6]
                        
                        # 规范化域名
                        normalized_domain = normalize_cookie_domain(domain_str, target_domain.lstrip('.'))
                        if not normalized_domain:
                            continue
                        
                        cookie = {
                            'name': name,
                            'value': value,
                            'domain': normalized_domain,
                            'path': path,
                            'secure': secure,
                            'httpOnly': False
                        }
                        cookies.append(cookie)
                        continue
                except Exception as e:
                    pass

            # 如果不是Netscape格式，尝试标准Cookie字符串格式
            if '=' in line:
                try:
                    name, value = line.split('=', 1)
                    name = name.strip()
                    value = value.strip()
                    if name and value:
                        cookie = {
                            'name': name,
                            'value': value,
                            'domain': target_domain,
                            'path': '/',
                            'secure': True,
                            'httpOnly': False
                        }
                        cookies.append(cookie)
                except Exception as e:
                    pass
                    
    except Exception as e:
        logging.error(f"Cookie解析失败: {str(e)}")
    
    return cookies

@router.post("/parse")
@require_license_api
async def parse_media(request: Request, current_user: User = Depends(get_current_user)):
    """解析媒体"""
    try:
        data = await request.json()
        url = data.get("url")
        
        if not url:
            raise ValueError("缺少必要的URL参数")
            
        # 检查是否存在wnxt_cookie.txt文件
        wnxt_cookie_path = '/app/database/cookie/wnxt_cookie.txt'
        has_cookie = os.path.exists(wnxt_cookie_path)
        
        # 判断是否为YouTube链接
        is_youtube = 'youtube.com' in url or 'youtu.be' in url
        
        # 使用yt-dlp获取视频信息
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,  # 改为False以获取完整信息
            'no_cache_dir': True,  # 禁用缓存目录，避免缓存堆积
            'socket_timeout': 60,  # 设置60秒超时，支持播放列表解析
            # 移除固定的format选项，让yt-dlp获取所有可用格式
        }
        
        # 如果存在cookie文件，添加到yt-dlp选项中
        if has_cookie:
            ydl_opts['cookiefile'] = wnxt_cookie_path
            logging.debug(f"[parse_media] 使用万能嗅探cookie文件: {wnxt_cookie_path}")
        
        # 为 YouTube 添加远程组件支持（yt-dlp 2025.11.12+ 需要）
        # 注意：remote_components 需要在顶层选项中设置
        if is_youtube:
            ydl_opts['remote_components'] = ['ejs:github']
            logging.debug(f"[parse_media] 检测到 YouTube URL，已启用远程组件支持")
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
        except Exception as e:
            # 如果第一次解析失败，尝试使用更宽松的配置
            logging.warning(f"[parse_media] 第一次解析失败，尝试使用更宽松的配置: {str(e)}")
            try:
                ydl_opts_fallback = {
                    'quiet': True,
                    'no_warnings': True,
                    'extract_flat': False,
                    'ignoreerrors': True,  # 忽略部分错误
                    'no_check_certificate': True,  # 忽略证书验证
                    'socket_timeout': 60,  # 设置60秒超时，支持播放列表解析
                }
                # 如果是YouTube，也需要添加远程组件支持
                if is_youtube:
                    ydl_opts_fallback['remote_components'] = ['ejs:github']
                # 如果存在cookie，也要添加到重试配置中
                if has_cookie:
                    ydl_opts_fallback['cookiefile'] = wnxt_cookie_path
                with yt_dlp.YoutubeDL(ydl_opts_fallback) as ydl:
                    info = ydl.extract_info(url, download=False)
            except Exception as e2:
                logging.error(f"[parse_media] 重试解析也失败: {str(e2)}")
                raise e2  # 抛出原始异常
        
        # 构建媒体数据 - 参考ytd.py的实现，支持更高分辨率
        formats = []
        all_formats = info.get('formats', [])
        logging.debug(f"[parse_media] 获取到总格式数量: {len(all_formats)}")
        
        # 分离视频和音频格式
        video_formats = []
        audio_formats = []
        
        for f in all_formats:
            has_video = f.get('vcodec') != 'none'
            has_audio = f.get('acodec') != 'none'
            
            # 跳过DRM保护的格式
            if f.get('drm') or f.get('has_drm'):
                continue
            
            # 跳过没有URL的格式（通常是SABR流媒体）
            if not f.get('url'):
                continue
            
            # 跳过fragment格式（通常不稳定）
            if f.get('fragments') or 'hls' in str(f.get('protocol', '')).lower():
                continue
            
            if has_video and not has_audio:
                # 纯视频格式
                resolution = f.get('resolution', '0x0')
                try:
                    height = int(resolution.split('x')[1]) if 'x' in resolution else (f.get('height') or 0)
                    if height >= 240:  # 240p以上
                        video_formats.append(f)
                        logging.debug(f"[parse_media] 添加视频格式: {f.get('format_id')} - {height}p")
                except:
                    # 如果没有resolution，尝试使用height字段
                    height = f.get('height', 0)
                    if height and height >= 240:
                        video_formats.append(f)
                        logging.debug(f"[parse_media] 添加视频格式: {f.get('format_id')} - {height}p")
            elif has_audio and not has_video:
                # 纯音频格式
                audio_formats.append(f)
                logging.debug(f"[parse_media] 添加音频格式: {f.get('format_id')}")

                # 同时为纯音频构造可选格式（例如网易云音乐这种只有音频没有视频的场景）
                try:
                    abr = f.get('abr') or f.get('tbr')  # 音频比特率
                    format_data = {
                        'format_id': f.get('format_id'),
                        'ext': f.get('ext', 'mp3'),
                        'height': 0,  # 纯音频无分辨率
                        'width': None,
                        'fps': None,
                        'vcodec': 'none',
                        'acodec': f.get('acodec'),
                        'filesize': f.get('filesize'),
                        'filesize_approx': f.get('filesize_approx'),
                        'tbr': abr,
                        'dynamic_range': 'SDR',
                        'container': f.get('container', f.get('ext', 'mp3')),
                        'resolution': 'audio'  # 前端可用此字段判断为音频
                    }
                    formats.append(format_data)
                    logging.debug(f"[parse_media] 添加纯音频可下载格式: {format_data['format_id']} - {abr}kbps")
                except Exception as e:
                    logging.debug(f"[parse_media] 构造纯音频格式失败: {str(e)}")
            elif has_video and has_audio:
                # 完整格式（既有视频又有音频）
                resolution = f.get('resolution', '0x0')
                try:
                    height = int(resolution.split('x')[1]) if 'x' in resolution else (f.get('height') or 0)
                    if height >= 240:
                        # 直接添加完整格式
                        format_data = {
                            'format_id': f.get('format_id'),
                            'ext': f.get('ext', 'mp4'),
                            'height': height,
                            'width': f.get('width'),
                            'fps': f.get('fps'),
                            'vcodec': f.get('vcodec'),
                            'acodec': f.get('acodec'),
                            'filesize': f.get('filesize'),
                            'filesize_approx': f.get('filesize_approx'),
                            'tbr': f.get('tbr'),
                            'dynamic_range': f.get('dynamic_range', 'SDR'),
                            'container': f.get('container', f.get('ext', 'mp4')),
                            'resolution': resolution
                        }
                        formats.append(format_data)
                        logging.debug(f"[parse_media] 添加完整格式: {format_data['format_id']} - {height}p")
                except:
                    height = f.get('height', 0)
                    if height and height >= 240:
                        format_data = {
                            'format_id': f.get('format_id'),
                            'ext': f.get('ext', 'mp4'),
                            'height': height,
                            'width': f.get('width'),
                            'fps': f.get('fps'),
                            'vcodec': f.get('vcodec'),
                            'acodec': f.get('acodec'),
                            'filesize': f.get('filesize'),
                            'filesize_approx': f.get('filesize_approx'),
                            'tbr': f.get('tbr'),
                            'dynamic_range': f.get('dynamic_range', 'SDR'),
                            'container': f.get('container', f.get('ext', 'mp4')),
                            'resolution': f.get('resolution', f'{f.get("width", 0)}x{height}')
                        }
                        formats.append(format_data)
                        logging.debug(f"[parse_media] 添加完整格式: {format_data['format_id']} - {height}p")
        
        # 按分辨率排序视频格式
        video_formats.sort(key=lambda x: (
            int(x.get('resolution', '0x0').split('x')[1]) if 'x' in x.get('resolution', '0x0') else (x.get('height') or 0),
            x.get('tbr', 0) or 0
        ), reverse=True)
        
        logging.debug(f"[parse_media] 筛选后视频格式数量: {len(video_formats)}, 音频格式数量: {len(audio_formats)}")
        
        # 选择最佳音频格式
        best_audio = None
        if audio_formats:
            # 优先选择m4a格式，然后是aac
            audio_formats.sort(key=lambda x: (
                x.get('ext') != 'm4a',  # m4a优先
                x.get('ext') != 'aac',  # 然后aac
                -(x.get('filesize') or 0)   # 文件大小降序
            ))
            best_audio = audio_formats[0]
            logging.debug(f"[parse_media] 选择最佳音频格式: {best_audio.get('format_id')}")
        
        # 生成合成格式选项（为所有视频格式生成合成选项，支持4K/8K）
        if len(video_formats) > 0 and best_audio:
            logging.debug(f"[parse_media] 开始生成合成格式，视频格式数量: {len(video_formats)}")
            for video_f in video_formats:
                resolution = video_f.get('resolution', '0x0')
                try:
                    height = int(resolution.split('x')[1]) if 'x' in resolution else (video_f.get('height') or 0)
                except:
                    height = video_f.get('height', 0)
                
                format_data = {
                    'format_id': f"{video_f.get('format_id')}+{best_audio.get('format_id')}",
                    'ext': 'mp4',
                    'height': height,
                    'width': video_f.get('width'),
                    'fps': video_f.get('fps'),
                    'vcodec': video_f.get('vcodec'),
                    'acodec': best_audio.get('acodec'),
                    'filesize': (video_f.get('filesize', 0) + best_audio.get('filesize', 0)) if video_f.get('filesize') and best_audio.get('filesize') else None,
                    'filesize_approx': (video_f.get('filesize_approx', 0) + best_audio.get('filesize_approx', 0)) if video_f.get('filesize_approx') and best_audio.get('filesize_approx') else None,
                    'tbr': (video_f.get('tbr', 0) or 0) + (best_audio.get('tbr', 0) or 0),
                    'dynamic_range': video_f.get('dynamic_range', 'SDR'),
                    'container': 'mp4',
                    'resolution': resolution
                }
                formats.append(format_data)
                logging.debug(f"[parse_media] 生成合成格式: {format_data['format_id']} - {height}p")
        
        # 按分辨率和比特率排序
        formats.sort(key=lambda x: (
            x.get('height', 0) or 0,
            x.get('tbr', 0) or 0
        ), reverse=True)
        
        # 去重：基于显示属性去除重复格式（用户看到的重复）
        original_count = len(formats)
        seen_keys = set()
        unique_formats = []
        for fmt in formats:
            # 基于用户看到的显示属性去重：height, tbr, filesize
            # 这样可以去除 format_id 不同但显示相同的重复格式
            height = fmt.get('height', 0) or 0
            tbr = fmt.get('tbr', 0) or 0
            filesize = fmt.get('filesize') or fmt.get('filesize_approx')
            
            # 创建唯一键：基于显示属性
            # 如果 filesize 为 None，使用 format_id 作为补充区分
            if filesize:
                key = (height, round(tbr, 2) if tbr else 0, filesize)
            else:
                # 如果 filesize 为 None，使用 format_id 来区分
                format_id = fmt.get('format_id', '')
                key = (height, round(tbr, 2) if tbr else 0, format_id)
            
            if key not in seen_keys:
                seen_keys.add(key)
                unique_formats.append(fmt)
            else:
                # 如果已存在相同显示属性的格式，记录日志
                logging.debug(f"[parse_media] 跳过重复格式: {fmt.get('format_id')} - {height}p, {tbr}Kbps, {filesize}")
        
        formats = unique_formats
        if original_count != len(formats):
            logging.debug(f"[parse_media] 去重后格式数量: {len(formats)} (去重前: {original_count}, 去除了 {original_count - len(formats)} 个重复格式)")
        else:
            logging.debug(f"[parse_media] 最终生成的格式数量: {len(formats)}")
        
        media_data = {
            'title': info.get('title', '未知标题'),
            'description': info.get('description', ''),
            'thumbnail': info.get('thumbnail'),  # 缩略图URL
            'duration': info.get('duration'),  # 视频时长
            'view_count': info.get('view_count'),  # 播放次数
            'uploader': info.get('uploader'),  # 上传者
            'upload_date': info.get('upload_date'),  # 上传日期
            'webpage_url': info.get('webpage_url', url),  # 网页URL
            'like_count': info.get('like_count'),  # 点赞数
            'channel': info.get('channel', info.get('uploader')),  # 频道名
            'channel_url': info.get('channel_url'),  # 频道URL
            'formats': formats,  # 所有可用格式
            'requestHeaders': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br'
            }
        }
        
        return {
            "success": True,
            "data": media_data
        }
        
    except Exception as e:
            logging.error(f"[parse_media] yt-dlp解析失败: {str(e)}")
            
            # 根据错误类型提供更具体的错误信息
            error_message = "未找到可用的媒体格式"
            if "Requested format is not available" in str(e):
                error_message = "请求的格式不可用"
            elif "Video unavailable" in str(e):
                error_message = "视频不可用或已被删除"
            elif "Private video" in str(e):
                error_message = "视频为私密视频，需要登录"
            elif "Sign in" in str(e):
                error_message = "需要登录才能访问此内容"
            elif "This video is not available" in str(e):
                error_message = "此视频在您的地区不可用"
            
            return {
                "success": False,
                "error": error_message,
                "message": f"可能的原因：\n• {error_message}\n• 链接格式不正确\n• 网站反爬虫机制\n• 需要登录或会员权限\n• 网络连接问题\n• 地区限制"
            }
            
    except Exception as e:
        logging.error(f"[parse_media] 解析失败: {str(e)}")
        return {
            "success": False,
            "error": f"解析失败: {str(e)}"
        }

# 移除插件相关的路由
# @router.post("/receive")
# @router.post("/debug")
# @router.get("/test-receive")
# @router.get("/debug-headers/{url:path}")
# @router.get("/plugin-data/{tab_id}")
# @router.delete("/plugin-data/{tab_id}")

@router.options("/download")
async def download_media_options():
    """处理下载接口的预检请求"""
    return JSONResponse(
        content={},
        headers={
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': '*',
        }
    )

@router.post("/download")
@require_license_api
async def download_media(request: Request, current_user: User = Depends(get_current_user)):
    """下载媒体文件"""
    try:
        # 支持JSON和表单数据
        content_type = request.headers.get("content-type", "")
        
        if "application/json" in content_type:
            # JSON格式
            data = await request.json()
            url = data.get("url")
            type_param = data.get("type", "video")
        else:
            # 表单格式
            form_data = await request.form()
            url = form_data.get("url")
            type_param = form_data.get("type", "video")
            
        if not url:
            raise HTTPException(status_code=400, detail="Missing URL")
            
        # 如果是代理URL，解码原始URL
        if "/proxy/" in url:
            path = url.split("/proxy/")[-1]
            url = base64.b64decode(path).decode()
            
        original_headers = dict(request.headers)
        
        # 尝试从captured_media中找到对应的插件请求头
        plugin_headers = None
        for tab_id, media_list in captured_media.items():
            for media in media_list:
                if media.get("url") == url and media.get("requestHeaders"):
                    plugin_headers = media.get("requestHeaders")
                    logging.debug(f"下载时找到插件请求头用于URL: {url}")
                    break
            if plugin_headers:
                break
        
        config = process_media_url(url, original_headers, plugin_headers=plugin_headers)
        
        # 检查是否是TikTok，如果是则跳过预检查
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        is_tiktok = 'tiktok.com' in domain or 'ttwstatic.com' in domain
        
        content_length = None
        content_type = 'application/octet-stream'
        
        if not is_tiktok:
            # 非TikTok平台进行预检查
            async with aiohttp.ClientSession() as session:
                # 预检查重试逻辑
                precheck_retries = 3
                for retry in range(precheck_retries):
                    try:
                        async with session.head(url, headers=config['headers'], ssl=False) as response:
                            if response.status == 403 and retry < precheck_retries - 1:
                                # 403错误处理 - 根据域名添加特定请求头
                                if 'xhscdn.com' in domain or 'xiaohongshu.com' in domain:
                                    # 小红书特殊处理
                                    config['headers'].update({
                                        'Referer': 'https://www.xiaohongshu.com',
                                        'Origin': 'https://www.xiaohongshu.com',
                                        'Accept': '*/*',
                                        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                                        'Accept-Encoding': 'gzip, deflate, br',
                                        'Cache-Control': 'no-cache',
                                        'Pragma': 'no-cache',
                                        'Sec-Fetch-Dest': 'video',
                                        'Sec-Fetch-Mode': 'cors',
                                        'Sec-Fetch-Site': 'cross-site',
                                        'Connection': 'keep-alive',
                                        'Upgrade-Insecure-Requests': '1',
                                        'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                                        'Sec-Ch-Ua-Mobile': '?0',
                                        'Sec-Ch-Ua-Platform': '"Windows"'
                                    })
                                elif 'bilivideo.com' in domain:
                                    # B站特殊处理
                                    config['headers'].update({
                                        'Referer': 'https://www.bilibili.com',
                                        'Origin': 'https://www.bilibili.com',
                                        'Accept': '*/*',
                                        'Accept-Language': 'zh-CN,zh;q=0.9',
                                        'Sec-Fetch-Dest': 'empty',
                                        'Sec-Fetch-Mode': 'cors',
                                        'Sec-Fetch-Site': 'cross-site',
                                        'Accept-Encoding': 'gzip, deflate, br',
                                        'Cache-Control': 'no-cache',
                                        'Pragma': 'no-cache'
                                    })
                                elif 'douyinvod.com' in domain or 'douyin.com' in domain:
                                    # 抖音特殊处理
                                    config['headers'].update({
                                        'Referer': 'https://www.douyin.com',
                                        'Origin': 'https://www.douyin.com',
                                        'Accept': '*/*',
                                        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                                        'Accept-Encoding': 'gzip, deflate, br',
                                        'Cache-Control': 'no-cache',
                                        'Pragma': 'no-cache',
                                        'Sec-Fetch-Dest': 'video',
                                        'Sec-Fetch-Mode': 'cors',
                                        'Sec-Fetch-Site': 'cross-site'
                                    })
                                else:
                                    # 其他平台通用处理
                                    config['headers'].update({
                                        'Accept': '*/*',
                                        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                                        'Accept-Encoding': 'gzip, deflate, br',
                                        'Cache-Control': 'no-cache',
                                        'Pragma': 'no-cache',
                                        'Sec-Fetch-Dest': 'video',
                                        'Sec-Fetch-Mode': 'cors',
                                        'Sec-Fetch-Site': 'cross-site',
                                        'Connection': 'keep-alive',
                                        'Upgrade-Insecure-Requests': '1'
                                    })
                                
                                logging.warning(f"预检查收到403错误，更新请求头后重试 ({retry + 1}/{precheck_retries})")
                                await asyncio.sleep(1)
                                continue
                            
                            if not response.ok:
                                raise HTTPException(
                                    status_code=response.status,
                                    detail=f"Failed to access media: {response.reason}"
                                )
                            
                            content_length = response.headers.get('Content-Length')
                            content_type = response.headers.get('Content-Type', 'application/octet-stream')
                            break
                            
                    except HTTPException:
                        raise
                    except Exception as e:
                        if retry < precheck_retries - 1:
                            logging.warning(f"预检查失败，重试 ({retry + 1}/{precheck_retries}): {str(e)}")
                            await asyncio.sleep(1)
                            continue
                        else:
                            raise HTTPException(
                                status_code=500,
                                detail=f"Pre-check failed after {precheck_retries} retries: {str(e)}"
                            )
        else:
            # TikTok跳过预检查，直接进行流式下载
            logging.debug("TikTok平台跳过预检查，直接进行流式下载")
                
        filename = get_filename(url)
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': '*',
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Accept-Ranges': 'bytes',
            'Transfer-Encoding': 'chunked',
            'Content-Type': content_type
        }
        
        if content_length:
            headers['Content-Length'] = content_length
            
        return StreamingResponse(
            stream_generator(config),
            headers=headers,
            media_type=content_type
        )
    except Exception as e:
        logging.error(f"下载失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



async def stream_generator(config: Dict):
    """流式传输生成器"""
    max_retries = 3
    retry_count = 0
    chunk_size = 8192  # 8KB chunks
    
    while retry_count < max_retries:
        try:
            timeout = aiohttp.ClientTimeout(total=60, connect=10)  # 增加超时时间
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(**config) as response:
                    if response.status == 403:
                        # 403错误处理 - 根据域名添加特定请求头
                        url = config['url']
                        parsed_url = urlparse(url)
                        domain = parsed_url.netloc
                        
                        if 'xhscdn.com' in domain or 'xiaohongshu.com' in domain:
                            # 小红书特殊处理
                            config['headers'].update({
                                'Referer': 'https://www.xiaohongshu.com',
                                'Origin': 'https://www.xiaohongshu.com',
                                'Accept': '*/*',
                                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                                'Accept-Encoding': 'gzip, deflate, br',
                                'Cache-Control': 'no-cache',
                                'Pragma': 'no-cache',
                                'Sec-Fetch-Dest': 'video',
                                'Sec-Fetch-Mode': 'cors',
                                'Sec-Fetch-Site': 'cross-site',
                                'Connection': 'keep-alive',
                                'Upgrade-Insecure-Requests': '1',
                                'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                                'Sec-Ch-Ua-Mobile': '?0',
                                'Sec-Ch-Ua-Platform': '"Windows"'
                            })
                        elif 'bilivideo.com' in domain:
                            # B站特殊处理
                            config['headers'].update({
                                'Referer': 'https://www.bilibili.com',
                                'Origin': 'https://www.bilibili.com',
                                'Accept': '*/*',
                                'Accept-Language': 'zh-CN,zh;q=0.9',
                                'Sec-Fetch-Dest': 'empty',
                                'Sec-Fetch-Mode': 'cors',
                                'Sec-Fetch-Site': 'cross-site',
                                'Accept-Encoding': 'gzip, deflate, br',
                                'Cache-Control': 'no-cache',
                                'Pragma': 'no-cache'
                            })
                        elif 'douyinvod.com' in domain or 'douyin.com' in domain:
                            # 抖音特殊处理
                            config['headers'].update({
                                'Referer': 'https://www.douyin.com',
                                'Origin': 'https://www.douyin.com',
                                'Accept': '*/*',
                                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                                'Accept-Encoding': 'gzip, deflate, br',
                                'Cache-Control': 'no-cache',
                                'Pragma': 'no-cache',
                                'Sec-Fetch-Dest': 'video',
                                'Sec-Fetch-Mode': 'cors',
                                'Sec-Fetch-Site': 'cross-site'
                            })
                        elif 'tiktok.com' in domain or 'ttwstatic.com' in domain:
                            # TikTok特殊处理
                            config['headers'].update({
                                'Referer': 'https://www.tiktok.com',
                                'Origin': 'https://www.tiktok.com',
                                'Accept': '*/*',
                                'Accept-Language': 'en-US,en;q=0.9',
                                'Accept-Encoding': 'gzip, deflate, br',
                                'Cache-Control': 'no-cache',
                                'Pragma': 'no-cache',
                                'Sec-Fetch-Dest': 'video',
                                'Sec-Fetch-Mode': 'cors',
                                'Sec-Fetch-Site': 'cross-site',
                                'Connection': 'keep-alive',
                                'Upgrade-Insecure-Requests': '1',
                                'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                                'Sec-Ch-Ua-Mobile': '?0',
                                'Sec-Ch-Ua-Platform': '"Windows"',
                                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                            })
                        else:
                            # 其他平台通用处理
                            config['headers'].update({
                                'Accept': '*/*',
                                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                                'Accept-Encoding': 'gzip, deflate, br',
                                'Cache-Control': 'no-cache',
                                'Pragma': 'no-cache',
                                'Sec-Fetch-Dest': 'video',
                                'Sec-Fetch-Mode': 'cors',
                                'Sec-Fetch-Site': 'cross-site',
                                'Connection': 'keep-alive',
                                'Upgrade-Insecure-Requests': '1'
                            })
                        
                        retry_count += 1
                        logging.warning(f"收到403错误，更新请求头后重试 ({retry_count}/{max_retries})")
                        continue
                            
                    if not response.ok and response.status != 206:
                        logging.error(f"请求失败: 状态码 {response.status}")
                        if retry_count < max_retries - 1:
                            retry_count += 1
                            await asyncio.sleep(1 * retry_count)
                            continue
                        raise HTTPException(
                            status_code=response.status,
                            detail=f"Failed to fetch media: {response.reason}"
                        )
                    
                    # 获取总大小
                    total_size = response.content_length or 0
                    bytes_read = 0
                    
                    # 使用 response.content.iter_chunked() 来处理分块
                    async for chunk in response.content.iter_chunked(chunk_size):
                        if chunk:  # 确保chunk不为空
                            bytes_read += len(chunk)
                            yield chunk
                            
                    # 验证是否完整传输
                    if total_size > 0 and bytes_read != total_size:
                        logging.error(f"传输不完整: 已读取 {bytes_read} / 总大小 {total_size}")
                        if retry_count < max_retries - 1:
                            retry_count += 1
                            await asyncio.sleep(1 * retry_count)
                            continue
                        raise HTTPException(
                            status_code=500,
                            detail="Incomplete transfer"
                        )
                            
                    return  # 成功完成传输
                    
        except aiohttp.ClientError as e:
            logging.error(f"客户端错误: {str(e)}")
            if retry_count < max_retries - 1:
                retry_count += 1
                await asyncio.sleep(1 * retry_count)
                continue
            raise HTTPException(
                status_code=500,
                detail=f"Download failed after {max_retries} retries: {str(e)}"
            )
            
        except Exception as e:
            logging.error(f"流式传输错误: {str(e)}")
            if retry_count < max_retries - 1:
                retry_count += 1
                await asyncio.sleep(1 * retry_count)
                continue
            raise HTTPException(status_code=500, detail=str(e))
            
    raise HTTPException(
        status_code=500,
        detail=f"Max retries ({max_retries}) exceeded"
    )

# ==================== 初始化函数 ====================

async def initialize_wnxt_service():
    """初始化万能嗅探服务"""
    try:
        logging.info("正在初始化万能嗅探服务...")
        # 这里可以添加其他初始化逻辑，如配置检查等
        logging.info("万能嗅探服务初始化成功")
        return True
    except Exception as e:
        logging.error(f"万能嗅探服务初始化异常: {str(e)}")
        return False

async def shutdown_wnxt_service():
    """关闭万能嗅探服务"""
    try:
        logging.info("正在关闭万能嗅探服务...")
        # 这里可以添加其他清理逻辑
        logging.info("万能嗅探服务已关闭")
    except Exception as e:
        logging.error(f"关闭万能嗅探服务异常: {str(e)}")

@router.post("/ytdlp-download")
@require_license_api
async def ytdlp_download(request: Request, current_user: User = Depends(get_current_user)):
    """通用下载接口"""
    try:
        data = await request.json()
        url = data.get("url")
        format_id = data.get("format_id")
        cookie = data.get("cookie", "")
        headers = data.get("headers", {})
        
        if not url:
            raise ValueError("缺少必要的URL参数")
            
        logging.info(f"[ytdlp-download] 收到下载请求: url={url}, format_id={format_id}")
        
        # 处理请求头
        request_headers = {}
        if headers:
            if isinstance(headers, str):
                try:
                    headers = json.loads(headers)
                except:
                    headers = {}
            
            # 直接使用传入的请求头
            request_headers = headers
        
        # 如果没有设置 User-Agent，使用默认值
        if not request_headers.get('User-Agent'):
            request_headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        
        # 创建下载任务
        task_id = str(uuid.uuid4())
        db = next(get_db())
        try:
            task = Task(
                id=task_id,
                url=url,
                source="others",
                status=TaskStatus.PENDING.value,
                progress=0.0,
                headers=json.dumps(request_headers) if request_headers else None,
                cookie=None,  # Cookie不再从前端传递，直接从文件读取
                format_id=format_id if format_id else None,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            db.add(task)
            db.commit()
            
            # 添加到下载队列（延迟导入避免循环依赖）
            import routers.downloader
            await routers.downloader.download_manager.add_download_task(task_id)
            
            # 注意：这里不再传递cookie参数，因为ytdlp_download_task会自动从文件读取
            
            return {
                "success": True,
                "message": "已添加到下载队列",
                "task_id": task_id
            }
            
        finally:
            try:
                db.rollback()
            except Exception:
                pass
            db.close()
            
    except Exception as e:
        logging.error(f"[ytdlp-download] 添加下载任务失败: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

async def ytdlp_download_task(task_id: str, url: str, format_id: str = None, headers: dict = None):
    """YTD下载实现"""
    import asyncio
    import aiohttp
    import threading
    
    db = next(get_db())
    temp_dir = None
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise Exception("任务不存在")
            
        # 创建临时目录
        temp_dir = tempfile.mkdtemp()
        
        # 设置yt-dlp选项
        # 优先使用数据库中的format_id，如果没有再从参数中获取
        final_format_id = task.format_id or format_id or 'bestvideo+bestaudio'
        logging.info(f"[ytdlp-download] 使用格式: {final_format_id} (数据库: {task.format_id}, 参数: {format_id})")
        # 智能格式选择：如果用户选择了特定格式，确保包含音频
        if final_format_id and final_format_id != 'bestvideo+bestaudio':
            # 检查是否是纯数字格式ID（YouTube等平台的格式ID）
            if final_format_id.isdigit():
                # 纯数字格式ID通常只包含视频，需要添加音频
                final_format_id = f"{final_format_id}+bestaudio"
                logging.debug(f"[ytdlp-download] 检测到纯数字格式ID，自动添加音频流: {final_format_id}")
            elif 'bestvideo' in final_format_id and 'bestaudio' not in final_format_id:
                # 如果只有视频没有音频，自动添加音频
                final_format_id = f"{final_format_id}+bestaudio"
                logging.debug(f"[ytdlp-download] 自动添加音频流: {final_format_id}")
            elif 'bestaudio' in final_format_id and 'bestvideo' not in final_format_id:
                # 如果只有音频没有视频，自动添加视频
                final_format_id = f"bestvideo+{final_format_id}"
                logging.debug(f"[ytdlp-download] 自动添加视频流: {final_format_id}")
            elif '+' not in final_format_id:
                # 如果格式ID中没有+号，说明可能是单一格式，需要添加音频
                final_format_id = f"{final_format_id}+bestaudio"
                logging.debug(f"[ytdlp-download] 检测到单一格式，自动添加音频流: {final_format_id}")
        
        ydl_opts = {
            'format': final_format_id,  # 使用最终的格式ID
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'no_cache_dir': True,  # 禁用缓存目录，避免缓存堆积
            'writethumbnail': True,
            'postprocessors': [
                # 缩略图转换
                {
                    'key': 'FFmpegThumbnailsConvertor',
                    'format': 'jpg'
                },
                # 自动删除中间文件（分离的音视频文件）
                {
                    'key': 'FFmpegVideoRemuxer',
                    'preferedformat': 'mp4'
                }
            ],
            # 音频相关设置
            'audioformat': 'best',
            'audioquality': '0',  # 最高音频质量
            # 确保下载完整的视频
            'extractaudio': False,  # 不单独提取音频
            'keepvideo': False,  # 合并后删除原始文件
            # 下载策略
            'prefer_ffmpeg': True,  # 优先使用FFmpeg处理
            # 如果视频和音频分离，自动合并
            'merge_output_format': 'mp4',
            # 自动清理设置
            'postprocessor_args': {
                'ffmpeg': [
                    '-c:v', 'copy',  # 复制视频流，不重新编码
                    '-c:a', 'copy',  # 复制音频流，不重新编码
                    '-strict', 'experimental'  # 允许实验性编码器
                ]
            }
        }
        
        # 处理请求头
        request_headers = {}
        if headers:
            if isinstance(headers, str):
                try:
                    headers = json.loads(headers)
                except:
                    headers = {}
            
            # 直接使用传入的请求头
            request_headers = headers
        
        # 如果没有设置 User-Agent，使用默认值
        if not request_headers.get('User-Agent'):
            request_headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        
        # 添加请求头到 yt-dlp 选项
        ydl_opts['http_headers'] = request_headers
        
        # 检查是否存在wnxt_cookie.txt文件
        wnxt_cookie_path = '/app/database/cookie/wnxt_cookie.txt'
        has_cookie = os.path.exists(wnxt_cookie_path)
        
        # 如果存在cookie文件，添加到选项中
        if has_cookie:
            ydl_opts['cookiefile'] = wnxt_cookie_path
            logging.debug(f"[ytdlp-download] 使用万能嗅探cookie文件: {wnxt_cookie_path}")
        
        # 检测是否是 YouTube URL，如果是则添加远程组件支持（yt-dlp 2025.11.12+ 需要）
        # 注意：remote_components 需要在顶层选项中设置
        is_youtube = 'youtube.com' in url or 'youtu.be' in url
        if is_youtube:
            ydl_opts['remote_components'] = ['ejs:github']
            logging.debug(f"[ytdlp-download] 检测到 YouTube URL，已启用远程组件支持")
            
        # 设置输出模板
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_filename = f"video_{timestamp}"
        ydl_opts['outtmpl'] = {
            'default': f'/app/downloads/others/{base_filename}/{base_filename}.%(ext)s',
            'thumbnail': f'/app/downloads/others/{base_filename}/{base_filename}.%(ext)s'  # 缩略图使用基础文件名，后续重命名
        }
        
        # 更新任务信息
        db.query(Task).filter(Task.id == task_id).update({
            'status': TaskStatus.DOWNLOADING.value,
            'progress': 0.0,
            'filename': f"others/{base_filename}/{base_filename}.%(ext)s",  # 使用动态扩展名，包含平台前缀
            'updated_at': datetime.now()
        })
        db.commit()
        
        # 设置进度回调（时间节流：每300ms更新一次，进度条更丝滑）
        last_progress_time = time.time()
        progress_queue = asyncio.Queue()
        
        def progress_hook(d):
            nonlocal last_progress_time
            
            if d['status'] == 'downloading':
                try:
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    downloaded = d.get('downloaded_bytes', 0)
                    if total > 0:
                        progress = (downloaded / total) * 100
                    else:
                        progress = 0
                except:
                    progress = 0
                    
                current_time = time.time()
                # 时间节流：每300ms更新一次
                if current_time - last_progress_time >= 0.3:
                    progress_queue.put_nowait({
                        'progress': progress,
                        'task_id': task_id
                    })
                    last_progress_time = current_time
            elif d['status'] == 'finished':
                # 下载完成，发送100%进度
                progress_queue.put_nowait({
                    'progress': 100.0,
                    'task_id': task_id
                })
                logging.info(f"[ytdlp-download] 下载完成: {d.get('filename', 'unknown')}")
                    
        ydl_opts['progress_hooks'] = [progress_hook]
        
        # 创建下载目录
        os.makedirs(os.path.dirname(ydl_opts['outtmpl']['default']), exist_ok=True)
        
        # 启动进度更新任务
        async def update_progress():
            while True:
                try:
                    # 检查是否被取消
                    if wnxt_cancel_flags.get(task_id):
                        logging.info(f"[ytdlp-download] 任务被取消: {task_id}")
                        break
                        
                    progress_info = await progress_queue.get()
                    if progress_info is None: # 结束信号
                        logging.debug(f"[ytdlp-download] 进度更新任务收到结束信号")
                        break
                        
                    update_db = next(get_db())
                    try:
                        logging.debug(f"[ytdlp-download] 更新进度: {progress_info['task_id']} -> {progress_info['progress']}%")
                        update_db.query(Task).filter(Task.id == progress_info['task_id']).update({
                            'progress': progress_info['progress'],
                            'updated_at': datetime.now()
                        })
                        update_db.commit()
                        
                        # 延迟导入避免循环依赖
                        import routers.websocket
                        await routers.websocket.broadcast_message('downloads', {
                            'type': 'progress_update',
                            'task': {
                                'id': progress_info['task_id'],
                                'progress': progress_info['progress'],
                                'status': TaskStatus.DOWNLOADING.value,
                                'updated_at': datetime.now().isoformat()
                            }
                        })
                    finally:
                        try:
                            update_db.rollback()
                        except Exception:
                            pass
                        update_db.close()
                except Exception as e:
                    logging.error(f"[ytdlp-download] 处理进度更新失败: {str(e)}")
                    continue
        
        progress_task = asyncio.create_task(update_progress())
        
        try:
            # 执行下载
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, url, download=True)
                
                # 检查是否被取消
                if wnxt_cancel_flags.get(task_id):
                    logging.info(f"[ytdlp-download] 任务被取消，停止处理: {task_id}")
                    # 更新任务状态为已取消
                    db.query(Task).filter(Task.id == task_id).update({
                        'status': TaskStatus.CANCELLED.value,
                        'updated_at': datetime.now()
                    })
                    db.commit()
                    return None
                
        except Exception as e:
            # 如果第一次下载失败，尝试使用更宽松的格式
            logging.warning(f"[ytdlp-download] 第一次下载失败，尝试使用更宽松的格式: {str(e)}")
            try:
                ydl_opts_fallback = ydl_opts.copy()
                
                # 智能重试策略：根据错误类型选择不同的格式
                if "format is not available" in str(e) or "Requested format" in str(e):
                    # 格式不可用，使用最佳质量
                    ydl_opts_fallback['format'] = 'best'
                    logging.info(f"[ytdlp-download] 检测到格式不可用，重试使用 'best' 格式")
                elif "bestvideo+bestaudio" in final_format_id:
                    # 如果已经是bestvideo+bestaudio还失败，尝试best
                    ydl_opts_fallback['format'] = 'best'
                    logging.info(f"[ytdlp-download] 检测到bestvideo+bestaudio失败，重试使用 'best' 格式")
                elif "tiktok" in url.lower() or "douyin" in url.lower():
                    # TikTok/抖音等平台，直接使用best格式
                    ydl_opts_fallback['format'] = 'best'
                    logging.info(f"[ytdlp-download] 检测到TikTok/抖音平台，重试使用 'best' 格式")
                else:
                    # 其他情况，尝试bestvideo+bestaudio
                    ydl_opts_fallback['format'] = 'bestvideo+bestaudio'
                    logging.info(f"[ytdlp-download] 重试使用 'bestvideo+bestaudio' 格式")
                
                ydl_opts_fallback['ignoreerrors'] = True  # 忽略部分错误
                ydl_opts_fallback['no_check_certificate'] = True  # 忽略证书验证
                
                with yt_dlp.YoutubeDL(ydl_opts_fallback) as ydl:
                    info = await asyncio.to_thread(ydl.extract_info, url, download=True)
                    
                    # 检查是否被取消
                    if wnxt_cancel_flags.get(task_id):
                        logging.info(f"[ytdlp-download] 重试下载后任务被取消，停止处理: {task_id}")
                        # 更新任务状态为已取消
                        db.query(Task).filter(Task.id == task_id).update({
                            'status': TaskStatus.CANCELLED.value,
                            'updated_at': datetime.now()
                        })
                        db.commit()
                        return None
                        
            except Exception as e2:
                logging.error(f"[ytdlp-download] 重试下载也失败: {str(e2)}")
                raise e2  # 抛出原始异常
        
        # 等待进度更新任务完成
        await progress_queue.put(None) # 发送结束信号
        await progress_task # 等待任务结束
        
        # 检查是否被取消
        if wnxt_cancel_flags.get(task_id):
            logging.info(f"[ytdlp-download] 任务被取消，停止后续处理: {task_id}")
            return None
        
        # 检查缩略图
        thumb_path = os.path.join(os.path.dirname(ydl_opts['outtmpl']['default']), f"{base_filename}.jpg")
        webp_path = os.path.join(os.path.dirname(ydl_opts['outtmpl']['default']), f"{base_filename}.webp")
        poster_path = os.path.join(os.path.dirname(ydl_opts['outtmpl']['default']), f"{base_filename}-poster.jpg")
        
        # 动态检测实际的视频文件路径
        video_path = None
        for ext in ['mp4', 'webm', 'mkv', 'avi', 'mov']:
            test_path = f'/app/downloads/others/{base_filename}/{base_filename}.{ext}'
            if os.path.exists(test_path):
                video_path = test_path
                break
        
        if not video_path:
            # 如果没找到任何视频文件，使用默认路径
            video_path = f'/app/downloads/others/{base_filename}/{base_filename}.mp4'
        
        # 优先使用yt-dlp下载的缩略图
        thumbnail_found = False  # 标记是否找到了yt-dlp缩略图
        
        if os.path.exists(thumb_path):
            # 如果jpg存在，重命名为poster.jpg
            os.rename(thumb_path, poster_path)
            logging.debug(f"[ytdlp-download] 使用yt-dlp下载的缩略图: {poster_path}")
            thumbnail_found = True
        elif os.path.exists(webp_path):
            # 如果webp存在，转换为标准jpg（兼容 FFmpeg 6.x）
            cmd = [
                "ffmpeg", "-y", "-i", webp_path, "-frames:v", "1", "-q:v", "2",
                poster_path
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0 or not os.path.exists(poster_path):
                fallback_cmd = [
                    "ffmpeg", "-y", "-i", webp_path, "-frames:v", "1", "-q:v", "2",
                    "-vcodec", "mjpeg", poster_path
                ]
                process = await asyncio.create_subprocess_exec(
                    *fallback_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
            if process.returncode == 0 and os.path.exists(poster_path):
                logging.debug(f"[ytdlp-download] 成功转换webp缩略图为标准JPG: {poster_path}")
                os.remove(webp_path)  # 删除webp文件
                thumbnail_found = True
            else:
                logging.error(f"[ytdlp-download] 转换webp缩略图失败: {stderr.decode()}")
        
        # 只有在yt-dlp没有缩略图时，才从视频中提取
        if not thumbnail_found and video_path and os.path.exists(video_path):
            cmd = [
                "ffmpeg", "-y", "-i", video_path,
                "-ss", "00:00:01", "-vframes", "1",
                "-q:v", "2", poster_path
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0 or not os.path.exists(poster_path):
                fallback_cmd = [
                    "ffmpeg", "-y", "-i", video_path,
                    "-ss", "00:00:01", "-vframes", "1",
                    "-q:v", "2", "-vcodec", "mjpeg", poster_path
                ]
                process = await asyncio.create_subprocess_exec(
                    *fallback_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
            if process.returncode == 0 and os.path.exists(poster_path):
                logging.debug(f"[ytdlp-download] 从视频截取缩略图成功: {poster_path}")
            else:
                logging.error(f"[ytdlp-download] 从视频截取缩略图失败: {stderr.decode()}")
        elif not video_path or not os.path.exists(video_path):
            logging.warning(f"[ytdlp-download] 视频文件不存在，无法生成缩略图: {video_path}")
        
        # 更新任务状态为完成，并更新实际的文件路径
        logging.info(f"[ytdlp-download] 任务完成: {task_id}")
        
        # 动态检测实际下载的文件扩展名
        actual_filename = None
        for ext in ['mp4', 'webm', 'mkv', 'avi', 'mov']:
            test_path = f'/app/downloads/others/{base_filename}/{base_filename}.{ext}'
            if os.path.exists(test_path):
                actual_filename = f"others/{base_filename}/{base_filename}.{ext}"
                break
        
        if not actual_filename:
            # 如果没找到任何文件，使用默认的mp4扩展名
            actual_filename = f"others/{base_filename}/{base_filename}.mp4"
        
        db.query(Task).filter(Task.id == task_id).update({
            'status': TaskStatus.COMPLETED.value,
            'progress': 100.0,
            'filename': actual_filename,  # 更新为实际的文件路径
            'updated_at': datetime.now()
        })
        db.commit()
        
        # 广播完成状态（延迟导入避免循环依赖）
        import routers.websocket
        await routers.websocket.broadcast_message('downloads', {
            'type': 'progress_update',
            'task': {
                'id': task_id,
                'progress': 100.0,
                'status': TaskStatus.COMPLETED.value,
                'updated_at': datetime.now().isoformat()
            }
        })
        logging.debug(f"[ytdlp-download] 已广播完成状态: {task_id}")
        
        # 下载完成发送通知逻辑
        try:
            import aiohttp
            import asyncio
            import threading
            
            # 1. 准备通知数据
            n_video_title = info.get('title') if info else (base_filename if 'base_filename' in locals() else "未知视频")
            # 过滤标题中的特殊字符，避免 Telegram 解析错误（Bad Request: can't parse entities）
            if n_video_title:
                n_video_title = str(n_video_title).replace('<', '《').replace('>', '》')
            
            n_platform_name = "通用解析"
            n_current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # 2. 获取封面图
            extra_data = {}
            try:
                if 'base_filename' in locals():
                    poster_filename = f"{base_filename}-poster.jpg"
                    poster_path = f"/app/downloads/others/{base_filename}/{poster_filename}"
                    if os.path.exists(poster_path):
                        # 构造相对路径供通知服务使用
                        relative_poster_path = f"/downloads/others/{base_filename}/{poster_filename}"
                        extra_data["cover"] = relative_poster_path
                        logging.debug(f"[ytdlp-download] 通知将包含海报: {relative_poster_path}")
            except Exception as _e:
                logging.warning(f"[ytdlp-download] 查找海报路径失败: {str(_e)}")

            # 3. 构造通知数据
            notification_data = {
                "title": f"🎉 下载完成 ({n_platform_name})",
                "content": f"内容《{n_video_title}》通过通用解析服务解析并下载完成！\n\n🏷️ 来源: {n_platform_name}\n👤 手动添加\n⏰ 完成时间: {n_current_time}",
                "user_id": "default",
                "extra_data": extra_data
            }
            
            def send_notification_thread():
                try:
                    async def send_notification():
                        try:
                            connector = aiohttp.UnixConnector(path="/app/sockets/easy-vdl.sock")
                            async with aiohttp.ClientSession(connector=connector) as session:
                                await session.post("http://localhost/api/notifications/download-completed", json=notification_data)
                        except: pass
                    
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(send_notification())
                    finally:
                        loop.close()
                except: pass
            
            threading.Thread(target=send_notification_thread, daemon=True).start()
        except Exception as e:
            logging.warning(f"[ytdlp-download] 通知处理异常: {e}")
        
        return info
        
    except Exception as e:
        # 发送失败通知
        try:
            def send_fail_notify():
                try:
                    async def send():
                        connector = aiohttp.UnixConnector(path="/app/sockets/easy-vdl.sock")
                        async with aiohttp.ClientSession(connector=connector) as session:
                             await session.post("http://localhost/api/notifications/download-error", json={
                                "title": "❌ 下载失败 (通用解析)",
                                "content": f"通用解析下载出错\n🚫 错误: {str(e)[:200]}\n🆔 任务: {task_id}",
                                "user_id": "default",
                                "extra_data": {
                                    "task_id": task_id,
                                    "url": url
                                }
                            })
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(send())
                    loop.close()
                except: pass
            threading.Thread(target=send_fail_notify, daemon=True).start()
        except: pass

        # 确保进度任务被正确清理
        try:
            await progress_queue.put(None) # 发送结束信号
            await progress_task # 等待任务结束
        except:
            pass
        logging.error(f"[ytdlp-download] 任务执行失败: {str(e)}")
        
        # 更新任务状态为错误
        db.query(Task).filter(Task.id == task_id).update({
            'status': TaskStatus.ERROR.value,
            'error_message': str(e),
            'updated_at': datetime.now()
        })
        db.commit()
        
        # 广播错误状态（延迟导入避免循环依赖）
        import routers.websocket
        await routers.websocket.broadcast_message('downloads', {
            'type': 'status_update',
            'task': {
                'id': task_id,
                'status': TaskStatus.ERROR.value,
                'error_message': str(e),
                'updated_at': datetime.now().isoformat()
            }
        })
        raise
            
    finally:
        # 尝试强制归还系统内存 (Linux glibc)
        try:
            import ctypes
            libc = ctypes.CDLL("libc.so.6")
            libc.malloc_trim(0)
        except Exception:
            pass
        # 清理临时文件和取消标志
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                logging.error(f"[ytdlp-download] 清理临时文件失败: {str(e)}")
        
        # 清理取消标志
        if task_id in wnxt_cancel_flags:
            del wnxt_cancel_flags[task_id]
            logging.debug(f"[ytdlp-download] 已清理取消标志: {task_id}")
        
        try:
            db.rollback()
        except Exception:
            pass
        db.close()


@router.post("/cancel/{task_id}")
@require_license_api
async def cancel_universal_download(task_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """取消万能嗅探下载任务"""
    try:
        # 查找任务
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        # 检查任务状态
        if task.status in [TaskStatus.COMPLETED.value, TaskStatus.ERROR.value, TaskStatus.CANCELLED.value]:
            raise HTTPException(status_code=400, detail="任务已完成或已取消，无法再次取消")
        
        # 设置取消标志
        wnxt_cancel_flags[task_id] = True
        
        # 更新任务状态为已取消
        task.status = TaskStatus.CANCELLED.value
        task.updated_at = datetime.now()
        db.commit()
        
        logging.info(f"[universal-cancel] 任务已取消: {task_id}")
        
        return {"status": "success", "message": "任务已成功取消"}
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"[universal-cancel] 取消任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"取消任务失败: {str(e)}")
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()
