import unittest

from app.atmosphere import make_atmosphere


class AtmosphereTests(unittest.TestCase):
    def test_atmosphere_is_dark_ash_with_warm_bias(self) -> None:
        image = make_atmosphere(800, 600)
        self.assertEqual(image.size, (800, 600))
        self.assertEqual(image.mode, "RGB")
        # Sample lower-right bloom vs upper-left night.
        left = image.getpixel((40, 40))
        right = image.getpixel((760, 540))
        self.assertLess(sum(left), 110)
        self.assertGreater(right[0], left[0])


if __name__ == "__main__":
    unittest.main()
