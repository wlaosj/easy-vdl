import json
import re
import urllib.parse
import uuid

from ...data import StreamData, wrap_stream
from ...requests.async_http import async_req
from ..base import BaseLiveStream


class SoopLiveStream(BaseLiveStream):
    """
    A class for fetching and processing SOOP live stream information.
    """
    def __init__(self, proxy_addr: str | None = None, cookies: str | None = None,
                 username: str | None = None, password: str | None = None):
        super().__init__(proxy_addr, cookies)
        self.username = username
        self.password = password
        self.pc_headers = self._get_pc_headers()
        self.mobile_headers = self._get_mobile_headers()

    def _get_pc_headers(self) -> dict:
        return {
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'origin': 'https://play.sooplive.com',
            'referer': 'https://play.sooplive.com/superbsw123/277837074',
            'cookie': self.cookies or '',
        }

    def _get_mobile_headers(self) -> dict:
        return {
            'client-id': str(uuid.uuid4()),
            'user-agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, '
                          'like Gecko) Version/18.5 Mobile/15E148 Safari/604.1 Edg/141.0.0.0',
            'origin': 'https://play.sooplive.com',
            'referer': 'https://play.sooplive.com/superbsw123/277837074',
            'cookie': self.cookies or '',
        }

    async def login_sooplive(self) -> str | None:
        if self.username and self.password and len(self.username) < 6 or len(self.password) < 10:
            raise RuntimeError("sooplive login failed! Please enter the correct account and password for the sooplive "
                               "platform in the config.ini file.")

        data = {
            'szWork': 'login',
            'szType': 'json',
            'szUid': self.username,
            'szPassword': self.password,
            'isSaveId': 'true',
            'isSavePw': 'true',
            'isSaveJoin': 'true',
            'isLoginRetain': 'Y',
        }

        url = 'https://login.sooplive.com/app/LoginAction.php'

        try:
            cookie_dict = await async_req(url, proxy_addr=self.proxy_addr, headers=self.pc_headers,
                                          data=data, return_cookies=True, timeout=20)
            self.cookies = '; '.join([f"{k}={v}" for k, v in cookie_dict.items()])
            self.pc_headers['cookie'] = self.cookies
            self.mobile_headers['cookie'] = self.cookies
            return self.cookies
        except Exception as e:
            raise Exception(
                f"sooplive login failed, please check if the account password in the configuration is correct. {e}"
            )

    async def _get_sooplive_cdn_url(self, broad_no: str) -> str:

        params = {
            'return_type': 'gcp_cdn',
            'use_cors': 'false',
            'cors_origin_url': 'play.sooplive.com',
            'broad_key': f'{broad_no}-common-master-hls',
            'time': '3061.2892404235236',
        }

        url2 = 'http://livestream-manager.sooplive.com/broad_stream_assign.html?' + urllib.parse.urlencode(params)
        json_str = await async_req(url=url2, proxy_addr=self.proxy_addr, headers=self.pc_headers)
        json_data = json.loads(json_str)
        return json_data['view_url']

    async def get_sooplive_user_nick(self, bj_id: str):
        api = 'https://st.sooplive.com/api/get_station_status.php?szBjId=' + bj_id
        json_str = await async_req(api, proxy_addr=self.proxy_addr, headers=self.pc_headers)
        json_data = json.loads(json_str)
        return json_data['DATA']['user_nick']

    async def get_sooplive_tk(self, url: str, rtype: str = '') -> str | tuple:
        split_url = url.split('/')
        bj_id = split_url[3] if len(split_url) < 6 else split_url[5]
        room_password = self.get_params(url, "pwd")
        if not room_password:
            room_password = ''
        data = {
            'bid': bj_id,
            'bno': '',
            'type': rtype,
            'pwd': room_password,
            'player_type': 'html5',
            'stream_type': 'common',
            'quality': 'master',
            'mode': 'landing',
            'from_api': '0',
            'is_revive': 'false',
        }

        url2 = 'https://live.sooplive.com/afreeca/player_live_api.php?bjid=' + bj_id
        json_str = await async_req(url=url2, proxy_addr=self.proxy_addr, headers=self.pc_headers, data=data)
        json_data = json.loads(json_str)
        if rtype == 'aid':
            token = json_data["CHANNEL"]["AID"]
            return token
        else:
            status = json_data['CHANNEL'].get('VIEWPRESET')
            title = json_data['CHANNEL'].get('TITLE')
            result_code = json_data['CHANNEL'].get('RESULT')
            broad_no = json_data['CHANNEL'].get('BNO')
            return result_code, status, title, broad_no

    async def _get_url_list(self, m3u8: str) -> list[str]:
        headers = {
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0',
        }
        resp = await async_req(url=m3u8, proxy_addr=self.proxy_addr, headers=headers)
        play_url_list = []
        url_prefix = m3u8.rsplit('/', maxsplit=1)[0]
        for i in resp.split('\n'):
            if not i.startswith('#') and i.strip():
                play_url_list.append(url_prefix + '/' + i.strip())
        bandwidth_pattern = re.compile(r'BANDWIDTH=(\d+)')
        bandwidth_list = bandwidth_pattern.findall(resp)
        url_to_bandwidth = {purl: int(bandwidth) for bandwidth, purl in zip(bandwidth_list, play_url_list)}
        play_url_list = sorted(play_url_list, key=lambda purl: url_to_bandwidth[purl], reverse=True)
        return play_url_list

    async def fetch_web_stream_data(self, url: str, process_data: bool = True) -> dict:
        """
        Fetches web stream data for a live room.

        Args:
            url (str): The room URL.
            process_data (bool): Whether to process the data. Defaults to True.

        Returns:
            dict: A dictionary containing anchor name, live status, room URL, and title.
        """
        split_url = url.split('/')
        bj_id = split_url[3] if len(split_url) < 6 else split_url[5]
        nickname = await self.get_sooplive_user_nick(bj_id)
        result = {"anchor_name": f"{nickname}-{bj_id}", "is_live": False, "live_url": url}
        result_code, status, title, broad_no = await self.get_sooplive_tk(url)
        if result_code not in [0, 1]:
            new_cookies = await self.login_sooplive()
            result_code, status, title, broad_no = await self.get_sooplive_tk(url)
            result['new_cookies'] = new_cookies

        if status:
            view_url = await self._get_sooplive_cdn_url(broad_no)
            authentication_key = await self.get_sooplive_tk(url, rtype='aid')
            m3u8_url = view_url + '?aid=' + authentication_key
            result |= {
                'is_live': True,
                'title': title,
                'm3u8_url': m3u8_url,
                'play_url_list': await self._get_url_list(m3u8_url)
            }
        return result

    async def fetch_stream_url(self, json_data: dict, video_quality: str | int | None = None) -> StreamData:
        """
        Fetches the stream URL for a live room and wraps it into a StreamData object.
        """
        data = await self.get_stream_url(json_data, video_quality, platform='SOOP', spec=True)
        return wrap_stream(data)
