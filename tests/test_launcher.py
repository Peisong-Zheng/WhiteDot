import unittest

from PySide6.QtGui import QImage, QPainter

from whitedot.windows_ui import dot_art


class LauncherTests(unittest.TestCase):
    def test_halo_is_symmetric_at_normal_and_retina_sizes(self):
        for size in (56, 112):
            with self.subTest(size=size):
                image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(0)
                painter = QPainter(image)
                dot_art(painter, size)
                painter.end()
                # Compare the translucent halo only. One alpha level of variation
                # is normal when QPainter rounds an antialiased edge.
                measured = 0
                for y in range(size // 2):
                    for x in range(size // 2):
                        alpha = image.pixelColor(x, y).alpha()
                        dx, dy = size / 2 - x - .5, size / 2 - y - .5
                        radius = (dx * dx + dy * dy) ** .5 * 56 / size
                        if 20 < radius < 26 and alpha:
                            measured += 1
                            self.assertLessEqual(abs(alpha - image.pixelColor(size - 1 - x, y).alpha()), 2)
                            self.assertLessEqual(abs(alpha - image.pixelColor(x, size - 1 - y).alpha()), 2)
                self.assertGreater(measured, 100)
