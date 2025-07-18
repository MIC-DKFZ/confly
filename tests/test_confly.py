import unittest
from confly import Confly


class TestConfly(unittest.TestCase):
    def test_basic(self):
        actual = Confly("tests/configs/base_test.yml")
        expected = {
            "model": {
                "arch": "cnn",
                "size": "big",
                "paras": {
                    "para1": "test",
                    "para2": 5,
                    "para3": 3e-5,
                    "para4": 0.01,
                    "para5": -0.002,
                    "para6": [None, 512, 128],
                    "para7": {"hello": "test"},
                    "para8": ["a", "b", "c"],
                    "para9": None,
                }
            },
            "training": {
                "lr": 0.01,
                "epochs": 1000
            },
            "preprocessing": {
                "img_size": 512
            }
        }

        self.assertEqual(actual.to_dict(), expected)

    def test_interpolation(self):
        actual = Confly("tests/configs/interpolation_test.yml")
        expected = {
            "model": {
                "arch": "cnn",
                "size": "big",
                "paras": {
                    "para1": "test",
                    "para2": 5,
                    "para3": 3e-5,
                    "para4": 0.01,
                    "para5": -0.002,
                    "para6": [None, 512, 128],
                    "para7": {"hello": "test"},
                    "para8": ["a", "b", "c"],
                    "para9": None,
                    "para10": {"a": 78},
                    "para11": 123,
                    "para12": 49
                }
            },
            "training": {
                "lr": 0.01,
                "epochs": 1000
            },
            "preprocessing": {
                "img_size": 512
            }
        }

        self.assertEqual(actual.to_dict(), expected)

if __name__ == '__main__':
    unittest.main()
