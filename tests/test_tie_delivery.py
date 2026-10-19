"""Offline Linux regression: real queue/receipts, simulated desktop and OCR only."""

import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from cricket import db, wechat
from cricket import service as s


@unittest.skipUnless(os.name == 'posix', 'sender requires Linux fcntl and private file permissions')
class TieDeliveryTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            'tie_sender', os.environ.get('TIE_SENDER_PATH', 'deploy/wechat/sender.py')
        )
        self.sender = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.sender)
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        db.initialize(self.root / 'db.sqlite3')
        self.conn = db.connect(self.root / 'db.sqlite3')
        self.addCleanup(self.conn.close)
        self.now = datetime(2026, 10, 19, 4, tzinfo=timezone.utc)
        self.config = dict(
            WECHAT_SEND_ENABLED=True,
            WECHAT_GROUP='isolated-test',
            WECHAT_OUTBOX=str(self.root / 'outbox'),
            PUBLIC_BASE_URL='https://example.test',
        )
        self.ui = self.sender.Desktop('isolated-test')
        self.ui.geometry = {'WIDTH': 907, 'HEIGHT': 667}
        frame = Image.new('RGB', (907, 667), 'white')
        ImageDraw.Draw(frame).rectangle((500, 300, 850, 390), fill=(149, 236, 105))
        self.compose = self.enterContext(patch.object(self.ui, 'compose_text'))
        self.guard = self.enterContext(
            patch.object(self.ui, 'guard', return_value=self.ui.geometry)
        )
        self.enterContext(patch.object(self.ui, 'wait_send_ready'))
        self.click = self.enterContext(patch.object(self.ui, 'click'))
        self.enterContext(patch.object(self.ui, 'clipboard'))
        self.enterContext(patch.object(self.ui, 'keys'))
        self.enterContext(patch.object(self.ui, 'screen', return_value=frame))
        self.ocr = self.enterContext(patch.object(self.ui, 'ocr'))
        self.run = self.enterContext(
            patch.object(self.sender, 'run', return_value=b'__PKU_EMPTY__')
        )
        self.enterContext(patch.object(self.sender.time, 'sleep'))
        # The result image's transport is outside this tie-text regression.
        original = wechat.materialize
        self.enterContext(
            patch.object(
                wechat,
                'materialize',
                side_effect=lambda conn, config, message: (
                    {'kind': 'image', 'png': 'isolated-image'}
                    if message['kind'] == 'image'
                    else original(conn, config, message)
                ),
            )
        )
        wechat.write_private(
            self.root / 'outbox/health.json',
            dict(state='ready', reason='', checked_at=self.now.timestamp()),
        )

    def prepare(self, count=1, text=None):
        text = text or s.congratulations(
            [dict(position=i + 1, outcome='tie') for i in range(count)]
        )
        messages = [
            dict(kind='image', url='https://example.test/result.png'),
            dict(kind='text', text=text),
            dict(kind='text', text='今天的曲目：A vs B\n投票链接：https://example.test'),
        ]
        with self.conn:
            self.conn.execute(
                'INSERT INTO dispatches VALUES (?,?,?,?)',
                (
                    '2026-10-19',
                    s.encode(messages),
                    'prepared',
                    s.stamp(self.now),
                ),
            )
        self.assertEqual(self.advance()['position'], 0)
        self.write_receipt(0, state='confirmed')
        self.assertEqual(self.advance()['position'], 1)
        return text

    def advance(self):
        return wechat.dispatch_next(self.conn, self.config, self.now)

    def write_receipt(self, position, **result):
        row = self.conn.execute(
            'SELECT key FROM wechat_deliveries WHERE position=?',
            (position,),
        ).fetchone()
        path = self.root / 'outbox/requests' / (row['key'] + '.json')
        request = json.loads(path.read_text())
        wechat.write_private(
            self.root / 'outbox/receipts' / path.name,
            {**{key: request[key] for key in ('key', 'digest', 'group')}, **result},
        )

    def before_click(self):
        self.write_receipt(1, state='uncertain', reason='interrupted_send')
        self.assertEqual(self.advance()['state'], 'uncertain')

    def check_success(self, count, observed, text=None):
        text = self.prepare(count, text)
        self.ocr.side_effect = ['OCR missed the first read', observed]
        result = self.ui.send_text(text, self.before_click)
        self.assertEqual(result['state'], 'confirmed')
        self.assertEqual(self.ocr.call_count, 2)
        self.compose.assert_called_once_with(text)
        send_clicks = [call for call in self.click.call_args_list if call.args == (857, 634)]
        self.assertEqual(len(send_clicks), 1, 'OCR retry must not click Send again')
        self.write_receipt(1, **result)
        self.assertEqual(self.advance()['position'], 2)
        row = self.conn.execute(
            'SELECT state,reason FROM wechat_deliveries WHERE position=1'
        ).fetchone()
        self.assertEqual(tuple(row), ('confirmed', ''))
        self.write_receipt(2, state='confirmed')
        self.assertEqual(self.advance()['state'], 'sent')
        self.assertIsNone(self.advance())
        self.assertEqual(
            self.conn.execute('SELECT COUNT(*) FROM wechat_deliveries').fetchone()[0], 3
        )

    def test_single_tie_recovers_ocr_and_continues_to_link(self):
        self.check_success(1, '平局很能打')

    def test_legacy_numbered_single_tie_continues_to_link(self):
        self.check_success(1, '第1组平局很能打', text='第 1 组平局，双方都很能打👏')

    def test_multiple_ties_recover_ocr_and_continue_to_link(self):
        self.check_success(2, '第1组平局很能打 第2组平局很能打')

    def test_unverified_tie_pauses_without_queueing_link_or_resending(self):
        text = self.prepare()
        self.ocr.return_value = '无法核验'
        with self.assertRaisesRegex(self.sender.GuardError, 'bubble_not_verified'):
            self.ui.send_text(text, self.before_click)
        self.write_receipt(1, state='uncertain', reason='bubble_not_verified')
        for _ in range(3):
            self.assertEqual(self.advance()['reason'], 'bubble_not_verified')
        self.assertEqual(
            self.conn.execute('SELECT COUNT(*) FROM wechat_deliveries').fetchone()[0], 2
        )
        self.compose.assert_called_once()

    def test_composer_not_cleared_is_not_confirmed_by_old_tie_bubble(self):
        self.run.return_value = '仍有草稿'.encode()
        with self.assertRaisesRegex(self.sender.GuardError, 'send_not_confirmed'):
            self.ui.send_text('平局，双方都很能打👏', lambda: None)
        self.ocr.assert_not_called()

    def test_wrong_target_stops_before_send(self):
        self.guard.side_effect = self.sender.GuardError('target_not_verified')
        with self.assertRaisesRegex(self.sender.GuardError, 'target_not_verified'):
            self.ui.send_text('平局，双方都很能打👏', lambda: self.fail('must not send'))
        self.click.assert_not_called()

    def test_tie_matching_requires_phrases_and_all_numbered_groups(self):
        matches = self.sender.outgoing_bubble_matches
        self.assertTrue(matches('平局，双方都很能打👏', '平局很能打'))
        self.assertFalse(matches('平局，双方都很能打👏', '平局'))
        self.assertFalse(matches('平局，双方都很能打👏', '很能打'))
        old = '第 1 组平局，双方都很能打👏'
        self.assertTrue(matches(old, '第1组平局很能打'))
        self.assertFalse(matches(old, '第2组平局很能打'))
        multiple = old + '\n第 2 组平局，双方都很能打👏'
        self.assertFalse(matches(multiple, '第1组平局很能打'))


if __name__ == '__main__':
    unittest.main()
