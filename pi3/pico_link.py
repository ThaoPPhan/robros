"""Background link to the Pico: sends the current command + a heartbeat at
20 Hz, keeps the latest telemetry line, and tells the Pico to stop when this
thread stops cleanly. (If the Pi process is killed outright, nothing here
runs -- the Pico's own failsafe in pico/main.py is what actually saves you.)

Wire protocol (text lines, \\n-terminated) -- see CLAUDE.md:
  Pi -> Pico: M,<left>,<right> | S,<steer>,<speed> | H,<seq> | R | X
  Pico -> Pi: E,<ms>,<countL>,<countR>,<rateL>,<rateR>,<outL>,<outR>,<failsafe>
"""
import threading
import time


def parse_telemetry_line(line: str):
    """Parse one 'E,...' line into a dict, or None if it isn't valid telemetry."""
    parts = line.strip().split(",")
    if len(parts) != 9 or parts[0] != "E":
        return None
    try:
        return {
            "ms": int(parts[1]),
            "count_left": int(parts[2]),
            "count_right": int(parts[3]),
            "rate_left": float(parts[4]),
            "rate_right": float(parts[5]),
            "out_left": float(parts[6]),
            "out_right": float(parts[7]),
            "failsafe": parts[8] == "1",
        }
    except ValueError:
        return None


class PicoLink:
    """start() it once; call set_wheels()/set_steer() as often as you like --
    the background thread sends whatever is current at SEND_HZ regardless.
    latest_telemetry() returns the most recent parsed 'E,...' line, or None.
    stop() closes the port and sends a final 'X' (best effort)."""

    SEND_HZ = 20

    def __init__(self, port: str, baud: int = 115200):
        self._port_name = port
        self._baud = baud
        self._lock = threading.Lock()
        self._command = "M,0,0"
        self._oneshot = None
        self._telemetry = None
        self._seq = 0
        self._stop_event = threading.Event()
        self._serial = None
        self._thread = None

    def start(self) -> None:
        import serial  # hardware lib: deferred so this module imports on the laptop

        self._serial = serial.Serial(self._port_name, self._baud, timeout=0)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._serial:
            self._serial.close()

    def set_wheels(self, left: float, right: float) -> None:
        with self._lock:
            self._command = "M,{:.3f},{:.3f}".format(left, right)

    def set_steer(self, steer: float, speed: float) -> None:
        with self._lock:
            self._command = "S,{:.3f},{:.3f}".format(steer, speed)

    def reset_encoders(self) -> None:
        with self._lock:
            self._oneshot = "R"

    def latest_telemetry(self):
        with self._lock:
            return self._telemetry

    def _run(self) -> None:
        interval = 1.0 / self.SEND_HZ
        buf = b""
        while not self._stop_event.is_set():
            tick_start = time.monotonic()

            with self._lock:
                oneshot, self._oneshot = self._oneshot, None
                command = self._command
                self._seq += 1
                seq = self._seq

            try:
                if oneshot:
                    self._serial.write((oneshot + "\n").encode())
                self._serial.write((command + "\n").encode())
                self._serial.write("H,{}\n".format(seq).encode())

                buf += self._serial.read(4096)
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    telemetry = parse_telemetry_line(raw.decode(errors="ignore"))
                    if telemetry:
                        with self._lock:
                            self._telemetry = telemetry
            except Exception:
                pass  # a dropped read/write this tick isn't fatal, next tick retries

            time.sleep(max(0.0, interval - (time.monotonic() - tick_start)))

        try:
            self._serial.write(b"X\n")
        except Exception:
            pass
