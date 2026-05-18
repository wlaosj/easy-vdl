#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
X(Twitter) GraphQL API helpers (Likes + UserByScreenName)

依赖：auth_token + ct0 cookie
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import logging

import httpx

try:
    from curl_cffi import requests as cffi_requests  # type: ignore
except Exception:  # pragma: no cover - optional
    cffi_requests = None


X_BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

DEFAULT_LIKES_QUERY_ID = "RozQdCp4CilQzrcuU0NY5w"
DEFAULT_USER_QUERY_ID = "IGgvgiOx4QZndDHuD3x9TQ"
CURRENT_LIKES_QUERY_ID = DEFAULT_LIKES_QUERY_ID
CURRENT_USER_QUERY_ID = DEFAULT_USER_QUERY_ID

logger = logging.getLogger(__name__)

_KNOWN_FALSE_FEATURES = {
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled",
    "rweb_tipjar_consumption_enabled",
    "premium_content_api_read_enabled",
    "responsive_web_grok_analyze_button_fetch_trends_enabled",
    "responsive_web_grok_analyze_post_followups_enabled",
    "responsive_web_grok_show_grok_translated_post",
    "responsive_web_grok_community_note_auto_translation_is_enabled",
    "tweet_awards_web_tipping_enabled",
    "post_ctas_fetch_enabled",
    "longform_notetweets_inline_media_enabled",
    "responsive_web_enhance_cards_enabled",
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled",
}

GRAPHQL_FEATURES = {
    "rweb_video_screen_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": False,
    "rweb_tipjar_consumption_enabled": False,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": False,
    "responsive_web_jetfuel_frame": True,
    "responsive_web_grok_share_attachment_enabled": True,
    "responsive_web_grok_annotations_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "content_disclosure_indicator_enabled": True,
    "content_disclosure_ai_generated_indicator_enabled": True,
    "responsive_web_grok_show_grok_translated_post": False,
    "responsive_web_grok_analysis_button_from_backend": True,
    "post_ctas_fetch_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": False,
    "responsive_web_grok_image_annotation_enabled": True,
    "responsive_web_grok_imagine_annotation_enabled": True,
    "responsive_web_grok_community_note_auto_translation_is_enabled": False,
    "responsive_web_enhance_cards_enabled": False,
}


@dataclass
class XUserInfo:
    screen_name: str
    user_id: str
    nickname: str
    avatar_url: str | None = None
    follower_count: int | None = None
    following_count: int | None = None
    video_count: int | None = None
    signature: str | None = None


_cached_user_id: dict[str, str] = {}


def _cookies_path() -> str:
    return os.getenv("X_COOKIES_FILE", "/app/database/cookie/x.txt")


def parse_screen_name(value: str | None) -> str:
    if not value:
        return ""
    raw = value.strip()
    if raw.startswith("@"):
        return raw[1:]
    if "x.com/" in raw or "twitter.com/" in raw:
        match = re.search(r"(?:x|twitter)\.com/([^/?#]+)", raw)
        if match:
            handle = match.group(1)
            if handle.startswith("@"):
                handle = handle[1:]
            return handle
    return raw.lstrip("@")


def _parse_cookies_from_netscape(cookie_path: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    try:
        with open(cookie_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                domain = parts[0].lower().lstrip(".")
                name, value = parts[5], parts[6]
                if domain in ("twitter.com", "x.com") or domain.endswith(".twitter.com") or domain.endswith(".x.com"):
                    cookies[name] = value
    except OSError:
        pass
    return cookies


def _build_headers(ct0: str) -> dict[str, str]:
    return {
        "authorization": f"Bearer {urllib.parse.unquote(X_BEARER_TOKEN)}",
        "x-csrf-token": ct0,
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
        "content-type": "application/json",
    }


def _build_session(cookies: dict[str, str]):
    ct0 = cookies.get("ct0", "")
    headers = _build_headers(ct0)
    proxy = os.getenv("HTTP_PROXY") or os.getenv("http_proxy") or os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
    if cffi_requests:
        sess = cffi_requests.Session(impersonate="chrome")
        sess.headers.update(headers)
        for name, value in cookies.items():
            sess.cookies.set(name, value, domain=".x.com")
        if proxy:
            sess.proxies = {"https": proxy, "http": proxy}
        return sess

    client = httpx.Client(headers=headers, timeout=30)
    for name, value in cookies.items():
        client.cookies.set(name, value, domain=".x.com")
    if proxy:
        # 当前环境的 httpx 版本不一定支持 proxies 参数，依赖环境变量代理
        # 需要的话请在容器环境中设置 HTTP_PROXY/HTTPS_PROXY
        pass
    return client


def _get_json(sess, url: str) -> dict:
    resp = sess.get(url, timeout=30)
    if resp.status_code in (401, 403):
        raise RuntimeError(f"GraphQL 返回 {resp.status_code}: cookies 可能已过期")
    if resp.status_code == 429:
        raise RuntimeError("GraphQL 触发限流 (429)")
    if resp.status_code == 404:
        raise RuntimeError(f"GraphQL 返回 404 (queryId 可能失效): {url}")
    resp.raise_for_status()
    return resp.json()


def _resolve_user_id(sess, screen_name: str, user_query_id: str) -> str | None:
    if screen_name in _cached_user_id:
        return _cached_user_id[screen_name]
    variables = json.dumps({"screen_name": screen_name, "withSafetyModeUserFields": True})
    features = json.dumps({
        "hidden_profile_subscriptions_enabled": True,
        "profile_label_improvements_pcf_label_in_post_enabled": True,
        "responsive_web_profile_redirect_enabled": False,
        "rweb_tipjar_consumption_enabled": False,
        "verified_phone_label_enabled": False,
        "subscriptions_verification_info_is_identity_verified_enabled": True,
        "subscriptions_verification_info_verified_since_enabled": True,
        "highlights_tweets_tab_ui_enabled": True,
        "responsive_web_twitter_article_notes_tab_enabled": True,
        "subscriptions_feature_can_gift_premium": True,
        "creator_subscriptions_tweet_preview_api_enabled": True,
        "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
        "responsive_web_graphql_timeline_navigation_enabled": True,
    })
    url = (
        f"https://x.com/i/api/graphql/{user_query_id}/UserByScreenName"
        f"?variables={urllib.parse.quote(variables)}&features={urllib.parse.quote(features)}"
    )
    data = _get_json(sess, url)
    uid = data.get("data", {}).get("user", {}).get("result", {}).get("rest_id")
    if uid:
        _cached_user_id[screen_name] = uid
    return uid


def _auto_discover_graphql() -> dict:
    """从 X 前端 JS bundle 中提取 GraphQL 端点的 queryId 和 featureSwitches。"""
    targets = {"Likes", "UserByScreenName"}
    result: dict[str, dict] = {}

    proxy = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("http_proxy") or os.getenv("https_proxy")
    use_cffi = cffi_requests is not None
    if use_cffi:
        sess = cffi_requests.Session(impersonate="chrome")
        if proxy:
            sess.proxies = {"https": proxy, "http": proxy}
    else:
        sess = httpx.Client(timeout=20, follow_redirects=True)

    try:
        if use_cffi:
            resp = sess.get("https://x.com", timeout=20, allow_redirects=True)
        else:
            resp = sess.get("https://x.com", timeout=20)
        html = resp.text
    except Exception as exc:
        logger.warning("自动发现: 无法访问 x.com: %s", exc)
        try:
            sess.close()
        except Exception:
            pass
        return result

    js_urls = re.findall(r'src="(https://abs\\.twimg\\.com/responsive-web/client-web[^"]*\\.js)"', html)
    if not js_urls:
        js_urls = re.findall(r'src="(https://abs\\.twimg\\.com/[^"]*\\.js)"', html)
    if not js_urls:
        logger.warning("自动发现: HTML 中未找到 JS bundle URL")
        try:
            sess.close()
        except Exception:
            pass
        return result

    logger.info("自动发现: 找到 %d 个 JS bundle，开始扫描...", len(js_urls))

    endpoint_pattern = re.compile(
        r'\\{queryId:"([^"]{10,40})",operationName:"([^"]+)",operationType:"\\w+"'
        r',metadata:\\{featureSwitches:\\[([^\\]]*)\\]'
    )
    qid_only_pattern = re.compile(
        r'queryId:"([^"]{10,40})",operationName:"(Likes|UserByScreenName)"'
    )

    for url in js_urls:
        if len(result) >= len(targets):
            break
        try:
            js_text = sess.get(url, timeout=15).text
        except Exception:
            continue

        for m in endpoint_pattern.finditer(js_text):
            qid, op_name, features_raw = m.group(1), m.group(2), m.group(3)
            if op_name in targets and op_name not in result:
                feature_keys = [k.strip().strip('"').strip("'") for k in features_raw.split(",") if k.strip()]
                features = {k: (k not in _KNOWN_FALSE_FEATURES) for k in feature_keys}
                result[op_name] = {"queryId": qid, "features": features}
                logger.info("自动发现: %s -> queryId=%s (%d features)", op_name, qid, len(features))

        if len(result) < len(targets):
            for m in qid_only_pattern.finditer(js_text):
                qid, op_name = m.group(1), m.group(2)
                if op_name not in result:
                    result[op_name] = {"queryId": qid}
                    logger.info("自动发现: %s -> queryId=%s (features 使用默认)", op_name, qid)

    try:
        sess.close()
    except Exception:
        pass
    return result


def _refresh_query_ids(sess) -> None:
    """刷新 queryId（如失效时自动发现）"""
    global CURRENT_LIKES_QUERY_ID, CURRENT_USER_QUERY_ID, GRAPHQL_FEATURES
    discovered = _auto_discover_graphql()
    if "Likes" in discovered:
        CURRENT_LIKES_QUERY_ID = discovered["Likes"]["queryId"]
        if "features" in discovered["Likes"]:
            GRAPHQL_FEATURES = discovered["Likes"]["features"]
        logger.info("Likes queryId 已更新为: %s", CURRENT_LIKES_QUERY_ID)
    else:
        logger.warning("自动发现未找到 Likes 端点，使用默认 queryId: %s", CURRENT_LIKES_QUERY_ID)
    if "UserByScreenName" in discovered:
        CURRENT_USER_QUERY_ID = discovered["UserByScreenName"]["queryId"]
        logger.info("UserByScreenName queryId 已更新为: %s", CURRENT_USER_QUERY_ID)
    else:
        logger.warning("自动发现未找到 UserByScreenName 端点，使用默认 queryId: %s", CURRENT_USER_QUERY_ID)


def _extract_cursor_bottom(entries: list[dict]) -> str | None:
    for entry in reversed(entries):
        entry_id = entry.get("entryId", "")
        if entry_id.startswith("cursor-bottom-"):
            return entry.get("content", {}).get("value")
    return None


def _parse_tweet_entries(entries: list[dict]) -> list[dict]:
    items: list[dict] = []
    for entry in entries:
        try:
            tweet_result = (
                entry.get("content", {})
                .get("itemContent", {})
                .get("tweet_results", {})
                .get("result", {})
            )
            if not tweet_result:
                continue
            tweet_id = tweet_result.get("rest_id")
            if not tweet_id:
                continue
            legacy = tweet_result.get("legacy", {}) or {}
            media_list = legacy.get("extended_entities", {}).get("media") or legacy.get("entities", {}).get("media") or []
            media_list = media_list if isinstance(media_list, list) else []
            screen_name = (
                tweet_result.get("core", {})
                .get("user_results", {})
                .get("result", {})
                .get("legacy", {})
                .get("screen_name", "")
            )
            created_at = legacy.get("created_at")
            publish_time = None
            if created_at:
                try:
                    publish_time = datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
                except Exception:
                    publish_time = None
            if publish_time is None:
                publish_time = snowflake_to_datetime(tweet_id)

            cover_url = None
            if media_list:
                cover_url = media_list[0].get("media_url_https") or media_list[0].get("media_url")

            if screen_name:
                url = f"https://x.com/{screen_name}/status/{tweet_id}"
            else:
                url = f"https://x.com/i/status/{tweet_id}"

            items.append({
                "video_id": tweet_id,
                "url": url,
                "title": legacy.get("full_text") or legacy.get("text") or "",
                "cover_url": cover_url,
                "publish_time": publish_time,
                "screen_name": screen_name,
            })
        except Exception:
            continue
    return items


def snowflake_to_datetime(tweet_id: str) -> datetime:
    try:
        ts_ms = (int(tweet_id) >> 22) + 1288834974657
        return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def fetch_user_info(screen_name: str, user_query_id: str | None = None) -> Optional[XUserInfo]:
    screen_name = parse_screen_name(screen_name)
    if not screen_name:
        return None
    cookies_path = _cookies_path()
    if not os.path.isfile(cookies_path):
        raise RuntimeError(f"未找到 cookies 文件: {cookies_path}")
    cookies = _parse_cookies_from_netscape(cookies_path)
    if "auth_token" not in cookies or "ct0" not in cookies:
        raise RuntimeError("cookies 中缺少 auth_token 或 ct0，无法调用 GraphQL API。")
    sess = _build_session(cookies)
    try:
        query_id = user_query_id or CURRENT_USER_QUERY_ID
        try:
            uid = _resolve_user_id(sess, screen_name, query_id)
        except RuntimeError as exc:
            if "404" in str(exc):
                logger.warning("UserByScreenName queryId 失效，尝试自动发现并重试")
                _refresh_query_ids(sess)
                uid = _resolve_user_id(sess, screen_name, CURRENT_USER_QUERY_ID)
            else:
                raise
        if not uid:
            return None
        # 再拿一次用户信息（复用 UserByScreenName 的返回）
        variables = json.dumps({"screen_name": screen_name, "withSafetyModeUserFields": True})
        features = json.dumps({
            "hidden_profile_subscriptions_enabled": True,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "responsive_web_profile_redirect_enabled": False,
            "rweb_tipjar_consumption_enabled": False,
            "verified_phone_label_enabled": False,
            "subscriptions_verification_info_is_identity_verified_enabled": True,
            "subscriptions_verification_info_verified_since_enabled": True,
            "highlights_tweets_tab_ui_enabled": True,
            "responsive_web_twitter_article_notes_tab_enabled": True,
            "subscriptions_feature_can_gift_premium": True,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "responsive_web_graphql_timeline_navigation_enabled": True,
        })
        url = (
            f"https://x.com/i/api/graphql/{query_id}/UserByScreenName"
            f"?variables={urllib.parse.quote(variables)}&features={urllib.parse.quote(features)}"
        )
        try:
            data = _get_json(sess, url)
        except RuntimeError as exc:
            if "404" in str(exc):
                logger.warning("UserByScreenName queryId 失效，尝试自动发现并重试")
                _refresh_query_ids(sess)
                query_id = CURRENT_USER_QUERY_ID
                url = (
                    f"https://x.com/i/api/graphql/{query_id}/UserByScreenName"
                    f"?variables={urllib.parse.quote(variables)}&features={urllib.parse.quote(features)}"
                )
                data = _get_json(sess, url)
            else:
                raise
        result = data.get("data", {}).get("user", {}).get("result", {}) or {}
        legacy = result.get("legacy", {}) or {}
        avatar_https = legacy.get("profile_image_url_https")
        avatar_http = legacy.get("profile_image_url")
        logger.info(
            "X用户信息: screen_name=%s avatar_https=%s avatar=%s",
            screen_name,
            avatar_https,
            avatar_http,
        )
        return XUserInfo(
            screen_name=legacy.get("screen_name") or screen_name,
            user_id=result.get("rest_id") or uid,
            nickname=legacy.get("name") or screen_name,
            avatar_url=avatar_https or avatar_http,
            follower_count=legacy.get("followers_count"),
            following_count=legacy.get("friends_count"),
            video_count=legacy.get("statuses_count"),
            signature=legacy.get("description"),
        )
    finally:
        try:
            sess.close()
        except Exception:
            pass


def fetch_liked_items(
    screen_name: str,
    max_items: int | None = 50,
    likes_query_id: str | None = None,
    user_query_id: str | None = None,
    stop_at_id: str | None = None,
    max_pages: int | None = None
) -> list[dict]:
    screen_name = parse_screen_name(screen_name)
    if not screen_name:
        return []
    cookies_path = _cookies_path()
    if not os.path.isfile(cookies_path):
        raise RuntimeError(f"未找到 cookies 文件: {cookies_path}")
    cookies = _parse_cookies_from_netscape(cookies_path)
    if "auth_token" not in cookies or "ct0" not in cookies:
        raise RuntimeError("cookies 中缺少 auth_token 或 ct0，无法调用 GraphQL API。")

    sess = _build_session(cookies)
    try:
        resolved_user_query_id = user_query_id or CURRENT_USER_QUERY_ID
        try:
            uid = _resolve_user_id(sess, screen_name, resolved_user_query_id)
        except RuntimeError as exc:
            if "404" in str(exc):
                logger.warning("UserByScreenName queryId 失效，尝试自动发现并重试")
                _refresh_query_ids(sess)
                resolved_user_query_id = CURRENT_USER_QUERY_ID
                uid = _resolve_user_id(sess, screen_name, resolved_user_query_id)
            else:
                raise
        if not uid:
            return []

        query_id = likes_query_id or CURRENT_LIKES_QUERY_ID
        features_str = json.dumps(GRAPHQL_FEATURES)
        all_items: list[dict] = []
        cursor: str | None = None
        page = 0
        if max_pages is None and max_items is not None:
            max_pages = max(max_items // 20, 1) + 2

        def _should_continue() -> bool:
            if max_pages is not None and page >= max_pages:
                return False
            if max_items is not None and len(all_items) >= max_items:
                return False
            return True

        while _should_continue():
            page += 1
            variables: dict = {
                "userId": uid,
                "count": min(max_items - len(all_items), 100) if max_items is not None else 100,
                "includePromotedContent": False,
            }
            if cursor:
                variables["cursor"] = cursor
            url = (
                f"https://x.com/i/api/graphql/{query_id}/Likes"
                f"?variables={urllib.parse.quote(json.dumps(variables))}"
                f"&features={urllib.parse.quote(features_str)}"
            )
            try:
                data = _get_json(sess, url)
            except RuntimeError as exc:
                if "404" in str(exc):
                    logger.warning("Likes queryId 失效，尝试自动发现并重试")
                    _refresh_query_ids(sess)
                    query_id = CURRENT_LIKES_QUERY_ID
                    features_str = json.dumps(GRAPHQL_FEATURES)
                    url = (
                        f"https://x.com/i/api/graphql/{query_id}/Likes"
                        f"?variables={urllib.parse.quote(json.dumps(variables))}"
                        f"&features={urllib.parse.quote(features_str)}"
                    )
                    data = _get_json(sess, url)
                else:
                    raise
            entries: list[dict] = []
            for instruction in (
                data.get("data", {})
                .get("user", {})
                .get("result", {})
                .get("timeline", {})
                .get("timeline", {})
                .get("instructions", [])
            ):
                entries.extend(instruction.get("entries", []))

            page_items = _parse_tweet_entries(entries)
            if not page_items:
                break
            if stop_at_id:
                trimmed_items: list[dict] = []
                for item in page_items:
                    if item.get("video_id") == stop_at_id:
                        page_items = trimmed_items
                        stop_at_id = None
                        break
                    trimmed_items.append(item)
                all_items.extend(page_items)
                if stop_at_id is None:
                    break
            else:
                all_items.extend(page_items)

            new_cursor = _extract_cursor_bottom(entries)
            if not new_cursor or new_cursor == cursor:
                break
            cursor = new_cursor
            # 轻量延迟，避免触发风控
            time.sleep(random.uniform(0.5, 1.2))

        if os.getenv("X_LIKES_ORDER_DEBUG") == "1":
            sample = all_items[:10]
            times: list[datetime] = []
            for item in sample:
                pt = item.get("publish_time")
                if isinstance(pt, datetime):
                    times.append(pt)
            publish_time_desc = True
            if len(times) != len(sample) or len(times) == 0:
                publish_time_desc = False
            else:
                for i in range(1, len(times)):
                    if times[i] > times[i - 1]:
                        publish_time_desc = False
                        break
            sample_str = " | ".join(
                f"{item.get('video_id')}@{(item.get('publish_time').isoformat() if isinstance(item.get('publish_time'), datetime) else item.get('publish_time'))}"
                for item in sample
            )
            logger.info(
                "X点赞顺序调试: user=%s items=%d stop_at_id=%s publish_time_desc=%s sample=%s",
                screen_name,
                len(all_items),
                stop_at_id,
                publish_time_desc,
                sample_str
            )

        return all_items if max_items is None else all_items[:max_items]
    finally:
        try:
            sess.close()
        except Exception:
            pass
