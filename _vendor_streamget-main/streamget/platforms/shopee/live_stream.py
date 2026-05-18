import json
import re

from ...data import StreamData, wrap_stream
from ...requests.async_http import async_req
from ..base import BaseLiveStream


class ShopeeLiveStream(BaseLiveStream):
    """
    A class for fetching and processing Shopee live stream information.
    """
    def __init__(self, proxy_addr: str | None = None, cookies: str | None = None):
        super().__init__(proxy_addr, cookies)
        self.mobile_headers = self._get_mobile_headers()

    def _get_mobile_headers(self) -> dict:

        return {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'referer': 'https://live.shopee.sg/share?from=live&session=802458&share_user_id=',
            'user-agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
            'cookie': self.cookies or '',
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

        headers = {
            'User-Agent': 'ShopeeSG/3.68.33 (com.beeasy.shopee.sg; build:3.68.33; iOS 17.0.0) Alamofire/5.0.5 '
                          'appver=36833 language=en app_type=1 platform=native_ios os_ver=17.0.0 Cronet/102.0.5005.61',
            'Content-Type': 'application/json',
        }

        redirect_url = await async_req(url, proxy_addr=self.proxy_addr, headers=headers, redirect_url=True)
        match_session_id = re.search('session=(.*?)&', redirect_url)
        if not match_session_id:
            raise RuntimeError("Shopee session id not found")
        session_id = match_session_id.group(1)
        json_data = {
            'extra': '{"url_history":{"first_frame_succ_cost":[],"connection_succ_cost":[]},'
                     '"client_speed_version":"1.0","client_speed_result":{"bitrates":[],'
                     '"status_times":[]},"is_first_session":true}',
            'quality_level_id': 0,
            'session_ids': [
                int(session_id)
            ],
        }
        api = 'https://live.shopee.sg/api/v1/play_param/session'
        json_str = await async_req(api, json_data=json_data, proxy_addr=self.proxy_addr, headers=headers)
        json_data = json.loads(json_str)
        json_data['live_url'] = url
        return json_data

    async def fetch_web_stream_data(self, url: str, process_data: bool = True) -> dict:
        """
        Fetches web stream data for a live room.

        Args:
            url (str): The room URL.
            process_data (bool): Whether to process the data. Defaults to True.

        Returns:
            dict: A dictionary containing anchor name, live status, room URL, and title.
        """
        pass

    async def fetch_stream_url(self, json_data: dict, video_quality: str | int | None = None) -> StreamData:
        """
        Fetches the stream URL for a live room and wraps it into a StreamData object.
        """
        status = json_data['data']['play_param_list']
        if not status:
            return wrap_stream({"platform": "Shopee", "anchor_name": "", "is_live": False})

        room_data = json_data['data']['play_param_list'][0]
        username = room_data['session']['username']
        nickname = room_data['session']['nickname']
        auchor_name = nickname + '_' + username

        result = {"platform": "Shopee", "anchor_name": auchor_name, "is_live": False}

        if not room_data['play_param']['las_param']['mpd']:
            play_url_list = room_data['play_param']['play_url_list']
            flv_url = play_url_list[0]
            backup_urls = play_url_list[1:]
            result |= {
                "anchor_name": auchor_name,
                "is_live": True,
                "flv_url": flv_url,
                "record_url": flv_url,
                "live_url": json_data['live_url'],
                'extra': {'backup_url_list': backup_urls}}
        else:
            mpd_data = json.loads(room_data['play_param']['las_param']['mpd'])
            play_url_list = mpd_data['adaptationSet'][0]['representation']
            play_url_list = sorted(play_url_list, key=lambda x: x["maxBitrate"])

            video_quality, quality_index = self.get_quality_index(video_quality)
            flv_url = play_url_list[quality_index]['url']
            backup_urls = play_url_list[quality_index]['backupUrl']
            result |= {
                "anchor_name": auchor_name,
                "is_live": True,
                "flv_url": flv_url,
                "record_url": flv_url,
                "live_url": json_data['live_url'],
                'extra': {'backup_url_list': backup_urls}
            }
        return wrap_stream(result)
