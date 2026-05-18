import asyncio
import html
import json
import logging
import os
import random
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from routers.dyd import sanitize_filename
from routers.websocket import broadcast_message
from sql.database_postgresql import get_session
from sql.models import Subscription, SubscriptionVideo, Task, TaskStatus


logger = logging.getLogger(__name__)
SETTINGS_DIR = "/app/database/instagram"
DEFAULT_MEDIA_COUNT = 50
REQUEST_BASE_DELAY = 2.0      # 基础延迟（秒）
REQUEST_JITTER_MAX = 3.0      # 随机抖动上限（秒），实际延迟 = base + random(0, jitter_max)
FULL_SYNC_PAGE_DELAY_RANGE = (5.0, 10.0)   # 全量同步页间随机等待
FULL_SYNC_LONG_PAUSE_EVERY = 10            # 全量同步每 N 页长暂停一次
FULL_SYNC_LONG_PAUSE_RANGE = (20.0, 30.0)
RISK_STATE_FILE = os.path.join(SETTINGS_DIR, "risk_state.json")
RISK_BASE_COOLDOWN_SECONDS = 20 * 60   # 首次风控冷却 20 分钟
RISK_MAX_COOLDOWN_SECONDS = 6 * 60 * 60  # 最大冷却 6 小时
RISK_KEYWORDS = (
    "429",
    "too many",
    "redirect",
    "403",
    "challenge",
    "checkpoint",
    "feedback_required",
    "login required",
    "login_required",
)


def _jittered_delay() -> None:
    """带随机抖动的等待，使请求间隔不均匀，降低被风控标记的概率。"""
    time.sleep(REQUEST_BASE_DELAY + random.random() * REQUEST_JITTER_MAX)


def full_sync_page_delay_seconds(page_no: int) -> float:
    """Instagram 全量同步分页等待策略，不限制总量，只放慢连续翻页节奏。"""
    delay = random.uniform(*FULL_SYNC_PAGE_DELAY_RANGE)
    if page_no > 0 and page_no % FULL_SYNC_LONG_PAUSE_EVERY == 0:
        delay += random.uniform(*FULL_SYNC_LONG_PAUSE_RANGE)
    return delay


def _load_risk_state() -> Dict[str, Any]:
    try:
        if not os.path.exists(RISK_STATE_FILE):
            return {}
        data = json.loads(Path(RISK_STATE_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_risk_state(state: Dict[str, Any]) -> None:
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        Path(RISK_STATE_FILE).write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _is_risk_error(message: str) -> bool:
    text = (message or "").lower()
    return any(keyword in text for keyword in RISK_KEYWORDS)


def is_instagram_risk_error(message: str) -> bool:
    return _is_risk_error(message)


def _risk_cooldown_seconds(failure_count: int) -> int:
    level = max(0, int(failure_count) - 1)
    return min(RISK_BASE_COOLDOWN_SECONDS * (2 ** level), RISK_MAX_COOLDOWN_SECONDS)


def _mark_risk_failure(reason: str) -> None:
    _clear_client_cache()
    state = _load_risk_state()
    failure_count = int(state.get("failure_count", 0) or 0) + 1
    cooldown_seconds = _risk_cooldown_seconds(failure_count)
    blocked_until = int(time.time()) + cooldown_seconds
    state.update({
        "failure_count": failure_count,
        "blocked_until": blocked_until,
        "last_reason": (reason or "")[:500],
        "last_failed_at": datetime.now(timezone.utc).isoformat(),
    })
    _save_risk_state(state)
    logger.warning(
        "Instagram 风控命中，进入冷却: count=%s cooldown=%ss until=%s reason=%s",
        failure_count,
        cooldown_seconds,
        datetime.fromtimestamp(blocked_until, tz=timezone.utc).isoformat(),
        (reason or "")[:180],
    )


def _clear_risk_failure() -> None:
    state = _load_risk_state()
    if not state:
        return
    if state.get("failure_count", 0) or state.get("blocked_until", 0):
        _save_risk_state({
            "failure_count": 0,
            "blocked_until": 0,
            "last_recovered_at": datetime.now(timezone.utc).isoformat(),
        })


def _ensure_not_in_cooldown() -> None:
    state = _load_risk_state()
    blocked_until = int(state.get("blocked_until", 0) or 0)
    now_ts = int(time.time())
    if blocked_until > now_ts:
        remain = blocked_until - now_ts
        raise RuntimeError(f"Instagram 处于风控冷却期，剩余约 {remain} 秒，请稍后再试")


def parse_instagram_username(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    if not text:
        return None
    if text.startswith("@"):
        text = text[1:]
    if text.startswith("http://") or text.startswith("https://"):
        parsed = urlparse(text)
        host = (parsed.netloc or "").lower()
        if "instagram.com" not in host:
            return None
        parts = [p for p in (parsed.path or "").split("/") if p]
        if not parts:
            return None
        if parts[0] in {"p", "reel", "reels", "stories", "explore", "accounts"}:
            return None
        text = parts[0]
    text = text.strip().strip("/")
    if not re.match(r"^[A-Za-z0-9._]{1,30}$", text):
        return None
    return text


def profile_url(username: str) -> str:
    return f"https://www.instagram.com/{username.strip('@')}/"


_client_cache = None  # instagrapi Client 实例缓存，避免重复验证
CREDENTIALS_KEY_FILE = os.path.join(SETTINGS_DIR, ".credentials.key")


def _load_encryption_key() -> bytes:
    """加载或生成 Fernet 加密密钥"""
    from cryptography.fernet import Fernet
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    if os.path.exists(CREDENTIALS_KEY_FILE):
        return Path(CREDENTIALS_KEY_FILE).read_bytes()
    key = Fernet.generate_key()
    Path(CREDENTIALS_KEY_FILE).write_bytes(key)
    return key


def _encrypt_password(password: str) -> str:
    from cryptography.fernet import Fernet
    key = _load_encryption_key()
    return Fernet(key).encrypt(password.encode()).decode()


def _decrypt_password(encrypted: str) -> str:
    from cryptography.fernet import Fernet
    key = _load_encryption_key()
    return Fernet(key).decrypt(encrypted.encode()).decode()


def _clear_client_cache():
    global _client_cache
    _client_cache = None


def _get_client():
    global _client_cache

    # 缓存命中 → 直接复用，不发任何验证请求
    if _client_cache is not None:
        return _client_cache

    try:
        from instagrapi import Client
        from instagrapi.exceptions import ClientLoginRequired
    except Exception as e:
        raise RuntimeError("缺少 instagrapi 依赖，请重新构建镜像或安装 instagrapi") from e

    os.makedirs(SETTINGS_DIR, exist_ok=True)
    _ensure_not_in_cooldown()

    # 从 credentials.json 读取账号密码
    creds_file = Path(SETTINGS_DIR) / "credentials.json"
    if not creds_file.exists():
        raise ValueError(
            "未配置 Instagram 账号密码，请在 WebUI「设置 - Cookie管理」中填写 Instagram 用户名和密码"
        )
    creds = json.loads(creds_file.read_text(encoding="utf-8"))
    username = (creds.get("username") or "").strip()
    encrypted_pw = (creds.get("password") or "")
    if not username or not encrypted_pw:
        raise ValueError("Instagram 账号密码未正确配置，请在 WebUI「设置 - Cookie管理」中重新填写")
    # 解密密码（兼容旧的明文格式）
    try:
        password = _decrypt_password(encrypted_pw)
    except Exception:
        password = encrypted_pw
        raise ValueError("Instagram 账号密码未正确配置，请在 WebUI「设置 - Cookie管理」中重新填写")

    settings_file = Path(SETTINGS_DIR) / "session.json"
    client = Client()

    # 尝试从已保存的 session 恢复（避免每次重新登录）
    if settings_file.exists():
        try:
            client.load_settings(json.loads(settings_file.read_text(encoding="utf-8")))
            client.login(username, password)  # session 有效时不会重复登录
            _client_cache = client
            return client
        except Exception:
            try:
                settings_file.unlink(missing_ok=True)
            except Exception:
                pass

    # 全新登录
    try:
        client.login(username, password)
        try:
            settings_file.write_text(json.dumps(client.get_settings()), encoding="utf-8")
        except Exception:
            pass
        _client_cache = client
        return client
    except Exception as e:
        try:
            settings_file.unlink(missing_ok=True)
        except Exception:
            pass
        raise ClientLoginRequired(f"Instagram 账号登录失败: {e}") from e


def _to_iso(value: Any) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _first_attr(obj: Any, names: List[str], default: Any = None) -> Any:
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return default


def _media_base(media: Any) -> Dict[str, Any]:
    code = getattr(media, "code", "") or ""
    return {
        "pk": str(getattr(media, "pk", "") or ""),
        "code": code,
        "post_url": f"https://www.instagram.com/p/{code}/" if code else "",
        "caption": getattr(media, "caption_text", "") or "",
        "like_count": getattr(media, "like_count", 0) or 0,
        "comment_count": getattr(media, "comment_count", 0) or 0,
        "taken_at": _to_iso(getattr(media, "taken_at", None)),
        "thumbnail_url": str(getattr(media, "thumbnail_url", "") or ""),
        "media_type": getattr(media, "media_type", None),
    }


def _flatten_media(media: Any) -> List[Dict[str, Any]]:
    base = _media_base(media)
    media_type = base.get("media_type")
    items: List[Dict[str, Any]] = []

    if media_type == 1:
        item = dict(base)
        item["platform_media_type"] = "image"
        item["image_url"] = base.get("thumbnail_url") or ""
        item["carousel_index"] = None
        items.append(item)
    elif media_type == 2:
        item = dict(base)
        item["platform_media_type"] = "video"
        item["video_url"] = str(getattr(media, "video_url", "") or "")
        item["view_count"] = getattr(media, "view_count", 0) or 0
        item["video_duration"] = getattr(media, "video_duration", None)
        item["carousel_index"] = None
        items.append(item)
    elif media_type == 8:
        resources = getattr(media, "resources", None) or []
        for index, resource in enumerate(resources, start=1):
            child_type = getattr(resource, "media_type", None)
            if child_type not in (1, 2):
                continue
            item = dict(base)
            item["child_pk"] = str(getattr(resource, "pk", "") or "")
            item["platform_media_type"] = "video" if child_type == 2 else "image"
            item["thumbnail_url"] = str(getattr(resource, "thumbnail_url", "") or base.get("thumbnail_url") or "")
            item["image_url"] = item["thumbnail_url"] if child_type == 1 else ""
            item["video_url"] = str(getattr(resource, "video_url", "") or "") if child_type == 2 else ""
            item["view_count"] = getattr(resource, "view_count", 0) or 0
            item["video_duration"] = getattr(resource, "video_duration", None)
            item["carousel_index"] = index
            items.append(item)
    return items


def get_user_info_sync(username_or_url: str) -> Dict[str, Any]:
    username = parse_instagram_username(username_or_url)
    if not username:
        raise ValueError("请输入有效的 Instagram 用户名或主页链接")
    try:
        client = _get_client()
        _jittered_delay()
        info = client.user_info_by_username(username)
    except Exception as e:
        if _is_risk_error(str(e)):
            _mark_risk_failure(str(e))
        raise
    username = _first_attr(info, ["username"], username)
    full_name = _first_attr(info, ["full_name"], "") or username
    profile_pic_url = _first_attr(info, ["profile_pic_url", "profile_pic_url_hd"], "")
    result = {
        "user_id": username,
        "username": username,
        "nickname": full_name,
        "avatar_url": str(profile_pic_url) if profile_pic_url else "",
        "follower_count": _first_attr(info, ["follower_count", "followers_count"], 0) or 0,
        "following_count": _first_attr(info, ["following_count", "followings_count"], 0) or 0,
        "video_count": _first_attr(info, ["media_count"], 0) or 0,
        "signature": _first_attr(info, ["biography"], "") or "",
        "is_private": _first_attr(info, ["is_private"], False) or False,
        "profile_url": profile_url(username),
    }
    _clear_risk_failure()
    return result


def get_user_medias_sync(username_or_url: str, count: int = DEFAULT_MEDIA_COUNT) -> List[Dict[str, Any]]:
    username = parse_instagram_username(username_or_url)
    if not username:
        raise ValueError("请输入有效的 Instagram 用户名或主页链接")
    try:
        client = _get_client()
        _jittered_delay()
        user_id = client.user_id_from_username(username)
        _jittered_delay()
        medias = client.user_medias(user_id, count)
    except Exception as e:
        if _is_risk_error(str(e)):
            _mark_risk_failure(str(e))
        raise
    items: List[Dict[str, Any]] = []
    for media in medias:
        items.extend(_flatten_media(media))
    _clear_risk_failure()
    return items


def get_user_id_sync(username_or_url: str) -> str:
    username = parse_instagram_username(username_or_url)
    if not username:
        raise ValueError("请输入有效的 Instagram 用户名或主页链接")
    try:
        client = _get_client()
        _jittered_delay()
        value = str(client.user_id_from_username(username))
    except Exception as e:
        if _is_risk_error(str(e)):
            _mark_risk_failure(str(e))
        raise
    _clear_risk_failure()
    return value


def get_user_medias_page_sync(user_id: str, count: int = DEFAULT_MEDIA_COUNT, end_cursor: str = "") -> Dict[str, Any]:
    try:
        client = _get_client()
        _jittered_delay()
        medias, next_cursor = client.user_medias_paginated(str(user_id), amount=count, end_cursor=end_cursor or "")
    except Exception as e:
        if _is_risk_error(str(e)):
            _mark_risk_failure(str(e))
        raise
    items: List[Dict[str, Any]] = []
    for media in medias:
        items.extend(_flatten_media(media))
    result = {
        "items": items,
        "next_cursor": next_cursor or "",
        "post_count": len(medias),
    }
    _clear_risk_failure()
    return result


async def get_user_info(username_or_url: str) -> Dict[str, Any]:
    return await asyncio.to_thread(get_user_info_sync, username_or_url)


async def get_user_medias(username_or_url: str, count: int = DEFAULT_MEDIA_COUNT) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(get_user_medias_sync, username_or_url, count)


async def get_user_id(username_or_url: str) -> str:
    return await asyncio.to_thread(get_user_id_sync, username_or_url)


async def get_user_medias_page(user_id: str, count: int = DEFAULT_MEDIA_COUNT, end_cursor: str = "") -> Dict[str, Any]:
    return await asyncio.to_thread(get_user_medias_page_sync, user_id, count, end_cursor)


def normalize_media_item(item: Dict[str, Any]) -> Dict[str, Any]:
    post_pk = str(item.get("pk") or item.get("code") or "")
    code = str(item.get("code") or "")
    carousel_index = item.get("carousel_index")
    video_id = f"{post_pk}_{carousel_index}" if carousel_index else post_pk
    media_type = item.get("platform_media_type") or "image"
    direct_url = item.get("video_url") if media_type == "video" else item.get("image_url")
    if not direct_url:
        direct_url = item.get("post_url") or (f"https://www.instagram.com/p/{code}/" if code else "")
    title_source = (item.get("caption") or "").strip()
    title = title_source[:120] if title_source else f"Instagram {media_type} {code or video_id}"
    publish_time = None
    taken_at = item.get("taken_at")
    if taken_at:
        try:
            publish_time = datetime.fromisoformat(str(taken_at).replace("Z", "+00:00"))
        except Exception:
            publish_time = None
    extra_data = {
        "platform_media_type": media_type,
        "post_code": code,
        "post_pk": post_pk,
        "parent_post_url": item.get("post_url") or "",
        "carousel_index": carousel_index,
        "direct_url": direct_url,
        "raw": {
            "media_type": item.get("media_type"),
            "like_count": item.get("like_count", 0),
            "comment_count": item.get("comment_count", 0),
            "view_count": item.get("view_count", 0),
        },
    }
    return {
        "video_id": video_id,
        "title": title,
        "description": item.get("caption") or "",
        "url": direct_url,
        "cover_url": item.get("thumbnail_url") or direct_url,
        "duration": item.get("video_duration"),
        "publish_time": publish_time,
        "extra_data": extra_data,
        "stats": extra_data["raw"],
    }


def _guess_ext(url: str, media_type: str) -> str:
    path = urlparse(url or "").path.lower()
    _, ext = os.path.splitext(path)
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov"}:
        return ext
    return ".mp4" if media_type == "video" else ".jpg"


def _build_instagram_output_path(base_dir: str, task: Task, extra: Dict[str, Any], direct_url: str, media_type: str) -> str:
    post_code = sanitize_filename(extra.get("post_code") or "", max_length=40)
    title = sanitize_filename(task.title or post_code or task.id, max_length=70)
    if not post_code or post_code == "untitled":
        post_code = sanitize_filename(str(extra.get("post_pk") or task.id), max_length=40)

    if title == "untitled":
        folder_name = post_code
    elif title.startswith(post_code):
        folder_name = sanitize_filename(title, max_length=90)
    else:
        folder_name = sanitize_filename(f"{post_code}_{title}", max_length=90)

    post_dir = os.path.join(base_dir, folder_name)
    os.makedirs(post_dir, exist_ok=True)

    carousel_index = extra.get("carousel_index")
    if carousel_index:
        try:
            item_name = f"{post_code}_{int(carousel_index):02d}"
        except Exception:
            item_name = f"{post_code}_{carousel_index}"
    else:
        item_name = post_code

    ext = _guess_ext(direct_url, media_type)
    return os.path.join(post_dir, f"{item_name}{ext}")


def _xml_text(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=False)


def _nfo_date(value: Optional[datetime]) -> str:
    if not value:
        return ""
    if value.tzinfo:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _instagram_parent_url(extra: Dict[str, Any]) -> str:
    parent_url = extra.get("parent_post_url") or ""
    if parent_url:
        return parent_url
    post_code = extra.get("post_code") or ""
    return f"https://www.instagram.com/p/{post_code}/" if post_code else ""


async def _download_instagram_poster(client: httpx.AsyncClient, source_url: str, poster_path: str) -> bool:
    if not source_url:
        return False
    try:
        response = await client.get(source_url, timeout=60.0)
        response.raise_for_status()
        tmp_path = poster_path + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(response.content)
        try:
            os.replace(tmp_path, poster_path)
        except Exception:
            shutil.move(tmp_path, poster_path)
        return os.path.exists(poster_path) and os.path.getsize(poster_path) > 0
    except Exception as e:
        logger.warning(f"Instagram poster 下载失败: {e}")
        return False


async def _ensure_instagram_poster(client: httpx.AsyncClient, output_path: str, media_type: str, video: Optional[SubscriptionVideo], direct_url: str) -> Optional[str]:
    post_dir = os.path.dirname(output_path)
    poster_path = os.path.join(post_dir, "poster.jpg")
    if os.path.exists(poster_path) and os.path.getsize(poster_path) > 0:
        return "poster.jpg"

    try:
        if media_type == "image" and os.path.exists(output_path):
            shutil.copyfile(output_path, poster_path)
            return "poster.jpg"
    except Exception as e:
        logger.warning(f"Instagram poster 复制失败: {e}")

    cover_url = video.cover_url if video else None
    if await _download_instagram_poster(client, cover_url or direct_url, poster_path):
        return "poster.jpg"
    return None


def _write_instagram_nfo(
    output_path: str,
    task: Task,
    video: Optional[SubscriptionVideo],
    extra: Dict[str, Any],
    media_type: str,
    poster_filename: Optional[str],
) -> None:
    post_code = extra.get("post_code") or ""
    title = task.title or (video.title if video else None) or post_code or task.id
    description = video.description if video else ""
    publish_time = _nfo_date(video.publish_time if video else None)
    year = publish_time[:4] if publish_time else ""
    parent_url = _instagram_parent_url(extra)
    carousel_index = extra.get("carousel_index")
    media_label = "Instagram Image" if media_type == "image" else "Instagram Video"

    author = ""
    db = get_session()
    try:
        if video and video.subscription_id:
            subscription = db.query(Subscription).filter(Subscription.id == video.subscription_id).first()
            if subscription:
                author = subscription.nickname or subscription.user_id or ""
    except Exception:
        author = ""
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()

    nfo_content = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<movie>
  <title>{_xml_text(title)}</title>
  <originaltitle>{_xml_text(title)}</originaltitle>
  <year>{_xml_text(year)}</year>
  <plot>{_xml_text(description)}</plot>
  <director>{_xml_text(author)}</director>
  <premiered>{_xml_text(publish_time)}</premiered>
  <studio>Instagram</studio>
  <trailer>{_xml_text(parent_url)}</trailer>
  <source>instagram</source>
  <genre>{_xml_text(media_label)}</genre>
  <tag>Instagram</tag>
  <tag>{_xml_text(media_type)}</tag>
  <tag>{_xml_text(post_code)}</tag>
  <thumb>{_xml_text(poster_filename or "")}</thumb>
  <uniqueid type="instagram">{_xml_text(post_code)}</uniqueid>
  <set>{_xml_text(post_code)}</set>
  <sorttitle>{_xml_text(f"{post_code}_{carousel_index}" if carousel_index else post_code)}</sorttitle>
  <actor>
    <name>{_xml_text(author)}</name>
    <role>Uploader</role>
  </actor>
</movie>

'''
    nfo_path = os.path.splitext(output_path)[0] + ".nfo"
    with open(nfo_path, "w", encoding="utf-8") as f:
        f.write(nfo_content)


def _instagram_author_name(video: Optional[SubscriptionVideo]) -> str:
    if not video or not video.subscription_id:
        return "Instagram"
    db = get_session()
    try:
        subscription = db.query(Subscription).filter(Subscription.id == video.subscription_id).first()
        if subscription:
            return subscription.nickname or subscription.user_id or "Instagram"
    except Exception:
        pass
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()
    return "Instagram"


async def _send_instagram_notification(
    endpoint: str,
    title: str,
    content: str,
    extra_data: Dict[str, Any],
) -> None:
    try:
        async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds="/app/sockets/easy-vdl.sock"), timeout=10.0) as client:
            await client.post(
                f"http://localhost/api/notifications/{endpoint}",
                json={
                    "title": title,
                    "content": content,
                    "user_id": "default",
                    "extra_data": extra_data,
                },
            )
    except Exception as e:
        logger.warning(f"Instagram 通知发送失败（不影响下载任务）: {e}")


async def _notify_instagram_download_completed(
    task: Task,
    video: Optional[SubscriptionVideo],
    extra: Dict[str, Any],
    media_type: str,
    output_path: str,
    poster_filename: Optional[str],
) -> None:
    rel_path = os.path.relpath(output_path, "/app/downloads").replace("\\", "/")
    poster_path = None
    if poster_filename:
        poster_abs = os.path.join(os.path.dirname(output_path), poster_filename)
        if os.path.exists(poster_abs):
            poster_path = f"/downloads/{os.path.relpath(poster_abs, '/app/downloads').replace(os.sep, '/')}"

    author_name = _instagram_author_name(video)
    media_label = "图片" if media_type == "image" else "视频"
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parent_url = _instagram_parent_url(extra) or task.url
    extra_data = {
        "task_id": task.id,
        "subscription_id": task.subscription_id or (video.subscription_id if video else None),
        "source": "instagram",
        "url": parent_url,
        "source_url": parent_url,
        "file_path": rel_path,
        "local_path": rel_path,
        "download_path": rel_path,
        "cover": poster_path,
        "poster": poster_path,
        "platform_media_type": media_type,
        "post_code": extra.get("post_code"),
        "post_pk": extra.get("post_pk"),
        "carousel_index": extra.get("carousel_index"),
    }
    await _send_instagram_notification(
        "download-completed",
        f"🎉 下载完成 (Instagram)",
        f"Instagram {media_label}《{task.title or extra.get('post_code') or task.id}》下载完成！\n\n🏷️ 来源: Instagram\n👤 {author_name}\n⏰ 完成时间: {current_time}",
        extra_data,
    )


async def _notify_instagram_download_error(
    task: Optional[Task],
    video: Optional[SubscriptionVideo],
    extra: Dict[str, Any],
    error: Exception,
    fallback_url: str,
    fallback_subscription_id: Optional[str],
) -> None:
    media_type = extra.get("platform_media_type") or "media"
    media_label = "图片" if media_type == "image" else "视频"
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parent_url = _instagram_parent_url(extra) or (task.url if task else fallback_url)
    title = (task.title if task else None) or extra.get("post_code") or "Instagram"
    extra_data = {
        "task_id": task.id if task else None,
        "subscription_id": (task.subscription_id if task else None) or (video.subscription_id if video else None) or fallback_subscription_id,
        "source": "instagram",
        "url": parent_url,
        "source_url": parent_url,
        "platform_media_type": media_type,
        "post_code": extra.get("post_code"),
        "post_pk": extra.get("post_pk"),
        "carousel_index": extra.get("carousel_index"),
    }
    await _send_instagram_notification(
        "download-error",
        "❌ 下载失败 (Instagram)",
        f"Instagram {media_label}《{title}》下载失败！\n\n🏷️ 来源: Instagram\n🚫 错误信息: {str(error)[:300]}\n⏰ 失败时间: {current_time}",
        extra_data,
    )


async def _refresh_direct_url(video: SubscriptionVideo, media_type: str) -> Optional[str]:
    subscription_id = video.subscription_id
    db = get_session()
    try:
        subscription = db.query(Subscription).filter(Subscription.id == subscription_id).first()
        if not subscription:
            return None
        extra = json.loads(video.extra_data or "{}")
        post_pk = str(extra.get("post_pk") or "")
        carousel_index = extra.get("carousel_index")

        # 分页扫描：最多扫 500 条，直到找到 target post_pk
        # 仅首次调用会走完，后续 CDN 触发时会复用缓存的直链
        resolved_user_id = await get_user_id(subscription.user_id)
        end_cursor = ""
        max_scan = 500
        scanned = 0

        while scanned < max_scan:
            page = await get_user_medias_page(
                resolved_user_id,
                count=DEFAULT_MEDIA_COUNT,
                end_cursor=end_cursor
            )
            batch = page.get("items", []) or []
            if not batch:
                break

            for item in batch:
                normalized = normalize_media_item(item)
                item_extra = normalized.get("extra_data") or {}
                if str(item_extra.get("post_pk") or "") == post_pk and item_extra.get("carousel_index") == carousel_index:
                    return normalized.get("url")

            scanned += len(batch)
            end_cursor = page.get("next_cursor") or ""
            if not end_cursor:
                break

        return None
    except Exception:
        return None
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()


async def instagram_download_task(task_id: str, url: str, download_dir: Optional[str] = None, subscription_id: Optional[str] = None):
    db = get_session()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return
        video = db.query(SubscriptionVideo).filter(SubscriptionVideo.download_task_id == task_id).first()
        extra = {}
        if video and video.extra_data:
            try:
                extra = json.loads(video.extra_data)
            except Exception:
                extra = {}
        media_type = extra.get("platform_media_type") or ("video" if ".mp4" in (url or "").lower() else "image")
        direct_url = extra.get("direct_url") or url

        task.status = TaskStatus.DOWNLOADING.value
        task.progress = 5
        task.updated_at = datetime.now()
        db.commit()
        await broadcast_message('downloads', {
            "type": "progress_update",
            "task": {
                "id": task_id,
                "status": task.status,
                "progress": task.progress,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                "filename": task.filename,
                "source": task.source,
                "title": task.title,
                "url": task.url,
                "subscription_id": task.subscription_id,
                "created_at": task.created_at.isoformat() if task.created_at else None
            }
        })

        if (not direct_url or "instagram.com/p/" in direct_url or "instagram.com/reel/" in direct_url) and video:
            refreshed = await _refresh_direct_url(video, media_type)
            if refreshed:
                direct_url = refreshed

        if not direct_url:
            raise RuntimeError("无法获取 Instagram 媒体下载链接")

        base_dir = download_dir or "/app/downloads/instagram"
        os.makedirs(base_dir, exist_ok=True)
        output_path = _build_instagram_output_path(base_dir, task, extra, direct_url, media_type)

        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": "https://www.instagram.com/",
        }
        async with httpx.AsyncClient(follow_redirects=True, timeout=120.0, headers=headers) as client:
            async with client.stream("GET", direct_url) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length") or 0)
                downloaded = 0
                with open(output_path, "wb") as f:
                    async for chunk in response.aiter_bytes(1024 * 256):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            progress = min(95, 5 + downloaded * 90 / total)
                            task.progress = progress
                            task.updated_at = datetime.now()
                            db.commit()
                            await broadcast_message('downloads', {
                                "type": "progress_update",
                                "task": {
                                    "id": task_id,
                                    "status": task.status,
                                    "progress": task.progress,
                                    "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                                    "filename": task.filename,
                                    "source": task.source,
                                    "title": task.title,
                                    "url": task.url,
                                    "subscription_id": task.subscription_id,
                                    "created_at": task.created_at.isoformat() if task.created_at else None
                                }
                            })

            poster_filename = None
            try:
                poster_filename = await _ensure_instagram_poster(client, output_path, media_type, video, direct_url)
                _write_instagram_nfo(output_path, task, video, extra, media_type, poster_filename)
            except Exception as scrape_error:
                logger.warning(f"Instagram 刮削文件生成失败，但媒体下载已完成: {scrape_error}")

        rel_path = os.path.relpath(output_path, "/app/downloads")
        task.status = TaskStatus.COMPLETED.value
        task.progress = 100
        task.filename = rel_path
        task.updated_at = datetime.now()
        if video:
            video.downloaded = "true"
            video.error_message = None
        db.commit()
        await broadcast_message('downloads', {
            "type": "progress_update",
            "task": {
                "id": task_id,
                "status": task.status,
                "progress": task.progress,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                "filename": task.filename,
                "source": task.source,
                "title": task.title,
                "url": task.url,
                "subscription_id": task.subscription_id,
                "created_at": task.created_at.isoformat() if task.created_at else None
            }
        })
        await _notify_instagram_download_completed(task, video, extra, media_type, output_path, poster_filename)
    except Exception as e:
        notify_task = None
        notify_video = None
        notify_extra = {}
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            notify_task = task
            if task:
                task.status = TaskStatus.ERROR.value
                task.error_message = str(e)
                task.updated_at = datetime.now()
            video = db.query(SubscriptionVideo).filter(SubscriptionVideo.download_task_id == task_id).first()
            notify_video = video
            if video:
                if video.extra_data:
                    try:
                        notify_extra = json.loads(video.extra_data)
                    except Exception:
                        notify_extra = {}
                video.downloaded = "false"
                video.error_message = str(e)
            db.commit()
            await broadcast_message('downloads', {
                "type": "progress_update",
                "task": {
                    "id": task_id,
                    "status": task.status if task else TaskStatus.ERROR.value,
                    "progress": task.progress if task else 0,
                    "error_message": str(e),
                    "updated_at": task.updated_at.isoformat() if task and task.updated_at else None,
                    "filename": task.filename if task else None,
                    "source": task.source if task else "instagram",
                    "title": task.title if task else None,
                    "url": task.url if task else url,
                    "subscription_id": task.subscription_id if task else subscription_id,
                    "created_at": task.created_at.isoformat() if task and task.created_at else None
                }
            })
        except Exception:
            pass
        await _notify_instagram_download_error(notify_task, notify_video, notify_extra, e, url, subscription_id)
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()
