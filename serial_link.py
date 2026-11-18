"""UART link to the Raspberry Pi Pico.

Messages (ASCII, newline terminated, 115200 8N1 by default):
  S,<steer>,<speed>,<confidence>   at rate_hz (20 Hz)   steer -1..1 (+ = right), speed 0..1
  H,<seq>                          at heartbeat_hz (5 Hz), seq counts up 0..65535

A background thread sends the latest command at a fixed rate, independent of the camera
frame rate. If the vision loop stops producing results for `stale_timeout` seconds,
the thread sends stop commands (S,0.000,0.000,0.00) and stops the heartbeat, so the
Pico's own timeout also trips. The Pico should stop the motors if it gets no valid
S/H line for ~300 ms.
"""

import threading
import time

import serial


class SerialLink:
    def __init__(self, port="/dev/serial0", baud=115200, rate_hz=20, heartbeat_hz=5,
                 stale_timeout=0.3):
        self.port, self.baud = port, baud
        self.period = 1.0 / rate_hz
        self.hb_period = 1.0 / heartbeat_hz if heartbeat_hz else 0
        self.stale_timeout = stale_timeout
        self.ser = None
        self._lock = threading.Lock()
        self._cmd = (0.0, 0.0, 0.0)
        self._t_cmd = 0.0
        self._stop = threading.Event()
        self._thread = None
        self.sent = 0
        self.last_rx = ""
        self.last_tx = ""

    def open(self):
        self.ser = serial.serial_for_url(self.port, baudrate=self.baud, timeout=0,
                                         write_timeout=0.05)
        self._thread = threading.Thread(target=self._run, name="serial", daemon=True)
        self._thread.start()
        return self

    def send(self, steer, speed, confidence):
        """Called by the vision loop with every new result."""
        with self._lock:
            self._cmd = (float(steer), float(speed), float(confidence))
            self._t_cmd = time.monotonic()

    @staticmethod
    def format_command(steer, speed, confidence):
        return f"S,{steer:.3f},{speed:.3f},{confidence:.2f}\n"

    def _write(self, line):
        try:
            self.ser.write(line.encode("ascii"))
            self.last_tx = line.strip()
            self.sent += 1
        except serial.SerialTimeoutException:
            pass

    def _run(self):
        seq = 0
        t_next = t_hb = time.monotonic()
        buf = b""
        while not self._stop.is_set():
            now = time.monotonic()
            with self._lock:
                cmd, age = self._cmd, now - self._t_cmd
            fresh = age < self.stale_timeout
            if not fresh:
                cmd = (0.0, 0.0, 0.0)
            self._write(self.format_command(*cmd))
            if self.hb_period and fresh and now >= t_hb:
                self._write(f"H,{seq}\n")
                seq = (seq + 1) % 65536
                t_hb = now + self.hb_period
            try:                                   # keep anything the Pico prints
                data = self.ser.read(256)
                if data:
                    buf = (buf + data)[-512:]
                    *done, buf = buf.split(b"\n")
                    if done:
                        self.last_rx = done[-1].decode("ascii", "replace").strip()
            except serial.SerialException:
                pass
            t_next += self.period
            time.sleep(max(0.0, t_next - time.monotonic()))

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        if self.ser is not None:
            for _ in range(3):
                self._write(self.format_command(0.0, 0.0, 0.0))
            try:
                self.ser.flush()
            finally:
                self.ser.close()
                self.ser = None
