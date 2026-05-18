#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PostgreSQL数据库适配器
支持增量检测和动态表结构更新
# Updated at 2026-01-21: Support 50 connections pool
"""

import asyncio
import logging
from typing import Optional, List, Dict, Any, Set
import asyncpg
from sqlalchemy import create_engine, text, inspect, MetaData
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import QueuePool
import time
import json

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 创建Base类，用于SQLAlchemy模型定义
Base = declarative_base()

class DatabaseSchemaManager:
    """数据库模式管理器，支持增量检测和动态更新"""
    
    def __init__(self):
        self.schema_version = "1.0.0"  # 当前模式版本
        self.required_tables = {
            'tasks': {
                'columns': {
                    'id': {'type': 'VARCHAR(36)', 'primary_key': True, 'nullable': False},
                    'url': {'type': 'TEXT', 'primary_key': False, 'nullable': False},
                    'original_url': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'title': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'author': {'type': 'VARCHAR(256)', 'primary_key': False, 'nullable': True},
                    'source': {'type': 'VARCHAR(50)', 'primary_key': False, 'nullable': True},
                    'status': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True},
                    'progress': {'type': 'REAL', 'primary_key': False, 'nullable': True, 'default': '0.0'},
                    'error_message': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'created_at': {'type': 'TIMESTAMP', 'primary_key': False, 'nullable': True},
                    'updated_at': {'type': 'TIMESTAMP', 'primary_key': False, 'nullable': True},
                    'filename': {'type': 'VARCHAR(512)', 'primary_key': False, 'nullable': True},
                    'proxy': {'type': 'VARCHAR(256)', 'primary_key': False, 'nullable': True},
                    'cookie': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'format_id': {'type': 'VARCHAR(50)', 'primary_key': False, 'nullable': True},
                    'headers': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'subscription_id': {'type': 'VARCHAR(36)', 'primary_key': False, 'nullable': True},
                    'file_path': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': True},
                    'file_size': {'type': 'BIGINT', 'primary_key': False, 'nullable': True},
                    'platform': {'type': 'VARCHAR(50)', 'primary_key': False, 'nullable': True},
                    'quality': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True},
                    'format': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True},
                    'resolution': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True},
                    'duration': {'type': 'INTEGER', 'primary_key': False, 'nullable': True},
                    'thumbnail_url': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': True},
                    'description': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'view_count': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '0'},
                    'like_count': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '0'},
                    'comment_count': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '0'},
                    'share_count': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '0'},
                    'tags': {'type': 'TEXT[]', 'primary_key': False, 'nullable': True},
                    'extra_data': {'type': 'JSONB', 'primary_key': False, 'nullable': True}
                },
                'indexes': [
                    'CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON tasks(status, created_at)',
                    'CREATE INDEX IF NOT EXISTS idx_tasks_subscription_id ON tasks(subscription_id)',
                    'CREATE INDEX IF NOT EXISTS idx_tasks_source ON tasks(source)',  # 按来源查询优化
                    'CREATE INDEX IF NOT EXISTS idx_tasks_updated_at ON tasks(updated_at DESC)',  # 按更新时间排序优化
                    'CREATE INDEX IF NOT EXISTS idx_tasks_status_updated ON tasks(status, updated_at DESC)',  # 分页查询优化
                    # 【性能优化】任务列表查询优化索引
                    'CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC)',  # 无状态过滤的排序（最常用）
                    'CREATE INDEX IF NOT EXISTS idx_tasks_status_created_at ON tasks(status, created_at DESC)',  # 有状态过滤的排序
                    'CREATE INDEX IF NOT EXISTS idx_tasks_subscription_created_at ON tasks(subscription_id, created_at DESC)',  # 按订阅ID过滤的排序
                    'CREATE INDEX IF NOT EXISTS idx_tasks_id_status ON tasks(id, status)'  # 【性能优化】添加复合索引以优化JOIN查询
                ]
            },
            'subscriptions': {
                'columns': {
                    'id': {'type': 'VARCHAR(36)', 'primary_key': True, 'nullable': False},
                    'platform': {'type': 'VARCHAR(50)', 'primary_key': False, 'nullable': False},
                    'user_id': {'type': 'VARCHAR(100)', 'primary_key': False, 'nullable': False},
                    'nickname': {'type': 'VARCHAR(200)', 'primary_key': False, 'nullable': True},
                    'storage_name': {'type': 'VARCHAR(200)', 'primary_key': False, 'nullable': True},
                    'nickname_locked': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'false'"},
                    # 订阅类型字段（user=用户视频, collection=合集, favorite=点赞列表）
                    'subscription_type': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True, 'default': "'user'"},
                    # 合集相关字段
                    'collection_id': {'type': 'VARCHAR(100)', 'primary_key': False, 'nullable': True},
                    'collection_title': {'type': 'VARCHAR(200)', 'primary_key': False, 'nullable': True},
                    'author_id': {'type': 'VARCHAR(100)', 'primary_key': False, 'nullable': True},
                    'author_name': {'type': 'VARCHAR(200)', 'primary_key': False, 'nullable': True},
                    'avatar_url': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'signature': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'follower_count': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '0'},
                    'following_count': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '0'},
                    'video_count': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '0'},
                    'like_count': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '0'},
                    'last_sync_info': {'type': 'TIMESTAMP', 'primary_key': False, 'nullable': True},
                    'latest_video_time': {'type': 'TIMESTAMP', 'primary_key': False, 'nullable': True},
                    'latest_video_id': {'type': 'VARCHAR(100)', 'primary_key': False, 'nullable': True},
                    'latest_video_title': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': True},
                    'latest_video_cover': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'update_interval': {'type': 'REAL', 'primary_key': False, 'nullable': True, 'default': '3600'},
                    'auto_download': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'false'"},
                    'quality': {'type': 'VARCHAR(50)', 'primary_key': False, 'nullable': True, 'default': "'best'"},
                    'youtube_tab_type': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True},  # YouTube标签类型：videos/shorts/playlists（仅对platform=youtube有效）
                    'last_check': {'type': 'TIMESTAMP', 'primary_key': False, 'nullable': True},
                    'last_update': {'type': 'TIMESTAMP', 'primary_key': False, 'nullable': True},
                    'status': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True, 'default': "'active'"},
                    'created_at': {'type': 'TIMESTAMP', 'primary_key': False, 'nullable': True, 'default': 'CURRENT_TIMESTAMP'},
                    'updated_at': {'type': 'TIMESTAMP', 'primary_key': False, 'nullable': True, 'default': 'CURRENT_TIMESTAMP'},
                    'error_message': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'extra_data': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'sync_status': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True, 'default': "'idle'"},
                    'sync_progress': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '0'},
                    'batch_download_status': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True},
                    'batch_download_progress': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '0'},
                    'batch_download_total': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '0'},
                    'batch_download_completed': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '0'},
                    'batch_download_failed': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '0'},
                    'batch_download_start_time': {'type': 'TIMESTAMP', 'primary_key': False, 'nullable': True},
                    'url': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'profile_url': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': True},
                    'title': {'type': 'VARCHAR(200)', 'primary_key': False, 'nullable': True},
                    'download_path': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': True},
                    'check_interval': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '3600'},
                    'skip_bilibili_upower': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'false'"}
                },
                'indexes': [
                    'CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status)',
                    'CREATE INDEX IF NOT EXISTS idx_subscriptions_platform ON subscriptions(platform)',
                    'CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id)',
                    'CREATE INDEX IF NOT EXISTS idx_subscriptions_latest_video_time ON subscriptions(latest_video_time)',
                    'CREATE INDEX IF NOT EXISTS idx_subscriptions_subscription_type ON subscriptions(subscription_type)',
                    'CREATE INDEX IF NOT EXISTS idx_subscriptions_collection_id ON subscriptions(collection_id)',
                    'CREATE INDEX IF NOT EXISTS idx_subscriptions_author_id ON subscriptions(author_id)',
                    'CREATE INDEX IF NOT EXISTS idx_subscriptions_auto_download ON subscriptions(auto_download)'
                ]
            },
            'subscription_videos': {
                'columns': {
                    'id': {'type': 'VARCHAR(36)', 'primary_key': True, 'nullable': False},
                    'subscription_id': {'type': 'VARCHAR(36)', 'primary_key': False, 'nullable': False},
                    'video_id': {'type': 'VARCHAR(100)', 'primary_key': False, 'nullable': False},
                    'title': {'type': 'TEXT', 'primary_key': False, 'nullable': True},  # 改为TEXT支持长标题
                    'description': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'url': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': True},
                    'cover_url': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'duration': {'type': 'REAL', 'primary_key': False, 'nullable': True},
                    'created_at': {'type': 'TIMESTAMP', 'primary_key': False, 'nullable': True, 'default': 'CURRENT_TIMESTAMP'},
                    'publish_time': {'type': 'TIMESTAMP', 'primary_key': False, 'nullable': True},
                    'downloaded': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'false'"},
                    'download_task_id': {'type': 'VARCHAR(100)', 'primary_key': False, 'nullable': True},
                    'error_message': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'extra_data': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'video_url': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': True},
                    'status': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True, 'default': "'pending'"},
                    'downloaded_at': {'type': 'TIMESTAMP', 'primary_key': False, 'nullable': True},
                    'file_path': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': True},
                    'file_size': {'type': 'BIGINT', 'primary_key': False, 'nullable': True}
                },
                'indexes': [
                    'CREATE INDEX IF NOT EXISTS idx_videos_subscription_id ON subscription_videos(subscription_id)',
                    'CREATE INDEX IF NOT EXISTS idx_videos_downloaded ON subscription_videos(downloaded)',
                    'CREATE INDEX IF NOT EXISTS idx_videos_video_id ON subscription_videos(video_id)',
                    'CREATE INDEX IF NOT EXISTS idx_videos_download_task_id ON subscription_videos(download_task_id)',
                    'CREATE INDEX IF NOT EXISTS idx_videos_publish_time ON subscription_videos(publish_time DESC)',
                    # 【性能优化】添加复合索引以优化JOIN查询
                    'CREATE INDEX IF NOT EXISTS idx_videos_subscription_task ON subscription_videos(subscription_id, download_task_id)'
                ]
            },
            'users': {
                'columns': {
                    'id': {'type': 'VARCHAR(36)', 'primary_key': True, 'nullable': False},
                    'username': {'type': 'VARCHAR(50)', 'primary_key': False, 'nullable': False, 'unique': True},
                    'password_hash': {'type': 'VARCHAR(255)', 'primary_key': False, 'nullable': False},
                    'email': {'type': 'VARCHAR(100)', 'primary_key': False, 'nullable': True},
                    'is_admin': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'true'"},
                    'is_active': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'true'"},
                    'created_at': {'type': 'TIMESTAMP', 'primary_key': False, 'nullable': True, 'default': 'CURRENT_TIMESTAMP'},
                    'last_login': {'type': 'TIMESTAMP', 'primary_key': False, 'nullable': True}
                },
                'indexes': [
                    'CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)'
                ]
            },
            'global_config': {
                'columns': {
                    'key': {'type': 'VARCHAR(100)', 'primary_key': True, 'nullable': False},
                    'value': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'updated_at': {'type': 'TIMESTAMP', 'primary_key': False, 'nullable': True, 'default': 'CURRENT_TIMESTAMP'}
                },
                'indexes': [
                    'CREATE INDEX IF NOT EXISTS idx_global_config_key ON global_config(key)'
                ]
            },
            'system_config': {
                'columns': {
                    'key': {'type': 'VARCHAR(100)', 'primary_key': True, 'nullable': False},
                    'value': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'updated_at': {'type': 'TIMESTAMP', 'primary_key': False, 'nullable': True, 'default': 'CURRENT_TIMESTAMP'}
                },
                'indexes': []
            },
            'cookie_config': {
                'columns': {
                    'platform': {'type': 'VARCHAR(50)', 'primary_key': True, 'nullable': False},
                    'enabled': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'false'"},
                    'interval_minutes': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '10'},
                    'last_update': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': True},
                    'next_update': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': True},
                    'created_at': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': False, 'default': 'CURRENT_TIMESTAMP'},
                    'updated_at': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': False, 'default': 'CURRENT_TIMESTAMP'}
                },
                'indexes': [
                    'CREATE INDEX IF NOT EXISTS idx_cookie_config_platform ON cookie_config(platform)'
                ]
            },
            'notifications': {
                'columns': {
                    'id': {'type': 'VARCHAR(36)', 'primary_key': True, 'nullable': False},
                    'user_id': {'type': 'VARCHAR(36)', 'primary_key': False, 'nullable': True},
                    'type': {'type': 'VARCHAR(50)', 'primary_key': False, 'nullable': False},
                    'title': {'type': 'VARCHAR(256)', 'primary_key': False, 'nullable': False},
                    'content': {'type': 'TEXT', 'primary_key': False, 'nullable': False},
                    'status': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True, 'default': "'pending'"},
                    'channel': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True, 'default': "'wechat_bot'"},
                    'priority': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '1'},
                    'extra_data': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'sent_at': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': True},
                    'read_at': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': True},
                    'error_message': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': True},
                    'retry_count': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '0'},
                    'created_at': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': False, 'default': 'CURRENT_TIMESTAMP'},
                    'updated_at': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': False, 'default': 'CURRENT_TIMESTAMP'}
                },
                'indexes': [
                    'CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id)',
                    'CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(type)',
                    'CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status)',
                    'CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at)'
                ]
            },
            'notification_settings': {
                'columns': {
                    'id': {'type': 'VARCHAR(36)', 'primary_key': True, 'nullable': False},
                    'user_id': {'type': 'VARCHAR(36)', 'primary_key': False, 'nullable': False, 'unique': True},
                    'wechat_bot_enabled': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'true'"},
                    'wechat_webhook_url': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': True},
                    'serverchan3_enabled': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'false'"},
                    'serverchan3_uid': {'type': 'VARCHAR(100)', 'primary_key': False, 'nullable': True},
                    'serverchan3_sendkey': {'type': 'VARCHAR(200)', 'primary_key': False, 'nullable': True},
                    'email_enabled': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'false'"},
                    'email_address': {'type': 'VARCHAR(100)', 'primary_key': False, 'nullable': True},
                    'web_push_enabled': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'true'"},
                    'websocket_enabled': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'true'"},
                    'download_completed_enabled': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'true'"},
                    'download_error_enabled': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'true'"},

                    'subscription_check_failed_enabled': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'true'"},
                    'subscription_check_new_videos_enabled': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'true'"},
                    'subscription_check_no_new_videos_enabled': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'false'"},
                    'quiet_hours_enabled': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'true'"},
                    'system_status_enabled': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'true'"},
            
                    'quiet_hours_start': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'22:00'"},
                    'quiet_hours_end': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'08:00'"},
                    
                    # Telegram 机器人配置
                    'telegram_bot_enabled': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'false'"},
                    'telegram_bot_token': {'type': 'VARCHAR(200)', 'primary_key': False, 'nullable': True},
                    'telegram_chat_id': {'type': 'VARCHAR(100)', 'primary_key': False, 'nullable': True},
                    'telegram_proxy': {'type': 'VARCHAR(200)', 'primary_key': False, 'nullable': True},
                    'telegram_media_max_concurrent': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '5'},
                    'telegram_media_use_date_subdir': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'true'"},
                    # Bark (iOS 推送)
                    'bark_enabled': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'false'"},
                    'bark_server_url': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': True},
                    'bark_device_key': {'type': 'VARCHAR(200)', 'primary_key': False, 'nullable': True},
                    'bark_sound': {'type': 'VARCHAR(100)', 'primary_key': False, 'nullable': True},
                    'bark_group': {'type': 'VARCHAR(100)', 'primary_key': False, 'nullable': True},
                    'bark_icon': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': True},
                    'bark_url': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': True},
                    'bark_automatically_copy': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'false'"},
                    # 媒体服务器集成（Jellyfin/Emby）
                    'media_server_enabled': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'false'"},
                    'media_server_type': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True, 'default': "'jellyfin'"},
                    'media_server_url': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': True},
                    'media_server_api_key': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': True},
                    'created_at': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': False, 'default': 'CURRENT_TIMESTAMP'},
                    'updated_at': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': False, 'default': 'CURRENT_TIMESTAMP'}
                },
                'indexes': [
                    'CREATE INDEX IF NOT EXISTS idx_notification_settings_user_id ON notification_settings(user_id)'
                ]
            },
            'playback_records': {
                'columns': {
                    'subscription_id': {'type': 'VARCHAR(36)', 'primary_key': True, 'nullable': False},
                    'current_index': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '0'},
                    'playback_mode': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True, 'default': "'asc'"},
                    'video_progress': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'last_updated': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': False, 'default': 'CURRENT_TIMESTAMP'}
                },
                'indexes': []
            },
            'api_params_cache': {
                'columns': {
                    'platform': {'type': 'VARCHAR(50)', 'primary_key': True, 'nullable': False},
                    'params_json': {'type': 'TEXT', 'primary_key': False, 'nullable': False},
                    'expire_seconds': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '1800'},
                    'updated_at': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': False, 'default': 'CURRENT_TIMESTAMP'},
                    'created_at': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': False, 'default': 'CURRENT_TIMESTAMP'}
                },
                'indexes': []
            },
            'api_tokens': {
                'columns': {
                    'id': {'type': 'VARCHAR(36)', 'primary_key': True, 'nullable': False},
                    'token': {'type': 'VARCHAR(255)', 'primary_key': False, 'nullable': False, 'unique': True},
                    'name': {'type': 'VARCHAR(200)', 'primary_key': False, 'nullable': False},
                    'user_id': {'type': 'VARCHAR(36)', 'primary_key': False, 'nullable': True},
                    'created_at': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': False, 'default': 'CURRENT_TIMESTAMP'},
                    'expires_at': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': True},
                    'last_used_at': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': True},
                    'is_active': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'true'"}
                },
                'indexes': [
                    'CREATE UNIQUE INDEX IF NOT EXISTS idx_api_tokens_token ON api_tokens(token)',
                    'CREATE INDEX IF NOT EXISTS idx_api_tokens_user_id ON api_tokens(user_id)',
                    'CREATE INDEX IF NOT EXISTS idx_api_tokens_is_active ON api_tokens(is_active)'
                ]
            },
            'live_subscriptions': {
                'columns': {
                    'id': {'type': 'VARCHAR(36)', 'primary_key': True, 'nullable': False},
                    'platform': {'type': 'VARCHAR(50)', 'primary_key': False, 'nullable': False},
                    'room_url': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': False},
                    'room_id': {'type': 'VARCHAR(100)', 'primary_key': False, 'nullable': True},
                    'anchor_name': {'type': 'VARCHAR(200)', 'primary_key': False, 'nullable': True},
                    'avatar_url': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': True},
                    'signature': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'quality': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True, 'default': "'原画'"},
                    'auto_record': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'true'"},
                    'monitor_enabled': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'true'"},
                    'check_interval': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '60'},
                    'output_format': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'ts'"},
                    'split_enabled': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'false'"},
                    'split_duration': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '3600'},
                    'max_duration': {'type': 'INTEGER', 'primary_key': False, 'nullable': True},
                    'is_live': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'false'"},
                    'is_recording': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'false'"},
                    'last_check_time': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': True},
                    'last_live_time': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': True},
                    'notification_enabled': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'true'"},
                    'notification_end_enabled': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'false'"},
                    'proxy': {'type': 'VARCHAR(200)', 'primary_key': False, 'nullable': True},
                    'cookies': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'total_record_count': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '0'},
                    'total_record_duration': {'type': 'BIGINT', 'primary_key': False, 'nullable': True, 'default': '0'},
                    'total_record_size': {'type': 'BIGINT', 'primary_key': False, 'nullable': True, 'default': '0'},
                    'remark': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': True},
                    'extra_data': {'type': 'JSONB', 'primary_key': False, 'nullable': True},
                    'created_at': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': False, 'default': 'CURRENT_TIMESTAMP'},
                    'updated_at': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': False, 'default': 'CURRENT_TIMESTAMP'}
                },
                'indexes': [
                    'CREATE INDEX IF NOT EXISTS idx_live_sub_platform ON live_subscriptions(platform)',
                    'CREATE INDEX IF NOT EXISTS idx_live_sub_room_id ON live_subscriptions(room_id)',
                    'CREATE INDEX IF NOT EXISTS idx_live_sub_auto_record ON live_subscriptions(auto_record)',
                    'CREATE INDEX IF NOT EXISTS idx_live_sub_monitor_enabled ON live_subscriptions(monitor_enabled)',
                    'CREATE INDEX IF NOT EXISTS idx_live_sub_is_live ON live_subscriptions(is_live)',
                    'CREATE INDEX IF NOT EXISTS idx_live_sub_last_check_time ON live_subscriptions(last_check_time)'
                ]
            },
            'live_records': {
                'columns': {
                    'id': {'type': 'VARCHAR(36)', 'primary_key': True, 'nullable': False},
                    'subscription_id': {'type': 'VARCHAR(36)', 'primary_key': False, 'nullable': False},
                    'platform': {'type': 'VARCHAR(50)', 'primary_key': False, 'nullable': True},
                    'anchor_name': {'type': 'VARCHAR(200)', 'primary_key': False, 'nullable': True},
                    'room_id': {'type': 'VARCHAR(100)', 'primary_key': False, 'nullable': True},
                    'live_title': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': True},
                    'stream_url': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'quality': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True},
                    'start_time': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': False},
                    'end_time': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': True},
                    'duration': {'type': 'INTEGER', 'primary_key': False, 'nullable': True},
                    'file_path': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': True},
                    'file_name': {'type': 'VARCHAR(255)', 'primary_key': False, 'nullable': True},
                    'file_size': {'type': 'BIGINT', 'primary_key': False, 'nullable': True},
                    'status': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True, 'default': "'recording'"},
                    'error_message': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'remark': {'type': 'TEXT', 'primary_key': False, 'nullable': True},
                    'format': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True},
                    'resolution': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True},
                    'fps': {'type': 'REAL', 'primary_key': False, 'nullable': True},
                    'bitrate': {'type': 'INTEGER', 'primary_key': False, 'nullable': True},
                    'segment_index': {'type': 'INTEGER', 'primary_key': False, 'nullable': True, 'default': '0'},
                    'parent_record_id': {'type': 'VARCHAR(36)', 'primary_key': False, 'nullable': True},
                    'trigger_type': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True, 'default': "'auto'"},
                    'converted': {'type': 'VARCHAR(10)', 'primary_key': False, 'nullable': True, 'default': "'false'"},
                    'converted_path': {'type': 'VARCHAR(500)', 'primary_key': False, 'nullable': True},
                    'converted_format': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True},
                    'convert_status': {'type': 'VARCHAR(20)', 'primary_key': False, 'nullable': True},
                    'extra_data': {'type': 'JSONB', 'primary_key': False, 'nullable': True},
                    'created_at': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': False, 'default': 'CURRENT_TIMESTAMP'},
                    'updated_at': {'type': 'TIMESTAMP WITH TIME ZONE', 'primary_key': False, 'nullable': False, 'default': 'CURRENT_TIMESTAMP'}
                },
                'indexes': [
                    'CREATE INDEX IF NOT EXISTS idx_live_rec_sub_id ON live_records(subscription_id)',
                    'CREATE INDEX IF NOT EXISTS idx_live_rec_status ON live_records(status)',
                    'CREATE INDEX IF NOT EXISTS idx_live_rec_start_time ON live_records(start_time)',
                    'CREATE INDEX IF NOT EXISTS idx_live_rec_platform ON live_records(platform)',
                    'CREATE INDEX IF NOT EXISTS idx_live_rec_parent_id ON live_records(parent_record_id)',
                    'CREATE INDEX IF NOT EXISTS idx_live_rec_updated_at ON live_records(updated_at DESC)'
                ]
            }
        }
    
    async def initialize_schema(self, engine):
        """初始化数据库模式，支持增量检测和更新"""
        try:
            # 增量检测过程本身仅在调试时输出
            logger.debug("🔍 开始增量检测数据库模式...")
            
            # 创建schema_version表来跟踪版本
            await self._ensure_version_table(engine)
            
            # 检查并创建缺失的表
            await self._ensure_required_tables(engine)
            
            # 检查并添加缺失的字段
            await self._ensure_required_columns(engine)
            
            # 检查并创建缺失的索引
            await self._ensure_required_indexes(engine)
            
            # 检查并修复字段长度
            await self._ensure_column_lengths(engine)
            
            # 迁移字段类型到 TEXT（支持长文本）
            await self._migrate_column_to_text(engine)
            
            # 执行画质格式迁移
            await self._migrate_quality_formats(engine)
            
            # 更新版本信息
            await self._update_schema_version(engine)
            
            logger.info("✅ 数据库模式增量检测和更新完成")
            
        except Exception as e:
            logger.error(f"❌ 数据库模式初始化失败: {e}")
            raise
    
    async def _ensure_version_table(self, engine):
        """确保版本跟踪表存在"""
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    id SERIAL PRIMARY KEY,
                    version VARCHAR(20) NOT NULL,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    description TEXT
                )
            """))
            conn.commit()
    
    async def _ensure_required_tables(self, engine):
        """确保所有必需的表都存在"""
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
        
        for table_name, table_info in self.required_tables.items():
            if table_name not in existing_tables:
                logger.info(f"📋 创建缺失的表: {table_name}")
                await self._create_table(engine, table_name, table_info)
            else:
                logger.debug(f"✅ 表 {table_name} 已存在")
    
    async def _create_table(self, engine, table_name, table_info):
        """创建表"""
        with engine.connect() as conn:
            # 构建CREATE TABLE语句
            columns = []
            for col_name, col_info in table_info['columns'].items():
                col_def = f"{col_name} {col_info['type']}"
                
                if col_info.get('primary_key'):
                    col_def += " PRIMARY KEY"
                elif not col_info.get('nullable', True):
                    col_def += " NOT NULL"
                
                if 'default' in col_info:
                    col_def += f" DEFAULT {col_info['default']}"
                
                if col_info.get('unique'):
                    col_def += " UNIQUE"
                
                columns.append(col_def)
            
            create_sql = f"""
                CREATE TABLE {table_name} (
                    {', '.join(columns)}
                )
            """
            
            conn.execute(text(create_sql))
            conn.commit()
            logger.info(f"✅ 表 {table_name} 创建成功")
    
    async def _ensure_required_columns(self, engine):
        """确保所有必需的字段都存在"""
        inspector = inspect(engine)
        
        for table_name, table_info in self.required_tables.items():
            try:
                existing_columns = {col['name'] for col in inspector.get_columns(table_name)}
                required_columns = set(table_info['columns'].keys())
                
                missing_columns = required_columns - existing_columns
                
                if missing_columns:
                    logger.info(f"🔧 表 {table_name} 需要添加字段: {missing_columns}")
                    await self._add_missing_columns(engine, table_name, missing_columns, table_info)
                else:
                    logger.debug(f"✅ 表 {table_name} 所有字段都已存在")
                    
            except Exception as e:
                logger.warning(f"检查表 {table_name} 字段时出错: {e}")
    
    async def _add_missing_columns(self, engine, table_name, missing_columns, table_info):
        """添加缺失的字段"""
        with engine.connect() as conn:
            for col_name in missing_columns:
                try:
                    col_info = table_info['columns'][col_name]
                    col_def = f"{col_name} {col_info['type']}"
                    
                    if not col_info.get('nullable', True):
                        col_def += " NOT NULL"
                    
                    if 'default' in col_info:
                        # 处理不同类型的默认值，避免对已带引号的字符串再次加引号
                        default_value = col_info['default']
                        if isinstance(default_value, str):
                            dv = default_value.strip()
                            if dv == 'CURRENT_TIMESTAMP':
                                col_def += f" DEFAULT {dv}"
                            elif (dv.startswith("'") and dv.endswith("'")) or (dv.startswith('"') and dv.endswith('"')):
                                # 已包含引号，直接使用
                                col_def += f" DEFAULT {dv}"
                            elif dv.lower() in ("true", "false"):  # 兼容布尔字符串
                                col_def += f" DEFAULT '{dv}'"
                            elif dv.replace('.', '', 1).isdigit():  # 数字字符串
                                col_def += f" DEFAULT {dv}"
                            else:
                                col_def += f" DEFAULT '{dv}'"
                        else:
                            col_def += f" DEFAULT {default_value}"
                    
                    # 使用ADD COLUMN添加字段
                    alter_sql = f"ALTER TABLE {table_name} ADD COLUMN {col_def}"
                    conn.execute(text(alter_sql))
                    
                    logger.info(f"✅ 字段 {table_name}.{col_name} 添加成功")
                    
                except Exception as e:
                    logger.error(f"❌ 添加字段 {table_name}.{col_name} 失败: {e}")
                    # 继续处理其他字段
    
            conn.commit()
    
    async def _ensure_required_indexes(self, engine):
        """确保所有必需的索引都存在"""
        inspector = inspect(engine)
        
        for table_name, table_info in self.required_tables.items():
            try:
                existing_indexes = {idx['name'] for idx in inspector.get_indexes(table_name)}
                
                for index_sql in table_info['indexes']:
                    # 从索引SQL中提取索引名称
                    index_name = self._extract_index_name(index_sql)
                    
                    if index_name and index_name not in existing_indexes:
                        logger.info(f"🔧 创建缺失的索引: {index_name}")
                        await self._create_index(engine, index_sql)
                    else:
                        logger.debug(f"✅ 索引 {index_name} 已存在")
                        
            except Exception as e:
                logger.warning(f"检查表 {table_name} 索引时出错: {e}")
    
    def _extract_index_name(self, index_sql):
        """从索引SQL中提取索引名称"""
        try:
            # 简单的索引名称提取逻辑
            if 'IF NOT EXISTS' in index_sql:
                parts = index_sql.split('IF NOT EXISTS')
                if len(parts) > 1:
                    return parts[1].split('ON')[0].strip()
            else:
                parts = index_sql.split('INDEX')
                if len(parts) > 1:
                    return parts[1].split('ON')[0].strip()
        except:
            pass
        return None
    
    async def _create_index(self, engine, index_sql):
        """创建索引"""
        try:
            with engine.connect() as conn:
                conn.execute(text(index_sql))
                conn.commit()
                logger.info(f"✅ 索引创建成功")
        except Exception as e:
            logger.warning(f"索引创建警告: {e}")
            # 索引可能已存在，忽略错误
    
    async def _ensure_column_lengths(self, engine):
        """检查并修复字段长度不匹配的问题"""
        try:
            logger.debug("🔧 开始检查字段长度...")
            inspector = inspect(engine)
            
            # 需要检查的字段长度映射
            column_length_checks = {
                'tasks': {
                    'filename': {'current': 256, 'target': 512}
                },
                'subscription_videos': {
                    'title': {'current': 200, 'target': 500},
                    'cover_url': {'current': 200, 'target': 500}
                },
                'subscriptions': {
                    'latest_video_title': {'current': 200, 'target': 500},
                    'url': {'current': 200, 'target': 500},
                    'profile_url': {'current': 200, 'target': 500}
                }
            }
            
            for table_name, columns in column_length_checks.items():
                try:
                    # 检查表是否存在
                    if table_name not in inspector.get_table_names():
                        logger.debug(f"表 {table_name} 不存在，跳过字段长度检查")
                        continue
                    
                    existing_columns = {col['name']: col for col in inspector.get_columns(table_name)}
                    
                    for column_name, length_info in columns.items():
                        if column_name not in existing_columns:
                            logger.debug(f"字段 {table_name}.{column_name} 不存在，跳过长度检查")
                            continue
                        
                        current_col = existing_columns[column_name]
                        current_type = current_col['type']
                        
                        # 检查当前字段类型和长度
                        current_type_str = str(current_type).lower()
                        if 'character varying' in current_type_str or 'varchar' in current_type_str:
                            # 提取当前长度 - 支持两种格式：character varying(200) 和 VARCHAR(200)
                            import re
                            match = re.search(r'(?:character varying|varchar)\((\d+)\)', current_type_str)
                            if match:
                                current_length = int(match.group(1))
                                target_length = length_info['target']
                                
                                if current_length < target_length:
                                    logger.info(f"🔧 更新字段长度: {table_name}.{column_name} ({current_length} -> {target_length})")
                                    await self._alter_column_length(engine, table_name, column_name, target_length)
                                else:
                                    logger.debug(f"字段 {table_name}.{column_name} 长度已正确: {current_length}")
                            else:
                                logger.debug(f"无法解析字段 {table_name}.{column_name} 的长度信息: {current_type}")
                        else:
                            logger.debug(f"字段 {table_name}.{column_name} 不是 VARCHAR 类型，跳过长度检查: {current_type}")
                            
                except Exception as e:
                    logger.warning(f"检查表 {table_name} 字段长度时出错: {e}")
                    continue
            
            logger.debug("字段长度检查完成")
            
        except Exception as e:
            logger.error(f"字段长度检查失败: {e}")
            # 不抛出异常，避免阻止系统启动
    
    async def _alter_column_length(self, engine, table_name, column_name, new_length):
        """修改字段长度"""
        try:
            with engine.connect() as conn:
                # 使用 ALTER TABLE 修改字段长度
                alter_sql = f"ALTER TABLE {table_name} ALTER COLUMN {column_name} TYPE VARCHAR({new_length})"
                conn.execute(text(alter_sql))
                conn.commit()
                logger.info(f"✅ 字段 {table_name}.{column_name} 长度更新成功: -> VARCHAR({new_length})")
                
        except Exception as e:
            logger.error(f"❌ 更新字段 {table_name}.{column_name} 长度失败: {e}")
            # 不抛出异常，继续处理其他字段
    
    async def _migrate_column_to_text(self, engine):
        """将需要支持长文本的字段从 VARCHAR 迁移到 TEXT"""
        try:
            inspector = inspect(engine)
            
            # 需要迁移到 TEXT 的字段
            columns_to_migrate = {
                'tasks': ['title', 'url', 'original_url'],  # 抖音标题/Instagram 签名直链可能很长
                'subscriptions': ['avatar_url', 'latest_video_cover'],  # Instagram 等平台头像/封面URL可能超过500字符
                'subscription_videos': ['title', 'url', 'cover_url'],  # 抖音/Instagram 标题和媒体URL可能超过500字符
            }
            
            for table_name, columns in columns_to_migrate.items():
                if table_name not in inspector.get_table_names():
                    continue
                    
                existing_columns = {col['name']: col for col in inspector.get_columns(table_name)}
                
                for column_name in columns:
                    if column_name not in existing_columns:
                        continue
                    
                    current_type = str(existing_columns[column_name]['type']).lower()
                    
                    # 如果已经是 TEXT 类型，跳过
                    if current_type == 'text':
                        logger.debug(f"字段 {table_name}.{column_name} 已经是 TEXT 类型")
                        continue
                    
                    # 如果是 VARCHAR 类型，迁移到 TEXT
                    if 'character varying' in current_type or 'varchar' in current_type:
                        logger.info(f"🔧 迁移字段类型: {table_name}.{column_name} (VARCHAR -> TEXT)")
                        with engine.connect() as conn:
                            alter_sql = f"ALTER TABLE {table_name} ALTER COLUMN {column_name} TYPE TEXT"
                            conn.execute(text(alter_sql))
                            conn.commit()
                        logger.info(f"✅ 字段 {table_name}.{column_name} 已迁移到 TEXT 类型")
                        
        except Exception as e:
            logger.error(f"字段类型迁移失败: {e}")
            # 不抛出异常，避免阻止系统启动
    
    async def _migrate_quality_formats(self, engine):
        """智能迁移画质格式到兼容格式"""
        with engine.connect() as conn:
            try:
                # 检查YouTube订阅表是否需要迁移（仅检查在映射表中的旧格式，或NULL）
                # 注意：映射表中的旧格式才会触发UPDATE，所以统计也应只统计这些
                old_formats = ['best', 'best[height<=4320]', 'best[height<=2160]', 'best[height<=1440]', 'best[height<=1080]', 'best[height<=720]', 'best[height<=480]']
                old_formats_str = "', '".join(old_formats)
                
                youtube_subscription_count = conn.execute(text(f"""
                    SELECT COUNT(*) FROM subscriptions 
                    WHERE (quality IN ('{old_formats_str}') OR quality IS NULL)
                    AND platform IN ('youtube', 'youtube_playlist')
                """)).scalar()
                
                # 检查YouTube任务表是否需要迁移
                youtube_task_count = conn.execute(text(f"""
                    SELECT COUNT(*) FROM tasks 
                    WHERE (format_id IN ('{old_formats_str}') OR format_id IS NULL)
                    AND source = 'youtube'
                """)).scalar()
                
                # 检查B站订阅表是否需要迁移（从best迁移回bestvideo+bestaudio）
                bilibili_subscription_count = conn.execute(text("""
                    SELECT COUNT(*) FROM subscriptions 
                    WHERE quality = 'best' 
                    AND platform = 'bilibili'
                """)).scalar()
                
                # 检查B站任务表是否需要迁移
                bilibili_task_count = conn.execute(text("""
                    SELECT COUNT(*) FROM tasks 
                    WHERE format_id = 'best' 
                    AND source = 'bilibili'
                """)).scalar()
                
                total_count = youtube_subscription_count + youtube_task_count + bilibili_subscription_count + bilibili_task_count
                
                if total_count == 0:
                    logger.info("📋 没有需要迁移的画质格式，跳过")
                    return
                
                logger.info(f"🔄 发现需要迁移的画质格式: YouTube({youtube_subscription_count}订阅+{youtube_task_count}任务), B站({bilibili_subscription_count}订阅+{bilibili_task_count}任务)")
                
                # YouTube格式转换映射（best -> bestvideo+bestaudio，提升画质）
                youtube_format_mappings = [
                    ('best', 'bestvideo+bestaudio'),
                    ('best[height<=4320]', 'bestvideo[height<=4320]+bestaudio'),  # 8K
                    ('best[height<=2160]', 'bestvideo[height<=2160]+bestaudio'),  # 4K
                    ('best[height<=1440]', 'bestvideo[height<=1440]+bestaudio'),  # 2K
                    ('best[height<=1080]', 'bestvideo[height<=1080]+bestaudio'),  # 1080p
                    ('best[height<=720]', 'bestvideo[height<=720]+bestaudio'),   # 720p
                    ('best[height<=480]', 'bestvideo[height<=480]+bestaudio'),   # 480p
                ]
                
                # B站格式转换映射（best -> bestvideo+bestaudio）
                bilibili_format_mappings = [
                    ('best', 'bestvideo+bestaudio'),
                ]
                
                # 迁移YouTube订阅表（包括youtube和youtube_playlist）
                for old_format, new_format in youtube_format_mappings:
                    result = conn.execute(text("""
                        UPDATE subscriptions 
                        SET quality = :new_format, updated_at = CURRENT_TIMESTAMP
                        WHERE quality = :old_format 
                        AND platform IN ('youtube', 'youtube_playlist')
                    """), {
                        'new_format': new_format,
                        'old_format': old_format
                    })
                    if result.rowcount > 0:
                        logger.info(f"✅ YouTube订阅表迁移: {old_format} -> {new_format}, 影响 {result.rowcount} 条记录")
                
                # 迁移YouTube任务表
                for old_format, new_format in youtube_format_mappings:
                    result = conn.execute(text("""
                        UPDATE tasks 
                        SET format_id = :new_format, updated_at = CURRENT_TIMESTAMP
                        WHERE format_id = :old_format 
                        AND source = 'youtube'
                    """), {
                        'new_format': new_format,
                        'old_format': old_format
                    })
                    if result.rowcount > 0:
                        logger.info(f"✅ YouTube任务表迁移: {old_format} -> {new_format}, 影响 {result.rowcount} 条记录")
                
                # 迁移B站订阅表（best -> bestvideo+bestaudio）
                for old_format, new_format in bilibili_format_mappings:
                    result = conn.execute(text("""
                        UPDATE subscriptions 
                        SET quality = :new_format, updated_at = CURRENT_TIMESTAMP
                        WHERE quality = :old_format 
                        AND platform = 'bilibili'
                    """), {
                        'new_format': new_format,
                        'old_format': old_format
                    })
                    if result.rowcount > 0:
                        logger.info(f"✅ B站订阅表迁移: {old_format} -> {new_format}, 影响 {result.rowcount} 条记录")
                
                # 迁移B站任务表
                for old_format, new_format in bilibili_format_mappings:
                    result = conn.execute(text("""
                        UPDATE tasks 
                        SET format_id = :new_format, updated_at = CURRENT_TIMESTAMP
                        WHERE format_id = :old_format 
                        AND source = 'bilibili'
                    """), {
                        'new_format': new_format,
                        'old_format': old_format
                    })
                    if result.rowcount > 0:
                        logger.info(f"✅ B站任务表迁移: {old_format} -> {new_format}, 影响 {result.rowcount} 条记录")
                
                # 处理 NULL 值的订阅（根据平台设置默认值）
                null_quality_subscription_count = conn.execute(text("""
                    SELECT COUNT(*) FROM subscriptions 
                    WHERE quality IS NULL
                """)).scalar()
                
                if null_quality_subscription_count > 0:
                    # 处理 YouTube 订阅的 NULL 值（使用高画质，包括youtube和youtube_playlist）
                    youtube_null_result = conn.execute(text("""
                        UPDATE subscriptions 
                        SET quality = 'bestvideo+bestaudio', updated_at = CURRENT_TIMESTAMP
                        WHERE quality IS NULL 
                        AND platform IN ('youtube', 'youtube_playlist')
                    """))
                    if youtube_null_result.rowcount > 0:
                        logger.info(f"✅ YouTube订阅表NULL值处理: 影响 {youtube_null_result.rowcount} 条记录")
                    
                    # 处理 B站订阅的 NULL 值
                    bilibili_null_result = conn.execute(text("""
                        UPDATE subscriptions 
                        SET quality = 'bestvideo+bestaudio', updated_at = CURRENT_TIMESTAMP
                        WHERE quality IS NULL 
                        AND platform = 'bilibili'
                    """))
                    if bilibili_null_result.rowcount > 0:
                        logger.info(f"✅ B站订阅表NULL值处理: 影响 {bilibili_null_result.rowcount} 条记录")
                    
                    # 处理其他平台订阅的 NULL 值（默认使用 best）
                    other_null_result = conn.execute(text("""
                        UPDATE subscriptions 
                        SET quality = 'best', updated_at = CURRENT_TIMESTAMP
                        WHERE quality IS NULL 
                        AND platform NOT IN ('youtube', 'bilibili')
                    """))
                    if other_null_result.rowcount > 0:
                        logger.info(f"✅ 其他平台订阅表NULL值处理: 影响 {other_null_result.rowcount} 条记录")
                
                conn.commit()
                logger.info("✅ 画质格式迁移完成")
                
            except Exception as e:
                conn.rollback()
                logger.error(f"❌ 画质格式迁移失败: {str(e)}")
                raise

    async def _update_schema_version(self, engine):
        """更新模式版本信息"""
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO schema_version (version, description) 
                VALUES (:version, :description)
            """), {
                'version': self.schema_version,
                'description': f'Schema updated at {time.strftime("%Y-%m-%d %H:%M:%S")}'
            })
            conn.commit()
    
    async def add_new_table(self, table_name: str, table_definition: Dict):
        """动态添加新表（运行时）"""
        try:
            if table_name in self.required_tables:
                logger.warning(f"表 {table_name} 已存在定义")
                return False
            
            # 添加到必需表定义中
            self.required_tables[table_name] = table_definition
            
            # 创建表
            engine = get_engine()
            await self._create_table(engine, table_name, table_definition)
            
            logger.info(f"✅ 新表 {table_name} 添加成功")
            return True
            
        except Exception as e:
            logger.error(f"❌ 添加新表 {table_name} 失败: {e}")
            return False
    
    async def add_new_column(self, table_name: str, column_name: str, column_definition: Dict):
        """动态添加新字段（运行时）"""
        try:
            if table_name not in self.required_tables:
                logger.error(f"表 {table_name} 不存在")
                return False
            
            # 添加到表定义中
            self.required_tables[table_name]['columns'][column_name] = column_definition
            
            # 添加字段到数据库
            engine = get_engine()
            await self._add_missing_columns(engine, table_name, [column_name], self.required_tables[table_name])
            
            logger.info(f"✅ 新字段 {table_name}.{column_name} 添加成功")
            return True
            
        except Exception as e:
            logger.error(f"❌ 添加新字段 {table_name}.{column_name} 失败: {e}")
            return False

class PostgreSQLDatabase:
    """PostgreSQL数据库连接管理器"""
    
    def __init__(self):
        self.engine = None
        self.SessionLocal = None
        self.pool = None
        self._lock = asyncio.Lock()
        self.schema_manager = DatabaseSchemaManager()
        
    async def initialize(self):
        """初始化数据库连接"""
        # [优化]以此屏蔽 SQLAlchemy 连接池在回收断开的连接时报出的 "server closed the connection unexpectedly" 错误
        # 这是预期行为（连接断了就丢弃），不需要 ERROR 级别日志刷屏
        logging.getLogger("sqlalchemy.pool").setLevel(logging.CRITICAL)
        
        try:
            # 第一步：使用postgres超级用户创建应用数据库和用户
            logger.info("🔧 开始创建应用数据库和用户...")
            await self._create_database_and_user()
            
            # 第二步：创建SQLAlchemy引擎（基于实际使用优化，支持大规模同步）
            self.engine = create_engine(
                "postgresql://easy_vdl_user:easy_vdl_password@localhost:5432/easy_vdl",
                poolclass=QueuePool,
                pool_size=100,                   # [优化] 基础连接池增加到100个，支持大规模同步
                max_overflow=100,                # [优化] 溢出连接100个（总共200个连接）

                pool_timeout=10,                 # 连接池超时时间
                pool_recycle=300,                # [优化] 回收时间设为300秒（5分钟），确保早于服务端超时过期（15分钟）
                pool_use_lifo=True,              # 复用最近归还连接
                echo=False,                      # 关闭SQL回显
                pool_pre_ping=True,              # 连接前ping检查
                pool_reset_on_return='rollback', # [恢复] 恢复自动回滚，防止 dirty transaction 导致的 "set_session" 错误
                connect_args={                   # 连接参数优化
                    'connect_timeout': 10,       # 连接超时10秒
                    'application_name': 'easy_vdl_optimized',
                    'keepalives': 1,             
                    'keepalives_idle': 10,       # [修改] 缩短keepalive空闲时间
                    'keepalives_interval': 5,    # [修改] 缩短keepalive间隔
                    'keepalives_count': 3        
                }
            )
            
            # 创建会话工厂
            self.SessionLocal = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.engine
            )
            
            # 输出连接池配置信息（仅在调试时查看）
            logger.debug(f"📊 数据库连接池配置: pool_size={100}, max_overflow={100}, 最大容量={200}, pool_recycle={300}秒")
            
            # 启动连接池监控
            self._start_pool_monitoring()
            
            # 测试连接
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                logger.info("✅ PostgreSQL数据库连接成功")
            
            # 第三步：检查和修复权限，然后使用增量检测初始化表（调试日志）
            logger.debug("正在检查和修复数据库权限...")
            await self._ensure_permissions()
            
            # 使用增量检测初始化数据库模式
            await self.schema_manager.initialize_schema(self.engine)
            logger.info("✅ PostgreSQL数据库增量初始化成功")
            
            # 第四步：自动启动后台静默监控
            await self._start_memory_monitoring()
            
        except Exception as e:
            logger.error(f"❌ PostgreSQL数据库初始化失败: {e}")
            raise
    
    async def _create_database_and_user(self):
        """创建应用数据库和用户"""
        try:
            # 使用postgres超级用户连接（连接到默认的postgres数据库）
            # 重要：禁用自动事务，因为CREATE DATABASE不能在事务块内执行
            admin_engine = create_engine(
                "postgresql://postgres@localhost:5432/postgres",
                echo=False,
                isolation_level="AUTOCOMMIT"  # 禁用事务，启用自动提交
            )
            
            with admin_engine.connect() as conn:
                # 检查并创建应用数据库
                result = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = 'easy_vdl'"))
                if not result.fetchone():
                    logger.info("📁 创建应用数据库 easy_vdl...")
                    conn.execute(text("CREATE DATABASE easy_vdl"))
                    # 不需要手动提交，AUTOCOMMIT模式会自动提交
                    logger.info("✅ 应用数据库创建成功")
                else:
                    logger.info("✅ 应用数据库已存在")
                
                # 检查并创建应用用户
                result = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'easy_vdl_user'"))
                if not result.fetchone():
                    logger.info("👤 创建应用用户 easy_vdl_user...")
                    conn.execute(text("CREATE USER easy_vdl_user WITH PASSWORD 'easy_vdl_password'"))
                    conn.execute(text("ALTER USER easy_vdl_user CREATEDB"))
                    # 不需要手动提交，AUTOCOMMIT模式会自动提交
                    logger.info("✅ 应用用户创建成功")
                else:
                    logger.info("✅ 应用用户已存在")
                
                # 设置数据库权限
                logger.debug("🔐 设置数据库权限并优化超时参数...")
                conn.execute(text("GRANT ALL PRIVILEGES ON DATABASE easy_vdl TO easy_vdl_user"))
                
                # [优化] 设置超时时间，解决耗时操作（如发通知/处理媒体库）导致的连接被数据库强行断开的问题
                # 将事务中空闲超时设置为 15分钟（900秒），普通会话空闲超时设置为 1小时
                # 注意：此设置会覆盖全局配置，确保用户级别设置生效
                conn.execute(text("ALTER USER easy_vdl_user SET idle_in_transaction_session_timeout = '900s'"))
                conn.execute(text("ALTER USER easy_vdl_user SET idle_session_timeout = '3600s'"))
                # 验证设置是否生效
                result = conn.execute(text("SELECT name, setting FROM pg_settings WHERE name = 'idle_in_transaction_session_timeout'"))
                setting = result.fetchone()
                if setting:
                    logger.debug(f"✅ 用户级别超时设置已生效: {setting[0]} = {setting[1]}")
                
                # 不需要手动提交，AUTOCOMMIT模式会自动提交
                logger.debug("✅ 数据库权限与参数优化设置完成")
                
            admin_engine.dispose()
            
        except Exception as e:
            logger.error(f"❌ 创建数据库和用户失败: {str(e)}")
            raise
    
    async def _ensure_permissions(self):
        """确保用户权限正确"""
        try:
            # 使用postgres超级用户连接来检查和修复权限
            admin_engine = create_engine(
                "postgresql://postgres@localhost:5432/easy_vdl",
                echo=False
            )
            
            with admin_engine.connect() as conn:
                # 检查权限
                result = conn.execute(text("""
                    SELECT has_schema_privilege('easy_vdl_user', 'public', 'USAGE') as has_usage,
                           has_schema_privilege('easy_vdl_user', 'public', 'CREATE') as has_create
                """))
                permissions = result.fetchone()
                
                if not permissions.has_usage or not permissions.has_create:
                    logger.info("检测到权限不足，正在修复...")
                    # 修复权限
                    conn.execute(text("GRANT ALL PRIVILEGES ON SCHEMA public TO easy_vdl_user"))
                    conn.execute(text("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO easy_vdl_user"))
                    conn.execute(text("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO easy_vdl_user"))
                    conn.execute(text("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO easy_vdl_user"))
                    conn.execute(text("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO easy_vdl_user"))
                    conn.commit()
                    logger.info("✅ 权限修复完成")
                else:
                    logger.info("✅ 用户权限正常")
                    
            admin_engine.dispose()
            
        except Exception as e:
            logger.error(f"❌ 权限检查和修复失败: {str(e)}")
            raise
    
    def get_session(self) -> Session:
        """获取数据库会话"""
        if not self.SessionLocal:
            raise RuntimeError("数据库未初始化")
        return self.SessionLocal()
    
    async def execute_query(self, query: str, params: Optional[Dict] = None) -> List[Dict]:
        """执行查询"""
        try:
            with self.get_session() as session:
                result = session.execute(text(query), params or {})
                return [dict(row._mapping) for row in result]
        except Exception as e:
            logger.error(f"查询执行失败: {e}")
            raise
    
    async def execute_update(self, query: str, params: Optional[Dict] = None) -> int:
        """执行更新操作"""
        try:
            with self.get_session() as session:
                result = session.execute(text(query), params or {})
                session.commit()
                return result.rowcount
        except Exception as e:
            logger.error(f"更新执行失败: {e}")
            raise

    def get_pool_status(self) -> Dict[str, Any]:
        """获取统一的连接池状态信息（供API和监控复用）
        返回标准字典: pool_size, max_overflow, checked_out, checked_in, overflow, usage_rate, max_capacity
        """
        status = {
            "pool_size": 100,         # [更新] 默认配置已增加到100
            "max_overflow": 100,      # [更新] 默认配置已增加到100
            "checked_out": 0,
            "checked_in": 0,
            "overflow": 0,
            "usage_rate": 0.0,
            "max_capacity": 200       # [更新] 最大容量已增加到200
        }
        
        try:
            if self.engine and self.engine.pool:
                pool = self.engine.pool
                
                # 获取动态属性
                status["pool_size"] = pool.size()
                status["max_overflow"] = getattr(pool, '_max_overflow', 100)
                status["checked_out"] = pool.checkedout()
                status["checked_in"] = pool.checkedin()
                status["overflow"] = pool.overflow()
                
                # 计算衍生指标
                status["max_capacity"] = status["pool_size"] + status["max_overflow"]
                if status["max_capacity"] > 0:
                    status["usage_rate"] = round((status["checked_out"] / status["max_capacity"] * 100), 1)
        except Exception as e:
            logger.warning(f"获取连接池状态失败: {e}")
            
        return status
    
    async def close(self):
        """关闭数据库连接"""
        if self.engine:
            self.engine.dispose()
            logger.info("PostgreSQL数据库连接已关闭")
    
    # ==================== 自动后台静默监控功能 ====================
    
    async def _start_memory_monitoring(self):
        """启动内存监控任务（后台静默运行）"""
        try:
            # 创建后台监控任务（静默后台运行，正常情况下无需 INFO 提示）
            asyncio.create_task(self._background_monitoring_loop())
            logger.debug("✅ 数据库内存监控已自动启动（后台静默运行）")
        except Exception:
            # 启动失败时静默处理，不影响主功能
            pass
    
    def _start_pool_monitoring(self):
        """启动连接池监控"""
        import asyncio
        
        async def monitor_pool():
            """监控连接池状态"""
            while True:
                try:
                    if self.engine and self.engine.pool:
                        pool = self.engine.pool
                        # 获取连接池状态
                        size = pool.size()
                        checked_in = pool.checkedin()
                        checked_out = pool.checkedout()
                        overflow = pool.overflow()
                        
                        # 修复: 使用配置的池大小来计算总容量，避免overflow负数问题
                        # [更新] pool_size=100, max_overflow=100, 理论最大容量=200
                        pool_size_config = 100
                        max_overflow_config = 100
                        
                        # 实际总容量: 基础池大小 + 当前溢出数(但不超过配置的max_overflow)
                        # 使用max(0, overflow)避免负数
                        actual_overflow = max(0, overflow)
                        total_capacity = pool_size_config + min(actual_overflow, max_overflow_config)
                        
                        # 计算使用率: 基于已checkout的连接数和理论最大容量
                        max_capacity = pool_size_config + max_overflow_config  # 200
                        usage_rate = (checked_out / max_capacity * 100) if max_capacity > 0 else 0
                        
                        # 只在使用率过高时才记录日志，降低噪音
                        if usage_rate > 85:
                            logger.warning(f"🔥 数据库连接池使用率过高: {usage_rate:.1f}% "
                                         f"(已用:{checked_out}/{max_capacity}, "
                                         f"池大小:{size}, 溢出:{overflow}, 空闲:{checked_in})")
                        # 正常使用率(<85%)不再记录日志，通过前端监控页面查看
                        
                        # 每30秒检查一次
                        await asyncio.sleep(30)
                    else:
                        await asyncio.sleep(60)
                except Exception as e:
                    logger.error(f"连接池监控异常: {str(e)}")
                    await asyncio.sleep(60)
        
        # 启动监控任务
        asyncio.create_task(monitor_pool())
        logger.info("✅ 数据库连接池监控已启动")
    
    async def _background_monitoring_loop(self):
        """后台监控主循环（静默运行）"""
        recovery_attempts = 0
        max_recovery_attempts = 5
        
        while recovery_attempts < max_recovery_attempts:
            try:
                # 静默执行监控任务
                await self._silent_monitoring_cycle()
                
                # 根据系统状态自适应监控间隔
                interval = await self._adaptive_monitoring_interval()
                await asyncio.sleep(interval)
                
            except Exception:
                # 监控异常时静默重启，不记录错误日志
                recovery_attempts += 1
                await asyncio.sleep(60 * recovery_attempts)  # 递增延迟
        
        # 如果恢复失败，静默停止监控
        logger.warning("⚠️ 数据库监控自动恢复失败，已静默停止")
    
    async def _silent_monitoring_cycle(self):
        """静默监控周期（无日志输出）"""
        try:
            # 1. 检查连接数（静默）
            await self._check_connections_silently()
            
            # 2. 检查长事务（静默）
            await self._check_transactions_silently()
            
            # 3. 自动清理（静默）
            await self._auto_cleanup_silently()
            
        except Exception:
            # 完全静默，不记录任何错误
            pass
    
    async def _adaptive_monitoring_interval(self):
        """根据系统状态自适应监控间隔"""
        try:
            with self.get_session() as session:
                # 检查系统繁忙程度
                result = session.execute(text("""
                    SELECT count(*) as busy_queries
                    FROM pg_stat_activity 
                    WHERE state = 'active'
                """))
                busy_queries = result.fetchone()[0]
                
                # 根据繁忙程度调整监控间隔
                if busy_queries > 10:
                    return 60      # 繁忙时：1分钟
                elif busy_queries > 5:
                    return 300     # 中等时：5分钟
                else:
                    return 600     # 空闲时：10分钟
                    
        except Exception:
            return 300  # 异常时使用默认间隔
    
    async def _check_connections_silently(self):
        """静默检查连接数，自动处理异常"""
        try:
            with self.get_session() as session:
                # 检查活跃连接数
                result = session.execute(text("""
                    SELECT count(*) as active_count
                    FROM pg_stat_activity 
                    WHERE state = 'active'
                """))
                active_count = result.fetchone()[0]
                
                # 如果连接数过多，自动清理空闲连接
                if active_count > 15:  # 接近连接池限制
                    await self._auto_cleanup_connections()
                    
        except Exception:
            # 静默处理，不记录日志
            pass
    
    async def _check_transactions_silently(self):
        """静默检查长事务，自动清理"""
        try:
            with self.get_session() as session:
                # 查找长时间运行的事务
                result = session.execute(text("""
                    SELECT pid, now() - query_start as duration
                    FROM pg_stat_activity 
                    WHERE state = 'idle in transaction' 
                    AND now() - query_start > interval '10 minutes'
                """))
                long_txns = result.fetchall()
                
                # 自动清理超时事务
                for pid, duration in long_txns:
                    if duration.total_seconds() > 600:  # 10分钟
                        await self._terminate_long_transaction(pid)
                        
        except Exception:
            # 静默处理
            pass
    
    async def _auto_cleanup_silently(self):
        """静默自动清理"""
        try:
            # 清理空闲连接
            await self._cleanup_idle_connections()
            
            # 清理过期缓存
            await self._cleanup_expired_cache()
            
            # 执行轻量级VACUUM
            await self._lightweight_vacuum()
            
        except Exception:
            # 静默处理
            pass
    
    async def _auto_cleanup_connections(self):
        """自动清理过多连接
        
        注意：已禁用主动杀连接逻辑，因为 SQLAlchemy 连接池已经通过
        pool_pre_ping=True 和 pool_recycle=300 很好地管理连接。
        主动 pg_terminate_backend() 会导致 SQLAlchemy 报错：
        "server closed the connection unexpectedly"
        """
        # 禁用主动杀连接，让 SQLAlchemy 连接池自己管理
        pass
    
    async def _terminate_long_transaction(self, pid):
        """终止长时间运行的事务"""
        try:
            with self.get_session() as session:
                session.execute(text(f"SELECT pg_terminate_backend({pid})"))
                session.commit()
        except Exception:
            # 静默处理
            pass
    
    async def _cleanup_idle_connections(self):
        """清理空闲连接
        
        注意：已禁用主动杀连接逻辑，因为 SQLAlchemy 连接池已经通过
        pool_pre_ping=True 和 pool_recycle=300 很好地管理连接。
        主动 pg_terminate_backend() 会导致 SQLAlchemy 报错：
        "server closed the connection unexpectedly"
        """
        # 禁用主动杀连接，让 SQLAlchemy 连接池自己管理
        pass
    
    async def _cleanup_expired_cache(self):
        """清理过期缓存"""
        try:
            # 在非事务上下文中执行，以避免 "DISCARD ALL cannot run inside a transaction block"
            with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.exec_driver_sql("DISCARD ALL")
        except Exception:
            pass
    
    async def _lightweight_vacuum(self):
        """执行轻量级VACUUM"""
        try:
            with self.get_session() as session:
                # 只在系统空闲时执行轻量级VACUUM
                result = session.execute(text("""
                    SELECT count(*) as active_queries
                    FROM pg_stat_activity 
                    WHERE state = 'active'
                """))
                active_queries = result.fetchone()[0]
                
                # 只有在查询数很少时才执行VACUUM
                if active_queries < 3:
                    # 仅对业务表执行，以避免非超级用户对系统表的警告
                    business_tables = list(self.schema_manager.required_tables.keys()) if hasattr(self, 'schema_manager') and self.schema_manager else []
                    if business_tables:
                        tables_sql = ", ".join([f"public.{t}" for t in business_tables])
                        vacuum_sql = f"VACUUM (ANALYZE) {tables_sql}"
                        # 在非事务上下文中执行，以避免 "VACUUM cannot run inside a transaction block"
                        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                            conn.exec_driver_sql(vacuum_sql)
                    
        except Exception:
            pass
    
    async def get_monitoring_stats(self):
        """获取监控统计信息（用于调试，正常运行时不会调用）"""
        try:
            with self.get_session() as session:
                # 连接统计
                result = session.execute(text("""
                    SELECT 
                        count(*) as total_connections,
                        count(*) FILTER (WHERE state = 'active') as active_connections,
                        count(*) FILTER (WHERE state = 'idle') as idle_connections,
                        count(*) FILTER (WHERE state = 'idle in transaction') as idle_transactions
                    FROM pg_stat_activity
                """))
                conn_stats = result.fetchone()
                
                # 缓存统计
                result = session.execute(text("""
                    SELECT 
                        round(100.0 * sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)), 2) as cache_hit_ratio
                    FROM pg_statio_user_tables
                """))
                cache_stats = result.fetchone()
                
                return {
                    'total_connections': conn_stats[0],
                    'active_connections': conn_stats[1],
                    'idle_connections': conn_stats[2],
                    'idle_transactions': conn_stats[3],
                    'cache_hit_ratio': cache_stats[0] if cache_stats[0] else 0
                }
                
        except Exception as e:
            return {'error': str(e)}

# 全局数据库实例
db = PostgreSQLDatabase()

# 全局SessionLocal变量（初始为None，初始化后会被设置）
SessionLocal = None

async def init_database():
    """初始化数据库"""
    await db.initialize()
    # 设置全局SessionLocal变量
    global SessionLocal
    SessionLocal = db.SessionLocal
    # 正常情况下无需 INFO；仅在调试初始化顺序时使用
    logger.debug("✅ 全局SessionLocal已设置")

def get_db_session() -> Session:
    """获取数据库会话（用于依赖注入）"""
    if not SessionLocal:
        raise RuntimeError("数据库未初始化，请先调用init_database()")
    return SessionLocal()

# 兼容性函数，保持与原有代码的兼容性
def get_engine():
    """获取数据库引擎"""
    if not db.engine:
        raise RuntimeError("数据库未初始化，请先调用init_database()")
    return db.engine

def get_session():
    """获取数据库会话（带重试和无效事务恢复机制）
    
    此函数会自动处理以下情况：
    1. 数据库连接断开（OperationalError, DisconnectionError）
    2. 无效事务状态（InvalidRequestError，如 "Can't reconnect until invalid transaction is rolled back"）
    3. 连接健康检查：确保连接不在无效事务状态
    """
    if not SessionLocal:
        raise RuntimeError("数据库未初始化，请先调用init_database()")
    
    import time
    from sqlalchemy.exc import OperationalError, DisconnectionError, InvalidRequestError
    
    max_retries = 3
    session = None
    for attempt in range(max_retries):
        try:
            session = SessionLocal()
            # [增强] 连接健康检查：测试连接是否有效
            # 如果连接在事务中，先回滚确保连接干净
            try:
                # 测试连接是否有效
                session.execute(text("SELECT 1"))
                # 如果连接在事务中，先回滚（pool_reset_on_return='rollback'应该已经处理，但双重保险）
                if session.in_transaction():
                    session.rollback()
            except Exception as health_check_error:
                # 健康检查失败，关闭连接并重试
                logger.warning(f"连接健康检查失败: {health_check_error}")
                if session:
                    try:
                        session.rollback()
                    except:
                        pass
                    try:
                        session.close()
                    except:
                        pass
                    session = None
                if attempt < max_retries - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                else:
                    raise
            return session
        except InvalidRequestError as e:
            # 处理无效事务状态：先回滚再重试
            error_msg = str(e).lower()
            if 'rollback' in error_msg or 'invalid transaction' in error_msg:
                logger.warning(f"检测到无效事务状态，尝试回滚恢复（第{attempt + 1}次）: {str(e)}")
                if session:
                    try:
                        session.rollback()
                    except Exception:
                        pass
                    try:
                        session.close()
                    except Exception:
                        pass
                    session = None
                
                if attempt < max_retries - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                else:
                    logger.error(f"无效事务恢复失败，已重试{max_retries}次: {str(e)}")
                    raise
            else:
                raise
        except (OperationalError, DisconnectionError) as e:
            if session:
                try:
                    session.rollback()  # 先尝试回滚
                except Exception:
                    pass
                try:
                    session.close()
                except Exception:
                    pass
                session = None
            
            if attempt < max_retries - 1:
                logger.warning(f"数据库连接失败（第{attempt + 1}次），{1 if attempt == 0 else 2 ** attempt}秒后重试: {str(e)}")
                time.sleep(1 if attempt == 0 else 2 ** attempt)
                continue
            else:
                logger.error(f"数据库连接最终失败，已重试{max_retries}次: {str(e)}")
                raise
        except Exception as e:
            if session:
                try:
                    session.rollback()
                except Exception:
                    pass
                try:
                    session.close()
                except Exception:
                    pass
            logger.error(f"数据库会话创建失败: {str(e)}")
            raise

def get_db():
    """获取数据库会话（FastAPI依赖注入用，带重试机制）"""
    if not SessionLocal:
        raise RuntimeError("数据库未初始化，请先调用init_database()")
    
    max_retries = 3
    retry_delay = 0.1
    
    for attempt in range(max_retries):
        try:
            db_session = SessionLocal()
            try:
                yield db_session
            finally:
                # 【性能优化】确保事务正确关闭，避免idle in transaction
                try:
                    db_session.rollback()  # 回滚任何未提交的更改
                except Exception:
                    pass
                db_session.close()
            break  # 成功时跳出循环，不使用return
        except Exception as e:
            # 检查是否是HTTPException（业务逻辑错误），如果是则不重试
            if hasattr(e, 'status_code') and hasattr(e, 'detail'):
                # 这是业务逻辑错误，直接抛出，不重试
                raise
            
            # 检查是否是数据库连接相关的错误
            error_str = str(e).lower()
            if any(keyword in error_str for keyword in [
                'connection', 'timeout', 'operational', 'database', 'postgresql',
                'psycopg2', 'sqlalchemy', 'session', 'transaction'
            ]):
                if attempt < max_retries - 1:
                    logger.warning(f"数据库连接失败，尝试重连 ({attempt + 1}/{max_retries}): {e}")
                    time.sleep(retry_delay * (2 ** attempt))  # 指数退避
                else:
                    logger.error(f"数据库连接最终失败: {e}")
                    raise
            else:
                # 其他类型的错误，直接抛出，不重试
                raise

# 批量更新器（PostgreSQL版本）
class BatchUpdater:
    """批量更新器，减少数据库写入频率（适配1GB内存限制优化配置）"""
    def __init__(self, batch_size=100, flush_interval=5):  # 批量大小减少到100，刷新间隔减少到5秒，适配work_mem=16MB
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.pending_updates = []
        self.last_flush = time.time()
        self._lock = asyncio.Lock()
        self._stats = {                    # 新增统计信息
            'total_processed': 0,
            'total_batches': 0,
            'last_batch_size': 0,
            'last_flush_time': 0
        }
        self._initialized = False  # 新增：标记是否已初始化
    
    async def _ensure_initialized(self):
        """确保批量更新器已初始化"""
        if not self._initialized:
            self._initialized = True
    
    async def add_update(self, query: str, params: Dict):
        """添加更新操作到队列"""
        await self._ensure_initialized()  # 确保已初始化
        
        async with self._lock:
            self.pending_updates.append((query, params))
            
            if (len(self.pending_updates) >= self.batch_size or 
                time.time() - self.last_flush >= self.flush_interval):
                await self.flush()
    
    async def flush(self):
        """执行批量更新（优化版本，支持大量数据批量处理）"""
        if not self.pending_updates:
            return
            
        async with self._lock:
            try:
                start_time = time.time()
                batch_size = len(self.pending_updates)
                
                # 使用事务批量执行，提高性能
                with db.get_session() as session:
                    # 批量执行所有更新操作
                    for query, params in self.pending_updates:
                        session.execute(text(query), params)
                    
                    # 提交事务
                    session.commit()
                
                # 更新统计信息
                self._stats['total_processed'] += batch_size
                self._stats['total_batches'] += 1
                self._stats['last_batch_size'] = batch_size
                self._stats['last_flush_time'] = time.time()
                
                processing_time = time.time() - start_time
                avg_time_per_record = processing_time / batch_size if batch_size > 0 else 0
                
                logger.info(f"批量更新完成，处理了 {batch_size} 条记录，耗时 {processing_time:.2f}秒，平均每条 {avg_time_per_record*1000:.2f}ms")
                
                # 清空待处理队列
                self.pending_updates.clear()
                self.last_flush = time.time()
                
            except Exception as e:
                logger.error(f"批量更新失败: {e}")
                # 失败时保留未处理的更新，避免数据丢失
                pass
    
    def get_stats(self) -> Dict:
        """获取批量更新统计信息"""
        return self._stats.copy()
    
    def get_queue_size(self) -> int:
        """获取当前队列大小"""
        return len(self.pending_updates)

# 任务状态缓存（PostgreSQL版本）
class TaskStatusCache:
    """任务状态内存缓存，减少数据库查询（适配1GB内存限制）"""
    def __init__(self, max_size=500, ttl=30):  # 缓存大小减少到500，适配内存限制
        self.cache = {}
        self.max_size = max_size
        self.ttl = ttl  # 缓存生存时间（秒）
        self._lock = asyncio.Lock()
        self._cleanup_task = None
        self._cleanup_started = False  # 新增：标记是否已启动清理任务
    
    def _start_cleanup_task(self):
        """启动清理任务（延迟启动，避免模块导入时的问题）"""
        if self._cleanup_started:
            return
            
        try:
            # 检查是否有运行的事件循环
            try:
                loop = asyncio.get_running_loop()
                # 只有在有运行的事件循环时才创建任务
                async def cleanup():
                    while True:
                        await asyncio.sleep(60)  # 每分钟清理一次
                        await self._cleanup_expired()
                
                self._cleanup_task = loop.create_task(cleanup())
                self._cleanup_started = True
            except RuntimeError:
                # 没有运行的事件循环，延迟启动
                self._cleanup_started = False
        except Exception as e:
            # 启动失败，记录日志但不影响主流程
            pass
    
    async def _ensure_cleanup_task(self):
        """确保清理任务已启动"""
        if not self._cleanup_started:
            self._start_cleanup_task()
    
    async def _cleanup_expired(self):
        """清理过期的缓存项"""
        current_time = time.time()
        async with self._lock:
            expired_keys = [
                key for key, (_, timestamp) in self.cache.items()
                if current_time - timestamp > self.ttl
            ]
            for key in expired_keys:
                del self.cache[key]
            
            if expired_keys:
                logger.debug(f"清理了 {len(expired_keys)} 个过期缓存项")
    
    async def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        await self._ensure_cleanup_task()  # 确保清理任务已启动
        
        async with self._lock:
            if key in self.cache:
                value, timestamp = self.cache[key]
                if time.time() - timestamp <= self.ttl:
                    return value
                else:
                    del self.cache[key]
            return None
    
    async def set(self, key: str, value: Any):
        """设置缓存值"""
        await self._ensure_cleanup_task()  # 确保清理任务已启动
        
        async with self._lock:
            if len(self.cache) >= self.max_size:
                # 删除最旧的项
                oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][1])
                del self.cache[oldest_key]
            
            self.cache[key] = (value, time.time())
    
    async def invalidate(self, key: str):
        """使缓存失效"""
        await self._ensure_cleanup_task()  # 确保清理任务已启动
        
        async with self._lock:
            if key in self.cache:
                del self.cache[key]
    
    async def clear(self):
        """清空缓存"""
        await self._ensure_cleanup_task()  # 确保清理任务已启动
        
        async with self._lock:
            self.cache.clear()
    
    def __len__(self):
        """获取缓存项数量"""
        return len(self.cache)

# 创建全局实例
batch_updater = BatchUpdater()
task_status_cache = TaskStatusCache()

# 导出主要接口
__all__ = [
    'db', 'init_database', 'get_db_session', 'get_db', 'get_engine', 'get_session',
    'Base', 'SessionLocal', 'BatchUpdater', 'TaskStatusCache', 'batch_updater', 'task_status_cache'
]

# ==================== 监控调试接口（仅用于开发调试） ====================
async def get_database_monitoring_status():
    """获取数据库监控状态（仅用于调试，正常运行时不需要）"""
    try:
        return await db.get_monitoring_stats()
    except Exception as e:
        return {'error': f'获取监控状态失败: {e}'}
