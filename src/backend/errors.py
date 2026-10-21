"""Errors as codes: the backend says what happened, the page says it in its own words
(src/app/services/errors.ts has the texts). No Python sentence reaches the page."""
import logging
import time

log = logging.getLogger('music-sorter')


class AppError(Exception):
    """An expected failure, with the code the page turns into a text, and that text's values."""

    def __init__(self, code, **params):
        super().__init__(code)
        self.code = code
        self.params = params


def describe(e):
    """(code, params) for any exception. An unexpected one is logged in full in the backend's terminal."""
    import requests
    from spotify_client import SpotifyLimitError

    if isinstance(e, AppError):
        return e.code, e.params
    if isinstance(e, SpotifyLimitError):
        return 'spotify_limit', {'until': time.strftime('%H:%M', time.localtime(time.time() + e.retry_after))}
    if isinstance(e, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        url = str(getattr(getattr(e, 'request', None), 'url', '') or '')
        if 'spotify.com' in url:
            return 'spotify_down', {}
        if 'youtube.com' in url:
            return 'youtube_down', {}
        if 'last.fm' in url or 'audioscrobbler' in url:
            return 'lastfm_down', {}
        return 'no_internet', {}
    log.exception('Unexpected error', exc_info=e)
    return 'unexpected', {}
