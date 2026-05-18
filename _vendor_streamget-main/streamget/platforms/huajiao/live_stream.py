import json
import re
import time
import urllib.parse

from ...data import StreamData, wrap_stream
from ...requests.async_http import async_req
from ..base import BaseLiveStream


class HuajiaoLiveStream(BaseLiveStream):
    """
    A class for fetching and processing Huajiao live stream information.
    """
    def __init__(self, proxy_addr: str | None = None, cookies: str | None = None):
        super().__init__(proxy_addr, cookies)
        self.pc_headers = self._get_pc_headers()
        self.mobile_headers = self._get_mobile_headers()

    def _get_pc_headers(self) -> dict:
        return {
            'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'referer': 'https://www.huajiao.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
            'cookie': self.cookies or '',
        }

    async def get_huajiao_sn(self, url: str) -> tuple | None:

        live_id = url.split('?')[0].rsplit('/', maxsplit=1)[1]
        api = 'https://www.huajiao.com/l/' + live_id
        try:
            html_str = await async_req(url=api, proxy_addr=self.proxy_addr, headers=self.pc_headers)
            json_str = re.search('var feed = (.*?});', html_str).group(1)
            json_data = json.loads(json_str)
            sn = json_data['feed']['sn']
            uid = json_data['author']['uid']
            nickname = json_data['author']['nickname']
            live_id = url.split('?')[0].rsplit('/', maxsplit=1)[1]
            return nickname, sn, uid, live_id
        except Exception:
            raise RuntimeError(
                "Failed to retrieve live room data, the Huajiao live room address is not fixed, please use "
                "the anchor's homepage address for recording.")

    async def get_huajiao_stream_url_app(self, url: str) -> dict | None:
        headers = {
            'User-Agent': 'living/9.4.0 (com.huajiao.seeding; build:2410231746; iOS 17.0.0) Alamofire/9.4.0',
            'accept-language': 'zh-Hans-US;q=1.0',
            'sdk_version': '1',
            'cookie': self.cookies or ''
        }

        match_room_id = re.search('liveid=(.*?)&', url)
        if not match_room_id:
            raise Exception("liveid is empty")
        room_id = match_room_id.group(1)

        api = 'https://live.huajiao.com/feed/getFeedInfo?relateid=' + room_id
        json_str = await async_req(api, proxy_addr=self.proxy_addr, headers=headers)
        json_data = json.loads(json_str)
        if json_data['errmsg'] or not json_data['data'].get('creatime'):
            raise Exception(
                "Failed to retrieve live room data, the Huajiao live room address is not fixed, please manually change "
                "the address for recording.")

        data = json_data['data']
        return {
            "anchor_name": data['author']['nickname'],
            "title": data['feed']['title'],
            "is_live": True,
            "sn": data['feed']['sn'],
            "liveid": data['feed']['relateid'],
            "uid": data['author']['uid']
        }

    async def fetch_app_stream_data(self, url: str, process_data: bool = True) -> dict:
        """
        Fetches app stream data for a live room.

        Args:
            url (str): The room URL.
            process_data (bool): Whether to process the data. Defaults to True.

        Returns:
            dict: A dictionary containing anchor name, live status, room URL, and title.
        """
        match_room_id = re.search('&author=(.*?)&', url)
        if not match_room_id:
            raise Exception("room_id is empty")
        room_id = match_room_id.group(1)
        api = 'https://live.huajiao.com/feed/getUserFeeds?channel=Apple&userid=' + room_id + '&uid=' + room_id
        json_str = await async_req(api, proxy_addr=self.proxy_addr, headers=self.mobile_headers)
        json_data = json.loads(json_str)
        room_data = json_data['data']['feeds'][0]
        anchor_name = room_data['author']['nickname']
        status = room_data['feed']['rtop'] == '直播中'
        result = {"anchor_name": anchor_name, "is_live": status, "live_url": url}
        if status:
            encode = room_data['feed']['encode']
            flv_url = room_data['feed']['pull_url'] + '&codec=' + encode
            result['flv_url'] = flv_url
            result['record_url'] = flv_url
        return result

    async def fetch_web_stream_data(self, url: str, process_data: bool = True) -> dict:
        """
        Fetches web stream data for a live room.

        Args:
            url (str): The room URL.
            process_data (bool): Whether to process the data. Defaults to True.

        Returns:
            dict: A dictionary containing anchor name, live status, room URL, and title.
        """
        result = {"anchor_name": "", "is_live": False, "live_url": url}

        if 'liveid=' not in url:
            raise Exception(
                    "Failed to retrieve live room data, the Huajiao live room address is not fixed, please manually "
                    "change the address for recording.")

        room_data = await self.get_huajiao_stream_url_app(url)

        if room_data:
            result["anchor_name"] = room_data.pop("anchor_name")
            live_status = room_data.pop("is_live")

            if live_status:
                result["title"] = room_data.pop("title")
                params = {
                    "time": int(time.time() * 1000),
                    "version": "1.0.0",
                    **room_data,
                    "encode": "h265"
                }

                api = 'https://live.huajiao.com/live/substream?' + urllib.parse.urlencode(params)
                json_str = await async_req(url=api, proxy_addr=self.proxy_addr, headers=self.pc_headers)
                json_data = json.loads(json_str)
                result |= {
                    'is_live': True,
                    'flv_url': json_data['data']['h264_url'],
                    'm3u8_url': json_data['data']['pull_m3u8'],
                    'record_url': json_data['data']['h264_url'],
                }
        return result

    @staticmethod
    async def fetch_stream_url(json_data: dict, video_quality: str | int | None = None) -> StreamData:
        """
         Fetches the stream URL for a live room and wraps it into a StreamData object.
         """
        json_data |= {"platform": "花椒直播"}
        return wrap_stream(json_data)
