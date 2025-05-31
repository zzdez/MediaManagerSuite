# app/utils/rtorrent_client.py
import requests
from requests.auth import HTTPDigestAuth
from flask import current_app
import json
import time

# _make_httprpc_request remains the same as the version with HTTPDigestAuth and User-Agent
def _make_httprpc_request(method='POST', params=None, data=None, files=None, timeout=30):
    api_url = current_app.config.get('RUTORRENT_API_URL')
    user = current_app.config.get('RUTORRENT_USER')
    password = current_app.config.get('RUTORRENT_PASSWORD')
    ssl_verify = current_app.config.get('SEEDBOX_SSL_VERIFY', False)

    if not api_url:
        current_app.logger.error("RUTORRENT_API_URL is not configured.")
        return None, "ruTorrent API URL not configured."
    auth = HTTPDigestAuth(user, password) if user and password else None
    headers = {
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36'
    }
    if not ssl_verify:
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    try:
        current_app.logger.debug(f"Making httprpc request to {api_url}: Method={method}, Auth=Digest, SSLVerify={ssl_verify}, UserAgent='{headers['User-Agent']}', Params={params}, Data={data}, Files={bool(files)}")
        response = requests.request(method, api_url, params=params, data=data, files=files, auth=auth, verify=ssl_verify, timeout=timeout, headers=headers)
        current_app.logger.debug(f"httprpc response status: {response.status_code}, content type: {response.headers.get('Content-Type')}")
        if response.status_code == 401:
            current_app.logger.error(f"httprpc authentication failed (401) even with Digest Auth for URL: {api_url}.")
            return None, "Authentication failed with ruTorrent httprpc (Digest). Check user/password or server Digest settings."
        if response.status_code == 404:
            current_app.logger.error(f"httprpc API endpoint not found (404): {api_url}")
            return None, "ruTorrent httprpc API endpoint not found. Check RUTORRENT_API_URL."
        response.raise_for_status()
        if response.content and 'application/json' in response.headers.get('Content-Type', ''):
            try:
                json_response = response.json()
                # Log the raw JSON response if debug is desired for all JSON responses
                # current_app.logger.debug(f"Raw JSON response from httprpc: {json_response}")
                return json_response, None
            except ValueError as e_json: # json.JSONDecodeError is a subclass
                current_app.logger.error(f"Failed to decode JSON response from httprpc: {e_json}. Response text: {response.text[:500]}")
                return None, f"Failed to decode JSON response: {response.text[:200]}"
        elif response.status_code in [200, 201, 202, 204]:
             current_app.logger.info(f"httprpc request successful (status {response.status_code}) but no JSON content or non-JSON content type. Response text: {response.text[:200]}")
             return response.text.strip() if response.content else True, None # Return stripped text or True
        else: # Should be caught by raise_for_status, but as a fallback
            current_app.logger.warning(f"httprpc request returned status {response.status_code} with non-JSON content: {response.text[:200]}")
            return None, f"Unexpected response from httprpc (status {response.status_code})."
    except requests.exceptions.SSLError as e_ssl:
        current_app.logger.error(f"SSL Error connecting to httprpc at {api_url}: {e_ssl}. Try SEEDBOX_SSL_VERIFY=False in .env if using a self-signed cert.")
        return None, f"SSL Error: {e_ssl}. Check SEEDBOX_SSL_VERIFY."
    except requests.exceptions.ConnectionError as e_conn:
        current_app.logger.error(f"Connection Error for httprpc at {api_url}: {e_conn}")
        return None, f"Connection Error: {e_conn}."
    except requests.exceptions.Timeout as e_timeout:
        current_app.logger.error(f"Timeout connecting to httprpc at {api_url}: {e_timeout}")
        return None, f"Timeout connecting to ruTorrent."
    except requests.exceptions.RequestException as e_req:
        current_app.logger.error(f"Generic RequestException for httprpc at {api_url}: {e_req}")
        return None, f"Request Error: {e_req}."
    except Exception as e_generic:
        current_app.logger.error(f"Unexpected error in _make_httprpc_request for {api_url}: {e_generic}", exc_info=True)
        return None, f"An unexpected error occurred: {str(e_generic)}"

# list_torrents remains the same for now (with its own debug logging for parsing)
def list_torrents():
    payload = {'mode': 'list'}
    json_response, error = _make_httprpc_request(data=payload)
    if error: return None, error
    if not isinstance(json_response, dict) or 't' not in json_response:
        current_app.logger.error(f"httprpc list_torrents: Unexpected JSON structure. 't' key missing. Response: {str(json_response)[:1000]}")
        return None, "Unexpected JSON structure from ruTorrent for torrent list."
    torrents_dict_from_api = json_response.get('t', {})
    if torrents_dict_from_api:
        first_hash = next(iter(torrents_dict_from_api), None)
        if first_hash:
            first_data_array = torrents_dict_from_api[first_hash]
            current_app.logger.info(f"DEBUGGING httprpc list_torrents: First torrent hash: {first_hash}")
            current_app.logger.info(f"DEBUGGING httprpc list_torrents: First torrent data_array (length {len(first_data_array)}): {first_data_array}")
            for i, item_val in enumerate(first_data_array):
                 current_app.logger.info(f"  Index {i}: {item_val} (Type: {type(item_val)})")
    simplified_torrents = []
    for torrent_hash, data_array in torrents_dict_from_api.items():
        try:
            if len(data_array) < 15:
                current_app.logger.warning(f"Skipping torrent {torrent_hash} due to unexpected data_array length: {len(data_array)}")
                continue
            status_code = int(data_array[0])
            name = str(data_array[1])
            size_bytes = int(data_array[2])
            progress_permille = int(data_array[3])
            downloaded_bytes = int(data_array[4])
            uploaded_bytes = int(data_array[5])
            ratio_api = int(data_array[6])
            up_rate_bytes_sec = int(data_array[7])
            down_rate_bytes_sec = int(data_array[8])
            eta_seconds = int(data_array[9])
            label = str(data_array[10]) if data_array[10] else ""
            download_dir = str(data_array[14]) if data_array[14] else ""
            is_active = bool(status_code & 1) and not bool(status_code & 32)
            is_complete = (progress_permille == 1000)
            is_paused = bool(status_code & 32)
            status_str = "Unknown"
            if is_paused: status_str = "Paused"
            elif not (status_code & 1): status_str = "Stopped"
            elif is_active and is_complete: status_str = "Seeding"
            elif is_active and not is_complete: status_str = "Downloading"
            elif bool(status_code & 16): status_str = "Error"
            elif bool(status_code & 2): status_str = "Checking"
            torrent_info = {
                'hash': torrent_hash, 'name': name, 'size_bytes': size_bytes,
                'progress_permille': progress_permille, 'progress_percent': progress_permille / 10.0,
                'downloaded_bytes': downloaded_bytes, 'uploaded_bytes': uploaded_bytes,
                'ratio': ratio_api / 1000.0,
                'up_rate_bytes_sec': up_rate_bytes_sec, 'down_rate_bytes_sec': down_rate_bytes_sec,
                'eta_seconds': eta_seconds, 'label': label, 'download_dir': download_dir,
                'status_text': status_str, 'rtorrent_status_code': status_code,
                'is_active': is_active, 'is_complete': is_complete, 'is_paused': is_paused
            }
            simplified_torrents.append(torrent_info)
        except (IndexError, ValueError, TypeError) as e:
            current_app.logger.error(f"Error parsing data_array for torrent {torrent_hash}: Data was {data_array}. Error: {e}", exc_info=True)
            continue
    current_app.logger.info(f"Successfully listed and attempted to parse {len(torrents_dict_from_api)} torrent entries from httprpc. Parsed {len(simplified_torrents)} successfully.")
    return simplified_torrents, None


def add_magnet(magnet_link, label=None, download_dir=None):
    if not magnet_link:
        return False, "Magnet link cannot be empty."
    payload = {'mode': 'add', 'url': magnet_link, 'fast_resume': '1', 'start_now': '1'}
    if label: payload['label'] = label
    if download_dir: payload['dir_edit'] = download_dir
    current_app.logger.info(f"Adding magnet via httprpc: Payload={payload}, Magnet='{magnet_link[:100]}...'")

    response_data, error = _make_httprpc_request(data=payload)

    # MODIFIED PART: Log the actual response_data more clearly
    if isinstance(response_data, dict):
        current_app.logger.info(f"httprpc 'add magnet' JSON response: {json.dumps(response_data)}")
    else:
        current_app.logger.info(f"httprpc 'add magnet' non-JSON response_data: {response_data}")

    if error:
        current_app.logger.error(f"Error adding magnet via httprpc: {error}")
        return False, error # Return actual error message

    # Success if no error and response_data is typically an empty JSON dict for httprpc add
    # or True (if empty non-JSON 2xx response from _make_httprpc_request)
    # Some httprpc might return nothing (empty string) on success as well.
    if isinstance(response_data, dict) and not response_data: # {} is success
        current_app.logger.info(f"Magnet link '{magnet_link[:100]}...' successfully processed by httprpc (empty JSON response).")
        return True, None
    elif response_data is True or (isinstance(response_data, str) and response_data == ""):
        current_app.logger.info(f"Magnet link '{magnet_link[:100]}...' successfully processed by httprpc (empty/True response).")
        return True, None
    elif isinstance(response_data, dict) and response_data: # Non-empty JSON
        # Check for common error patterns if any, otherwise assume it's not a clean success
        current_app.logger.warning(f"Magnet add via httprpc returned non-empty JSON, potentially indicating an issue: {response_data}")
        return False, f"Torrent add command sent, but server returned unexpected JSON data: {str(response_data)[:200]}"
    else: # Other non-True, non-empty-dict, non-empty-string responses
        current_app.logger.warning(f"Magnet add via httprpc returned unexpected data type or content: {response_data}")
        return False, f"Torrent add command sent, but server response was unexpected: {str(response_data)[:200]}"


def add_torrent_file(file_content_bytes, filename, label=None, download_dir=None):
    if not file_content_bytes or not filename:
        return False, "File content and filename cannot be empty."
    form_data = {'mode': 'add', 'fast_resume': '1', 'start_now': '1'}
    if label: form_data['label'] = label
    if download_dir: form_data['dir_edit'] = download_dir
    files_payload = {'torrent_file': (filename, file_content_bytes, 'application/x-bittorrent')}
    current_app.logger.info(f"Adding torrent file '{filename}' via httprpc: Data={form_data}")

    response_data, error = _make_httprpc_request(data=form_data, files=files_payload)

    # MODIFIED PART: Log the actual response_data more clearly
    if isinstance(response_data, dict):
        current_app.logger.info(f"httprpc 'add file' JSON response: {json.dumps(response_data)}")
    else:
        current_app.logger.info(f"httprpc 'add file' non-JSON response_data: {response_data}")

    if error:
        current_app.logger.error(f"Error adding torrent file '{filename}' via httprpc: {error}")
        return False, error

    if isinstance(response_data, dict) and not response_data: # {} is success
        current_app.logger.info(f"Torrent file '{filename}' successfully processed by httprpc (empty JSON response).")
        return True, None
    elif response_data is True or (isinstance(response_data, str) and response_data == ""):
        current_app.logger.info(f"Torrent file '{filename}' successfully processed by httprpc (empty/True response).")
        return True, None
    elif isinstance(response_data, dict) and response_data:
        current_app.logger.warning(f"Torrent file add via httprpc returned non-empty JSON, potentially indicating an issue: {response_data}")
        return False, f"File add command sent, but server returned unexpected JSON data: {str(response_data)[:200]}"
    else:
        current_app.logger.warning(f"Torrent file add via httprpc returned unexpected data type or content: {response_data}")
        return False, f"File add command sent, but server response was unexpected: {str(response_data)[:200]}"

# get_torrent_hash_by_name remains the same
def get_torrent_hash_by_name(torrent_name, max_retries=3, delay_seconds=2):
    if not torrent_name: return None
    current_app.logger.info(f"Attempting to find hash for torrent name: '{torrent_name}'")
    for attempt in range(max_retries):
        torrents, error = list_torrents()
        if error: current_app.logger.warning(f"get_torrent_hash_by_name: Error listing torrents on attempt {attempt + 1}: {error}")
        if torrents:
            for torrent in torrents:
                if torrent.get('name') == torrent_name:
                    current_app.logger.info(f"Found hash '{torrent.get('hash')}' for torrent name '{torrent_name}' on attempt {attempt + 1}.")
                    return torrent.get('hash')
        if attempt < max_retries - 1:
            current_app.logger.debug(f"Hash for '{torrent_name}' not found yet. Retrying in {delay_seconds}s...")
            time.sleep(delay_seconds)
        else:
            current_app.logger.warning(f"Could not find hash for torrent name '{torrent_name}' after {max_retries} attempts.")
    return None
