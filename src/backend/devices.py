"""What the Library page needs to help put the songs on an iPhone (macOS).

Apple gives no command to turn on Sync Library or to sync an iPhone, and clicking for the user
needs the Accessibility permission: the app opens Apple Music or the Finder, and the page says
what to do there.
"""
import json
import plistlib
import platform
import subprocess
from pathlib import Path

SUBSCRIPTION_CACHE = Path.home() / 'Library' / 'Preferences' / 'com.apple.itunescloud.plist'


def _find(value, key):
    """The first dict under `key`, anywhere in the plist."""
    if isinstance(value, dict):
        if isinstance(value.get(key), dict):
            return value[key]
        for item in value.values():
            found = _find(item, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find(item, key)
            if found is not None:
                return found
    return None


def subscription():
    """True with an Apple Music or iTunes Match subscription, False without, None when unknown.
    Read from the status macOS keeps for the Music app (not documented by Apple)."""
    try:
        with open(SUBSCRIPTION_CACHE, 'rb') as f:
            data = plistlib.load(f)
    except (OSError, plistlib.InvalidFileException):
        return None
    statuses = [(_find(data, name) or {}).get('status') for name in ('music', 'match')]
    if not any(statuses):
        return None
    return any(status and status != 'Disabled' for status in statuses)


def iphone_connected():
    """An iPhone plugged in by cable."""
    try:
        out = subprocess.run(['system_profiler', 'SPUSBDataType', 'SPUSBHostDataType', '-json'],
                             capture_output=True, text=True, timeout=10).stdout
        return 'iPhone' in json.dumps(json.loads(out or '{}'))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def status():
    if platform.system() != 'Darwin':
        return {'available': False}
    return {'available': True, 'subscription': subscription(), 'iphone': iphone_connected()}


def open_music():
    """Opens Apple Music (its Settings can't be opened without the Accessibility permission)."""
    subprocess.run(['open', '-a', 'Music'], timeout=10)


def open_finder():
    """Opens a Finder window: the iPhone is in its sidebar (selecting it needs the Accessibility permission)."""
    subprocess.run(['open', '-a', 'Finder', str(Path.home())], timeout=10)
