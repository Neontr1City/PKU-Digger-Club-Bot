from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


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


def render(round_, page=1, custom_font=''):
    matches = round_['matches'][(page - 1) * 4 : page * 4]
    if page < 1 or not matches:
        raise ValueError('结果图片页码不存在。')
    path = font_path(custom_font)
    fonts = {size: ImageFont.truetype(path, size) for size in (22, 26, 32, 44, 64)}
    # Upper bound from accepted text lengths, including four long CJK titles.
    canvas = Image.new('RGB', (1080, 12000), '#f5f3e9')
    draw = ImageDraw.Draw(canvas)
    ink, muted, accent = '#20221e', '#65675d', '#d5f16b'

    def wrapped(value, x, y, size=32, width=850, color=ink):
        current = ''
        for char in value:
            if char == '\n' or (
                current and draw.textlength(current + char, font=fonts[size]) > width
            ):
                draw.text((x, y), current, font=fonts[size], fill=color)
                y += size + 12
                current = '' if char == '\n' else char
            else:
                current += char
        draw.text((x, y), current, font=fonts[size], fill=color)
        return y + size + 12

    draw.rectangle((0, 0, 1080, 18), fill=accent)
    draw.text((64, 65), '今天你滚了吗 / PKU Digger Club', font=fonts[26], fill=muted)
    draw.text((64, 122), '每日斗蛐蛐 · 赛果', font=fonts[64], fill=ink)
    draw.text(
        (64, 220),
        round_['day'] + f'     {page}/{(len(round_["matches"]) + 3) // 4}',
        font=fonts[26],
        fill=muted,
    )
    y = 295
    for m in matches:
        draw.line((64, y, 1016, y), fill=ink, width=2)
        y += 26
        y = wrapped(f'第 {m["position"]:02d} 组 / 提名：{m["nominator"]}', 64, y, 22, color=muted)
        total = m['votes_a'] + m['votes_b']
        for side in ('a', 'b'):
            t = m[side]
            y = wrapped(f'{t["artist"]} - {t["title"]}', 64, y + 14, 32, 770)
            draw.text((870, y - 44), f'{m["votes_" + side]} 票', font=fonts[32], fill=ink)
            draw.rectangle((64, y + 6, 1016, y + 20), fill='#e2e1d7')
            fraction = m['votes_' + side] / total if total else 0
            if fraction:
                draw.rectangle(
                    (64, y + 6, 64 + int(952 * fraction), y + 20),
                    fill=accent if m['outcome'] in (side, 'tie') else '#92978a',
                )
            y += 42
        label = (
            '本组暂无有效投票'
            if m['outcome'] == 'zero'
            else '平局，双方都很能打'
            if m['outcome'] == 'tie'
            else '胜出：' + m[m['outcome']]['title']
        )
        y = wrapped(label, 64, y + 8, 26) + 30
    output = BytesIO()
    canvas.crop((0, 0, 1080, y + 40)).save(output, format='PNG')
    output.seek(0)
    return output
