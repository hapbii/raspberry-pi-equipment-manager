from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

from scripts.download_photos import checked_name, rotate_photo, transfer_photos

try:
    from PIL import Image
except ImportError:
    Image = None


class LocalSFTP:
    """Exercise transfer boundaries without a network or real project data."""
    def __init__(self, root):
        self.root = root
        self.fail_name = None
        self.changed_name = None
        self.downloaded = set()

    def local(self, remote):
        return self.root.joinpath(*PurePosixPath(remote).relative_to('/project').parts)

    def listdir_attr(self, remote):
        return [SimpleNamespace(filename=p.name, st_mode=p.lstat().st_mode)
                for p in self.local(remote).iterdir()]

    def stat(self, remote):
        info = self.local(remote).stat()
        return SimpleNamespace(st_size=info.st_size, st_mtime=info.st_mtime + (
            1 if Path(remote).name == self.changed_name and remote in self.downloaded else 0))

    def get(self, remote, local):
        if Path(remote).name == self.fail_name:
            Path(local).write_bytes(b'partial download')
            raise OSError('connection lost')
        shutil.copyfile(self.local(remote), local)
        self.downloaded.add(remote)


@unittest.skipIf(Image is None, 'Pillow is an optional PC photo-transfer dependency')
class DownloadPhotosTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / 'pi'
        (self.remote / 'training').mkdir(parents=True)
        (self.remote / 'training' / 'classes.txt').write_text('raspberry_pi\narduino\n')
        self.photos = self.remote / 'datasets' / 'raw' / 'raspberry_pi' / 'session'
        self.photos.mkdir(parents=True)
        self.output = self.root / 'pc'
        self.sftp = LocalSFTP(self.remote)

    def photo(self, name='photo.png'):
        path = self.photos / name
        with Image.new('RGB', (2, 2)) as picture:
            picture.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)])
            picture.save(path)
        return path

    def test_rotates_pixels_preserves_source_and_hierarchy(self):
        import json
        path = self.photo()
        original = path.read_bytes()
        (self.photos / 'photo.txt').write_text('labels must not be copied unchanged')
        self.assertEqual(transfer_photos(self.sftp, '/project', self.output), 1)
        copied = self.output / 'raw' / 'raspberry_pi' / 'session' / 'photo.png'
        with Image.open(copied) as image:
            self.assertEqual([image.getpixel((x, y)) for y in range(2) for x in range(2)],
                             [(255, 255, 0), (0, 0, 255), (0, 255, 0), (255, 0, 0)])
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(copied.with_suffix('.txt').exists())
        self.assertEqual((self.output / 'classes.txt').read_text(), 'raspberry_pi\narduino\n')
        self.assertEqual(json.loads((self.output / 'transfer.json').read_text())['status'], 'complete')
        self.assertFalse(list(self.output.glob('.transfer-*')))

    def test_interrupted_download_keeps_completed_photos_only(self):
        import json
        self.photo('a.png')
        self.photo('b.png')
        self.sftp.fail_name = 'b.png'
        with self.assertRaisesRegex(OSError, 'connection lost'):
            transfer_photos(self.sftp, '/project', self.output)
        self.assertEqual([p.name for p in self.output.rglob('*.png')], ['a.png'])
        self.assertFalse(list(self.output.glob('.transfer-*')))
        report = json.loads((self.output / 'transfer.json').read_text())
        self.assertEqual((report['status'], report['saved']), ('incomplete', 1))

    def test_changed_remote_photo_is_not_published(self):
        self.photo()
        self.sftp.changed_name = 'photo.png'
        with self.assertRaisesRegex(OSError, '변경'):
            transfer_photos(self.sftp, '/project', self.output)
        self.assertFalse(list(self.output.rglob('*.png')))

    def test_existing_destination_is_never_overwritten(self):
        self.output.mkdir()
        marker = self.output / 'photo.txt'
        marker.write_text('existing labels')
        with self.assertRaises(FileExistsError):
            transfer_photos(self.sftp, '/project', self.output)
        self.assertEqual(marker.read_text(), 'existing labels')

    def test_class_filter_and_no_rotation(self):
        path = self.photo()
        other = self.remote / 'datasets' / 'raw' / 'arduino'
        other.mkdir()
        shutil.copyfile(path, other / 'other.png')
        self.assertEqual(transfer_photos(self.sftp, '/project', self.output, 0, 'raspberry_pi'), 1)
        with Image.open(next(self.output.rglob('*.png'))) as image:
            self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))

    def test_corrupt_photo_is_not_published(self):
        (self.photos / 'broken.jpg').write_bytes(b'not a jpeg')
        with self.assertRaises(OSError):
            transfer_photos(self.sftp, '/project', self.output)
        self.assertFalse(list(self.output.rglob('*.jpg')))
        self.assertFalse(list(self.output.glob('.transfer-*')))

    def test_exif_orientation_is_removed_after_pixel_rotation(self):
        source = self.photos / 'orientation.jpg'
        with Image.new('RGB', (12, 8), (255, 0, 0)) as picture:
            exif = picture.getexif()
            exif[274] = 6
            picture.save(source, exif=exif)
        destination = self.root / 'rotated.jpg'
        rotate_photo(source, destination, 180)
        with Image.open(destination) as image:
            self.assertEqual(image.size, (8, 12))
            self.assertNotIn(274, image.getexif())


class RemotePathTests(unittest.TestCase):
    def test_unsafe_remote_names_are_rejected(self):
        for value in ('..', '../escape', 'a\\b', 'C:escape', 'NUL.jpg', 'a.', 'a '):
            with self.subTest(value=value), self.assertRaises(ValueError):
                checked_name(value)
        self.assertEqual(checked_name('raspberry_pi'), 'raspberry_pi')


if __name__ == '__main__':
    unittest.main()
