"""Encoder counting: IRQ on A's rising edge, read B for direction (1x decoding).

decode_step and compute_rate are pure (no `machine` import), so
tests/test_encoders.py runs them on the laptop. Encoder is the only part that
touches hardware.
"""


def decode_step(b_level: int, sign: int) -> int:
    """+1 if B is low when A rises, -1 if high; `sign` flips a reversed encoder."""
    step = 1 if b_level == 0 else -1
    return step * sign


def compute_rate(count: int, last_count: int, dt: float) -> float:
    """Counts per second since the last sample."""
    if dt <= 0:
        return 0.0
    return (count - last_count) / dt


class Encoder:
    def __init__(self, a_pin: int, b_pin: int, sign: int = 1):
        from machine import Pin  # hardware: only importable on the Pico

        self.sign = sign
        self.count = 0
        self._pin_b = Pin(b_pin, Pin.IN)
        self._pin_a = Pin(a_pin, Pin.IN)
        self._pin_a.irq(trigger=Pin.IRQ_RISING, handler=self._on_rising_a)

    def _on_rising_a(self, pin) -> None:
        self.count += decode_step(self._pin_b.value(), self.sign)

    def reset(self) -> None:
        self.count = 0
