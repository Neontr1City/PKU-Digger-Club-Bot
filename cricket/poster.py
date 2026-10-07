"""Compact shareable results, laid out from measured text and official cover art."""

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .artwork import allowed_url, cache_path, load_artwork

PAPER = '#f5f5f7'
INK = '#1d1d1f'
MUTED = '#777780'
RED = '#de2848'
PURPLE = '#71639f'
WIDTH = 1080
EXPORT_WIDTH = 864


def font_path(custom=''):
    candidates = [
        custom,
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/STHeiti Medium.ttc',
    ]
    for path in candidates:
        if path and Path(path).is_file():
            return path
    raise RuntimeError('结果图需要中文字体。请安装 fonts-noto-cjk 或设置 RESULT_FONT。')


class Typography:
    def __init__(self, path):
        self.path = path
        self.fonts = {}

    def font(self, size):
        if size not in self.fonts:
            self.fonts[size] = ImageFont.truetype(self.path, size)
        return self.fonts[size]

    def lines(self, text, size, width):
        # Prefer whitespace for Latin titles, while retaining every CJK character.
        lines, current = [], ''
        for char in str(text):
            if char == '\n':
                lines.append(current)
                current = ''
            elif current and self.font(size).getlength(current + char) > width:
                split = current.rfind(' ')
                if split > len(current) // 2:
                    lines.append(current[:split])
                    current = current[split + 1 :] + char
                else:
                    lines.append(current)
                    current = char
            else:
                current += char
        return lines + [current]

    def height(self, text, size, width):
        return len(self.lines(text, size, width)) * (size + 10)

    def text(self, draw, xy, text, size, color=INK, width=None, bold=False):
        x, y = xy
        for line in self.lines(text, size, width) if width else [str(text)]:
            draw.text(
                (x, y),
                line,
                font=self.font(size),
                fill=color,
                anchor='lt',
                stroke_width=1 if bold else 0,
            )
            y += size + 10
        return y


def paste_cover(canvas, cover, x, y, size):
    if cover is None:
        placeholder = Image.new('RGB', (size, size), '#e9e7ed')
        draw = ImageDraw.Draw(placeholder)
        for radius in range(int(size * 0.39), int(size * 0.10), -3):
            shade = '#33333b' if radius % 2 else '#40404a'
            draw.ellipse(
                (size / 2 - radius, size / 2 - radius, size / 2 + radius, size / 2 + radius),
                fill=shade,
            )
        draw.ellipse((size * 0.39, size * 0.39, size * 0.61, size * 0.61), fill='#fa3656')
        draw.ellipse((size * 0.487, size * 0.487, size * 0.513, size * 0.513), fill=PAPER)
        cover = placeholder
    cover = ImageOps.fit(cover, (size, size), Image.Resampling.LANCZOS)
    mask = Image.new('L', (size, size))
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=12, fill=255)
    canvas.paste(cover, (x, y), mask)


def match_panel(match, typography, covers):
    t = typography
    total = match['votes_a'] + match['votes_b']
    outcome = match['outcome']
    winner = outcome in ('a', 'b')
    color = RED if winner else PURPLE if outcome == 'tie' else MUTED
    nomination = f'提名 / {match["nominator"]}'
    heading_height = max(30, t.height(nomination, 22, 670))
    top = 38 + heading_height + 28
    # Both columns share baselines, even when one title wraps onto several lines.
    artist_height = max(t.height(match[s]['artist'], 28, 382) for s in ('a', 'b'))
    title_height = max(t.height(match[s]['title'], 42, 382) for s in ('a', 'b'))
    album_height = max(
        t.height(match[s].get('album') or '发行信息待补', 22, 382) for s in ('a', 'b')
    )
    metadata_y = top + 74 + 382 + 28
    votes_y = metadata_y + artist_height + 10 + title_height + 14 + album_height + 30
    height = votes_y + 158 + 44
    canvas = Image.new('RGB', (984, height), PAPER)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((0, 0, 983, height - 1), radius=24, fill='white')
    t.text(draw, (34, 38), f'ROUND {match["position"]:02d}', 24, color, bold=True)
    t.text(draw, (280, 38), nomination, 22, MUTED, 670)
    for index, side in enumerate(('a', 'b')):
        x = 20 + index * 480
        selected = side == outcome
        draw.rounded_rectangle(
            (x, top, x + 464, height - 24),
            radius=18,
            fill='#fff0f3' if selected else '#f7f7f9',
        )
        left = x + 40
        t.text(draw, (left, top + 26), f'{side.upper()} SIDE', 21, MUTED)
        label = 'WINNER / 胜出' if selected else 'DRAW / 平局' if outcome == 'tie' else ''
        if label:
            badge_width = int(t.font(21).getlength(label)) + 28
            bx = x + 424 - badge_width
            draw.rounded_rectangle(
                (bx, top + 17, x + 424, top + 53), radius=6, fill=RED if selected else PURPLE
            )
            t.text(draw, (bx + 14, top + 24), label, 21, 'white')
        cover = covers.get(match[side].get('artwork', ''))
        paste_cover(canvas, cover, left, top + 74, 382)
        if cover is None:
            # Explicit placeholder rather than invented release artwork.
            draw.rectangle((left + 110, top + 409, left + 272, top + 440), fill='#e9e7ed')
            t.text(draw, (left + 128, top + 414), '封面暂缺', 22, MUTED)
        track = match[side]
        t.text(draw, (left, metadata_y), track['artist'], 28, RED if selected else MUTED, 382)
        title_y = metadata_y + artist_height + 10
        t.text(draw, (left, title_y), track['title'], 42, INK, 382, bold=True)
        t.text(
            draw,
            (left, title_y + title_height + 14),
            track.get('album') or '发行信息待补',
            22,
            MUTED,
            382,
        )
        count = match['votes_' + side]
        count_size = 94
        while t.font(count_size).getlength(str(count)) > 290:
            count_size -= 2
        t.text(draw, (left, votes_y), count, count_size, RED if selected else INK, bold=True)
        count_width = t.font(count_size).getlength(str(count))
        t.text(draw, (left + count_width + 12, votes_y + count_size - 26), '票', 24, MUTED)
        share = count / total if total else 0
        draw.rounded_rectangle(
            (left, votes_y + 112, left + 382, votes_y + 119), radius=3, fill='#e5e5eb'
        )
        if share:
            draw.rounded_rectangle(
                (left, votes_y + 112, left + max(6, round(382 * share)), votes_y + 119),
                radius=3,
                fill=RED if selected else PURPLE if outcome == 'tie' else '#93939e',
            )
        t.text(draw, (left, votes_y + 136), f'{share:.1%}', 22, MUTED)
    detail = (
        f'{outcome.upper()} 面胜出 · 领先 {abs(match["votes_a"] - match["votes_b"])} 票'
        if winner
        else '平局 · 不分高下'
        if outcome == 'tie'
        else '本组暂无有效投票'
    )
    # The group summary lives between panels, keeping the artwork area uncluttered.
    footer = Image.new('RGB', (984, 64), PAPER)
    fdraw = ImageDraw.Draw(footer)
    t.text(fdraw, (12, 20), detail, 23, color)
    total_text = f'共 {total} 票'
    t.text(fdraw, (972 - t.font(23).getlength(total_text), 20), total_text, 23, MUTED)
    result = Image.new('RGB', (984, height + 64), PAPER)
    result.paste(canvas, (0, 0))
    result.paste(footer, (0, height))
    return result


def render(round_, page=1, custom_font='', artwork_dir=None):
    matches = round_['matches'][(page - 1) * 4 : page * 4]
    if page < 1 or not matches:
        raise ValueError('结果图片页码不存在。')
    t = Typography(font_path(custom_font))
    urls = sorted({m[s].get('artwork', '') for m in matches for s in ('a', 'b')})
    with ThreadPoolExecutor(max_workers=4) as pool:
        covers = dict(zip(urls, pool.map(lambda url: load_artwork(url, artwork_dir), urls)))
    panels = [match_panel(m, t, covers) for m in matches]
    height = 350 + sum(panel.height + 24 for panel in panels) + 76
    canvas = Image.new('RGB', (WIDTH, height), PAPER)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, WIDTH, 299), fill=INK)
    draw.rounded_rectangle((48, 42, 104, 98), radius=3, fill='#fa3656')
    t.text(draw, (55, 48), '滚', 42, 'white', bold=True)
    t.text(draw, (123, 45), 'PKU DIGGER CLUB', 25, 'white', bold=True)
    t.text(draw, (124, 79), '今天你滚了吗', 16, '#b9b9c1')
    t.text(draw, (48, 133), '每日斗蛐蛐', 80, 'white', bold=True)
    t.text(draw, (52, 241), 'THE RESULTS', 22, '#fa6b84', bold=True)
    date = round_['day'].replace('-', '.')
    t.text(draw, (1032 - t.font(26).getlength(date), 239), date, 26, '#d1d1d8')
    draw.rectangle((48, 296, 172, 302), fill='#fa3656')
    y = 334
    for panel in panels:
        canvas.paste(panel, (48, y))
        y += panel.height + 24
    draw.line((48, y + 4, 1032, y + 4), fill='#d8d8df', width=1)
    t.text(draw, (48, y + 26), '每日斗蛐蛐 / 最终赛果', 20, MUTED)
    pages = (len(round_['matches']) + 3) // 4
    if pages > 1:
        folio = f'{page:02d} / {pages:02d}'
        t.text(draw, (1032 - t.font(20).getlength(folio), y + 26), folio, 20, MUTED)
    output = BytesIO()
    canvas = canvas.resize(
        (EXPORT_WIDTH, round(canvas.height * EXPORT_WIDTH / WIDTH)), Image.Resampling.LANCZOS
    ).quantize(colors=256, method=Image.Quantize.FASTOCTREE)
    canvas.save(output, format='PNG', optimize=True)
    output.seek(0)
    return output


# One renderer per process keeps concurrent cold requests from multiplying PNG memory.
_RENDER_LOCK = Lock()
_RENDER_VERSION = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def cached_path(round_, page, custom_font, output_dir):
    """Persist frozen results shared by the website and WeChat delivery worker."""
    matches = round_['matches'][(page - 1) * 4 : page * 4]
    if not round_.get('snapshot') or page < 1 or not matches:
        raise ValueError('结果图片需要已冻结的有效轮次。')
    output_dir = Path(output_dir)
    artwork_dir = output_dir / 'artwork'
    urls = sorted({m[side].get('artwork', '') for m in matches for side in ('a', 'b')})

    def target():
        covers = []
        missing = False
        for url in urls:
            path = cache_path(url, artwork_dir)
            try:
                stat = path.stat()
                covers.append((url, stat.st_mtime_ns, stat.st_size))
            except FileNotFoundError:
                covers.append((url, None, None))
                missing |= allowed_url(url)
        identity = [
            _RENDER_VERSION,
            round_['day'],
            round_['snapshot'],
            page,
            custom_font,
            covers,
        ]
        digest = hashlib.sha256(
            json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        return output_dir / 'results' / (digest + '.png'), missing

    def usable(path, missing):
        try:
            return not missing or time.time() - path.stat().st_mtime < 60
        except FileNotFoundError:
            return False

    path, missing = target()
    if path.is_file() and usable(path, missing):
        return path
    with _RENDER_LOCK:
        path, missing = target()
        if path.is_file() and usable(path, missing):
            return path
        rendered = render(round_, page, custom_font, artwork_dir)
        # Rendering may populate previously absent album covers.
        path, _ = target()
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, suffix='.tmp', delete=False) as temp:
            temporary = Path(temp.name)
            temp.write(rendered.getvalue())
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return path
