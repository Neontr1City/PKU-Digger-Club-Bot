"""Shared cover cache for webpages, enrichment and result posters."""

import hashlib
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image, ImageOps

MAX_BYTES = 5 * 1024 * 1024


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


def load_artwork(url, cache_dir):
    """Return a 600px cover, or None on missing/unsupported/unavailable artwork.

    None disables downloads (useful for offline rendering and tests). Redirects are
    deliberately rejected so a trusted CDN cannot redirect the server elsewhere.
    """
    if cache_dir is None or not allowed_url(url):
        return None
    path = cache_path(url, cache_dir)
    try:
        if path.is_file():
            try:
                return decode(path.read_bytes())
            except (OSError, ValueError):
                pass  # A broken cache entry can be replaced by the original cover.
        request = Request(url, headers={'User-Agent': 'PKU-Digger-Club-Bot/0.1'})
        with build_opener(NoRedirects).open(request, timeout=4) as response:
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return None
        image = decode(data)
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, suffix='.png', delete=False) as temp:
            temporary = Path(temp.name)
        try:
            image.save(temporary, format='PNG')
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return image
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
