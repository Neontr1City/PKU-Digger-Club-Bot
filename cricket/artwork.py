"""Shared cover cache for webpages, enrichment and result posters."""

import hashlib
import time
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import BoundedSemaphore, Lock
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image, ImageOps

MAX_BYTES = 5 * 1024 * 1024
FAILURE_COOLDOWN = 60
# Bound external work within the four-thread web process. Contenders show a placeholder.
_DOWNLOAD_SLOTS = BoundedSemaphore(2)
_COVER_LOCKS = [Lock() for _ in range(64)]


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def allowed_url(url):
    try:
        parts = urlsplit(url)
        host = parts.hostname or ''
        return (
            parts.scheme == 'https'
            and parts.port in (None, 443)
            and not parts.username
            and not parts.password
            and (host.endswith('.mzstatic.com') or host.endswith('.music.126.net'))
        )
    except ValueError:
        return False


def decode(data):
    with Image.open(BytesIO(data)) as image:
        if image.format not in ('JPEG', 'PNG', 'WEBP') or max(image.size) > 4096:
            raise ValueError('Unsupported cover image')
        return ImageOps.fit(image.convert('RGB'), (600, 600), Image.Resampling.LANCZOS)


def cache_path(url, cache_dir):
    return Path(cache_dir) / (hashlib.sha256(url.encode()).hexdigest() + '.png')


def _cached(path):
    try:
        return decode(path.read_bytes()) if path.is_file() else None
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def _cooling_down(failure):
    try:
        return 0 <= time.time() - failure.stat().st_mtime < FAILURE_COOLDOWN
    except OSError:
        return False


def load_artwork(url, cache_dir):
    """Use cached covers; bound concurrent downloads and back off failed URLs for 60s.

    Other requests get a placeholder while the first download is in progress. None
    disables downloads. Redirects cannot send requests beyond the trusted CDN list.
    """
    if cache_dir is None or not allowed_url(url):
        return None
    path = cache_path(url, cache_dir)
    image = _cached(path)
    if image is not None:
        return image
    failure = path.with_suffix('.failed')
    if _cooling_down(failure):
        return None
    lock = _COVER_LOCKS[int(path.stem[:8], 16) % len(_COVER_LOCKS)]
    if not lock.acquire(blocking=False):
        return None
    acquired = False
    try:
        image = _cached(path)
        if image is not None:
            return image
        if _cooling_down(failure):
            return None
        acquired = _DOWNLOAD_SLOTS.acquire(blocking=False)
        if not acquired:
            return None
        request = Request(url, headers={'User-Agent': 'PKU-Digger-Club-Bot/0.1'})
        with build_opener(NoRedirects).open(request, timeout=4) as response:
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('Cover image exceeds download limit')
        image = decode(data)
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, suffix='.png', delete=False) as temp:
            temporary = Path(temp.name)
        try:
            image.save(temporary, format='PNG')
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        failure.unlink(missing_ok=True)
        return image
    except (OSError, ValueError, Image.DecompressionBombError):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            failure.touch()
        except OSError:
            pass  # Disk trouble must not turn missing artwork into an HTTP 500.
        return None
    finally:
        if acquired:
            _DOWNLOAD_SLOTS.release()
        lock.release()


def web_cover_path(source):
    """A small browser derivative; keep the original PNG for result artwork."""
    source = Path(source)
    target = source.with_suffix('.webp')
    if target.is_file() and target.stat().st_mtime_ns >= source.stat().st_mtime_ns:
        return target
    lock = _COVER_LOCKS[int(source.stem[:8], 16) % len(_COVER_LOCKS)]
    if not lock.acquire(blocking=False):
        return source  # Another first request is encoding it; don't make visitors wait.
    try:
        if target.is_file() and target.stat().st_mtime_ns >= source.stat().st_mtime_ns:
            return target
        with Image.open(source) as image:
            image = image.convert('RGB').resize((480, 480), Image.Resampling.LANCZOS)
            with NamedTemporaryFile(dir=source.parent, suffix='.tmp', delete=False) as temp:
                temporary = Path(temp.name)
            try:
                image.save(temporary, format='WEBP', quality=82, method=3)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return target
    except (OSError, ValueError):
        return source
    finally:
        lock.release()
