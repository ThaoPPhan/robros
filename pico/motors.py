"""DRV8871 motor control: slow-decay PWM.

mix_steer, ramp_toward and apply_dead_band are pure (no `machine` import), so
tests/test_motors.py runs them on the laptop. Motor is the only part that
actually touches hardware, and only once instantiated.
"""


def mix_steer(steer: float, speed: float):
    """S,<steer>,<speed> -> (left, right) in -1..1. steer + means turn right."""
    left = speed + 0.5 * steer
    right = speed - 0.5 * steer
    largest = max(abs(left), abs(right), 1.0)
    return left / largest, right / largest


def ramp_toward(current: float, target: float, dt: float, ramp_up_per_s: float, ramp_down_per_s: float) -> float:
    """Step `current` toward `target`, limited to ramp_up/ramp_down units/second.

    Speeding up (|target| grows) uses the slower ramp_up limit so the payload
    isn't pushed around; slowing down uses the faster ramp_down limit so the
    robot can still stop quickly.
    """
    diff = target - current
    if diff == 0:
        return current
    speeding_up = abs(target) > abs(current)
    max_step = (ramp_up_per_s if speeding_up else ramp_down_per_s) * dt
    if abs(diff) <= max_step:
        return target
    return current + (max_step if diff > 0 else -max_step)


def apply_dead_band(output: float, min_output: float) -> float:
    """Lift a tiny nonzero output up to min_output so the wheel actually turns."""
    if output == 0:
        return 0.0
    if abs(output) < min_output:
        return min_output if output > 0 else -min_output
    return output


class Motor:
    """One DRV8871-driven wheel.

    Forward: IN1 steady high, IN2 gets the inverted PWM (slow decay).
    Reverse is the mirror: IN2 steady high, IN1 gets the inverted PWM.
    At output 0 both pins sit high, which brakes rather than coasts -- that's
    the point of slow decay (smoother low-speed control than coast would give).
    off() is a true (0,0) coast, used at boot and for an immediate stop.
    """

    def __init__(self, in1_pin: int, in2_pin: int, direction_sign: int, pwm_freq_hz: int):
        from machine import Pin, PWM  # hardware: only importable on the Pico

        self._dir_sign = direction_sign
        self._in1 = PWM(Pin(in1_pin))
        self._in2 = PWM(Pin(in2_pin))
        self._in1.freq(pwm_freq_hz)
        self._in2.freq(pwm_freq_hz)
        self.off()

    def set(self, output: float) -> None:
        """output in -1..1, already ramped and dead-band-lifted by the caller."""
        output = max(-1.0, min(1.0, output * self._dir_sign))
        if output >= 0:
            self._in1.duty_u16(65535)
            self._in2.duty_u16(int((1.0 - output) * 65535))
        else:
            self._in2.duty_u16(65535)
            self._in1.duty_u16(int((1.0 + output) * 65535))

    def off(self) -> None:
        self._in1.duty_u16(0)
        self._in2.duty_u16(0)
