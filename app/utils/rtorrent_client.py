# app/utils/rtorrent_client.py
import requests
from requests.auth import HTTPBasicAuth
from flask import current_app
import json
import time # For get_torrent_hash_by_name retry logic

# --- Keep the previously defined _make_httprpc_request() and list_torrents() ---

def _make_httprpc_request(method='POST', params=None, data=None, files=None, timeout=30):
    # ... (Implementation from Part 1 - unchanged) ...
    api_url = current_app.config.get('RUTORRENT_API_URL')
    user = current_app.config.get('RUTORRENT_USER')
    password = current_app.config.get('RUTORRENT_PASSWORD')
    ssl_verify = current_app.config.get('SEEDBOX_SSL_VERIFY', False)

    if not api_url:
        current_app.logger.error("RUTORRENT_API_URL is not configured.")
        return None, "ruTorrent API URL not configured."
    auth = HTTPBasicAuth(user, password) if user and password else None
    headers = {'Accept': 'application/json'}
    if not ssl_verify:
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    try:
        current_app.logger.debug(f"Making httprpc request to {api_url}: Method={method}, SSLVerify={ssl_verify}, Params={params}, Data={data}, Files={bool(files)}")
        response = requests.request(method, api_url, params=params, data=data, files=files, auth=auth, verify=ssl_verify, timeout=timeout, headers=headers)
        current_app.logger.debug(f"httprpc response status: {response.status_code}, content type: {response.headers.get('Content-Type')}")
        if response.status_code == 401:
            current_app.logger.error(f"httprpc authentication failed (401) for URL: {api_url}")
            return None, "Authentication failed with ruTorrent httprpc. Check user/password."
        if response.status_code == 404:
            current_app.logger.error(f"httprpc API endpoint not found (404): {api_url}")
            return None, "ruTorrent httprpc API endpoint not found. Check RUTORRENT_API_URL."
        response.raise_for_status()
        if response.content and 'application/json' in response.headers.get('Content-Type', ''):
            try:
                json_response = response.json()
                return json_response, None
            except ValueError as e_json:
                current_app.logger.error(f"Failed to decode JSON response from httprpc: {e_json}. Response text: {response.text[:500]}")
                return None, f"Failed to decode JSON response: {response.text[:200]}"
        elif response.status_code in [200, 201, 202, 204]:
             current_app.logger.info(f"httprpc request successful (status {response.status_code}) but no JSON content or non-JSON content type.")
             return True, None
        else:
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


def list_torrents():
    # ... (Implementation from Part 1 - unchanged) ...
    payload = {'mode': 'list'}
    json_response, error = _make_httprpc_request(data=payload)
    if error: return None, error
    if not isinstance(json_response, dict) or 't' not in json_response:
        current_app.logger.error(f"httprpc list_torrents: Unexpected JSON structure. 't' key missing. Response: {str(json_response)[:500]}")
        return None, "Unexpected JSON structure from ruTorrent for torrent list."
    torrents_dict_from_api = json_response.get('t', {})
    simplified_torrents = []
    for torrent_hash, data_array in torrents_dict_from_api.items():
        try:
            status_code = int(data_array[0])
            is_active = bool(status_code & 1) and not bool(status_code & 32)
            is_complete = (int(data_array[3]) == 1000)
            is_paused = bool(status_code & 32)
            status_str = "Unknown"
            if is_paused: status_str = "Paused"
            elif not (status_code & 1): status_str = "Stopped"
            elif is_active and is_complete: status_str = "Seeding"
            elif is_active and not is_complete: status_str = "Downloading"
            elif bool(status_code & 16): status_str = "Error"
            elif bool(status_code & 2): status_str = "Checking"
            torrent_info = {
                'hash': torrent_hash, 'name': str(data_array[1]), 'size_bytes': int(data_array[2]),
                'progress_permille': int(data_array[3]), 'progress_percent': int(data_array[3]) / 10.0,
                'downloaded_bytes': int(data_array[4]), 'uploaded_bytes': int(data_array[5]),
                'ratio': int(data_array[6]) / 1000.0 if data_array[6] else 0.0,
                'up_rate_bytes_sec': int(data_array[7]), 'down_rate_bytes_sec': int(data_array[8]),
                'eta_seconds': int(data_array[9]),
                'label': str(data_array[10]) if len(data_array) > 10 and data_array[10] else "",
                'status_text': status_str, 'rtorrent_status_code': status_code,
                'is_active': is_active, 'is_complete': is_complete, 'is_paused': is_paused
            }
            if len(data_array) > 14 and data_array[14]: torrent_info['download_dir'] = str(data_array[14])
            simplified_torrents.append(torrent_info)
        except (IndexError, ValueError) as e:
            current_app.logger.error(f"Error parsing data_array for torrent {torrent_hash}: {data_array}. Error: {e}")
            continue
    current_app.logger.info(f"Successfully listed and parsed {len(simplified_torrents)} torrents from httprpc.")
    return simplified_torrents, None

# --- NEW FUNCTIONS for Part 2 ---

def add_magnet(magnet_link, label=None, download_dir=None):
    """
    Adds a torrent via magnet link using httprpc.
    Args:
        magnet_link (str): The magnet URI.
        label (str, optional): Label to assign to the torrent in rTorrent.
        download_dir (str, optional): Specific download directory on the seedbox.
    Returns:
        tuple: (True, None) if successful (httprpc 'add' often returns no body or non-JSON on success).
               (False, error_message_string) if an error occurred.
               Note: httprpc mode=add does not directly return the torrent hash.
    """
    if not magnet_link:
        return False, "Magnet link cannot be empty."

    payload = {
        'mode': 'add',
        'url': magnet_link,
        'fast_resume': '1', # Try to use fast resume data
        'start_now': '1'    # Attempt to start the torrent immediately
    }
    if label:
        payload['label'] = label
    if download_dir:
        payload['dir_edit'] = download_dir # dir_edit is common for setting download directory

    current_app.logger.info(f"Adding magnet via httprpc: Label='{label}', Dir='{download_dir}', Magnet='{magnet_link[:100]}...'")

    response_data, error = _make_httprpc_request(data=payload)

    if error:
        current_app.logger.error(f"Error adding magnet via httprpc: {error}")
        return False, error

    # httprpc 'add' mode might return an empty success or non-JSON.
    # _make_httprpc_request returns True for such cases if status code is OK.
    if response_data is True: # Success, but no specific data returned from httprpc
        current_app.logger.info(f"Magnet link '{magnet_link[:100]}...' successfully sent to httprpc.")
        return True, None
    else: # Should ideally be True or an error.
        current_app.logger.warning(f"Magnet add via httprpc returned unexpected data: {response_data}")
        # Assuming success if no error, but this is a bit ambiguous from httprpc.
        # If an error occurred, 'error' would be set.
        return True, "Torrent sent, but unexpected response from server."


def add_torrent_file(file_content_bytes, filename, label=None, download_dir=None):
    """
    Adds a torrent from its file content (bytes) using httprpc.
    Args:
        file_content_bytes (bytes): Raw byte content of the .torrent file.
        filename (str): The original filename of the .torrent file.
        label (str, optional): Label to assign to the torrent in rTorrent.
        download_dir (str, optional): Specific download directory on the seedbox.
    Returns:
        tuple: (True, None) if successful.
               (False, error_message_string) if an error occurred.
               Note: httprpc mode=add does not directly return the torrent hash.
    """
    if not file_content_bytes or not filename:
        return False, "File content and filename cannot be empty."

    form_data = {
        'mode': 'add',
        'fast_resume': '1',
        'start_now': '1'
    }
    if label:
        form_data['label'] = label
    if download_dir:
        form_data['dir_edit'] = download_dir

    # Files dict for requests: {'field_name': (filename, file_bytes, content_type)}
    # Assuming 'torrent_file' is the field name httprpc expects.
    files_payload = {
        'torrent_file': (filename, file_content_bytes, 'application/x-bittorrent')
    }

    current_app.logger.info(f"Adding torrent file '{filename}' via httprpc: Label='{label}', Dir='{download_dir}'")
    response_data, error = _make_httprpc_request(data=form_data, files=files_payload)

    if error:
        current_app.logger.error(f"Error adding torrent file '{filename}' via httprpc: {error}")
        return False, error

    if response_data is True:
        current_app.logger.info(f"Torrent file '{filename}' successfully sent to httprpc.")
        return True, None
    else:
        current_app.logger.warning(f"Torrent file add via httprpc returned unexpected data: {response_data}")
        return True, "Torrent file sent, but unexpected response from server."


def get_torrent_hash_by_name(torrent_name, max_retries=3, delay_seconds=2):
    """
    Attempts to find a torrent's hash by its name.
    This is useful because httprpc 'add' mode doesn't return the hash directly.
    It might take a few seconds for a newly added torrent to appear in the list.
    Args:
        torrent_name (str): The name of the torrent to search for.
        max_retries (int): How many times to retry listing torrents.
        delay_seconds (int): Seconds to wait between retries.
    Returns:
        str: The torrent hash if found, otherwise None.
    """
    if not torrent_name:
        return None

    current_app.logger.info(f"Attempting to find hash for torrent name: '{torrent_name}'")
    for attempt in range(max_retries):
        torrents, error = list_torrents()
        if error:
            current_app.logger.warning(f"get_torrent_hash_by_name: Error listing torrents on attempt {attempt + 1}: {error}")
            # Don't return immediately on list error, give it a chance to recover if transient

        if torrents: # Ensure torrents is not None
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
