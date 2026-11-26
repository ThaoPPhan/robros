"""Manual Pico test. RUN WITH THE WHEELS LIFTED OFF THE GROUND.

    ~/robros/.venv/bin/python3 pi3/test_pico.py              # forward/back/each-wheel/stop
    ~/robros/.venv/bin/python3 pi3/test_pico.py --hand-turn   # measure counts per wheel turn
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import yaml  # noqa: E402

from pico_link import PicoLink  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def run_step(link: PicoLink, left: float, right: float, seconds: float, label: str):
    print("-- {} ({:+.2f}, {:+.2f}) for {:.1f}s --".format(label, left, right, seconds))
    link.set_wheels(left, right)
    time.sleep(seconds)
    link.set_wheels(0.0, 0.0)
    time.sleep(0.3)  # let the ramp-down settle before reading counts
    telemetry = link.latest_telemetry()
    if telemetry:
        print("   counts: left={} right={}".format(telemetry["count_left"], telemetry["count_right"]))
    else:
        print("   no telemetry yet -- check the link")


def sequence_test(link: PicoLink):
    link.reset_encoders()
    time.sleep(0.2)
    run_step(link, 0.5, 0.5, 1.0, "forward")
    run_step(link, -0.5, -0.5, 1.0, "back")
    run_step(link, 0.5, 0.0, 1.0, "left wheel alone")
    run_step(link, 0.0, 0.5, 1.0, "right wheel alone")
    link.set_wheels(0.0, 0.0)
    print()
    print("check: both wheels physically drove forward during 'forward' and both")
    print("physically drove back during 'back'; each 'wheel alone' step only moved")
    print("its own count, and that count rose while the wheel visibly moved forward.")
    print("If either isn't true, flip that wheel's L_DIR/R_DIR (direction) or")
    print("L_ENC_SIGN/R_ENC_SIGN (count sign) in pico/config.py and redeploy.")


def hand_turn_mode(link: PicoLink):
    print("Hand-turn mode: motors stay off.")
    print("Turn ONE wheel by hand exactly 10 full turns, then press Enter.")
    link.set_wheels(0.0, 0.0)
    link.reset_encoders()
    time.sleep(0.2)
    input("Press Enter when you've done 10 turns... ")
    telemetry = link.latest_telemetry()
    if not telemetry:
        print("no telemetry received -- check the link")
        return
    print("left count: {}  ({:.1f} counts/turn)".format(
        telemetry["count_left"], telemetry["count_left"] / 10))
    print("right count: {}  ({:.1f} counts/turn)".format(
        telemetry["count_right"], telemetry["count_right"] / 10))
    print()
    print("write whichever wheel you turned into drive.counts_per_wheel_turn in pi3/config.yaml")


def main():
    config = load_config()
    link = PicoLink(config["pico"]["port"], config["pico"]["baud"])
    link.start()
    time.sleep(0.3)  # let the first telemetry arrive
    try:
        if "--hand-turn" in sys.argv:
            hand_turn_mode(link)
        else:
            sequence_test(link)
    finally:
        link.stop()


if __name__ == "__main__":
    main()
