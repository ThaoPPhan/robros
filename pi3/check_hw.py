"""Read-only hardware check: Pico port, LiDAR packets, camera frames.

Never moves a motor. Run on the Pi:
    ~/robros/.venv/bin/python3 pi3/check_hw.py

The parsing functions (lidar_crc8, parse_lidar_packet) have no hardware
dependency and are covered by tests/test_lidar_packet.py.
"""
import subprocess
import sys
import time
from pathlib import Path

PI3_DIR = Path(__file__).resolve().parent
REPO_ROOT = PI3_DIR.parent

LIDAR_HEADER = bytes([0x54, 0x2C])
LIDAR_PACKET_LEN = 47
CHECK_SECONDS = 2.0


def load_config() -> dict:
    import yaml  # not available on the laptop; only needed to run this script

    with open(PI3_DIR / "config.yaml") as f:
        return yaml.safe_load(f)


# ---------- LiDAR packet parsing (pure, hardware-free) ----------

def _build_crc8_table(poly: int = 0x4D) -> tuple:
    # Table-method CRC8 per the LD06/LD19-class protocol: poly 0x4D, init 0.
    # Built here instead of hand-copied so there is no transcription risk.
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
        table.append(crc)
    return tuple(table)


_CRC_TABLE = _build_crc8_table()


def lidar_crc8(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = _CRC_TABLE[(crc ^ b) & 0xFF]
    return crc


def parse_lidar_packet(data: bytes):
    """Return a dict for one valid 47-byte LiDAR packet, else None."""
    if len(data) != LIDAR_PACKET_LEN:
        return None
    if data[0:2] != LIDAR_HEADER:
        return None
    if lidar_crc8(data[:-1]) != data[-1]:
        return None
    # header(2) speed(2) start_angle(2) 12x[dist(2) intensity(1)](36) end_angle(2) timestamp(2) crc(1)
    return {
        "speed_deg_s": int.from_bytes(data[2:4], "little"),
        "start_angle": int.from_bytes(data[4:6], "little") / 100.0,
        "end_angle": int.from_bytes(data[42:44], "little") / 100.0,
    }


# ---------- Pico ----------

def check_pico(config: dict) -> bool:
    port = config["pico"]["port"]
    mpremote = str(REPO_ROOT / config["pico"]["mpremote_bin"])

    try:
        result = subprocess.run(
            [mpremote, "connect", port, "fs", "ls"],
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        print(f"PICO: FAIL (mpremote not found at {mpremote})")
        return False
    except subprocess.TimeoutExpired:
        print("PICO: FAIL (timed out talking to the board)")
        return False

    if result.returncode != 0:
        print(f"PICO: FAIL ({result.stderr.strip()})")
        return False

    print(f"PICO: OK (port {port})")
    for line in result.stdout.strip().splitlines():
        print(f"  {line}")
    return True


# ---------- LiDAR ----------

def check_lidar(config: dict) -> bool:
    import serial  # hardware lib: deferred so this file imports on the laptop

    port = config["lidar"]["port"]
    baud = config["lidar"]["baud"]
    try:
        ser = serial.Serial(port, baud, timeout=1)
    except Exception as e:
        print(f"LIDAR: FAIL (couldn't open {port}: {e})")
        return False

    packets = 0
    buf = b""
    start = time.time()
    try:
        while time.time() - start < CHECK_SECONDS:
            buf += ser.read(256)
            while True:
                idx = buf.find(LIDAR_HEADER)
                if idx == -1 or len(buf) - idx < LIDAR_PACKET_LEN:
                    buf = buf[idx:] if idx != -1 else b""
                    break
                if parse_lidar_packet(buf[idx:idx + LIDAR_PACKET_LEN]):
                    packets += 1
                buf = buf[idx + LIDAR_PACKET_LEN:]
    finally:
        ser.close()

    elapsed = time.time() - start
    if packets == 0:
        print("LIDAR: FAIL (no valid packets received)")
        return False
    print(f"LIDAR: OK ({packets} valid packets in {elapsed:.1f}s, ~{packets / elapsed:.1f} packets/s)")
    return True


# ---------- Camera ----------

def check_camera(config: dict) -> bool:
    backend = config["camera"]["backend"]
    size = tuple(config["camera"]["stream_size"])

    if backend == "picamera2":
        try:
            from picamera2 import Picamera2
        except ImportError as e:
            print(f"CAMERA: FAIL (picamera2 not importable: {e})")
            return False
        cam = Picamera2()
        cam.configure(cam.create_video_configuration(main={"size": size, "format": "RGB888"}))
        cam.start()
        grab = cam.capture_array
        stop = cam.stop
    else:
        import cv2

        cap = cv2.VideoCapture(config["camera"]["usb_index"])
        if not cap.isOpened():
            print("CAMERA: FAIL (could not open USB camera)")
            return False

        def grab():
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError("frame read failed")
            return frame

        stop = cap.release

    frames = 0
    start = time.time()
    try:
        while time.time() - start < CHECK_SECONDS:
            try:
                grab()
                frames += 1
            except RuntimeError:
                pass
    finally:
        stop()

    elapsed = time.time() - start
    if frames == 0:
        print("CAMERA: FAIL (no frames captured)")
        return False
    print(f"CAMERA: OK ({frames} frames in {elapsed:.1f}s, ~{frames / elapsed:.1f} fps)")
    return True


def main() -> int:
    config = load_config()
    results = {
        "pico": check_pico(config),
        "lidar": check_lidar(config),
        "camera": check_camera(config),
    }
    print()
    print("summary:", ", ".join(f"{name}={'OK' if ok else 'FAIL'}" for name, ok in results.items()))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
