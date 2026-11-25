"""Unit tests for LiDAR packet parsing: no hardware needed, runs on the laptop.

    python3 -m unittest tests/test_lidar_packet.py
"""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi3"))

from check_hw import LIDAR_PACKET_LEN, lidar_crc8, parse_lidar_packet  # noqa: E402


def build_packet(speed=4500, start_angle=0, end_angle=35999):
    body = bytes([0x54, 0x2C])
    body += struct.pack("<H", speed)
    body += struct.pack("<H", start_angle)
    for _ in range(12):
        body += struct.pack("<HB", 1000, 200)  # distance mm, intensity
    body += struct.pack("<H", end_angle)
    body += struct.pack("<H", 0)  # timestamp
    return body + bytes([lidar_crc8(body)])


class TestLidarPacket(unittest.TestCase):
    def test_valid_packet_is_right_length(self):
        self.assertEqual(len(build_packet()), LIDAR_PACKET_LEN)

    def test_valid_packet_parses(self):
        result = parse_lidar_packet(build_packet())
        self.assertIsNotNone(result)
        self.assertEqual(result["speed_deg_s"], 4500)
        self.assertEqual(result["start_angle"], 0)
        self.assertEqual(result["end_angle"], 359.99)

    def test_bad_crc_is_rejected(self):
        packet = build_packet()
        corrupted = packet[:-1] + bytes([(packet[-1] + 1) % 256])
        self.assertIsNone(parse_lidar_packet(corrupted))

    def test_wrong_header_is_rejected(self):
        packet = build_packet()
        corrupted = bytes([0x00, 0x00]) + packet[2:]
        self.assertIsNone(parse_lidar_packet(corrupted))

    def test_wrong_length_is_rejected(self):
        self.assertIsNone(parse_lidar_packet(b"\x54\x2c\x00"))


if __name__ == "__main__":
    unittest.main()
