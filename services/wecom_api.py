"""
企业微信应用API客户端
封装 access_token 管理、发消息、菜单操作等
"""
import os
import time
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

WECOM_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"


class WecomApiClient:
    """企业微信应用API客户端"""

    def __init__(self, corp_id: str, agent_id: str, secret: str, proxy: Optional[str] = None):
        self.corp_id = corp_id
        self.agent_id = int(agent_id)
        self.secret = secret
        self.proxy = proxy or os.environ.get("WECOM_API_PROXY", "")
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

    async def _get_access_token(self) -> str:
        """获取 access_token，带缓存和自动刷新"""
        now = time.time()
        if self._access_token and now < self._token_expires_at - 300:
            return self._access_token

        url = f"{WECOM_API_BASE}/gettoken"
        params = {"corpid": self.corp_id, "corpsecret": self.secret}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10, proxy=self.proxy or None) as resp:
                data = await resp.json()

        if data.get("errcode") != 0:
            raise Exception(f"获取access_token失败: {data}")

        self._access_token = data["access_token"]
        self._token_expires_at = now + data.get("expires_in", 7200)
        logger.debug("企业微信 access_token 已刷新")
        return self._access_token

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        """带 access_token 的 API 请求"""
        token = await self._get_access_token()
        url = f"{WECOM_API_BASE}/{path}"
        params = kwargs.pop("params", {})
        params["access_token"] = token

        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, params=params, timeout=15, proxy=self.proxy or None, **kwargs) as resp:
                result = await resp.json()

        if result.get("errcode") != 0:
            logger.error(f"企业微信API错误 [{path}]: {result}")
        return result

    async def send_message(self, user_id: str, content: str, msg_type: str = "text") -> dict:
        """
        发送消息给指定用户
        :param user_id: 用户UserID，"@all" 表示全员
        :param content: 消息内容
        :param msg_type: text 或 markdown
        """
        if msg_type == "markdown":
            body = {
                "touser": user_id,
                "msgtype": "markdown",
                "agentid": self.agent_id,
                "markdown": {"content": content}
            }
        else:
            body = {
                "touser": user_id,
                "msgtype": "text",
                "agentid": self.agent_id,
                "text": {"content": content}
            }

        return await self._request("POST", "message/send", json=body)

    async def set_menu(self, buttons: list) -> dict:
        """设置自定义菜单"""
        body = {"button": buttons}
        return await self._request("POST", "menu/create", json=body, params={"agentid": self.agent_id})

    async def get_menu(self) -> dict:
        """获取当前菜单"""
        return await self._request("GET", "menu/get", params={"agentid": self.agent_id})

    async def delete_menu(self) -> dict:
        """删除菜单"""
        return await self._request("GET", "menu/delete", params={"agentid": self.agent_id})

    async def test_connection(self) -> tuple[bool, str]:
        """测试连接，返回 (成功与否, 消息)"""
        try:
            token = await self._get_access_token()
            if token:
                return True, "连接成功，access_token 获取正常"
            return False, "获取 access_token 失败"
        except Exception as e:
            return False, f"连接失败: {str(e)}"
