# app/utils/rtorrent_client.py
import requests
from requests.auth import HTTPDigestAuth # Changed from HTTPBasicAuth
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
                return json_response, None
            except ValueError as e_json:
                current_app.logger.error(f"Failed to decode JSON response from httprpc: {e_json}. Response text: {response.text[:500]}")
                return None, f"Failed to decode JSON response: {response.text[:200]}"
        elif response.status_code in [200, 201, 202, 204]: # Success with no JSON content or non-JSON
             current_app.logger.info(f"httprpc request successful (status {response.status_code}) but no JSON content or non-JSON content type. Response text: {response.text[:200]}")
             # For mode=add, an empty 200 OK can be success by some httprpc plugins.
             # We will check the actual content of response_data in the calling functions.
             return response.text if response.content else True, None
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
    payload = {'mode': 'list'}
    json_response, error = _make_httprpc_request(data=payload)

    if error:
        return None, error

    if not isinstance(json_response, dict) or 't' not in json_response:
        current_app.logger.error(f"httprpc list_torrents: Unexpected JSON structure. 't' key missing. Response: {str(json_response)[:1000]}") # Log more of the response
        return None, "Unexpected JSON structure from ruTorrent for torrent list."

    # --- DEBUGGING: Log the structure of the first torrent's data_array ---
    torrents_dict_from_api = json_response.get('t', {})
    if torrents_dict_from_api:
        first_hash = next(iter(torrents_dict_from_api), None)
        if first_hash:
            first_data_array = torrents_dict_from_api[first_hash]
            current_app.logger.info(f"DEBUGGING httprpc list_torrents: First torrent hash: {first_hash}")
            current_app.logger.info(f"DEBUGGING httprpc list_torrents: First torrent data_array (length {len(first_data_array)}): {first_data_array}")
            # Log each element with its index
            for i, item_val in enumerate(first_data_array):
                 current_app.logger.info(f"  Index {i}: {item_val} (Type: {type(item_val)})")
    # --- END DEBUGGING ---

    simplified_torrents = []
    # The parsing logic below will likely still fail until we know the correct indices
    # It's kept here but expected to produce errors in the log, which is fine for this debug step.
    for torrent_hash, data_array in torrents_dict_from_api.items():
        try:
            # Assuming the order for now, this will likely need correction based on debug logs
            # Indices we *thought* were correct:
            # 0: Status, 1: Name, 2: Size, 3: Progress %, 4: Downloaded, 5: Uploaded, 6: Ratio, 7: UL, 8: DL, 9: ETA, 10: Label, 14: Directory

            # Defensive parsing: check array length before accessing indices
            if len(data_array) < 15: # Minimum expected length for fields we use
                current_app.logger.warning(f"Skipping torrent {torrent_hash} due to unexpected data_array length: {len(data_array)}")
                continue

            status_code = int(data_array[0]) # Potential error point
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
        except (IndexError, ValueError, TypeError) as e: # Added TypeError
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

    if error:
        current_app.logger.error(f"Error adding magnet via httprpc: {error}")
        return False, error

    # Log the actual response for mode=add
    current_app.logger.info(f"httprpc 'add magnet' response_data: {response_data}")

    # Check if response_data (which could be JSON dict or string) indicates success or failure
    # This part is speculative as httprpc plugins can vary.
    # A common success is an empty JSON object {} or just no error.
    # A failure might be a JSON object with an 'error' key or a non-empty string.
    if isinstance(response_data, dict) and not response_data: # Empty dict {} often means success
        current_app.logger.info(f"Magnet link '{magnet_link[:100]}...' successfully sent to httprpc (empty JSON response).")
        return True, None
    elif response_data is True: # Boolean True from _make_httprpc_request if no content but 2xx status
        current_app.logger.info(f"Magnet link '{magnet_link[:100]}...' successfully sent to httprpc (empty non-JSON response).")
        return True, None
    elif isinstance(response_data, str) and response_data.strip() == "": # Empty string response
        current_app.logger.info(f"Magnet link '{magnet_link[:100]}...' successfully sent to httprpc (empty string response).")
        return True, None
    elif isinstance(response_data, dict) and response_data: # Non-empty dict, check for error flags
        current_app.logger.warning(f"Magnet add via httprpc returned non-empty JSON: {response_data}")
        # You might need to inspect this dict for specific error messages from your plugin
        return False, f"Magnet add command sent, but server returned data: {str(response_data)[:200]}"
    else: # Other unexpected response
        current_app.logger.warning(f"Magnet add via httprpc returned unexpected data type or content: {response_data}")
        return False, f"Magnet add command sent, but server response was unexpected: {str(response_data)[:200]}"


def add_torrent_file(file_content_bytes, filename, label=None, download_dir=None):
    if not file_content_bytes or not filename:
        return False, "File content and filename cannot be empty."
    form_data = {'mode': 'add', 'fast_resume': '1', 'start_now': '1'}
    if label: form_data['label'] = label
    if download_dir: form_data['dir_edit'] = download_dir
    files_payload = {'torrent_file': (filename, file_content_bytes, 'application/x-bittorrent')}
    current_app.logger.info(f"Adding torrent file '{filename}' via httprpc: Data={form_data}")

    response_data, error = _make_httprpc_request(data=form_data, files=files_payload)

    if error:
        current_app.logger.error(f"Error adding torrent file '{filename}' via httprpc: {error}")
        return False, error

    current_app.logger.info(f"httprpc 'add file' response_data: {response_data}")

    if isinstance(response_data, dict) and not response_data: # Empty dict {}
        current_app.logger.info(f"Torrent file '{filename}' successfully sent to httprpc (empty JSON response).")
        return True, None
    elif response_data is True:
        current_app.logger.info(f"Torrent file '{filename}' successfully sent to httprpc (empty non-JSON response).")
        return True, None
    elif isinstance(response_data, str) and response_data.strip() == "":
        current_app.logger.info(f"Torrent file '{filename}' successfully sent to httprpc (empty string response).")
        return True, None
    elif isinstance(response_data, dict) and response_data:
        current_app.logger.warning(f"Torrent file add via httprpc returned non-empty JSON: {response_data}")
        return False, f"File add command sent, but server returned data: {str(response_data)[:200]}"
    else:
        current_app.logger.warning(f"Torrent file add via httprpc returned unexpected data type or content: {response_data}")
        return False, f"File add command sent, but server response was unexpected: {str(response_data)[:200]}"


def get_torrent_hash_by_name(torrent_name, max_retries=3, delay_seconds=2):
    # ... (Implementation from Part 2 - unchanged, but will benefit from corrected list_torrents parsing) ...
    if not torrent_name: return None
    current_app.logger.info(f"Attempting to find hash for torrent name: '{torrent_name}'")
    for attempt in range(max_retries):
        torrents, error = list_torrents() # This will now use the debug logging for the first torrent
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
