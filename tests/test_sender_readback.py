"""Attachment readback regression; no desktop or network access."""

import importlib.util
import io
import os
import subprocess
import unittest
from unittest.mock import patch

from PIL import Image


@unittest.skipUnless(os.name == 'posix', 'sender requires Linux fcntl')
class ImageReadbackTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('sender', 'deploy/wechat/sender.py')
        self.sender = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.sender)
        self.ui = self.sender.Desktop('isolated')
        self.ui.geometry = dict(WIDTH=913, HEIGHT=667)
        for name in ('guard', 'click', 'keys'):
            self.enterContext(patch.object(self.ui, name))
        self.clipboard = self.enterContext(patch.object(self.ui, 'clipboard'))
        self.run = self.enterContext(patch.object(self.sender, 'run'))
        self.reference = Image.new('RGB', (864, 2898), '#123456')

    def png(self, image):
        out = io.BytesIO()
        image.save(out, format='PNG')
        return out.getvalue()

    def test_exact_tall_attachment_and_cleared_clipboard(self):
        self.run.return_value = self.png(self.reference)
        self.assertTrue(self.ui.image_draft_matches(self.reference))
        self.clipboard.assert_called_once_with(b'__PKU_IMAGE_READBACK__')

    def test_wrong_pixel_is_rejected(self):
        wrong = self.reference.copy()
        wrong.putpixel((100, 2000), (255, 0, 0))
        self.run.return_value = self.png(wrong)
        self.assertFalse(self.ui.image_draft_matches(self.reference))

    def test_wrong_dimensions_are_rejected(self):
        self.run.return_value = self.png(self.reference.resize((432, 1449)))
        self.assertFalse(self.ui.image_draft_matches(self.reference))

    def test_no_image_or_corrupt_copy_is_rejected(self):
        for result in (b'not a png', subprocess.CalledProcessError(1, 'xclip')):
            with self.subTest(result=type(result).__name__):
                self.run.side_effect = result if isinstance(result, Exception) else None
                self.run.return_value = result
                self.assertFalse(self.ui.image_draft_matches(self.reference))

    def test_long_image_submits_when_preview_and_bubble_cannot_match(self):
        with (
            patch.object(self.ui, 'empty_composer', return_value=True),
            patch.object(self.ui, 'wait_send_ready'),
            patch.object(self.ui, 'screen', return_value=Image.new('RGB', (913, 667))),
            patch.object(self.ui, 'image_matches', return_value=False),
            patch.object(self.sender.time, 'sleep'),
        ):
            self.run.return_value = self.png(self.reference)
            boundary = self.enterContext(patch('builtins.print'))
            result = self.ui.send_image(self.png(self.reference), boundary)
            self.assertEqual(result['state'], 'submitted')
            boundary.assert_called_once()

    def test_invalid_draft_never_clicks_send(self):
        with (
            patch.object(self.ui, 'empty_composer', return_value=True),
            patch.object(self.sender.time, 'sleep'),
        ):
            self.run.return_value = b'not an image'
            boundary = self.enterContext(patch('builtins.print'))
            with self.assertRaisesRegex(self.sender.GuardError, 'image_draft_not_verified'):
                self.ui.send_image(self.png(self.reference), boundary)
            boundary.assert_not_called()

    def test_uncleared_image_remains_uncertain(self):
        with (
            patch.object(self.ui, 'empty_composer', side_effect=[True, False, False, False, False]),
            patch.object(self.ui, 'wait_send_ready'),
            patch.object(self.sender.time, 'sleep'),
        ):
            self.run.return_value = self.png(self.reference)
            with self.assertRaisesRegex(self.sender.GuardError, 'image_send_not_confirmed'):
                self.ui.send_image(self.png(self.reference), lambda: None)
