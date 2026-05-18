"""
代理服务相关路由
"""
import httpx
import io
import os
import hashlib
from fastapi import APIRouter, HTTPException, Query, Header
from fastapi.responses import Response, FileResponse
from routers.auth import require_license_api
from .common import logger

router = APIRouter()

# 文件缓存目录
CACHE_DIR = "/tmp/image_cache"
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR, exist_ok=True)


@router.get("/proxy/image")
@require_license_api
async def proxy_image(
    url: str = Query(..., description="图片URL"),
    if_none_match: str = Header(None)
):
    """代理图片请求，解决跨域/防盗链问题，并转换HEIC格式"""
    try:
        # 验证URL是否合法
        if not url or not url.startswith(('http://', 'https://')):
            raise HTTPException(status_code=400, detail="无效的图片URL")
        
        # 只允许代理白名单域名（B站/小红书/YouTube/Instagram/抖音 头像与封面）
        allowed_domains = [
            'hdslb.com',
            'bilibili.com',
            'biliimg.com',
            'xhscdn.com',
            'yt3.googleusercontent.com',
            'googleusercontent.com',
            'ytimg.com',
            'ggpht.com',
            'cdninstagram.com',
            'fbcdn.net',
            'instagram.com',
            'douyinpic.com',
            'byteimg.com',
            'douyinstatic.com',
        ]
        if not any(domain in url for domain in allowed_domains):
            raise HTTPException(status_code=400, detail="只允许代理白名单图片域名")
        
        # 计算缓存文件名 (MD5)
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_path = os.path.join(CACHE_DIR, f"{url_hash}.jpg")
        etag = f'"{url_hash}"'
        
        # 1. 检查浏览器缓存 (304)
        if if_none_match == etag:
            return Response(status_code=304)
        
        # 2. 检查本地文件缓存
        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
            # logger.debug(f"从文件缓存返回图片: {url}")
            return FileResponse(
                path=cache_path,
                media_type="image/jpeg",
                headers={
                    'Cache-Control': 'public, max-age=604800, immutable',
                    'Access-Control-Allow-Origin': '*',
                    'ETag': etag,
                    'Vary': 'Accept-Encoding',
                    'X-Cache': 'HIT'
                }
            )
        
        # 3. 下载并处理图片
        # 根据URL设置合适的Referer
        if 'xhscdn.com' in url:
            referer = 'https://www.xiaohongshu.com/'
        elif any(domain in url for domain in ['douyinpic.com', 'byteimg.com', 'douyinstatic.com']):
            referer = 'https://www.douyin.com/'
        elif any(domain in url for domain in ['cdninstagram.com', 'fbcdn.net', 'instagram.com']):
            referer = 'https://www.instagram.com/'
        elif any(domain in url for domain in ['googleusercontent.com', 'ytimg.com', 'ggpht.com']):
            referer = 'https://www.youtube.com/'
        else:
            referer = 'https://www.bilibili.com/'
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': referer,
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            
            if response.status_code == 200:
                content_type = response.headers.get("content-type", "image/jpeg")
                content = response.content
                
                # 检测HEIC格式并转换为JPEG
                is_heic = (
                    '.heic' in url.lower() or 
                    'image/heic' in content_type.lower() or 
                    'image/heif' in content_type.lower()
                )
                
                if is_heic:
                    try:
                        from pillow_heif import register_heif_opener
                        from PIL import Image
                        
                        register_heif_opener()
                        img = Image.open(io.BytesIO(content))
                        
                        # 缩小图片尺寸以提升性能（缩略图不需要高分辨率）
                        max_width = 400
                        if img.width > max_width:
                            ratio = max_width / img.width
                            new_height = int(img.height * ratio)
                            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
                        
                        if img.mode in ('RGBA', 'LA', 'P'):
                            background = Image.new('RGB', img.size, (255, 255, 255))
                            if img.mode == 'P':
                                img = img.convert('RGBA')
                            background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                            img = background
                        elif img.mode != 'RGB':
                            img = img.convert('RGB')
                        
                        # 保存为JPEG（质量60）
                        output = io.BytesIO()
                        img.save(output, format='JPEG', quality=60)
                        content = output.getvalue()
                        content_type = 'image/jpeg'
                        
                        logger.info(f"已将HEIC格式转换为JPEG: {url}")
                    except Exception as e:
                        logger.error(f"HEIC转换失败: {url}, 错误: {str(e)}")
                
                # 写入文件缓存 (先写临时文件再重命名，保证原子性)
                temp_path = cache_path + ".tmp"
                try:
                    with open(temp_path, "wb") as f:
                        f.write(content)
                    os.rename(temp_path, cache_path)
                except Exception as e:
                    logger.error(f"写入缓存失败: {e}")
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                
                # 返回即时内容
                return Response(
                    content=content,
                    media_type=content_type,
                    headers={
                        'Cache-Control': 'public, max-age=604800, immutable',
                        'Access-Control-Allow-Origin': '*',
                        'ETag': etag,
                        'Vary': 'Accept-Encoding',
                        'X-Cache': 'MISS'
                    }
                )
            else:
                logger.error(f"代理图片失败，状态码: {response.status_code}, URL: {url}")
                raise HTTPException(status_code=response.status_code, detail="图片获取失败")
                
    except HTTPException:
        raise
    except httpx.TimeoutException:
        logger.error(f"代理图片超时: {url}")
        raise HTTPException(status_code=504, detail="图片获取超时")
    except httpx.RequestError as e:
        logger.error(f"代理图片请求失败: {url}, 错误: {str(e)}")
        raise HTTPException(status_code=500, detail="图片请求失败")
    except Exception as e:
        logger.error(f"代理图片异常: {url}, 错误: {str(e)}")
        raise HTTPException(status_code=500, detail="图片代理失败")
