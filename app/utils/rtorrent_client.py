# app/utils/rtorrent_client.py
import xmlrpc.client
from flask import current_app, jsonify
import base64 # For handling .torrent file content

# KEEP THE EXISTING get_rtorrent_client() FUNCTION HERE
def get_rtorrent_client():
    """
    Initializes and returns an XML-RPC client for rTorrent.
    Retrieves RTORRENT_RPC_URL from Flask app config.
    """
    rtorrent_rpc_url = current_app.config.get('RTORRENT_RPC_URL')

    if not rtorrent_rpc_url:
        current_app.logger.error("RTORRENT_RPC_URL is not configured.")
        return None

    try:
        client = xmlrpc.client.ServerProxy(rtorrent_rpc_url)
        return client
    except Exception as e:
        current_app.logger.error(f"Failed to create rTorrent XML-RPC client: {e}")
        return None

# --- NEW FUNCTIONS ---

def add_torrent_url(magnet_link, download_path=None, label=None):
    """
    Adds a torrent to rTorrent using a magnet link.
    Optionally sets the download path and a label.
    Returns the torrent hash if successful, and an error message if not.
    Example usage: hash, err = add_torrent_url(...)
    """
    client = get_rtorrent_client()
    if not client:
        return None, "rTorrent client not available (not configured or connection failed)."

    try:
        current_app.logger.info(f"Attempting to add magnet link: {magnet_link[:100]}... with path='{download_path}' and label='{label}'")

        # Add the torrent first
        torrent_hash = client.load.raw_start_verbose("", magnet_link) # Use verbose to allow immediate info like hash

        if not torrent_hash: # Check if hash is valid (non-empty string)
            current_app.logger.error("Failed to add magnet link (load.raw_start_verbose returned empty or no hash).")
            return None, "Failed to add magnet link (rTorrent did not return a hash)."

        current_app.logger.info(f"Magnet link added, received hash: {torrent_hash}")

        # Set properties if provided
        if download_path:
            client.d.directory.set(torrent_hash, download_path)
            current_app.logger.info(f"Set directory for {torrent_hash} to {download_path}")
        if label:
            client.d.custom1.set(torrent_hash, label) # custom1 is commonly used for labels
            current_app.logger.info(f"Set label for {torrent_hash} to {label}")

        # Optionally, start the torrent if it wasn't started automatically (depends on rTorrent config)
        # client.d.start(torrent_hash)

        return torrent_hash, None
    except xmlrpc.client.Fault as err:
        current_app.logger.error(f"rTorrent XML-RPC Fault (add_torrent_url for {magnet_link[:50]}...): {err.faultCode} {err.faultString}")
        return None, f"rTorrent Error: {err.faultString}"
    except Exception as e:
        current_app.logger.error(f"Error adding torrent URL to rTorrent ({magnet_link[:50]}...): {e}", exc_info=True)
        return None, f"General error adding torrent URL: {str(e)}"

def add_torrent_file(file_content_base64, download_path=None, label=None):
    """
    Adds a torrent to rTorrent using the base64 encoded content of a .torrent file.
    Optionally sets the download path and a label.
    Returns the torrent hash if successful, and an error message if not.
    """
    client = get_rtorrent_client()
    if not client:
        return None, "rTorrent client not available."

    try:
        current_app.logger.info(f"Attempting to add torrent file (base64 content) with path='{download_path}' and label='{label}'")
        torrent_content_bytes = base64.b64decode(file_content_base64)

        # Add the torrent file content. load_raw takes raw file bytes.
        # Some clients/rTorrent versions might expect load.normal or load_verbose
        torrent_hash = client.load.raw_start_verbose("", xmlrpc.client.Binary(torrent_content_bytes))

        if not torrent_hash:
            current_app.logger.error("Failed to add torrent file (load.raw_start_verbose returned empty or no hash).")
            return None, "Failed to add torrent file (rTorrent did not return a hash)."

        current_app.logger.info(f"Torrent file added, received hash: {torrent_hash}")

        if download_path:
            client.d.directory.set(torrent_hash, download_path)
            current_app.logger.info(f"Set directory for {torrent_hash} to {download_path}")
        if label:
            client.d.custom1.set(torrent_hash, label)
            current_app.logger.info(f"Set label for {torrent_hash} to {label}")

        # client.d.start(torrent_hash)

        return torrent_hash, None
    except xmlrpc.client.Fault as err:
        current_app.logger.error(f"rTorrent XML-RPC Fault (add_torrent_file): {err.faultCode} {err.faultString}")
        return None, f"rTorrent Error: {err.faultString}"
    except Exception as e:
        current_app.logger.error(f"Error adding torrent file to rTorrent: {e}", exc_info=True)
        return None, f"General error adding torrent file: {str(e)}"

def list_torrents(view="main"):
    """
    Lists torrents from rTorrent.
    'view' can be 'main', 'seeding', 'leeching', etc.
    Returns a list of torrent details (dicts) and an error message if any.
    """
    client = get_rtorrent_client()
    if not client:
        return None, "rTorrent client not available."

    fields = [
        "d.hash=", "d.name=", "d.size_bytes=", "d.completed_bytes=", "d.ratio=",
        "d.up.rate=", "d.down.rate=", "d.message=", "d.is_active=", "d.is_open=",
        "d.is_complete=", "d.custom1=", "d.directory=", "d.creation_date=", "d.state=",
        "d.peers_connected=", "d.state_changed=", "d.priority_str="
    ]

    try:
        current_app.logger.debug(f"Listing torrents for view: {view}")
        # The first argument to d.multicall2 is the target, which is empty for system-wide/view-based calls.
        results = client.d.multicall2("", view, *fields)

        torrents_list = []
        for res_item in results:
            torrent_details = {}
            for i, field_name_cmd in enumerate(fields):
                key_name = field_name_cmd.replace("d.", "").replace("=", "").replace(".rate", "_rate").replace(".str","_str") # Adjust key names
                torrent_details[key_name] = res_item[i]

            if 'ratio' in torrent_details and isinstance(torrent_details['ratio'], int):
                torrent_details['ratio'] = torrent_details['ratio'] / 1000.0
            torrents_list.append(torrent_details)

        current_app.logger.info(f"Successfully listed {len(torrents_list)} torrents for view '{view}'.")
        return torrents_list, None
    except xmlrpc.client.Fault as err:
        current_app.logger.error(f"rTorrent XML-RPC Fault (list_torrents for view {view}): {err.faultCode} {err.faultString}")
        return None, f"rTorrent Error: {err.faultString}"
    except Exception as e:
        current_app.logger.error(f"Error listing torrents from rTorrent (view {view}): {e}", exc_info=True)
        return None, f"General error listing torrents: {str(e)}"

def get_torrent_details(torrent_hash):
    """
    Retrieves details for a specific torrent by its hash.
    Returns a dict of details and an error message if any.
    """
    client = get_rtorrent_client()
    if not client:
        return None, "rTorrent client not available."

    # Define which details to fetch. d.multicall is efficient for this.
    # These are commands that will be executed against the specific torrent_hash.
    commands = [
        "d.name=", "d.size_bytes=", "d.completed_bytes=", "d.ratio=", "d.up.rate=", "d.down.rate=",
        "d.message=", "d.is_active=", "d.is_open=", "d.is_complete=", "d.custom1=", "d.directory=",
        "d.creation_date=", "d.state=", "d.peers_connected=", "d.state_changed=", "d.priority_str="
        # To get individual file details (more complex):
        # "f.multicall", <hash>, "", "f.path=", "f.size_bytes=", "f.completed_chunks="
    ]

    try:
        current_app.logger.debug(f"Getting details for torrent hash: {torrent_hash}")
        # d.multicall takes the torrent hash as the first argument, then the list of commands.
        raw_results = client.d.multicall(torrent_hash, *commands)

        if not raw_results or len(raw_results) != len(commands):
             current_app.logger.warning(f"No details returned or unexpected result length for torrent {torrent_hash}.")
             # Check if torrent exists with a simple call
             try:
                 name_check = client.d.name(torrent_hash)
                 if name_check is not None: # Torrent exists but multicall failed for some reason
                    return None, f"Torrent {torrent_hash} exists, but failed to retrieve full details with multicall."
             except xmlrpc.client.Fault: # Torrent likely doesn't exist
                return None, f"Torrent with hash {torrent_hash} not found."
             return None, f"No details returned for torrent {torrent_hash} or result mismatch."


        details = {'hash': torrent_hash} # Start with the hash we know
        for i, command in enumerate(commands):
            key_name = command.replace("d.", "").replace("=", "").replace(".rate", "_rate").replace(".str","_str")
            details[key_name] = raw_results[i]

        if 'ratio' in details and isinstance(details['ratio'], int):
            details['ratio'] = details['ratio'] / 1000.0

        current_app.logger.info(f"Successfully retrieved details for torrent {torrent_hash}.")
        return details, None
    except xmlrpc.client.Fault as err:
        # Check if it's a "torrent not found" type of error
        if "not found" in err.faultString.lower() or "unregistered" in err.faultString.lower():
             current_app.logger.warning(f"Torrent with hash {torrent_hash} not found in rTorrent.")
             return None, f"Torrent with hash {torrent_hash} not found."
        current_app.logger.error(f"rTorrent XML-RPC Fault (get_torrent_details for {torrent_hash}): {err.faultCode} {err.faultString}")
        return None, f"rTorrent Error: {err.faultString}"
    except Exception as e:
        current_app.logger.error(f"Error getting torrent details from rTorrent for {torrent_hash}: {e}", exc_info=True)
        return None, f"General error getting details for {torrent_hash}: {str(e)}"
