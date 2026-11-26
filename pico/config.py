# Pico-side tunables: pins, PWM frequency, timeouts, ramp rates.
# Every number the firmware needs lives here, never hard-coded elsewhere.

# Motor driver pins (DRV8871)
L_IN1_PIN = 10
L_IN2_PIN = 11
R_IN1_PIN = 12
R_IN2_PIN = 13

# Encoder pins (A = interrupt edge, B = direction read)
L_ENC_A_PIN = 2
L_ENC_B_PIN = 3
R_ENC_A_PIN = 4
R_ENC_B_PIN = 5

PWM_FREQ_HZ = 20000

# Direction fixes, measured by hand with test_pico.py (wheels lifted) on
# 2026-11-25 -- not derived from the motor/wheel mounting, since that guess
# turned out backwards for this build. If the wiring ever changes, re-measure:
# run test_pico.py and watch each "wheel alone" step to fix *_DIR, then watch
# whether the printed counts rise while that same wheel visibly moves forward
# to fix *_ENC_SIGN.
L_DIR = 1
R_DIR = -1
L_ENC_SIGN = -1
R_ENC_SIGN = 1

# Protocol / failsafe timing
COMMAND_TIMEOUT_S = 0.3    # no M/S command for this long -> stop
HEARTBEAT_TIMEOUT_S = 0.6  # heartbeat seen once, then missing this long -> stop
TELEMETRY_HZ = 20

# Ramp: max change in wheel output per second (keeps the sand box from jostling)
RAMP_UP_PER_S = 1.5
RAMP_DOWN_PER_S = 3.0

# Dead-band: outputs below this are lifted so the wheel actually turns.
# TODO M1: measure the real value (currently a guess from CLAUDE.md).
MIN_OUTPUT = 0.12
