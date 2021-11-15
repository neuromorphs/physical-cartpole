import math
import logging
LOGGING_LEVEL = logging.INFO
PRINT_PERIOD_MS = 100  # shows state every this many ms

LIVE_PLOT = False

CALIBRATE = False  # If True calibration will be run at start-up of the program
# important to calibrate if running standalone to avoid motor burnout
# because limits are determined during this calibration

CONTROLLER_NAME = 'PD'
CONTROL_PERIOD_MS = 2  # It was 25 originally, we changed it to 5 - marcin & asude
PATH_TO_CONTROLLERS = './Controllers/'  # Path where controllers are stored

PATH_TO_EXPERIMENT_RECORDINGS = './ExperimentRecordings/'  # Path where the experiments data is stored

JSON_PATH = 'Json/'

MOTOR_FULL_SCALE = 8192  # 7199 # with pololu motor and scaling in firmware #7199 # with original motor
MOTOR_MAX_PWM = int(round(0.95 * MOTOR_FULL_SCALE))

# Angle unit conversion adc to radians: (ANGLE_TARGET + ANGLE DEVIATION - ANGLE_ADC_RANGE/2)/ANGLE_ADC_RANGE*math.pi
# ANGLE_KP_SOFTWARE = ANGLE_KP_FIRMWARE/ANGLE_NORMALIZATION_FACTOR/MOTOR_FULL_SCALE
ANGLE_AVG_LENGTH = 10  # adc routine in firmware reads ADC this many times quickly in succession to reduce noise
ANGLE_ADC_RANGE = 4096  # Range of angle values #
# ANGLE_HANGING = 1019  # right cartpole # Value from sensor when pendulum is at stable equilibrium point
ANGLE_HANGING = 1015 # left cartpole # Value from sensor when pendulum is at stable equilibrium point
#ANGLE_HANGING = 1024 # right cartpole # Value from sensor when pendulum is at stable equilibrium point

if ANGLE_HANGING < ANGLE_ADC_RANGE/2:
    ANGLE_DEVIATION = - ANGLE_HANGING - ANGLE_ADC_RANGE / 2 # moves upright to 0 and hanging to -pi
else:
    ANGLE_DEVIATION = - ANGLE_HANGING + ANGLE_ADC_RANGE / 2 # moves upright to 0 and hanging to pi

ANGLE_NORMALIZATION_FACTOR = 2 * math.pi / ANGLE_ADC_RANGE
ANGLE_DEVIATION_FINETUNE = 0.11999999999999998 # adjust from key commands such that upright angle error is minimized

# Position unit conversion adc to meters: POSITION_TARGET_SOFTWARE = POSITION_TARGET_FIRMWARE*POSITION_NORMALIZATION_FACTOR
# POSITION_KP_SOFTWARE = POSITION_KP_FIRMWARE/POSITION_NORMALIZATION_FACTOR/MOTOR_FULL_SCALE
POSITION_ENCODER_RANGE = 4660  # This is an empirical approximation # seems to be 4164 now
POSITION_OFFSET = 0  # Serves to adjust starting position - position after calibration is 0
POSITION_FULL_SCALE_N = int(POSITION_ENCODER_RANGE) / 2 # Corrected position full scale - cart position should range over +- this value if calibrated for zero at center
TRACK_LENGTH = 0.396  # Total usable track length in meters
POSITION_NORMALIZATION_FACTOR = TRACK_LENGTH/POSITION_ENCODER_RANGE # 0.000084978540773

POSITION_TARGET = 0.0  # meters

# Direction for measurement.py - n = 2 for right, n = 1 for left.
n = 1

JOYSTICK_SCALING = MOTOR_MAX_PWM  # how much joystick value -1:1 should be scaled to motor command
JOYSTICK_DEADZONE = 0.1  # deadzone around joystick neutral position that stick is ignored
# TODO: What is this? POSITION_ENCODER_RANGE and POSITION_FULL_SCALE_N cancel each other
JOYSTICK_POSITION_KP= 4 * JOYSTICK_SCALING * POSITION_ENCODER_RANGE / TRACK_LENGTH / POSITION_FULL_SCALE_N # proportional gain constant for joystick position control.
# it is set so that a position error of E in cart position units results in motor command E*JOYSTICK_POSITION_KP

import platform
import subprocess
SERIAL_PORT = subprocess.check_output('ls -a /dev/tty.usbserial*', shell=True).decode("utf-8").strip() if platform.system() == 'Darwin' else '/dev/ttyUSB1'
SERIAL_BAUD = 230400  # default 230400, in firmware. Alternatives if compiled and supported by USB serial intervace are are 115200, 128000, 153600, 230400, 460800, 921600, 1500000, 2000000

ratio = 1.05


def inc(param):
    if param < 2:
        param = round(param + 0.1, 1)
    else:
        old = param
        param = round(param * ratio)
        if param == old:
            param += 1
    return param


def dec(param):
    if param < 2:
        param = max(0, round(param - 0.1, 1))
    else:
        old = param
        param = round(param / ratio)
        if param == old:
            param -= 1
    return param