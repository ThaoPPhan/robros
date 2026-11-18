#!/usr/bin/env python3
"""Robros line-following vision.

Live:     python3 main.py                      (camera + web UI on :8000, no serial)
          python3 main.py --serial             (also drive the Pico over UART)
Offline:  python3 main.py --source snapshots/  (run the pipeline on saved images)
          python3 main.py --source run.mp4 --serve --rate 10   (replay + web UI)

Terminal keys (type + Enter): s = snapshot, g = arm (GO), x = disarm (STOP), q = quit
"""

import argparse
import csv
import os
import select
import sys
import threading
import time

import cv2

from camera import make_camera
from controller import Controller
from detector import LineDetector, draw_overlay
from settings import load_config, save_values

HERE = os.path.dirname(os.path.abspath(__file__))


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    p.add_argument("--source", help="offline: image file, image folder or video file")
    p.add_argument("--rate", type=float, default=None, help="offline playback fps (0 = max)")
    p.add_argument("--loop", action="store_true", help="offline: loop the source forever")
    p.add_argument("--serve", action="store_true", help="offline: start the web UI (implies --loop)")
    p.add_argument("--out", help="offline: write annotated frames to this folder")
    p.add_argument("--no-server", action="store_true", help="live: do not start the web UI")
    p.add_argument("--port", type=int, help="web UI port (default from config)")
    p.add_argument("--serial", action="store_true", help="send commands to the Pico over UART")
    p.add_argument("--serial-port", help="override serial.port (e.g. /dev/ttyAMA0, loop://)")
    p.add_argument("--no-log", action="store_true", help="do not write a CSV log")
    p.add_argument("--duration", type=float, default=0, help="stop after N seconds")
    p.add_argument("--record-every", type=float, default=0,
                   help="live: save a raw frame to snapshots/ every N seconds")
    p.add_argument("--size", help="override resolution, e.g. 640x480")
    p.add_argument("--mode", choices=["center", "lane"], help="override detector.mode")
    p.add_argument("--arm", action="store_true", help="start armed (speed allowed immediately)")
    p.add_argument("--quiet", action="store_true", help="offline: no per-image lines")
    return p.parse_args()


class CsvLog:
    FIELDS = ["timestamp", "frame", "source", "offset", "angle", "target_x", "target_y",
              "confidence", "lost", "steer", "speed", "armed", "fps", "proc_ms"]

    def __init__(self, folder, tag):
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, time.strftime(f"{tag}_%Y%m%d_%H%M%S.csv"))
        self.f = open(self.path, "w", newline="")
        self.w = csv.writer(self.f)
        self.w.writerow(self.FIELDS)
        self._t_flush = time.monotonic()

    def write(self, ts, n, src, det, cmd, fps, proc_ms):
        tx, ty = det.target if det.target else ("", "")
        self.w.writerow([f"{ts:.3f}", n, src, f"{det.offset:.4f}", f"{det.angle:.2f}",
                         f"{tx:.1f}" if tx != "" else "", f"{ty:.1f}" if ty != "" else "",
                         f"{det.confidence:.3f}", int(det.lost), f"{cmd.steer:.4f}",
                         f"{cmd.speed:.4f}", int(cmd.armed), f"{fps:.1f}", f"{proc_ms:.2f}"])
        if time.monotonic() - self._t_flush > 1.0:
            self.f.flush()
            self._t_flush = time.monotonic()

    def close(self):
        self.f.close()


class KeyReader:
    """Line-based terminal commands without blocking the vision loop."""

    def __init__(self):
        self.enabled = sys.stdin.isatty()

    def poll(self):
        if not self.enabled:
            return None
        r, _, _ = select.select([sys.stdin], [], [], 0)
        if not r:
            return None
        line = sys.stdin.readline()
        if line == "":           # EOF
            self.enabled = False
            return None
        return line.strip().lower()[:1] or None


def save_snapshot(folder, raw, view=None, tag="snap"):
    os.makedirs(folder, exist_ok=True)
    base = os.path.join(folder, time.strftime(f"{tag}_%Y%m%d_%H%M%S_") + f"{int(time.time() * 1000) % 1000:03d}")
    cv2.imwrite(base + ".png", raw)
    if view is not None:
        cv2.imwrite(base + "_view.jpg", view)
    return base + ".png"


def main():
    args = parse_args()
    cfg = load_config(args.config)
    cam_cfg, det_cfg, ctl_cfg = cfg["camera"], cfg["detector"], cfg["controller"]
    if args.size:
        cam_cfg["width"], cam_cfg["height"] = (int(v) for v in args.size.lower().split("x"))
    if args.mode:
        det_cfg["mode"] = args.mode
    if args.arm:
        ctl_cfg["start_armed"] = True
    offline = bool(args.source)
    serve = args.serve if offline else (not args.no_server and cfg["server"].get("enabled", True))
    loop = args.loop or (offline and args.serve)
    rate = args.rate if args.rate is not None else (10.0 if (offline and serve) else 0.0)
    snap_dir = os.path.join(HERE, cfg.get("snapshots", {}).get("dir", "snapshots"))

    cam = make_camera(cam_cfg, args.source, rate=rate, loop=loop)
    detector = LineDetector(det_cfg)
    controller = Controller(ctl_cfg, (cam_cfg["width"], cam_cfg["height"]))

    hub = web = link = log = None
    if serve:
        from server import Hub, WebServer, create_app

        def save_params():
            p = detector.params()
            p.update(hub.peek_pending())      # include slider changes not yet applied
            save_values(args.config, "detector", p)
            print(f"[calibrate] saved to {args.config}: {p}")
            return p

        hub = Hub(cfg["server"].get("jpeg_quality", 70))
        app = create_app(hub, detector.params, save_params, cfg["server"].get("stream_fps", 15))
        port = args.port or cfg["server"].get("port", 8000)
        web = WebServer(app, cfg["server"].get("host", "0.0.0.0"), port).start()
        print(f"[web] http://<pi-ip>:{port}/   calibration: /calibrate")
    if args.serial:
        from serial_link import SerialLink
        s = cfg["serial"]
        port = args.serial_port or s["port"]
        try:
            link = SerialLink(port, s.get("baud", 115200), s.get("rate_hz", 20),
                              s.get("heartbeat_hz", 5), s.get("stale_timeout", 0.3)).open()
            print(f"[serial] sending to {port} @ {s.get('baud', 115200)} baud, {s.get('rate_hz', 20)} Hz")
        except Exception as e:  # noqa: BLE001
            print(f"[serial] cannot open {port}: {e}")
            print("         (see README 'Enable the UART'); continuing without serial")
            link = None
    if cfg["logging"].get("enabled", True) and not args.no_log:
        log = CsvLog(os.path.join(HERE, cfg["logging"].get("dir", "logs")),
                     "offline" if offline else "run")
        print(f"[log] {log.path}")
    if args.out:
        os.makedirs(args.out, exist_ok=True)

    keys = KeyReader()
    if keys.enabled and not offline:
        print("[keys] s=snapshot  g=GO(arm)  x=STOP(disarm)  q=quit   (+Enter)")
    print(f"[run] source={cam.name} size={cam_cfg['width']}x{cam_cfg['height']} "
          f"mode={detector.mode} controller={ctl_cfg.get('method')} armed={controller.armed}")

    n, fps, win_n, t_win = 0, 0.0, 0, time.monotonic()
    t_start, t_rec = time.monotonic(), time.monotonic()
    proc_sum, view = 0.0, None
    det = cmd = None
    try:
        cam.start()
        while True:
            frame, ts = cam.read()
            if frame is None:
                break
            t0 = time.perf_counter()

            # requests from the web page / terminal
            actions = []
            if hub:
                pending, actions = hub.take_pending()
                if pending:
                    detector.update(pending)
            k = keys.poll()
            if k == "q":
                break
            if k in ("s", "g", "x"):
                actions.append({"s": ("snapshot", {}), "g": ("arm", {"armed": True}),
                                "x": ("arm", {"armed": False})}[k])
            for name, kw in actions:
                if name == "arm":
                    controller.armed = kw["armed"]
                    print(f"[control] {'ARMED - GO' if controller.armed else 'DISARMED - STOP'}")
                elif name == "snapshot":
                    print(f"[snapshot] {save_snapshot(snap_dir, frame, view)}")

            det, mask = detector.detect(frame)
            cmd = controller.update(det)
            if link:
                link.send(cmd.steer, cmd.speed, cmd.confidence)
            proc_ms = (time.perf_counter() - t0) * 1000
            proc_sum += proc_ms

            n += 1
            win_n += 1
            now = time.monotonic()
            if now - t_win >= 1.0:
                fps = win_n / (now - t_win)
                if not offline or args.quiet:
                    print(f"fps {fps:5.1f} | proc {proc_sum / win_n:4.1f} ms | off {det.offset:+.2f} "
                          f"ang {det.angle:+5.1f} conf {det.confidence:.2f}{' LOST' if det.lost else '     '} | "
                          f"steer {cmd.steer:+.2f} speed {cmd.speed:.2f}" +
                          ("" if cmd.armed else " [disarmed]") +
                          (f" | tx {link.sent}" if link else ""), flush=True)
                win_n, proc_sum, t_win = 0, 0.0, now
            src = os.path.basename(getattr(cam, "current", "") or "") if offline else ""
            if log:
                log.write(ts, n, src, det, cmd, fps, proc_ms)
            if offline and not args.quiet and not serve:
                print(f"{src:40s} off {det.offset:+.3f} ang {det.angle:+6.1f} conf {det.confidence:.2f} "
                      f"{'LOST(' + det.reason + ')' if det.lost else 'ok'}  steer {cmd.steer:+.2f}")

            need_view = (hub and hub.wants_view()) or args.out
            view = draw_overlay(frame, mask, det, cmd, fps, detector.roi_rows(frame.shape[0]),
                                extra=src or None) if need_view else None
            if hub:
                hub.publish(frame, view, mask, {
                    "fps": round(fps, 1), "frame": n, "offset": round(det.offset, 3),
                    "angle": round(det.angle, 1), "target": [round(v, 1) for v in det.target] if det.target else None,
                    "confidence": round(det.confidence, 2), "lost": det.lost, "reason": det.reason,
                    "steer": round(cmd.steer, 3), "speed": round(cmd.speed, 3), "armed": cmd.armed,
                    "mode": detector.mode, "source": src or cam.name,
                    "serial": (link.last_tx if link else "off"), "pico_rx": (link.last_rx if link else "")})
            if args.out:
                name = os.path.splitext(src)[0] if src and cam.name == "images" else f"frame_{n:05d}"
                cv2.imwrite(os.path.join(args.out, name + "_view.jpg"), view)
            if args.record_every and not offline and now - t_rec >= args.record_every:
                save_snapshot(snap_dir, frame, tag="rec")
                t_rec = now
            if args.duration and now - t_start >= args.duration:
                break
    except KeyboardInterrupt:
        pass
    finally:
        if link:
            link.close()          # sends stop commands
        cam.stop()
        if log:
            log.close()
        if web:
            web.stop()
        total = time.monotonic() - t_start
        if n:
            print(f"[done] {n} frames in {total:.1f} s = {n / total:.1f} fps average"
                  + (f"; log: {log.path}" if log else ""))


if __name__ == "__main__":
    main()
