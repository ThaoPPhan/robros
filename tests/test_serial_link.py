"""SerialLink tests over a pseudo-terminal pair (no Pico needed)."""
import os
import pty
import re
import sys
import time
import tty
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from serial_link import SerialLink  # noqa: E402

S_RE = re.compile(r"^S,(-?\d+\.\d{3}),(\d\.\d{3}),(\d\.\d{2})$")


def read_lines(fd, seconds):
    os.set_blocking(fd, False)
    buf, t_end = b"", time.monotonic() + seconds
    while time.monotonic() < t_end:
        try:
            buf += os.read(fd, 4096)
        except BlockingIOError:
            time.sleep(0.005)
    return buf.decode().splitlines()


class SerialLinkTests(unittest.TestCase):
    def setUp(self):
        self.master, slave = pty.openpty()
        tty.setraw(slave)
        self.port = os.ttyname(slave)
        self.slave = slave

    def tearDown(self):
        os.close(self.master)
        os.close(self.slave)

    def test_rate_format_heartbeat_and_stale_stop(self):
        link = SerialLink(self.port, 115200, rate_hz=20, heartbeat_hz=5, stale_timeout=0.3).open()
        try:
            t_end = time.monotonic() + 2.0
            lines = []
            while time.monotonic() < t_end:       # vision loop at ~30 fps
                link.send(-0.25, 0.4, 0.87)
                lines += read_lines(self.master, 1 / 30)
            s = [ln for ln in lines if ln.startswith("S,")]
            h = [ln for ln in lines if ln.startswith("H,")]
            self.assertTrue(all(S_RE.match(ln) for ln in s), s[:3])
            self.assertIn("S,-0.250,0.400,0.87", s)
            self.assertAlmostEqual(len(s) / 2.0, 20, delta=3)     # 20 Hz
            self.assertAlmostEqual(len(h) / 2.0, 5, delta=1.5)    # 5 Hz
            seqs = [int(x.split(",")[1]) for x in h]
            self.assertEqual(seqs, list(range(seqs[0], seqs[0] + len(seqs))))

            # vision loop stops -> stop commands, no heartbeat
            read_lines(self.master, 0.4)
            stale = read_lines(self.master, 0.5)
            self.assertTrue(stale)
            self.assertTrue(all(ln == "S,0.000,0.000,0.00" for ln in stale), stale)
        finally:
            link.close()
        tail = read_lines(self.master, 0.2)
        self.assertIn("S,0.000,0.000,0.00", tail)

    def test_reads_pico_replies(self):
        link = SerialLink(self.port).open()
        try:
            os.write(self.master, b"OK,1\nPICO,ready\n")
            time.sleep(0.2)
            self.assertEqual(link.last_rx, "PICO,ready")
        finally:
            link.close()


if __name__ == "__main__":
    unittest.main()
