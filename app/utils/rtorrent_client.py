# app/utils/rtorrent_client.py
import requests
from requests.auth import HTTPDigestAuth
from flask import current_app
import json
import time
import xmlrpc.client
import logging
# import base64 # For xmlrpc.client.Binary later

def _send_xmlrpc_request(method_name, params):
    api_url = current_app.config.get('RTORRENT_API_URL')
    user = current_app.config.get('RTORRENT_USER')
    password = current_app.config.get('RTORRENT_PASSWORD')
    # Read as string to handle "True"/"False" from config, default to "True"
    ssl_verify_str = str(current_app.config.get('RTORRENT_SSL_VERIFY', "True"))
    ssl_verify = False if ssl_verify_str.lower() == "false" else True

    if not api_url:
        current_app.logger.error("RTORRENT_API_URL is not configured for XML-RPC.")
        return None, "ruTorrent API URL not configured."

    auth = HTTPDigestAuth(user, password) if user and password else None

    try:
        # Ensure params is a tuple for dumps.
        # If params is a single list/tuple argument for a method expecting one list: (params,)
        # If params is a list of arguments for a method: tuple(params)
        # The prompt example `params = ("", magnet_uri, "d.custom1.set=label")` suggests params will be a list of arguments.
        xml_body = xmlrpc.client.dumps(tuple(params), methodname=method_name, encoding='UTF-8', allow_none=False)
    except Exception as e_dumps:
        current_app.logger.error(f"XML-RPC Dumps Error for {method_name}: {e_dumps}", exc_info=True)
        return None, f"Error creating XML-RPC request: {e_dumps}"

    headers = {
        'Content-Type': 'text/xml',
        'User-Agent': 'MediaManagerSuite/1.0 XML-RPC'
    }

    # Store original state of warnings
    warnings_disabled = False
    if not ssl_verify:
        # Check if warnings are already disabled by looking at the warnings module filters
        # This is a bit more involved than typical, but let's assume for now that repeated calls are fine
        # or that flask/app handles this. Simpler: just call disable_warnings.
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
        warnings_disabled = True # Track that we disabled them

    current_app.logger.debug(f"Sending XML-RPC request to {api_url}: Method='{method_name}', Params={params}")
    # Using debug for XML body log, as trace might not be configured. Truncate to avoid overly long logs.
    if current_app.logger.isEnabledFor(logging.DEBUG):
        current_app.logger.debug(f"XML-RPC Request Body for {method_name}:\n{xml_body}")
    else:
        current_app.logger.info(f"XML-RPC Request Body for {method_name} (first 500 bytes, DEBUG for full): {xml_body[:500]}")

    try:
        response = requests.post(api_url, data=xml_body.encode('UTF-8'), headers=headers, auth=auth, verify=ssl_verify, timeout=30)

        current_app.logger.debug(f"XML-RPC Response Status for {method_name}: {response.status_code}")
        current_app.logger.debug(f"XML-RPC Response Headers for {method_name}: {response.headers}")
        current_app.logger.debug(f"XML-RPC Response Body for {method_name} (raw, first 500 bytes): {response.content[:500]}")

        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        current_app.logger.debug(f"XML-RPC Raw Response Body for {method_name} (Content type: {response.headers.get('Content-Type')}):\n{response.text}")
        # Parser la réponse XML-RPC
        parsed_data, _ = xmlrpc.client.loads(response.content, use_builtin_types=True)

        # parsed_data is the 'params' part of xmlrpc.client.loads() output tuple.
        # For load.start, this is typically (0,).
        # For d.multicall2, this is typically ( [[torrent1_fields], [torrent2_fields]], )
        current_app.logger.debug(f"XML-RPC call to {method_name} successful. Parsed params from loads: {parsed_data!r}")

        if method_name == "d.multicall2":
            # parsed_data should be a tuple containing one element: the list of lists. e.g. ( [[fields1], [fields2]], )
            # We want to return the list of lists: [[fields1], [fields2]]
            if isinstance(parsed_data, tuple) and len(parsed_data) == 1 and isinstance(parsed_data[0], list):
                return parsed_data[0], None
            # Additional check: if parsed_data is already a list (e.g. if loads() behaves differently or for an empty multicall response from some servers like ([],) )
            # or if parsed_data is an empty list itself (from a response like ([],) which parsed_data[0] would yield [])
            elif isinstance(parsed_data, list):
                 return parsed_data, None
            else:
                current_app.logger.error(f"Unexpected structure for d.multicall2 response: {parsed_data!r}")
                return [], f"Unexpected structure for d.multicall2 response." # Return empty list and error
        else: # For other methods like load.start, load.raw_start
              # parsed_data should be a tuple containing one element, e.g. (0,) or ("string_result",)
            if isinstance(parsed_data, tuple):
                if len(parsed_data) > 0:
                    return parsed_data[0], None # Extract the actual value, e.g., 0 from (0,)
                else: # Empty tuple from loads e.g. ()
                    return None, None
            else: # Should not be reached if xmlrpc.client.loads consistently returns a tuple for params
                current_app.logger.warning(f"XML-RPC response params for {method_name} was not a tuple: {parsed_data!r}. Returning as is.")
                return parsed_data, None

    except xmlrpc.client.Fault as f:
        current_app.logger.error(f"XML-RPC Fault for {method_name}: Code {f.faultCode} - {f.faultString}", exc_info=True)
        return None, f"XML-RPC Fault {f.faultCode}: {f.faultString}"
    except requests.exceptions.HTTPError as e_http:
        # Log more details from response if available
        error_response_text = ""
        if e_http.response is not None:
            error_response_text = e_http.response.text[:500]
        current_app.logger.error(f"HTTP Error for XML-RPC {method_name} at {api_url}: {e_http}. Response: {error_response_text}", exc_info=True)
        return None, f"HTTP Error: {e_http}."
    except requests.exceptions.SSLError as e_ssl:
        current_app.logger.error(f"SSL Error for XML-RPC {method_name} at {api_url}: {e_ssl}", exc_info=True)
        return None, f"SSL Error: {e_ssl}. Check SEEDBOX_SSL_VERIFY (current: {ssl_verify})."
    except requests.exceptions.ConnectionError as e_conn:
        current_app.logger.error(f"Connection Error for XML-RPC {method_name} at {api_url}: {e_conn}", exc_info=True)
        return None, f"Connection Error: {e_conn}."
    except requests.exceptions.Timeout as e_timeout:
        current_app.logger.error(f"Timeout for XML-RPC {method_name} at {api_url}: {e_timeout}", exc_info=True)
        return None, f"Timeout connecting to ruTorrent for XML-RPC."
    except requests.exceptions.RequestException as e_req: # Catch other request-related exceptions
        current_app.logger.error(f"Request Exception for XML-RPC {method_name} at {api_url}: {e_req}", exc_info=True)
        return None, f"Request Exception: {e_req}."
    except Exception as e:
        current_app.logger.error(f"Unexpected error in _send_xmlrpc_request for {method_name} at {api_url}: {e}", exc_info=True)
        # Log the type of exception as well
        return None, f"Unexpected error ({type(e).__name__}) during XML-RPC request: {e}"
    finally:
        # Re-enable warnings only if we were the ones to disable them and they were not already disabled.
        # This basic check might not be perfectly robust if other parts of app also toggle warnings.
        if warnings_disabled:
            # This re-enables all warnings of this type. If they were specifically filtered before, this is not ideal.
            # A more robust solution would involve saving and restoring the exact warning filter state.
            # requests.packages.urllib3.enable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning) # This line causes AttributeError
            pass # Warnings are left as they were (potentially disabled for this session if SSL verify is False)

# _make_httprpc_request remains the same
def _make_httprpc_request(method='POST', params=None, data=None, files=None, timeout=30):
    # ... (implementation from previous correct version) ...
    api_url = current_app.config.get('RTORRENT_API_URL')
    user = current_app.config.get('RTORRENT_USER')
    password = current_app.config.get('RTORRENT_PASSWORD')
    ssl_verify = current_app.config.get('RTORRENT_SSL_VERIFY', False)
    if not api_url:
        current_app.logger.error("RTORRENT_API_URL is not configured.")
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
            return None, "ruTorrent httprpc API endpoint not found. Check RTORRENT_API_URL."
        if response.content and 'application/json' in response.headers.get('Content-Type', ''):
            try:
                json_response = response.json()
                if not (200 <= response.status_code < 300):
                     current_app.logger.error(f"httprpc returned HTTP {response.status_code} with JSON error: {json_response}")
                     error_detail = str(json_response.get('error', json_response)) if isinstance(json_response, dict) else str(json_response)
                     return None, f"HTTP {response.status_code} with error: {error_detail[:200]}"
                return json_response, None
            except ValueError as e_json:
                current_app.logger.error(f"Failed to decode JSON response from httprpc (status {response.status_code}): {e_json}. Response text: {response.text[:500]}")
                if 200 <= response.status_code < 300:
                    return None, f"Received HTTP {response.status_code} but failed to decode expected JSON response: {response.text[:200]}"
                else:
                    return None, f"HTTP {response.status_code}: {response.text[:200]}"
        elif 200 <= response.status_code < 300:
             current_app.logger.info(f"httprpc request successful (status {response.status_code}) but no JSON content or non-JSON content type. Response text: {response.text[:200]}")
             return response.text.strip() if response.content else True, None
        else:
            current_app.logger.error(f"httprpc request failed with HTTP status {response.status_code}. Response: {response.text[:200]}")
            response.raise_for_status()
            return None, f"HTTP Error {response.status_code}: {response.text[:200]}"
    except requests.exceptions.HTTPError as e_http:
        current_app.logger.error(f"HTTP Error for httprpc at {api_url}: {e_http}")
        return None, f"HTTP Error: {e_http}."
    except requests.exceptions.SSLError as e_ssl: return None, f"SSL Error: {e_ssl}. Check SEEDBOX_SSL_VERIFY."
    except requests.exceptions.ConnectionError as e_conn: return None, f"Connection Error: {e_conn}."
    except requests.exceptions.Timeout as e_timeout: return None, f"Timeout connecting to ruTorrent."
    except requests.exceptions.RequestException as e_req: return None, f"Request Error: {e_req}."
    except Exception as e_generic:
        current_app.logger.error(f"Unexpected error in _make_httprpc_request for {api_url}: {e_generic}", exc_info=True)
        return None, f"An unexpected error occurred: {str(e_generic)}"

# list_torrents is now reimplemented using XML-RPC
def list_torrents():
    current_app.logger.info("Listing torrents via XML-RPC d.multicall2.")
    fields = [
        "d.hash=", "d.name=", "d.base_path=", "d.custom1=", "d.size_bytes=",
        "d.bytes_done=", "d.up.total=", "d.down.rate=", "d.up.rate=",
        "d.ratio=", "d.is_open=", "d.is_active=", "d.complete=", # Using d.complete=
        "d.left_bytes=", "d.message="
    ]
    # Using ["", ""] as first two params, similar to Sonarr's multicall for downloads.
    # This typically means "all torrents" and "default view".
    params_for_xmlrpc = ["", ""] + fields

    # Note: _send_xmlrpc_request for d.multicall2 is expected to return the direct list of lists.
    # The previous _send_xmlrpc_request logic was:
    #   if isinstance(parsed_data, list) and len(parsed_data) > 0: return parsed_data[0], None
    #   This needs to be adjusted for d.multicall2, which returns a list of lists, so parsed_data itself is the result.
    # For now, let's assume _send_xmlrpc_request is modified or handles this.
    # For the purpose of this function, we expect `raw_torrents_data` to be the list of lists.
    # We need to ensure _send_xmlrpc_request returns the full list for d.multicall2, not just parsed_data[0]
    # This will require a slight modification in _send_xmlrpc_request or a new specific xmlrpc caller for multicall.
    # Let's assume _send_xmlrpc_request is generic and returns `parsed_data` directly.
    # If `_send_xmlrpc_request` returns `parsed_data[0]`, and `parsed_data` is `[[torrent1_fields], [torrent2_fields]]`
    # then `raw_torrents_data` would incorrectly be `[torrent1_fields]`.
    # Let's modify the expectation for _send_xmlrpc_request: it should return the *full* `parsed_data` if the method is 'd.multicall2'.
    # For now, this implementation will assume `_send_xmlrpc_request` correctly returns the list of lists for d.multicall2.
    # This is a critical assumption. If _send_xmlrpc_request always returns `parsed_data[0]`, this will break.
    # A quick fix for _send_xmlrpc_request would be:
    # if method_name == "d.multicall2": return parsed_data, None else: return parsed_data[0] if ... else ...

    raw_torrents_data, error = _send_xmlrpc_request(method_name="d.multicall2", params=params_for_xmlrpc)

    if error:
        current_app.logger.error(f"XML-RPC error calling d.multicall2 for list_torrents: {error}")
        return None, error

    if not isinstance(raw_torrents_data, list):
        # This will also catch the case where _send_xmlrpc_request returns parsed_data[0] if raw_torrents_data was [[fields_t1], [fields_t2]]
        # because then raw_torrents_data would be [fields_t1], which is a list, but its elements are not lists.
        # Or if it was a single torrent, raw_torrents_data would be [field1, field2...], not a list of lists.
        current_app.logger.error(f"XML-RPC d.multicall2 for list_torrents: Expected a list of lists, got {type(raw_torrents_data)}. Data: {str(raw_torrents_data)[:500]}")
        return None, "Unexpected data structure from rTorrent for torrent list (XML-RPC)."

    simplified_torrents = []
    field_keys = [
        'hash', 'name', 'download_dir', 'label', 'size_bytes', 'downloaded_bytes',
        'uploaded_bytes', 'down_rate_bytes_sec', 'up_rate_bytes_sec', 'ratio',
        'is_open', 'is_active', 'is_complete_rt', 'left_bytes', 'rtorrent_message' # is_complete_rt from d.get_complete
    ]

    for torrent_data_list in raw_torrents_data:
        if not isinstance(torrent_data_list, list) or len(torrent_data_list) != len(fields):
            current_app.logger.warning(f"Skipping torrent entry due to mismatched data length. Expected {len(fields)}, got {len(torrent_data_list)}. Data: {torrent_data_list}")
            continue

        try:
            data = dict(zip(field_keys, torrent_data_list))

            # Type conversions and calculations
            size_b = int(data.get('size_bytes', 0))
            done_b = int(data.get('downloaded_bytes', 0))

            # Progress
            progress_percent = 0
            if size_b > 0:
                progress_percent = round((done_b / size_b) * 100, 2)
            elif int(data.get('is_complete_rt', 0)) == 1 : # if size is 0 but marked complete (e.g. empty torrent)
                progress_percent = 100.0

            # Status determination
            status_text = "Unknown"
            rt_message = data.get('rtorrent_message', '')
            is_open_val = int(data.get('is_open', 0))
            is_active_val = int(data.get('is_active', 0))
            # is_complete_val from d.get_complete() is already 0 or 1
            is_complete_val = int(data.get('is_complete_rt', 0))
            # Alternative completeness check using left_bytes (more reliable with some rTorrent versions)
            left_bytes_val = int(data.get('left_bytes', -1)) # Use -1 to distinguish from 0 if key missing
            if left_bytes_val == 0 and size_b > 0 : # if left_bytes is 0 and size > 0, it's complete
                is_complete_val = 1


            if rt_message and rt_message.strip():
                status_text = "Error"
            elif is_open_val == 0:
                status_text = "Stopped"
            elif is_active_val == 0: # and is_open_val == 1
                status_text = "Paused"
            elif is_complete_val == 1: # and is_open_val == 1 and is_active_val == 1
                status_text = "Seeding"
            else: # is_open_val == 1 and is_active_val == 1 and is_complete_val == 0
                status_text = "Downloading"

            torrent_info = {
                'hash': str(data.get('hash', '')),
                'name': str(data.get('name', '')),
                'size_bytes': size_b,
                'progress_percent': progress_percent,
                'downloaded_bytes': done_b,
                'uploaded_bytes': int(data.get('uploaded_bytes', 0)),
                'ratio': round(int(data.get('ratio', 0)) / 1000.0, 3),
                'up_rate_bytes_sec': int(data.get('up_rate_bytes_sec', 0)),
                'down_rate_bytes_sec': int(data.get('down_rate_bytes_sec', 0)),
                'label': str(data.get('label', '')),
                'download_dir': str(data.get('download_dir', '')),
                'status_text': status_text,
                'is_active': bool(is_active_val and is_open_val), # Active means it's running (not paused, not stopped)
                'is_complete': bool(is_complete_val),
                'is_paused': bool(is_open_val and not is_active_val), # Paused means open but not active
                'rtorrent_message': rt_message
            }
            simplified_torrents.append(torrent_info)
        except Exception as e:
            current_app.logger.error(f"Error parsing torrent data entry: {torrent_data_list}. Error: {e}", exc_info=True)
            continue

    current_app.logger.info(f"Successfully parsed {len(simplified_torrents)} torrent(s) via XML-RPC d.multicall2.")
    return simplified_torrents, None

# add_magnet is refactored to use XML-RPC
def add_magnet(magnet_link, label=None, download_dir=None):
    if not magnet_link:
        current_app.logger.error("Magnet link cannot be empty.")
        return False, "Magnet link cannot be empty."

    params_for_xmlrpc = ["", magnet_link] # First param is for view (always ""), second is URI

    if label and isinstance(label, str) and label.strip():
        params_for_xmlrpc.append(f"d.custom1.set={label.strip()}")
        current_app.logger.debug(f"XML-RPC: Setting label for magnet: {label.strip()}")

    if download_dir and isinstance(download_dir, str) and download_dir.strip():
        params_for_xmlrpc.append(f"d.directory.set={download_dir.strip()}")
        current_app.logger.debug(f"XML-RPC: Setting download directory for magnet: {download_dir.strip()}")

    method_name = "load.start" # Use load.start to load and start the torrent
    current_app.logger.info(f"Adding magnet via XML-RPC: Method='{method_name}', Magnet='{magnet_link[:100]}...', Params (excluding magnet link itself for brevity): {params_for_xmlrpc[2:] if len(params_for_xmlrpc) > 2 else 'None'}")

    result, error = _send_xmlrpc_request(method_name=method_name, params=params_for_xmlrpc)

    if error:
        current_app.logger.error(f"Error adding magnet via XML-RPC ('{method_name}'): {error}. Magnet: {magnet_link[:100]}")
        return False, f"XML-RPC Error: {error}"

    current_app.logger.debug(f"XML-RPC result for {method_name} (magnet): {result!r} (type: {type(result)})")

    # For load.start, rTorrent typically returns 0 on success.
    if result == 0:
        current_app.logger.info(f"Magnet link '{magnet_link[:100]}...' successfully added via XML-RPC method '{method_name}'. Result: {result}")
        return True, "Magnet link added successfully via XML-RPC."
    else:
        # This case might indicate an issue if rTorrent's load.start doesn't behave as expected (e.g. returns non-zero on success)
        # or if _send_xmlrpc_request has an issue in its result parsing for this specific method.
        current_app.logger.warning(f"Magnet add via XML-RPC ('{method_name}') returned an unexpected result: {result}. Magnet: {magnet_link[:100]}. Considered as failure.")
        return False, f"Magnet add via XML-RPC returned an unexpected result: {result}. Expected 0 for success."

def add_torrent_file(file_content_bytes, filename, label=None, download_dir=None):
    if not file_content_bytes: # filename is only for logging, not strictly required for the call itself
        current_app.logger.error("Torrent file content (bytes) cannot be empty.")
        return False, "File content cannot be empty."
    if not filename: # Still good to have for logging
        current_app.logger.warning("Torrent filename was not provided for add_torrent_file (used for logging).")
        filename = "Unknown.torrent" # Default filename for logging if not provided

    # The first parameter for load.raw_start is an empty string (target/view, not used for raw loads)
    # The second is the torrent data itself, wrapped in xmlrpc.client.Binary
    params_for_xmlrpc = ["", xmlrpc.client.Binary(file_content_bytes)]

    if label and isinstance(label, str) and label.strip():
        params_for_xmlrpc.append(f"d.custom1.set={label.strip()}")
        current_app.logger.debug(f"XML-RPC: Setting label for torrent file '{filename}': {label.strip()}")

    if download_dir and isinstance(download_dir, str) and download_dir.strip():
        params_for_xmlrpc.append(f"d.directory.set={download_dir.strip()}")
        current_app.logger.debug(f"XML-RPC: Setting download directory for torrent file '{filename}': {download_dir.strip()}")

    # Potentially add other commands like "d.start_now.set=1" if desired, similar to load.start
    # For now, sticking to the direct translation of load.raw_start with label and dir.
    # rTorrent's load.raw_start implies starting the torrent.

    method_name = "load.raw_start"
    current_app.logger.info(f"Adding torrent file '{filename}' via XML-RPC: Method='{method_name}', Params (excluding torrent data for brevity): {params_for_xmlrpc[2:] if len(params_for_xmlrpc) > 2 else 'None'}")

    result, error = _send_xmlrpc_request(method_name=method_name, params=params_for_xmlrpc)

    if error:
        current_app.logger.error(f"Error adding torrent file '{filename}' via XML-RPC ('{method_name}'): {error}")
        return False, f"XML-RPC Error: {error}"

    current_app.logger.debug(f"XML-RPC result for {method_name} (file '{filename}'): {result!r} (type: {type(result)})")

    # For load.raw_start, rTorrent also typically returns 0 on success.
    if result == 0:
        current_app.logger.info(f"Torrent file '{filename}' successfully added via XML-RPC method '{method_name}'. Result: {result}")
        return True, "Torrent file added successfully via XML-RPC."
    else:
        current_app.logger.warning(f"Torrent file add ('{filename}') via XML-RPC ('{method_name}') returned an unexpected result: {result}. Considered as failure.")
        return False, f"Torrent file add via XML-RPC ('{method_name}') for '{filename}' returned an unexpected result: {result}. Expected 0 for success."

# get_torrent_hash_by_name remains the same
def get_torrent_hash_by_name(torrent_name, max_retries=3, delay_seconds=2):
    # ... (implementation unchanged) ...
    if not torrent_name: return None
    current_app.logger.info(f"Attempting to find hash for torrent name: '{torrent_name}' (using corrected list_torrents)")
    for attempt in range(max_retries):
        torrents, error = list_torrents()
        if error:
            current_app.logger.warning(f"get_torrent_hash_by_name: Error listing torrents on attempt {attempt + 1}: {error}")
            if attempt < max_retries - 1:
                time.sleep(delay_seconds)
                continue
            else: return None
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

# Dans app/utils/rtorrent_client.py

def add_magnet_and_get_hash_robustly(magnet_link, label=None, destination_path=None):
    """
    Ajoute un magnet à rTorrent en spécifiant le chemin/label, et retourne son hash de manière fiable.
    Retourne le hash (str) en cas de succès, ou None en cas d'échec.
    """
    logger = current_app.logger
    logger.info(f"Début de add_magnet_and_get_hash_robustly pour: {magnet_link[:100]}...")
    try:
        torrents_before_raw, error_before = _send_xmlrpc_request("d.multicall2", ["", "main", "d.hash="])
        if error_before:
            logger.error(f"Erreur XML-RPC avant l'ajout (magnet): {error_before}")
            return None
        hashes_before = {item[0] for item in torrents_before_raw if item} if torrents_before_raw else set()

        params_for_load = ["", magnet_link]
        if destination_path:
            params_for_load.append(f"d.directory.set={destination_path}")
        if label:
            params_for_load.append(f"d.custom1.set={label}")
            
        _send_xmlrpc_request("load.start", params_for_load)
        time.sleep(2) # Laisser à rTorrent le temps de traiter le magnet

        max_retries, retry_delay = 20, 2
        for i in range(max_retries):
            time.sleep(retry_delay)
            torrents_after_raw, error_after = _send_xmlrpc_request("d.multicall2", ["", "main", "d.hash="])
            if error_after: continue
            
            hashes_after = {item[0] for item in torrents_after_raw if item} if torrents_after_raw else set()
            new_hashes = hashes_after - hashes_before
            if new_hashes:
                new_hash = new_hashes.pop()
                logger.info(f"Nouveau hash trouvé : {new_hash}")
                return new_hash

        logger.error(f"Impossible de trouver le nouveau hash après {max_retries} tentatives.")
        return None
    except Exception as e:
        logger.error(f"Erreur inattendue dans add_magnet_and_get_hash_robustly: {e}", exc_info=True)
        return None

def add_torrent_data_and_get_hash_robustly(torrent_content_bytes, filename_for_rtorrent, label=None, destination_path=None):
    """
    Ajoute un torrent (via data), en spécifiant le chemin/label, et retourne son hash de manière fiable.
    Retourne le hash (str) en cas de succès, ou None en cas d'échec.
    """
    logger = current_app.logger
    logger.info(f"Début de add_torrent_data_and_get_hash_robustly pour '{filename_for_rtorrent}'...")
    if not torrent_content_bytes: return None

    try:
        torrents_before_raw, error_before = _send_xmlrpc_request("d.multicall2", ["", "main", "d.hash="])
        if error_before: return None
        hashes_before = {item[0] for item in torrents_before_raw if item} if torrents_before_raw else set()

        params_for_load_raw = ["", xmlrpc.client.Binary(torrent_content_bytes)]
        if destination_path:
            params_for_load_raw.append(f"d.directory.set={destination_path}")
        if label:
            params_for_load_raw.append(f"d.custom1.set={label}")

        _send_xmlrpc_request("load.raw_start", params_for_load_raw)
        time.sleep(2)

        max_retries, retry_delay = 20, 2
        for i in range(max_retries):
            time.sleep(retry_delay)
            torrents_after_raw, error_after = _send_xmlrpc_request("d.multicall2", ["", "main", "d.hash="])
            if error_after: continue
            
            hashes_after = {item[0] for item in torrents_after_raw if item} if torrents_after_raw else set()
            new_hashes = hashes_after - hashes_before
            if new_hashes:
                new_hash = new_hashes.pop()
                logger.info(f"Nouveau hash trouvé : {new_hash}")
                return new_hash

        logger.error(f"Impossible de trouver le nouveau hash après {max_retries} tentatives.")
        return None
    except Exception as e:
        logger.error(f"Erreur inattendue dans add_torrent_data_and_get_hash_robustly: {e}", exc_info=True)
        return None
        
def _decode_bencode_name(bencoded_data):
    """
    Minimalistic bencode decoder to find info['name'].
    Returns the value of info['name'] as a string, or None if not found or error.
    Expects bencoded_data as bytes.
    """
    try:
        # Find '4:infod' (start of info dict)
        info_dict_match = re.search(b'4:infod', bencoded_data)
        if not info_dict_match:
            # Use current_app.logger if available and in context, otherwise module logger
            try: current_app.logger.debug("Bencode: '4:infod' not found.")
            except RuntimeError: logger.debug("Bencode: '4:infod' not found (no app context).")
            return None

        start_index = info_dict_match.end(0) # Position after '4:infod'

        name_key_match = re.search(b'4:name', bencoded_data[start_index:])
        if not name_key_match:
            try: current_app.logger.debug("Bencode: '4:name' not found after '4:infod'.")
            except RuntimeError: logger.debug("Bencode: '4:name' not found after '4:infod' (no app context).")
            return None

        pos_after_name_key = start_index + name_key_match.end(0)

        len_match = re.match(rb'(\d+):', bencoded_data[pos_after_name_key:])
        if not len_match:
            try: current_app.logger.debug("Bencode: Length prefix for name value not found.")
            except RuntimeError: logger.debug("Bencode: Length prefix for name value not found (no app context).")
            return None

        str_len = int(len_match.group(1))
        pos_after_len_colon = pos_after_name_key + len_match.end(0)

        if (pos_after_len_colon + str_len) > len(bencoded_data):
            try: current_app.logger.debug(f"Bencode: Declared name length {str_len} is out of bounds.")
            except RuntimeError: logger.debug(f"Bencode: Declared name length {str_len} is out of bounds (no app context).")
            return None

        name_bytes = bencoded_data[pos_after_len_colon : pos_after_len_colon + str_len]

        try:
            return name_bytes.decode('utf-8')
        except UnicodeDecodeError:
            try:
                return name_bytes.decode('latin-1')
            except UnicodeDecodeError:
                return name_bytes.decode('utf-8', errors='replace')

    except Exception as e:
        # Use current_app.logger if available and in context, otherwise module logger
        try: current_app.logger.warning(f"Exception in _decode_bencode_name: {e}", exc_info=True)
        except RuntimeError: logger.warning(f"Exception in _decode_bencode_name (no app context): {e}", exc_info=True)
        return None        