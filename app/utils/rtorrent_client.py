# app/utils/rtorrent_client.py
import requests
from requests.auth import HTTPDigestAuth
import paramiko
from pathlib import Path
import stat
from flask import current_app
import json
import time
import xmlrpc.client
import logging
import re

def _send_xmlrpc_request(method_name, params):
    api_url = current_app.config.get('RTORRENT_API_URL')
    user = current_app.config.get('RTORRENT_USER')
    password = current_app.config.get('RTORRENT_PASSWORD')
    ssl_verify_str = str(current_app.config.get('RTORRENT_SSL_VERIFY', "True"))
    ssl_verify = False if ssl_verify_str.lower() == "false" else True
    if not api_url:
        current_app.logger.error("RTORRENT_API_URL is not configured for XML-RPC.")
        return None, "ruTorrent API URL not configured."
    auth = HTTPDigestAuth(user, password) if user and password else None
    try:
        xml_body = xmlrpc.client.dumps(tuple(params), methodname=method_name, encoding='UTF-8', allow_none=False)
    except Exception as e_dumps:
        current_app.logger.error(f"XML-RPC Dumps Error for {method_name}: {e_dumps}", exc_info=True)
        return None, f"Error creating XML-RPC request: {e_dumps}"
    headers = {'Content-Type': 'text/xml', 'User-Agent': 'MediaManagerSuite/1.0 XML-RPC'}
    if not ssl_verify:
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    try:
        response = requests.post(api_url, data=xml_body.encode('UTF-8'), headers=headers, auth=auth, verify=ssl_verify, timeout=30)
        response.raise_for_status()
        parsed_data, _ = xmlrpc.client.loads(response.content, use_builtin_types=True)
        if method_name == "d.multicall2":
            if isinstance(parsed_data, tuple) and len(parsed_data) == 1 and isinstance(parsed_data[0], list):
                return parsed_data[0], None
            elif isinstance(parsed_data, list):
                 return parsed_data, None
            else:
                return [], "Unexpected structure for d.multicall2 response."
        else:
            if isinstance(parsed_data, tuple):
                return parsed_data[0] if len(parsed_data) > 0 else None, None
            else:
                return parsed_data, None
    except Exception as e:
        return None, str(e)

def _make_httprpc_request(method='POST', params=None, data=None, files=None, timeout=30):
    api_url = current_app.config.get('RTORRENT_API_URL')
    user = current_app.config.get('RTORRENT_USER')
    password = current_app.config.get('RTORRENT_PASSWORD')
    ssl_verify = current_app.config.get('RTORRENT_SSL_VERIFY', False)
    if not api_url:
        return None, "ruTorrent API URL not configured."
    auth = HTTPDigestAuth(user, password) if user and password else None
    headers = {'Accept': 'application/json', 'User-Agent': 'MMS'}
    if not ssl_verify:
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    try:
        response = requests.request(method, api_url, params=params, data=data, files=files, auth=auth, verify=ssl_verify, timeout=timeout, headers=headers)
        if 200 <= response.status_code < 300:
            return True, None # Simple success for adds
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        return None, str(e)
    return None, "Request failed with status " + str(response.status_code)

def list_torrents():
    fields = ["d.hash=", "d.name=", "d.base_path=", "d.custom1=", "d.size_bytes=", "d.bytes_done=", "d.up.total=", "d.down.rate=", "d.up.rate=", "d.ratio=", "d.is_open=", "d.is_active=", "d.complete=", "d.left_bytes=", "d.message=", "d.load_date="]
    params_for_xmlrpc = ["", ""] + fields
    raw_torrents_data, error = _send_xmlrpc_request(method_name="d.multicall2", params=params_for_xmlrpc)
    if error: return None, error
    simplified_torrents = []
    field_keys = ['hash', 'name', 'base_path', 'label', 'size_bytes', 'downloaded_bytes', 'uploaded_bytes', 'down_rate_bytes_sec', 'up_rate_bytes_sec', 'ratio', 'is_open', 'is_active', 'is_complete_rt', 'left_bytes', 'rtorrent_message', 'load_date']
    for torrent_data_list in raw_torrents_data:
        data = dict(zip(field_keys, torrent_data_list))
        simplified_torrents.append(data)
    return simplified_torrents, None

def add_magnet_httprpc(magnet_link, label, download_dir):
    return _make_httprpc_request(params={'mode': 'add', 'url': magnet_link, 'label': label, 'dir_edit': download_dir})

def add_torrent_file_httprpc(file_content_bytes, filename, label, download_dir):
    files = {'torrent_file': (filename, file_content_bytes, 'application/x-bittorrent')}
    return _make_httprpc_request(data={'mode': 'addtorrent', 'label': label, 'dir_edit': download_dir}, files=files)

def get_torrent_hash_by_name(torrent_name, max_retries=20, delay_seconds=2):
    if not torrent_name: return None
    for attempt in range(max_retries):
        torrents, error = list_torrents()
        if error:
            time.sleep(delay_seconds)
            continue
        if torrents:
            for torrent in torrents:
                if torrent.get('name') == torrent_name:
                    return torrent.get('hash')
        time.sleep(delay_seconds)
    return None

def _decode_bencode_name(bencoded_data):
    try:
        info_dict_match = re.search(b'4:infod', bencoded_data)
        if not info_dict_match: return None
        start_index = info_dict_match.end(0)
        name_key_match = re.search(b'4:name', bencoded_data[start_index:])
        if not name_key_match: return None
        pos_after_name_key = start_index + name_key_match.end(0)
        len_match = re.match(rb'(\d+):', bencoded_data[pos_after_name_key:])
        if not len_match: return None
        str_len = int(len_match.group(1))
        pos_after_len_colon = pos_after_name_key + len_match.end(0)
        name_bytes = bencoded_data[pos_after_len_colon : pos_after_len_colon + str_len]
        try:
            return name_bytes.decode('utf-8')
        except UnicodeDecodeError:
            return name_bytes.decode('latin-1')
    except Exception:
        return None
