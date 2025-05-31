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

        # Do not call raise_for_status() here if we want to inspect the body of 200 OK responses that might indicate app-level errors
        # We will check the content for application-level success/failure.

        if response.content and 'application/json' in response.headers.get('Content-Type', ''):
            try:
                json_response = response.json()
                # If status is not 2xx even with JSON, it's an HTTP error reported in JSON.
                if not (200 <= response.status_code < 300):
                     current_app.logger.error(f"httprpc returned HTTP {response.status_code} with JSON error: {json_response}")
                     error_detail = str(json_response.get('error', json_response)) if isinstance(json_response, dict) else str(json_response)
                     return None, f"HTTP {response.status_code} with error: {error_detail[:200]}"
                return json_response, None
            except ValueError as e_json:
                current_app.logger.error(f"Failed to decode JSON response from httprpc (status {response.status_code}): {e_json}. Response text: {response.text[:500]}")
                # If it was supposed to be JSON but failed, and status was 2xx, it's a problem.
                if 200 <= response.status_code < 300:
                    return None, f"Received HTTP {response.status_code} but failed to decode expected JSON response: {response.text[:200]}"
                else: # HTTP error that wasn't JSON
                    return None, f"HTTP {response.status_code}: {response.text[:200]}"
        elif 200 <= response.status_code < 300: # Success with non-JSON or no content
             current_app.logger.info(f"httprpc request successful (status {response.status_code}) but no JSON content or non-JSON content type. Response text: {response.text[:200]}")
             return response.text.strip() if response.content else True, None # Return stripped text or True
        else: # Non-2xx and not JSON, this is a clear HTTP error
            current_app.logger.error(f"httprpc request failed with HTTP status {response.status_code}. Response: {response.text[:200]}")
            response.raise_for_status() # Let requests raise the HTTPError to be caught below
            return None, f"HTTP Error {response.status_code}: {response.text[:200]}" # Fallback, should be caught by raise_for_status

    except requests.exceptions.HTTPError as e_http: # Raised by response.raise_for_status()
        current_app.logger.error(f"HTTP Error for httprpc at {api_url}: {e_http}")
        return None, f"HTTP Error: {e_http}."
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
        current_app.logger.error(f"httprpc list_torrents: Unexpected JSON structure. 't' key missing. Response: {str(json_response)[:1000]}")
        return None, "Unexpected JSON structure from ruTorrent for torrent list."

    torrents_dict_from_api = json_response.get('t', {})
    # --- DEBUGGING LOGIC (can be removed or commented out after confirming structure) ---
    if torrents_dict_from_api and current_app.debug: # Only log in debug mode
        first_hash = next(iter(torrents_dict_from_api), None)
        if first_hash:
            first_data_array = torrents_dict_from_api[first_hash]
            current_app.logger.info(f"DEBUGGING httprpc list_torrents: First torrent hash: {first_hash}")
            current_app.logger.info(f"DEBUGGING httprpc list_torrents: First torrent data_array (length {len(first_data_array)}): {first_data_array}")
            for i, item_val in enumerate(first_data_array):
                 current_app.logger.info(f"  Index {i}: {item_val} (Type: {type(item_val)})")
    # --- END DEBUGGING ---

    simplified_torrents = []
    # Based on user log: https://<...>/rutorrent/plugins/httprpc/action.php
    # Index 0: d.is_open() (str '1' or '0')
    # Index 1: d.is_hash_checking() (str '1' or '0')
    # Index 2: d.is_hash_checked() (str '1' or '0')
    # Index 3: d.get_state() (str '1' or '0' for active/inactive)
    # Index 4: d.get_name() (str)
    # Index 5: d.get_size_bytes() (str)
    # Index 6: d.get_completed_chunks() (str)
    # Index 7: d.get_size_chunks() (str)
    # Index 8: d.get_bytes_done() (str)
    # Index 9: d.get_up_total() (str, total uploaded bytes)
    # Index 10: d.get_ratio() (str, ratio * 1000)
    # Index 11: d.get_up_rate() (str, bytes/sec)
    # Index 12: d.get_down_rate() (str, bytes/sec)
    # Index 13: d.get_chunk_size() (str, bytes)
    # Index 14: d.get_custom1() (Label, str)
    # Index 25: d.get_base_path() (Download directory, str)
    # Index 21: Timestamp of creation/loading (seems to be a unix timestamp string)

    for torrent_hash, data_array in torrents_dict_from_api.items():
        try:
            if len(data_array) < 26: # Need at least up to index 25 for base_path
                current_app.logger.warning(f"Skipping torrent {torrent_hash} due to insufficient data_array length: {len(data_array)}")
                continue

            # All values from httprpc data_array are strings, convert them carefully
            is_open = (data_array[0] == '1')
            is_hash_checking = (data_array[1] == '1')
            # is_hash_checked = (data_array[2] == '1') # Not directly used for status_text
            is_active_rt = (data_array[3] == '1') # rTorrent's concept of "active" (d.get_state)

            name = str(data_array[4])
            size_bytes = int(data_array[5])
            completed_chunks = int(data_array[6])
            total_chunks = int(data_array[7])
            bytes_done = int(data_array[8])
            # up_total = int(data_array[9]) # Not used in current simplified dict
            ratio_val = int(data_array[10])
            up_rate_bytes_sec = int(data_array[11])
            down_rate_bytes_sec = int(data_array[12])
            # chunk_size = int(data_array[13]) # Not used
            label = str(data_array[14])
            download_dir = str(data_array[25])

            # Calculate progress
            if total_chunks > 0:
                progress_permille = int((completed_chunks / total_chunks) * 1000)
            elif size_bytes > 0 : # Fallback if chunks are zero (e.g. magnet not fully loaded meta)
                progress_permille = int((bytes_done / size_bytes) * 1000)
            else:
                progress_permille = 0

            is_complete = (bytes_done >= size_bytes) and size_bytes > 0 # Ensure size_bytes > 0 for trackers/magnets without metadata yet

            # Determine status_text (improved logic)
            status_text = "Unknown"
            if is_hash_checking:
                status_text = "Checking"
            elif not is_open: # Torrent is closed/stopped
                 status_text = "Stopped"
            elif not is_active_rt: # Open but not active (implies paused by rTorrent's state)
                status_text = "Paused"
            elif is_active_rt:
                if is_complete:
                    status_text = "Seeding"
                else:
                    status_text = "Downloading"
            # Consider d.get_message() for error states if available at a known index

            torrent_info = {
                'hash': torrent_hash,
                'name': name,
                'size_bytes': size_bytes,
                'progress_permille': progress_permille,
                'progress_percent': progress_permille / 10.0,
                'downloaded_bytes': bytes_done,
                'uploaded_bytes': int(data_array[9]), # up_total
                'ratio': ratio_val / 1000.0,
                'up_rate_bytes_sec': up_rate_bytes_sec,
                'down_rate_bytes_sec': down_rate_bytes_sec,
                'eta_seconds': int(data_array[9]) if len(data_array) > 9 and data_array[9].isdigit() else 0, # Assuming index 9 is ETA, check if it's digit
                'label': label,
                'download_dir': download_dir,
                'status_text': status_text,
                'rtorrent_status_code': data_array[0] + data_array[3], # Composite for rough idea
                'is_active': is_active_rt and is_open, # Active means it's running and not paused
                'is_complete': is_complete,
                'is_paused': not is_active_rt and is_open # Paused means open but not active (d.get_state=0 but d.is_open=1)
            }
            simplified_torrents.append(torrent_info)
        except (IndexError, ValueError, TypeError) as e:
            current_app.logger.error(f"Error parsing data_array for torrent {torrent_hash}. Data: {data_array}. Error: {e}", exc_info=True)
            continue

    current_app.logger.info(f"Successfully listed and parsed {len(simplified_torrents)} out of {len(torrents_dict_from_api)} torrent entries from httprpc.")
    return simplified_torrents, None


def add_magnet(magnet_link, label=None, download_dir=None):
    if not magnet_link:
        return False, "Magnet link cannot be empty."
    payload = {'mode': 'add', 'url': magnet_link, 'fast_resume': '1', 'start_now': '1'}
    if label: payload['label'] = label
    if download_dir: payload['dir_edit'] = download_dir
    current_app.logger.info(f"Adding magnet via httprpc: Payload={payload}, Magnet='{magnet_link[:100]}...'")

    response_data, error = _make_httprpc_request(data=payload)

    # Log the actual response_data more clearly
    log_msg_prefix = "httprpc 'add magnet'"
    if isinstance(response_data, dict):
        current_app.logger.info(f"{log_msg_prefix} JSON response: {json.dumps(response_data)}")
    elif isinstance(response_data, str):
        current_app.logger.info(f"{log_msg_prefix} text response_data: '{response_data}'")
    else: # Boolean or None
        current_app.logger.info(f"{log_msg_prefix} other response_data: {response_data}")

    if error:
        current_app.logger.error(f"Error adding magnet via httprpc: {error}")
        return False, error # Return actual error message

    # Explicitly check if response_data is the boolean False (coming from JSON 'false')
    if response_data is False:
        current_app.logger.error(f"Magnet add failed: httprpc returned JSON 'false'. Magnet: {magnet_link[:100]}")
        return False, "ruTorrent httprpc indicated failure (returned false)."

    # Consider other non-empty dicts or non-empty strings as potential issues for 'add'
    if isinstance(response_data, dict) and response_data: # Non-empty dict
        current_app.logger.warning(f"Magnet add via httprpc returned non-empty JSON, potentially indicating an issue: {response_data}")
        return False, f"Torrent add command sent, but server returned unexpected JSON data: {str(response_data)[:200]}"
    if isinstance(response_data, str) and response_data: # Non-empty string
        current_app.logger.warning(f"Magnet add via httprpc returned non-empty text, potentially indicating an issue: '{response_data}'")
        return False, f"Torrent add command sent, but server returned unexpected text data: {str(response_data)[:200]}"

    # Success if response_data is True (empty 2xx) or empty dict {} or empty string ""
    current_app.logger.info(f"Magnet link '{magnet_link[:100]}...' successfully processed by httprpc.")
    return True, None


def add_torrent_file(file_content_bytes, filename, label=None, download_dir=None):
    if not file_content_bytes or not filename:
        return False, "File content and filename cannot be empty."
    form_data = {'mode': 'add', 'fast_resume': '1', 'start_now': '1'}
    if label: form_data['label'] = label
    if download_dir: form_data['dir_edit'] = download_dir
    files_payload = {'torrent_file': (filename, file_content_bytes, 'application/x-bittorrent')}
    current_app.logger.info(f"Adding torrent file '{filename}' via httprpc: Data={form_data}")

    response_data, error = _make_httprpc_request(data=form_data, files=files_payload)

    log_msg_prefix = "httprpc 'add file'"
    if isinstance(response_data, dict):
        current_app.logger.info(f"{log_msg_prefix} JSON response: {json.dumps(response_data)}")
    elif isinstance(response_data, str):
        current_app.logger.info(f"{log_msg_prefix} text response_data: '{response_data}'")
    else:
        current_app.logger.info(f"{log_msg_prefix} other response_data: {response_data}")

    if error:
        current_app.logger.error(f"Error adding torrent file '{filename}' via httprpc: {error}")
        return False, error

    if response_data is False: # Explicit JSON 'false' from server
        current_app.logger.error(f"Torrent file add failed: httprpc returned JSON 'false'. File: {filename}")
        return False, "ruTorrent httprpc indicated failure (returned false)."

    if isinstance(response_data, dict) and response_data: # Non-empty dict
        current_app.logger.warning(f"Torrent file add via httprpc returned non-empty JSON, potentially indicating an issue: {response_data}")
        return False, f"File add command sent, but server returned unexpected JSON data: {str(response_data)[:200]}"
    if isinstance(response_data, str) and response_data: # Non-empty string
        current_app.logger.warning(f"Torrent file add via httprpc returned non-empty text, potentially indicating an issue: '{response_data}'")
        return False, f"File add command sent, but server returned unexpected text data: {str(response_data)[:200]}"

    current_app.logger.info(f"Torrent file '{filename}' successfully processed by httprpc.")
    return True, None

def get_torrent_hash_by_name(torrent_name, max_retries=3, delay_seconds=2):
    if not torrent_name: return None
    current_app.logger.info(f"Attempting to find hash for torrent name: '{torrent_name}' (using corrected list_torrents)")
    for attempt in range(max_retries):
        torrents, error = list_torrents()
        if error:
            current_app.logger.warning(f"get_torrent_hash_by_name: Error listing torrents on attempt {attempt + 1}: {error}")
            # If list_torrents itself fails, wait and retry
            if attempt < max_retries - 1:
                time.sleep(delay_seconds)
                continue
            else: # Max retries for list_torrents error
                return None

        if torrents: # Ensure torrents is not None (it will be an empty list if parsing fails for all)
            for torrent in torrents: # torrents is now a list of dicts
                if torrent.get('name') == torrent_name:
                    current_app.logger.info(f"Found hash '{torrent.get('hash')}' for torrent name '{torrent_name}' on attempt {attempt + 1}.")
                    return torrent.get('hash')

        if attempt < max_retries - 1:
            current_app.logger.debug(f"Hash for '{torrent_name}' not found yet. Retrying in {delay_seconds}s...")
            time.sleep(delay_seconds)
        else:
            current_app.logger.warning(f"Could not find hash for torrent name '{torrent_name}' after {max_retries} attempts.")

    return None
