"""Protocol + failsafe loop. This is main.py, so MicroPython runs it at boot.

Wire protocol (text lines, \\n-terminated) -- see CLAUDE.md:
  Pi -> Pico: M,<left>,<right> | S,<steer>,<speed> | H,<seq> | R | X
  Pico -> Pi: E,<ms>,<countL>,<countR>,<rateL>,<rateR>,<outL>,<outR>,<failsafe>

parse_line, apply_command and check_failsafe are pure (no `machine`/`select`
import), so tests/test_main_protocol.py runs them on the laptop. run() is the
hardware integration and only ever executes on the Pico (guarded below).
"""
import config
from encoders import Encoder, compute_rate
from motors import Motor, apply_dead_band, mix_steer, ramp_toward


def parse_line(line: str):
    """Parse one protocol line into (kind, values), or None if invalid."""
    line = line.strip()
    if not line:
        return None
    parts = line.split(",")
    kind = parts[0]
    try:
        if kind == "M" and len(parts) == 3:
            return "M", (float(parts[1]), float(parts[2]))
        if kind == "S" and len(parts) == 3:
            return "S", (float(parts[1]), float(parts[2]))
        if kind == "H" and len(parts) == 2:
            return "H", (int(parts[1]),)
        if kind == "R" and len(parts) == 1:
            return "R", ()
        if kind == "X" and len(parts) == 1:
            return "X", ()
    except ValueError:
        return None
    return None


class State:
    """Everything the loop needs to carry between ticks."""

    def __init__(self):
        self.target_left = 0.0
        self.target_right = 0.0
        self.current_left = 0.0
        self.current_right = 0.0
        self.last_command_ms = None
        self.last_heartbeat_ms = None
        self.heartbeat_seen = False
        self.failsafe = False


def apply_command(state: State, kind: str, values, now_ms: int) -> None:
    """Fold one parsed command into `state`. 'R' is handled by the caller
    (it needs the encoder objects, not just state)."""
    if kind == "M":
        state.target_left, state.target_right = values
        state.last_command_ms = now_ms
    elif kind == "S":
        steer, speed = values
        state.target_left, state.target_right = mix_steer(steer, speed)
        state.last_command_ms = now_ms
    elif kind == "H":
        state.last_heartbeat_ms = now_ms
        state.heartbeat_seen = True
    elif kind == "X":
        # deliberate stop, not a fault -- cut instantly rather than ramp down
        state.target_left = 0.0
        state.target_right = 0.0
        state.current_left = 0.0
        state.current_right = 0.0


def check_failsafe(ms_since_command, ms_since_heartbeat, heartbeat_seen, command_timeout_ms, heartbeat_timeout_ms) -> bool:
    """True if the link looks dead and the robot should stop.

    No command yet, or none recently, always trips it. A missing heartbeat
    only matters once one has actually been seen (so start-up isn't a fault).
    """
    if ms_since_command is None or ms_since_command > command_timeout_ms:
        return True
    if heartbeat_seen and (ms_since_heartbeat is None or ms_since_heartbeat > heartbeat_timeout_ms):
        return True
    return False


def run():
    import select
    import sys
    import time

    motors = (
        Motor(config.L_IN1_PIN, config.L_IN2_PIN, config.L_DIR, config.PWM_FREQ_HZ),
        Motor(config.R_IN1_PIN, config.R_IN2_PIN, config.R_DIR, config.PWM_FREQ_HZ),
    )
    encoders = (
        Encoder(config.L_ENC_A_PIN, config.L_ENC_B_PIN, config.L_ENC_SIGN),
        Encoder(config.R_ENC_A_PIN, config.R_ENC_B_PIN, config.R_ENC_SIGN),
    )

    state = State()
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)
    rx_buffer = ""

    tick_ms = int(1000 / config.TELEMETRY_HZ)
    command_timeout_ms = int(config.COMMAND_TIMEOUT_S * 1000)
    heartbeat_timeout_ms = int(config.HEARTBEAT_TIMEOUT_S * 1000)
    last_tick = time.ticks_ms()
    last_counts = [0, 0]

    while True:
        now = time.ticks_ms()

        while poll.poll(0):
            char = sys.stdin.read(1)
            if char == "\n":
                parsed = parse_line(rx_buffer)
                rx_buffer = ""
                if parsed:
                    kind, values = parsed
                    if kind == "R":
                        encoders[0].reset()
                        encoders[1].reset()
                    else:
                        apply_command(state, kind, values, now)
            else:
                rx_buffer += char

        if time.ticks_diff(now, last_tick) < tick_ms:
            continue
        dt = time.ticks_diff(now, last_tick) / 1000.0
        last_tick = now

        ms_since_command = time.ticks_diff(now, state.last_command_ms) if state.last_command_ms is not None else None
        ms_since_heartbeat = time.ticks_diff(now, state.last_heartbeat_ms) if state.last_heartbeat_ms is not None else None
        state.failsafe = check_failsafe(
            ms_since_command, ms_since_heartbeat, state.heartbeat_seen,
            command_timeout_ms, heartbeat_timeout_ms,
        )

        if state.failsafe:
            state.target_left = 0.0
            state.target_right = 0.0
            state.current_left = 0.0
            state.current_right = 0.0
            out_left = 0.0
            out_right = 0.0
            motors[0].off()
            motors[1].off()
        else:
            state.current_left = ramp_toward(state.current_left, state.target_left, dt, config.RAMP_UP_PER_S, config.RAMP_DOWN_PER_S)
            state.current_right = ramp_toward(state.current_right, state.target_right, dt, config.RAMP_UP_PER_S, config.RAMP_DOWN_PER_S)
            out_left = apply_dead_band(state.current_left, config.MIN_OUTPUT)
            out_right = apply_dead_band(state.current_right, config.MIN_OUTPUT)
            motors[0].set(out_left)
            motors[1].set(out_right)

        rate_left = compute_rate(encoders[0].count, last_counts[0], dt)
        rate_right = compute_rate(encoders[1].count, last_counts[1], dt)
        last_counts[0] = encoders[0].count
        last_counts[1] = encoders[1].count

        print("E,{},{},{},{:.1f},{:.1f},{:.3f},{:.3f},{}".format(
            now, encoders[0].count, encoders[1].count,
            rate_left, rate_right, out_left, out_right,
            1 if state.failsafe else 0,
        ))


if __name__ == "__main__":
    run()
