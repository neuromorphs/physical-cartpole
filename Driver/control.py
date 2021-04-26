import logging
import time
import json
import math
import csv
import serial  # conda install pyserial
import sys
import glob
# pygame needs python 3.6, not available for 3.7
import pygame  # pip install -U pygame
# older:  conda install -c cogsci pygame; maybe because it only is supplied for earlier python, might need conda install -c evindunn pygame ; sudo apt-get install libsdl-ttf2.0-0
import pygame.joystick as joystick  # https://www.pygame.org/docs/ref/joystick.html
from datetime import datetime
# from Driver.pendulum import Pendulum
# from Driver.kbhit import KBHit
# from Driver.measure import StepResponseMeasurement

from pendulum import Pendulum
from kbhit import KBHit
from measure import StepResponseMeasurement

from Controllers.controller_PD import controller_PD
from state_utilities import create_cartpole_state, cartpole_state_varname_to_index

from globals import *

POLOLU_MOTOR = True  # set true to set options for this motor, which has opposite sign for set_motor TODO needs fixing in firmware or wiring of motor

SERIAL_PORT = None  # if None, takes first one available #"COM4" #"/dev/ttyUSB0" # might move if other devices plugged in
SERIAL_BAUD = 230400  # default 230400, in firmware.   Alternatives if compiled and supported by USB serial intervace are are 115200, 128000, 153600, 230400, 460800, 921600, 1500000, 2000000
PRINT_PERIOD_MS = 100  # shows state every this many ms
CONTROL_PERIOD_MS = 5 # It was 25 originally, we changed it to 5 - marcin & asude
CALIBRATE = False  # False # important to calibrate if running standalone to avoid motor burnout because limits are determined during this calibration
MOTOR_FULL_SCALE = 7199  # 7199 # with pololu motor and scaling in firmware #7199 # with original motor
MOTOR_MAX_PWM = int(round(0.95 * MOTOR_FULL_SCALE))

JOYSTICK_SCALING = MOTOR_MAX_PWM  # how much joystick value -1:1 should be scaled to motor command
JOYSTICK_DEADZONE = 0.1  # deadzone around joystick neutral position that stick is ignored

JOYSTICK_POSITION_KP=4*JOYSTICK_SCALING/POSITION_FULL_SCALE_N # proportional gain constant for joystick position control.
# it is set so that a position error of E in cart position units results in motor command E*JOYSTICK_POSITION_KP

# todo check position unit conversion for joystick
ANGLE_TARGET = 2061  # 3383  # adjust to exactly vertical angle value, read by inspecting angle output
# Angle target value is very sensitive. It keeps changing at every run - we tried stabilizing it by screwing the joint tighter.



POSITION_TARGET = 100/POSITION_NORMALIZATION*TRACK_LENGTH # 1200
POSITION_TARGET = POSITION_TARGET/POSITION_NORMALIZATION*TRACK_LENGTH # Normalizing to have range over track length .396 m
print('POSITION VALUE:', POSITION_TARGET)

PARAMS_JSON_FILE = 'control.json'
LOGGING_LEVEL = logging.INFO

controller = controller_PD()

def my_logger(name):
    # logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    logger = logging.getLogger(name)
    logger.setLevel(LOGGING_LEVEL)
    # create console handler
    ch = logging.StreamHandler()
    ch.setFormatter(CustomFormatter())
    logger.addHandler(ch)
    return logger


class CustomFormatter(logging.Formatter):
    """Logging Formatter to add colors and count warning / errors"""

    grey = "\x1b[38;21m"
    yellow = "\x1b[33;21m"
    red = "\x1b[31;21m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)"

    FORMATS = {
        logging.DEBUG: grey + format + reset,
        logging.INFO: grey + format + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


def serial_ports():  # from https://stackoverflow.com/questions/12090503/listing-available-com-ports-with-python
    """ Lists serial port names

        :raises EnvironmentError:
            On unsupported or unknown platforms
        :returns:
            A list of the serial ports available on the system
    """
    if sys.platform.startswith('win'):
        ports = ['COM%s' % (i + 1) for i in range(256)]
    elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
        # this excludes your current terminal "/dev/tty"
        # if cannot open, check permissions
        ports = glob.glob('/dev/ttyUSB[0-9]*')
    elif sys.platform.startswith('darwin'):
        ports = glob.glob('/dev/tty.*')
    else:
        raise EnvironmentError('Unsupported platform')

    result = []
    for port in ports:
        try:
            s = serial.Serial(port)
            s.close()
            result.append(port)
        except (OSError, serial.SerialException):
            pass
    return result


def help():
    print("\n***********************************")
    print("keystroke commands")
    print("ESC quit")
    print("k toggle control on/off (initially off)")
    print("K trigger motor position calibration")
    print("=/- increase/decrease angle target")
    print("[/] increase/decrease position target")
    print("w/q angle proportional gain")
    print("s/a angle derivative gain")
    print("z/x angle smoothing")
    print("r/e position proportional gain")
    print("f/d position derivative gain")
    print("c/v position smoothing")
    print("l toggle logging data")
    print("S/L Save/Load param values from disk")
    print("D Toggle dance mode")
    print(",./ Turn on motor left zero right")
    print("m Toggle measurement")
    print("***********************************")



log = my_logger(__name__)

# check that we are running from terminal, otherwise we cannot control it
if sys.stdin.isatty():
    # running interactively
    print('running interactively from an interactive terminal, ok')
else:
    print('run from an interactive terminal to allow keyboard input')
    quit()

serialPorts = serial_ports()
print('Available serial ports: ' + str(serialPorts))
if len(serialPorts) == 0:
    print('no serial ports available, or cannot open it; check linux permissions\n Under linux, sudo chmod a+rw [port] transiently, or add user to dialout or tty group')
    quit()

p = Pendulum()

if len(serialPorts) > 1:
    print(str(len(serialPorts)) + ' serial ports, taking first one which is ' + str(serialPorts[0]))
SERIAL_PORT = str(serialPorts[0])
try:
    p.open(SERIAL_PORT, SERIAL_BAUD)
except:
    print('cannot open port ' + str(SERIAL_PORT) + ': available ports are ' + str(serial_ports()))
    quit()

p.control_mode(False)
p.stream_output(False)

log.info('opened ' + str(SERIAL_PORT) + ' successfully')

joystickExists = False
joystickMode=None
pygame.init()
joystick.init()
if joystick.get_count() == 1:
    stick = joystick.Joystick(0)
    stick.init()
    axisNum = stick.get_numaxes()
    buttonNum = stick.get_numbuttons()
    joystickExists = True
    joystickMode='speed' # toggles to 'position' with 'j' key
    print('joystick found with ' + str(axisNum) + ' axes and ' + str(buttonNum) + ' buttons')
else:
    print('no joystick found, only PD control or no control possible')

if CALIBRATE:
    print("Calibrating motor position....")
    if not p.calibrate():
        print("Failed to connect to device")
        p.close()
        exit()
    print("Done calibrating")

controller.loadparams()
time.sleep(1)

p.set_angle_config(0,
                   ANGLE_AVG_LENGTH,
                   0,
                   0,
                   0,
                   )

# region This is a part responsible for setting the parameters for firmware controller. Not integrated in current design yet.
# p.set_angle_config(ANGLE_TARGET,
#                    ANGLE_AVG_LENGTH,
#                    ANGLE_SMOOTHING,
#                    ANGLE_KP,
#                    ANGLE_KD,
#                    )
#
# p.set_position_config(POSITION_TARGET,
#                       POSITION_CTRL_PERIOD_MS,
#                       POSITION_SMOOTHING,
#                       POSITION_KP,
#                       POSITION_KD)
#
# ################################################################################
# # GET PARAMETERS
# ################################################################################
#
# # Why is it getting parameters? To enable checking if they have been correctly written
# setPoint, avgLen, smoothing, KP, KD
(ANGLE_TARGET,
 ANGLE_AVG_LENGTH,
 ANGLE_SMOOTHING,
 ANGLE_KP,
 ANGLE_KD) = p.get_angle_config()
print('ANGLE_AVG_LENGTH: {}'.format(ANGLE_AVG_LENGTH))
#
# (POSITION_TARGET,
#  POSITION_CTRL_PERIOD_MS,
#  POSITION_SMOOTHING,
#  POSITION_KP,
#  POSITION_KD) = p.get_position_config()
# endregion

################################################################################
# CONTROL LOOP (PC BASED)
################################################################################
printCount = 0

controlEnabled = False
manualMotorSetting = False

danceEnabled = False
danceAmpl = 500
dancePeriodS = 8

loggingEnabled = False

kbAvailable = True
try:
    kb = KBHit()  # can only use in posix terminal; cannot use from spyder ipython console for example
except:
    kbAvailable = False

measurement = StepResponseMeasurement()

controller.printparams()
help()
startTime = time.time()
lastTime = startTime

lastControlTime = lastTime
angleErr = 0
positionErr = 0  # for printing even if not controlling
p.stream_output(True)  # now start streaming state
actualMotorCmd = 0
csvfile = None
csvfilename = None
csvwriter = None
motorCmd = 0

while True:

    # Adjust Parameters
    if kbAvailable & kb.kbhit():
        c = kb.getch()
        #Keys used in controller: p, =, -, w, q, s, a, x, z, r, e, f, d, v, c, S, L
        controller.keyboard_input(c)

        if c == '.':  # zero motor
            actualMotorCmd = 0
            controlEnabled = False
            manualMotorSetting = False
        elif c == ',':  # left
            controlEnabled = False
            actualMotorCmd += 100
            manualMotorSetting = True
        elif c == '/':  # right
            actualMotorCmd -= 100
            controlEnabled = False
            manualMotorSetting = True

        elif c == 'D':
            danceEnabled = ~danceEnabled
            print("\ndanceEnabled= {0}".format(danceEnabled))
        elif c == 'l':
            loggingEnabled = ~loggingEnabled
            print("\nloggingEnabled= {0}".format(loggingEnabled))
            if loggingEnabled:
                try:
                    csvfilename = datetime.now().strftime("cartpole-%Y-%m-%d-%H-%M-%S.csv")
                    csvfile = open(csvfilename, 'w', newline='')
                    csvwriter = csv.writer(csvfile, delimiter=',')
                    #csvwriter.writerow([elapsedTime, deltaTime * 1000, angle, position, ANGLE_TARGET, angleErr, positionTargetNow, positionErr, angleCmd, positionCmd, motorCmd, actualMotorCmd, stickControl, stickPos, measurement])

                    csvwriter.writerow(['time'] + ['deltaTimeMs'] + ['angle'] + ['position (m)'] + ['angleTarget'] + ['angleErr'] + ['positionTarget'] + ['positionErr'] + ['angleCmd'] + ['positionCmd'] + ['motorCmd'] + ['actualMotorCmd'] + ['stickControl'] + ['stickPos'] + ['measurement'])
                    # csvwriter.writerow(['time'] + ['angle'] + ['angleD'] + ['angle_cos'] + ['angle_sin'] + ['position'] + ['positionTarget'] + ['positionErr'] + ['angleCmd'] + ['positionCmd'] + ['motorCmd'] + ['actualMotorCmd'] + ['stickControl'] + ['stickPos'] + ['measurement'])
                    print("\n Started logging data to " + csvfilename)
                except Exception as e:
                    loggingEnabled = False
                    print("\n" + str(e) + ": Exception opening csvfile; logging disabled")
            else:
                csvfile.close()
                print("\n Stopped logging data to " + csvfilename)

        elif c == 'k':
            controlEnabled = ~controlEnabled
            print("\ncontrolEnabled= {0}".format(controlEnabled))
        elif c == 'K':
            controlEnabled = False
            print("\nCalibration triggered")
            p.calibrate()
            print("\nCalibration finished")
        elif c == 'h' or c == '?':
            help()

        # Increase Target Position
        elif c == ']':
            POSITION_TARGET += 200/POSITION_NORMALIZATION*TRACK_LENGTH
            print("\nIncreased target position to {0} meters".format(POSITION_TARGET))
        # Decrease Target Position
        elif c == '[':
            POSITION_TARGET -= 200/POSITION_NORMALIZATION*TRACK_LENGTH
            print("\nDecreased target position to {0} meters".format(POSITION_TARGET))
        elif c == 'm':  # toggle measurement
            if measurement.is_idle():
                measurement.start()
            else:
                measurement.stop()
        elif c=='j':
            if joystickMode is None:
                log.warning('no joystick')
            elif joystickMode=='speed':
                joystickMode='position'
                log.info(f'set joystick to cart {joystickMode} control mode')
            elif joystickMode=='position':
                joystickMode='speed'
                log.info(f'set joystick to cart {joystickMode} control mode')

        # Exit
        elif ord(c) == 27:  # ESC
            log.info("\nquitting....")
            break

    # This function will block at the rate of the control loop
    p.clear_read_buffer()  # if we don't clear read buffer, state output piles up in serial buffer #TODO
    (angle, position, command) = p.read_state()
    position = position/POSITION_NORMALIZATION*TRACK_LENGTH
    if POLOLU_MOTOR:
        position = -position
    # angle count is more positive CCW facing cart, position encoder count is more positive to right facing cart (for stock motor), more negative to right (for pololu motor)

    timeNow = time.time()
    deltaTime = timeNow - lastTime
    if deltaTime == 0:
        deltaTime = 1e-6
    lastTime = timeNow
    elapsedTime = timeNow - startTime
    diffFactor = (CONTROL_PERIOD_MS / (deltaTime * 1000))

    positionTargetNow = POSITION_TARGET
    if controlEnabled and danceEnabled:
        positionTargetNow = POSITION_TARGET + danceAmpl * math.sin(2 * math.pi * (elapsedTime / dancePeriodS))

    # Balance PD Control
    # Position PD Control
    s = create_cartpole_state()
    s[cartpole_state_varname_to_index('position')] = position
    s[cartpole_state_varname_to_index('angle')] = angle

    if timeNow - lastControlTime >= CONTROL_PERIOD_MS * .001:
        lastControlTime = timeNow
        motorCmd = controller.step(s=s, target_position=positionTargetNow, time=timeNow, diffFactor=diffFactor)

    motorCmd = MOTOR_MAX_PWM if motorCmd > MOTOR_MAX_PWM else motorCmd
    motorCmd = -MOTOR_MAX_PWM if motorCmd < -MOTOR_MAX_PWM else motorCmd

    stickPos = 0.0
    stickControl = False
    if joystickExists:
        # for event in pygame.event.get(): # User did something.
        #     if event.type == pygame.QUIT: # If user clicked close.
        #         done = True # Flag that we are done so we exit this loop.
        #     elif event.type == pygame.JOYBUTTONDOWN:
        #         print("Joystick button pressed.")
        #     elif event.type == pygame.JOYBUTTONUP:
        #         print("Joystick button released.")
        pygame.event.get()  # must call get() to handle internal queue
        stickPos = stick.get_axis(0)  # 0 left right, 1 front back 2 rotate
    # todo handle joystick control of cart to position, not speed
    if joystickMode=='speed' and abs(stickPos) > JOYSTICK_DEADZONE:
        stickControl = True
        actualMotorCmd = int(round(stickPos * JOYSTICK_SCALING))
    elif joystickMode=='position':
        stickControl=True
        actualMotorCmd=int((stickPos*POSITION_FULL_SCALE-position)*JOYSTICK_POSITION_KP)
    elif controlEnabled and not manualMotorSetting:
        actualMotorCmd = motorCmd
    elif manualMotorSetting == False:
        actualMotorCmd = 0

    if not measurement.is_idle():
        try:
            measurement.update_state(angle, position, timeNow)
            actualMotorCmd = measurement.motor
        except TimeoutError as e:
            log.warning(f'timeout in measurement: {e}')

    # clip motor to actual limits
    actualMotorCmd=actualMotorCmd if actualMotorCmd>-MOTOR_MAX_PWM and actualMotorCmd<MOTOR_MAX_PWM else -MOTOR_MAX_PWM if actualMotorCmd<0 else MOTOR_MAX_PWM
    p.set_motor(-actualMotorCmd)

    if loggingEnabled:
        csvwriter.writerow([elapsedTime, deltaTime * 1000, angle, position, ANGLE_TARGET, angleErr, positionTargetNow, positionErr, controller.angleCmd, controller.positionCmd, motorCmd, actualMotorCmd, stickControl, stickPos, measurement])

        # Print outputL
    printCount += 1
    if printCount >= (PRINT_PERIOD_MS / CONTROL_PERIOD_MS):
        printCount = 0
        print("\r a {:+4d} aErr {:+6.1f} p {:+6.3f} pErr {:+6.3f} aCmd {:+6d} pCmd {:+6d} mCmd {:+6d} dt {:.3f}ms  stick {:.3f}:{} meas={}        \r"
              .format(int(angle),
                      controller.angleErr,
                      position,
                      controller.positionErr,
                      int(round(controller.angleCmd)),
                      int(round(controller.positionCmd)),
                      actualMotorCmd,
                      deltaTime * 1000,
                      stickPos,
                      stickControl,
                      measurement)
              , end='')
# if we pause like below, state info piles up in serial input buffer
# instead loop at max possible rate to get latest state info
#    time.sleep(CONTROL_PERIOD_MS*.001)  # not quite correct since there will be time for execution below

# when x hit during loop or other loop exit
p.set_motor(0)  # turn off motor
p.close()
joystick.quit()

if loggingEnabled:
    csvfile.close()
# todo put position limitation on position set point increase and decrease
# todo add initial measurement that calculates normalization values for conversion to proper units for angle and position
# todo fix get and set params (for chip interface)
# todo check if position unit convertion  works for all featues: dance, joystick, measurement, save/load, etc.
