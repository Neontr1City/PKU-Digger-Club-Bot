"""Single-account official Linux WeChat UI sender. No protocol hooks or public API.

The app drops immutable requests in a private, shared outbox. This process owns
all desktop writes and journals the send boundary before clicking Send. An
interrupted/ambiguous send is never automatically repeated.
"""

import argparse
import base64
import csv
import fcntl
import hashlib
import io
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageStat


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as file:
        file.write(json.dumps(value, ensure_ascii=False))
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def compact(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text)).casefold()


def target_matches(text, group):
    # Only ignore OCR-inserted spaces and the client's member count suffix.
    title = re.sub(r'[（(]\d+[）)]$', '', compact(text))
    return title == compact(group)


def run(*args, data=None, timeout=15):
    return subprocess.run(
        args,
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        check=True,
    ).stdout


class GuardError(Exception):
    pass


class Desktop:
    def __init__(self, group, login_state_path=None, title_reference=None, restore_pinned=False):
        self.group = group
        self.title_reference = title_reference
        self.restore_pinned = restore_pinned
        self.geometry = None
        self.window = None
        self._verified_title = None
        self._verified_at = 0
        self.login_state_path = login_state_path
        try:
            self.login_state = json.loads(login_state_path.read_text()) if login_state_path else {}
        except (OSError, ValueError):
            self.login_state = {}

    def save_login_state(self):
        if self.login_state_path:
            atomic(self.login_state_path, self.login_state)

    def health_result(self, reason):
        pending = reason == 'phone_confirmation_pending'
        if (pending and not self.login_state.get('pending')) or (
            not reason and self.login_state.get('pending')
        ):
            self.login_state['pending'] = pending
            if pending:
                self.login_state['prompt_id'] = str(time.time_ns())
            self.save_login_state()
        result = {
            'state': 'blocked' if reason else 'ready',
            'reason': reason,
            'checked_at': time.time(),
        }
        if pending:
            result['login_request_id'] = self.login_state['prompt_id']
        return result

    def locate(self):
        ids = run('xdotool', 'search', '--onlyvisible', '--class', '^wechat$').decode().split()
        windows = []
        for window in ids:
            geometry = dict(
                line.split('=', 1)
                for line in run('xdotool', 'getwindowgeometry', '--shell', window)
                .decode()
                .splitlines()
            )
            if int(geometry['WIDTH']) > 200 and int(geometry['HEIGHT']) > 200:
                windows.append((window, geometry))
        large = [
            (window, g) for window, g in windows if int(g['WIDTH']) > 600 and int(g['HEIGHT']) > 400
        ]
        if len(large) == 1:
            windows = large
        if len(windows) != 1:
            raise GuardError('client_unavailable')
        self.window, self.geometry = windows[0]
        return {k: int(v) for k, v in self.geometry.items()}

    def screen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'screen.png'
            run('scrot', '-o', str(path))
            with Image.open(path) as source:
                image = source.convert('RGB')
        g = self.locate()
        return image.crop((g['X'], g['Y'], g['X'] + g['WIDTH'], g['Y'] + g['HEIGHT']))

    @staticmethod
    def ocr(image, psm=7):
        output = io.BytesIO()
        image.resize((image.width * 2, image.height * 2)).save(output, format='PNG')
        return (
            run(
                'tesseract',
                'stdin',
                'stdout',
                '-l',
                'eng+chi_sim',
                '--psm',
                str(psm),
                data=output.getvalue(),
                timeout=20,
            )
            .decode()
            .strip()
        )

    def check(self, *, reuse_title=False):
        try:
            frame = self.screen()
            # Fixed client layout, bounded by window-relative dimensions.
            w, h = frame.size
            if w > 600 and h > 400:
                title_image = frame.crop((325, 25, w - 175, 82))
                signature = (
                    self.window,
                    tuple(sorted(self.geometry.items())),
                    hashlib.sha256(title_image.tobytes()).digest(),
                )
                if (
                    reuse_title
                    and signature == self._verified_title
                    and time.monotonic() - self._verified_at < 300
                ):
                    return self.health_result('')
                title = self.ocr(title_image)
                if target_matches(title, self.group) or self.reference_matches(frame):
                    self._verified_title = signature
                    self._verified_at = time.monotonic()
                    return self.health_result('')
            self._verified_title = None
            text = compact(self.ocr(frame, 11))
            if ('confirm' in text and 'phone' in text) or ('手机' in text and '确认' in text):
                reason = 'phone_confirmation_pending'
            elif 'scanqrcode' in text or '扫码' in text:
                reason = 'qr_login_required'
            elif any(
                word in text
                for word in (
                    'login',
                    'scanqrcode',
                    'confirmonphone',
                    'signedout',
                    '登录',
                    '扫码',
                    '已退出',
                )
            ):
                reason = 'logged_out'
            else:
                reason = 'logged_out' if self.login_button(frame) else 'target_not_verified'
        except subprocess.TimeoutExpired:
            self._verified_title = None
            reason = 'check_timeout'
        except Exception:
            self._verified_title = None
            reason = 'client_unavailable'
        return self.health_result(reason)

    def reference_matches(self, frame):
        # A reference is calibrated from a visually verified group header, never
        # learned automatically from failed OCR. Member-count pixels are outside
        # the calibrated name region and never participate in identification.
        reference = self.title_reference
        if not reference or compact(reference.get('group', '')) != compact(self.group):
            return False
        bounds = reference.get('bounds', [])
        if len(bounds) != 4 or not all(isinstance(value, int) for value in bounds):
            return False
        left, top, right, bottom = bounds
        if left != 325 or top != 25 or bottom != 82 or not left < right < frame.width - 175:
            return False
        digest = hashlib.sha256(frame.crop(bounds).convert('RGB').tobytes()).hexdigest()
        return digest == reference.get('sha256')

    def login_button(self, frame):
        """Read only a single green action button in a small startup window."""
        w, h = frame.size
        if not (200 < w <= 600 and 200 < h <= 700):
            return None
        pixels = frame.convert('RGB').load()
        rows = {}
        for y in range(round(h * 0.45), round(h * 0.9)):
            xs = [
                x
                for x in range(round(w * 0.15), round(w * 0.85))
                for r, g, b in (pixels[x, y],)
                if g > r * 1.3 and g > b * 1.15 and g > 80
            ]
            if len(xs) >= w * 0.25:
                rows[y] = (min(xs), max(xs))
        bands = []
        for y in rows:
            if not bands or y > bands[-1][-1] + 1:
                bands.append([])
            bands[-1].append(y)
        buttons = []
        for band in bands:
            if not 20 <= len(band) <= 80:
                continue
            left, right = min(rows[y][0] for y in band), max(rows[y][1] for y in band)
            top, bottom = band[0], band[-1]
            buttons.append((left, top, right + 1, bottom + 1))
        if len(buttons) != 1:
            return None
        left, top, right, bottom = buttons[0]
        # Sparse whole-window OCR misses white text on the green button.
        # Isolate it and convert to black lettering on a white background.
        label = frame.crop((left + 5, top + 5, right - 5, bottom - 5)).convert('L')
        label = label.point(lambda value: 0 if value >= 210 else 255)
        if compact(self.ocr(label, 7)) not in ('login', '登录'):
            return None
        return round((left + right) / 2), round((top + bottom) / 2)

    def request_phone_login(self):
        # An expired phone prompt is still the same outage. Do not keep renewing
        # it and sending new action emails while the administrator is away.
        if self.login_state.get('pending'):
            return self.health_result('logged_out')
        last_probe = max(
            self.login_state.get('requested_at', 0), self.login_state.get('last_probe_at', 0)
        )
        if time.time() - last_probe < 600:
            return self.health_result('logged_out')
        self.login_state['last_probe_at'] = time.time()
        self.save_login_state()
        frame = self.screen()
        if frame.width > 600 or frame.height > 700:
            return self.check()
        button = self.login_button(frame)
        if button:
            self.login_state['requested_at'] = time.time()
            self.login_state['pending'] = False
            self.save_login_state()  # Record before clicking; never repeatedly click on errors.
            self.click(*button)
            time.sleep(1)
        return self.check()

    def restore_group_after_login(self):
        if not self.login_state.get('pending') or self.login_state.get(
            'restored_prompt_id'
        ) == self.login_state.get('prompt_id'):
            return self.health_result('target_not_verified')
        frame = self.screen()
        if frame.width <= 600 or frame.height <= 400:
            return self.check()
        data = io.BytesIO()
        sidebar = frame.crop((60, 70, 320, frame.height - 30))
        sidebar.resize((sidebar.width * 2, sidebar.height * 2)).save(data, format='PNG')
        tsv = run(
            'tesseract',
            'stdin',
            'stdout',
            '-l',
            'eng+chi_sim',
            '--psm',
            '11',
            'tsv',
            data=data.getvalue(),
            timeout=20,
        ).decode()
        button = self.group_in_sidebar(tsv)
        if not button and self.restore_pinned and self.title_reference:
            # The administrator explicitly pinned the operating group first.
            # Opening it is only inspection; the complete header guard still runs.
            button = (180, 110)
        if button:
            self.login_state['restored_prompt_id'] = self.login_state['prompt_id']
            self.save_login_state()
            self.click(*button)
            time.sleep(1)
        return self.check()

    def group_in_sidebar(self, tsv):
        lines = {}
        for row in csv.DictReader(io.StringIO(tsv), delimiter='\t'):
            if not row.get('text', '').strip():
                continue
            key = tuple(row[k] for k in ('page_num', 'block_num', 'par_num', 'line_num'))
            lines.setdefault(key, []).append(row)
        matches = []
        for words in lines.values():
            title = compact(''.join(row['text'] for row in words))
            prefix = re.sub(r'[.…]+$', '', title)
            truncated = (
                prefix != title and len(prefix) >= 8 and compact(self.group).startswith(prefix)
            )
            # Opening a truncated candidate is only an inspection. check() must
            # still match the complete chat header before any message can send.
            if not target_matches(title, self.group) and not truncated:
                continue
            if any(float(row['conf']) < 40 for row in words):
                continue
            left = min(int(row['left']) for row in words)
            top = min(int(row['top']) for row in words)
            right = max(int(row['left']) + int(row['width']) for row in words)
            bottom = max(int(row['top']) + int(row['height']) for row in words)
            matches.append((60 + round((left + right) / 4), 70 + round((top + bottom) / 4)))
        return matches[0] if len(matches) == 1 else None

    def guard(self):
        state = self.check()
        if state['state'] != 'ready':
            raise GuardError(state['reason'])
        active = run('xdotool', 'getactivewindow').decode().strip()
        if active != self.window:
            run('xdotool', 'windowactivate', '--sync', self.window)
            time.sleep(0.3)
        return self.geometry

    def click(self, x, y):
        g = self.geometry
        run('xdotool', 'mousemove', str(int(g['X']) + x), str(int(g['Y']) + y))
        time.sleep(0.3)
        run('xdotool', 'mousedown', '1')
        time.sleep(0.1)
        run('xdotool', 'mouseup', '1')

    def wait_send_ready(self):
        for _ in range(10):
            frame = self.screen()
            pixels = list(
                frame.crop(
                    (frame.width - 72, frame.height - 42, frame.width - 60, frame.height - 36)
                ).getdata()
            )
            if sum(g > r * 1.2 and g > b * 1.1 for r, g, b in pixels) >= 30:
                return
            time.sleep(1)
        raise GuardError('send_button_not_ready')

    @staticmethod
    def keys(value):
        run('xdotool', 'key', '--clearmodifiers', value)
        time.sleep(0.25)

    @staticmethod
    def clipboard(data, target='UTF8_STRING'):
        # xclip forks an owner process; don't capture inherited stdout pipes.
        subprocess.run(
            ['xclip', '-selection', 'clipboard', '-target', target, '-i'],
            input=data,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=5,
        )

    def compose_text(self, text):
        g = self.guard()
        self.click(370, int(g['HEIGHT']) - 112)
        # A pre-existing draft belongs to the human operator; do not overwrite it.
        self.clipboard(b'__PKU_EMPTY__')
        self.keys('ctrl+a')
        self.keys('ctrl+c')
        draft = run('xclip', '-selection', 'clipboard', '-o').decode()
        if draft != '__PKU_EMPTY__':
            raise GuardError('draft_present')
        self.clipboard(text.encode('utf-8'))
        self.keys('ctrl+v')
        time.sleep(0.5)
        self.keys('ctrl+a')
        self.keys('ctrl+c')
        actual = run('xclip', '-selection', 'clipboard', '-o').decode()
        if actual.replace('\r\n', '\n') != text:
            raise GuardError('text_verification_failed')
        self.keys('Right')
        return self.screen()

    def send_text(self, text, before_click):
        self.compose_text(text)
        self.guard()
        self.wait_send_ready()
        before_click()
        g = self.geometry
        self.click(int(g['WIDTH']) - 50, int(g['HEIGHT']) - 33)
        time.sleep(3)
        # A cleared composer plus a matching outgoing bubble is local confirmation,
        # not a server receipt or proof every group member has read the message.
        self.guard()
        self.click(370, int(g['HEIGHT']) - 112)
        self.clipboard(b'__PKU_EMPTY__')
        self.keys('ctrl+a')
        self.keys('ctrl+c')
        if run('xclip', '-selection', 'clipboard', '-o').decode() != '__PKU_EMPTY__':
            raise GuardError('send_not_confirmed')
        frame = self.screen()
        body = frame.crop((330, 82, frame.width - 35, frame.height - 152))
        # Outgoing messages use green bubbles. Ignore arbitrary incoming text.
        r, g, b = body.split()
        mask = ImageChops.multiply(
            ImageChops.subtract(g, r).point(lambda v: 255 if v > 15 else 0),
            ImageChops.subtract(g, b).point(lambda v: 255 if v > 15 else 0),
        ).filter(ImageFilter.MaxFilter(9))
        green = Image.new('RGB', body.size, 'white')
        green.paste(body, mask=mask)
        green = green.convert('L').point(lambda value: 0 if value < 160 else 255)
        observed = compact(self.ocr(green, 6))
        needle = re.sub(r'[^\w\u4e00-\u9fff]', '', compact(text))
        observed = re.sub(r'[^\w\u4e00-\u9fff]', '', observed)
        # Artist names can be Japanese or accented; their exact bytes were verified
        # in the composer. Match our stable Chinese label in the outgoing bubble,
        # instead of treating OCR transliteration errors as song ambiguity.
        expected = next(
            (compact(label) for label in ('今天的曲目', '让我们恭喜') if text.startswith(label)),
            needle[:24],
        )
        if expected not in observed:
            raise GuardError('bubble_not_verified')
        return {'state': 'confirmed', 'evidence': 'composer_cleared_and_outgoing_text'}

    def image_matches(self, frame, reference, area):
        """Match the poster itself, including votes/artwork, not just a changed screen.

        Result posters have a dark rectangular masthead. Its connected component
        yields candidate image bounds; compare the complete thumbnail afterwards.
        """
        left, top, right, bottom = area
        region = frame.crop(area).convert('L')
        small = region.resize((region.width // 2, region.height // 2))
        pixels = small.load()
        dark = {
            (x, y) for y in range(small.height) for x in range(small.width) if pixels[x, y] < 65
        }
        candidates = []
        while dark:
            seed = dark.pop()
            stack = [seed]
            xs, ys = [seed[0]], [seed[1]]
            while stack:
                x, y = stack.pop()
                for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if neighbor in dark:
                        dark.remove(neighbor)
                        stack.append(neighbor)
                        xs.append(neighbor[0])
                        ys.append(neighbor[1])
            width = (max(xs) - min(xs) + 1) * 2
            height = (max(ys) - min(ys) + 1) * 2
            if width >= 90 and height >= 8:
                candidates.append((left + min(xs) * 2, top + min(ys) * 2, width))
        expected = reference.convert('RGB').resize((32, 44))
        for x, y, width in candidates:
            for delta in range(-4, 5, 2):
                w = width + delta
                h = round(w * reference.height / reference.width)
                for dx in (-2, 0, 2):
                    for dy in (-2, 0, 2):
                        bounds = (x + dx, y + dy, x + dx + w, y + dy + h)
                        if bounds[3] > bottom + 3:
                            continue
                        actual = frame.crop(bounds).resize((32, 44))
                        difference = (
                            sum(ImageStat.Stat(ImageChops.difference(actual, expected)).mean) / 3
                        )
                        if difference < 13:
                            return True
        return False

    def empty_composer(self):
        g = self.geometry
        self.click(int(g['WIDTH']) - 150, int(g['HEIGHT']) - 100)
        self.clipboard(b'__PKU_EMPTY__')
        self.keys('ctrl+a')
        self.keys('ctrl+c')
        try:
            return run('xclip', '-selection', 'clipboard', '-o').decode() == '__PKU_EMPTY__'
        except Exception:
            return False

    def send_image(self, data, before_click):
        if len(data) > 5 * 1024 * 1024:
            raise GuardError('invalid_payload')
        with Image.open(io.BytesIO(data)) as source:
            if source.format != 'PNG' or source.width * source.height > 10_000_000:
                raise GuardError('invalid_payload')
            reference = source.convert('RGB')
        self.guard()
        if not self.empty_composer():
            raise GuardError('draft_present')
        self.clipboard(data, 'image/png')
        self.keys('ctrl+v')
        time.sleep(2)
        # Pasting a fresh PNG may finish decoding after the thumbnail first appears.
        # Move focus off the attachment and wait for the complete preview.
        self.click(int(self.geometry['WIDTH']) - 150, int(self.geometry['HEIGHT']) - 100)
        self.keys('Right')
        for _ in range(8):
            frame = self.screen()
            if self.image_matches(
                frame, reference, (320, 100, frame.width - 20, frame.height - 45)
            ):
                break
            time.sleep(2)
        else:
            raise GuardError('image_preview_not_verified')
        self.guard()
        self.wait_send_ready()
        before_click()
        g = self.geometry
        self.click(int(g['WIDTH']) - 50, int(g['HEIGHT']) - 33)
        for _ in range(4):
            time.sleep(3)
            self.guard()
            if self.empty_composer():
                frame = self.screen()
                if self.image_matches(
                    frame, reference, (frame.width // 2, 82, frame.width - 45, frame.height - 150)
                ):
                    return {
                        'state': 'confirmed',
                        'evidence': 'composer_cleared_and_outgoing_image_fingerprint',
                    }
        raise GuardError('image_send_not_confirmed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--outbox', default='/home/wechat/bot-outbox')
    parser.add_argument('--probe', action='store_true')
    args = parser.parse_args()
    root = Path(args.outbox)
    root.mkdir(parents=True, exist_ok=True)
    config = json.loads((root / 'config.json').read_text())
    ui = Desktop(
        config['group'],
        root / 'login-state.json',
        config.get('title_reference'),
        config.get('restore_pinned', False),
    )
    if args.probe:
        print(json.dumps({'geometry': ui.locate(), 'health': ui.check()}, ensure_ascii=False))
        return
    with Path('/tmp/wechat-sender.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        (root / 'requests').mkdir(exist_ok=True)
        (root / 'receipts').mkdir(exist_ok=True)
        health = {'state': 'blocked', 'checked_at': 0}
        reload_requested = False

        def request_reload(signum, frame):
            nonlocal reload_requested
            reload_requested = True

        signal.signal(signal.SIGHUP, request_reload)
        while True:
            if reload_requested:
                # Same PID: the desktop supervisor keeps the WeChat session alive.
                os.execv(
                    sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
                )
            if time.time() - health['checked_at'] >= 30:
                health = ui.check(reuse_title=True)
                if health.get('reason') in ('logged_out', 'target_not_verified'):
                    try:
                        if health['reason'] == 'logged_out':
                            health = ui.request_phone_login()
                        elif ui.login_state.get('pending'):
                            health = ui.restore_group_after_login()
                    except subprocess.TimeoutExpired:
                        health = ui.health_result('check_timeout')
                    except Exception:
                        health = ui.health_result('client_unavailable')
                atomic(root / 'health.json', health)
            # Keep login checks and mail heartbeats active before launch, but
            # never interact with the chat composer before the configured start.
            if time.time() < float(config.get('send_not_before', 0)):
                time.sleep(2)
                continue
            for path in sorted((root / 'requests').glob('*.json')):
                receipt_path = root / 'receipts' / path.name
                if receipt_path.exists():
                    continue
                request = json.loads(path.read_text())
                receipt = dict(key=request['key'], digest=request['digest'], group=config['group'])
                if request.get('group') != config['group'] or request['expires_at'] < time.time():
                    atomic(
                        receipt_path,
                        {**receipt, 'state': 'blocked', 'reason': 'invalid_target_or_expired'},
                    )
                    continue
                if health['state'] != 'ready':
                    break
                clicked = False

                def before_click():
                    nonlocal clicked
                    atomic(
                        receipt_path,
                        {**receipt, 'state': 'uncertain', 'reason': 'interrupted_send'},
                    )
                    clicked = True

                try:
                    payload = request['payload']
                    digest = hashlib.sha256(
                        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
                    ).hexdigest()
                    if digest != request['digest']:
                        raise GuardError('invalid_payload')
                    if payload['kind'] == 'text':
                        result = ui.send_text(payload['text'], before_click)
                    elif payload['kind'] == 'image':
                        result = ui.send_image(
                            base64.b64decode(payload['png'], validate=True), before_click
                        )
                    else:
                        raise GuardError('invalid_payload')
                    atomic(receipt_path, {**receipt, **result, 'finished_at': time.time()})
                except Exception as error:
                    reason = str(error) if isinstance(error, GuardError) else 'desktop_error'
                    atomic(
                        receipt_path,
                        {
                            **receipt,
                            'state': 'uncertain' if clicked else 'blocked',
                            'reason': reason,
                        },
                    )
                break
            time.sleep(2)


if __name__ == '__main__':
    os.umask(0o077)
    os.environ.setdefault('OMP_THREAD_LIMIT', '1')
    main()
