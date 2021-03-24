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
import pendulum
import kbhit

from Driver.measure import StepResponseMeasurement

POLOLU_MOTOR = True  # set true to set options for this motor, which has opposite sign for set_motor TODO needs fixing in firmware or wiring of motor

SERIAL_PORT = None  # if None, takes first one available #"COM4" #"/dev/ttyUSB0" # might move if other devices plugged in
SERIAL_BAUD = 230400  # default 230400, in firmware.   Alternatives if compiled and supported by USB serial intervace are are 115200, 128000, 153600, 230400, 460800, 921600, 1500000, 2000000
PRINT_PERIOD_MS = 100  # shows state every this many ms
CONTROL_PERIOD_MS = 5
CALIBRATE = False  # False # important to calibrate if running standalone to avoid motor burnout because limits are determined during this calibration
MOTOR_FULL_SCALE = 7199  # 7199 # with pololu motor and scaling in firmware #7199 # with original motor
MOTOR_MAX_PWM = int(round(0.95 * MOTOR_FULL_SCALE))

JOYSTICK_SCALING = MOTOR_MAX_PWM  # how much joystick value -1:1 should be scaled to motor command
JOYSTICK_DEADZONE = 0.1  # deadzone around joystick neutral position that stick is ignored

ANGLE_TARGET = 3129  # 3383  # adjust to exactly vertical angle value, read by inspecting angle output
# I don't think this is true now. I measure approximately +3525
ANGLE_CTRL_PERIOD_MS = 5  # Must be a multiple of CONTROL_PERIOD_MS
ANGLE_AVG_LENGTH = 4  # adc routine in firmware reads ADC this many times quickly in succession to reduce noise
ANGLE_SMOOTHING = 1  # 1.0 turns off smoothing
ANGLE_KP = 400
ANGLE_KD = 400
ANGLE_KI = 0

POSITION_TARGET = 0  # 1200
POSITION_CTRL_PERIOD_MS = 25  # Must be a multiple of CONTROL_PERIOD_MS
POSITION_SMOOTHING = 1  # 1.0 turns off smoothing
POSITION_KP = 20
POSITION_KD = 300

PARAMS_JSON_FILE = 'control.json'
LOGGING_LEVEL = logging.INFO


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


def saveparams():
    print(f"\nSaving parameters to {PARAMS_JSON_FILE}")
    p = {}
    p['ANGLE_TARGET'] = ANGLE_TARGET
    p['ANGLE_KP'] = ANGLE_KP
    p['ANGLE_KD'] = ANGLE_KD
    p['ANGLE_KI'] = ANGLE_KI
    p['POSITION_TARGET'] = POSITION_TARGET
    p['POSITION_KP'] = POSITION_KP
    p['POSITION_KD'] = POSITION_KD
    p['ANGLE_SMOOTHING'] = ANGLE_SMOOTHING
    p['POSITION_SMOOTHING'] = POSITION_SMOOTHING
    with open('control.json', 'w') as f:
        json.dump(p, f)


def loadparams():
    print(f"\nLoading parameters from {PARAMS_JSON_FILE}....")
    f = open(PARAMS_JSON_FILE)
    try:
        p = json.load(f)
        global ANGLE_TARGET, ANGLE_KP, ANGLE_KD, POSITION_TARGET, POSITION_KP, POSITION_KD, ANGLE_SMOOTHING, POSITION_SMOOTHING
        ANGLE_TARGET = p['ANGLE_TARGET']
        ANGLE_KP = p['ANGLE_KP']
        ANGLE_KD = p['ANGLE_KD']
        # ANGLE_KI=p['ANGLE_KI']
        POSITION_TARGET = p['POSITION_TARGET']
        POSITION_KP = p['POSITION_KP']
        POSITION_KD = p['POSITION_KD']
        ANGLE_SMOOTHING = p['ANGLE_SMOOTHING']
        POSITION_SMOOTHING = p['POSITION_SMOOTHING']
    except Exception as e:
        print(f"\nsomething went wrong loading parameters: {e}")
        return
    print("success, parameters are")
    printparams()


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
    print("y/t angle integral gain")
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


def printparams():
    print("\nAngle PD Control Parameters")
    print("    Set point       {0}".format(ANGLE_TARGET))
    print("    Average Length  {0}".format(ANGLE_AVG_LENGTH))
    print("    Smoothing       {0:.2f}".format(ANGLE_SMOOTHING))
    print("    P Gain          {0:.2f}".format(ANGLE_KP))
    print("    D Gain          {0:.2f}".format(ANGLE_KD))
    print("    I Gain          {0:.2f}".format(ANGLE_KI))

    print("Position PD Control Parameters")
    print("    Set point       {0}".format(POSITION_TARGET))
    print("    Control Period  {0} ms".format(POSITION_CTRL_PERIOD_MS))
    print("    Smoothing       {0:.2f}".format(POSITION_SMOOTHING))
    print("    P Gain          {0:.2f}".format(POSITION_KP))
    print("    D Gain          {0:.2f}".format(POSITION_KD))


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


log = my_logger(__name__)

if ANGLE_CTRL_PERIOD_MS < CONTROL_PERIOD_MS or POSITION_CTRL_PERIOD_MS < CONTROL_PERIOD_MS:
    raise Exception("angle or position control periods too short compared to CONTROL_PERIOD_MS")

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

p = pendulum.Pendulum()

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
pygame.init()
joystick.init()
if joystick.get_count() == 1:
    stick = joystick.Joystick(0)
    stick.init()
    axisNum = stick.get_numaxes()
    buttonNum = stick.get_numbuttons()
    joystickExists = True
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

loadparams()
time.sleep(1)

p.set_angle_config(ANGLE_TARGET,
                   ANGLE_AVG_LENGTH,
                   ANGLE_SMOOTHING,
                   ANGLE_KP,
                   ANGLE_KD,
                   # ANGLE_KI
                   )

p.set_position_config(POSITION_TARGET,
                      POSITION_CTRL_PERIOD_MS,
                      POSITION_SMOOTHING,
                      POSITION_KP,
                      POSITION_KD)

################################################################################
# GET PARAMETERS
################################################################################

# Why is it getting parameters? To enable checking if they have been correctly written
# setPoint, avgLen, smoothing, KP, KD
(ANGLE_TARGET,
 ANGLE_AVG_LENGTH,
 ANGLE_SMOOTHING,
 ANGLE_KP,
 ANGLE_KD) = p.get_angle_config()

(POSITION_TARGET,
 POSITION_CTRL_PERIOD_MS,
 POSITION_SMOOTHING,
 POSITION_KP,
 POSITION_KD) = p.get_position_config()

################################################################################
# CONTROL LOOP (PC BASED)
################################################################################
printCount = 0

angleErrPrev = 0
angleCmd = 0
positionErrPrev = 0
positionCmd = 0

controlEnabled = False
manualMotorSetting = False

danceEnabled = False
danceAmpl = 500
dancePeriodS = 8

loggingEnabled = False

kbAvailable = True
try:
    kb = kbhit.KBHit()  # can only use in posix terminal; cannot use from spyder ipython console for example
except:
    kbAvailable = False

measurement = StepResponseMeasurement()

printparams()
help()
startTime = time.time()
lastTime = startTime
lastAngleControlTime = lastTime
lastPositionControlTime = lastTime
angleErr = 0
positionErr = 0  # for printing even if not controlling
angleErrSum = 0
p.stream_output(True)  # now start streaming state
actualMotorCmd = 0
csvfile = None
csvfilename = None
csvwriter = None

while True:

    # Adjust Parameters
    if kbAvailable & kb.kbhit():
        c = kb.getch()
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
                    # csvwriter.writerow([elapsedTime, deltaTime * 1000, angle, position, ANGLE_TARGET, angleErr, positionTargetNow, positionErr, angleCmd, positionCmd, motorCmd, actualMotorCmd, stickControl, stickPos, measurement])

                    csvwriter.writerow(['time'] + ['deltaTimeMs'] + ['angle'] + ['position'] + ['angleTarget'] + ['angleErr'] + ['positionTarget'] + ['positionErr'] + ['angleCmd'] + ['positionCmd'] + ['motorCmd'] + ['actualMotorCmd'] + ['stickControl'] + ['stickPos'] + ['measurement'])
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
        elif c == 'p':
            printparams()
        # Increase Target Angle
        elif c == '=':
            ANGLE_TARGET += 1
            print("\nIncreased target angle to {0}".format(ANGLE_TARGET))
        # Decrease Target Angle
        elif c == '-':
            ANGLE_TARGET -= 1
            print("\nDecreased target angle to {0}".format(ANGLE_TARGET))

        # Increase Target Position
        elif c == ']':
            POSITION_TARGET += 200
            print("\nIncreased target position to {0}".format(POSITION_TARGET))
        # Decrease Target Position
        elif c == '[':
            POSITION_TARGET -= 200
            print("\nDecreased target position to {0}".format(POSITION_TARGET))

        # Angle Gains
        elif c == 'w':
            ANGLE_KP = inc(ANGLE_KP)
            print("\nIncreased angle KP {0}".format(ANGLE_KP))
        elif c == 'q':
            ANGLE_KP = dec(ANGLE_KP)
            print("\nDecreased angle KP {0}".format(ANGLE_KP))
        elif c == 's':
            ANGLE_KD = inc(ANGLE_KD)
            print("\nIncreased angle KD {0}".format(ANGLE_KD))
        elif c == 'a':
            ANGLE_KD = dec(ANGLE_KD)
            print("\nDecreased angle KD {0}".format(ANGLE_KD))

        elif c == 'y':
            ANGLE_KI = inc(ANGLE_KI)
            print("\nIncreased angle KI {0}".format(ANGLE_KI))

        elif c == 't':
            ANGLE_KI = dec(ANGLE_KI)
            print("\nDecreased angle KI {0}".format(ANGLE_KI))


        elif c == 'x':
            ANGLE_SMOOTHING = dec(ANGLE_SMOOTHING)
            if ANGLE_SMOOTHING > 1:
                ANGLE_SMOOTHING = 1
            print("\nIncreased ANGLE_SMOOTHING {0}".format(ANGLE_SMOOTHING))
        elif c == 'z':
            ANGLE_SMOOTHING = inc(ANGLE_SMOOTHING)
            if ANGLE_SMOOTHING > 1:
                ANGLE_SMOOTHING = 1
            print("\nDecreased ANGLE_SMOOTHING {0}".format(ANGLE_SMOOTHING))

        # Position Gains
        elif c == 'r':
            POSITION_KP = inc(POSITION_KP)
            print("\nIncreased position KP {0}".format(POSITION_KP))
        elif c == 'e':
            POSITION_KP = dec(POSITION_KP)
            print("\nDecreased position KP {0}".format(POSITION_KP))
        elif c == 'f':
            POSITION_KD = inc(POSITION_KD)
            print("\nIncreased position KD {0}".format(POSITION_KD))
        elif c == 'd':
            POSITION_KD = dec(POSITION_KD)
            print("\nDecreased position KD {0}".format(POSITION_KD))
        elif c == 'v':
            POSITION_SMOOTHING = dec(POSITION_SMOOTHING)
            if POSITION_SMOOTHING > 1:
                POSITION_SMOOTHING = 1
            print("\nIncreased POSITION_SMOOTHING {0}".format(POSITION_SMOOTHING))
        elif c == 'c':
            POSITION_SMOOTHING = inc(POSITION_SMOOTHING)
            if POSITION_SMOOTHING > 1:
                POSITION_SMOOTHING = 1
            print("\nDecreased POSITION_SMOOTHING {0}".format(POSITION_SMOOTHING))
        elif c == 'S':
            saveparams()
        elif c == 'L':
            loadparams()
        elif c == 'm':  # toggle measurement
            if measurement.is_idle():
                measurement.start()
            else:
                measurement.stop()

        # Exit
        elif ord(c) == 27:  # ESC
            log.info("\nquitting....")
            break

    # This function will block at the rate of the control loop
    p.clear_read_buffer()  # if we don't clear read buffer, state output piles up in serial buffer #TODO
    (angle, position, command) = p.read_state()
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
    if timeNow - lastPositionControlTime >= POSITION_CTRL_PERIOD_MS * .001:
        lastPositionControlTime = timeNow
        positionErr = POSITION_SMOOTHING * (position - positionTargetNow) + (1.0 - POSITION_SMOOTHING) * positionErrPrev  # First order low-P=pass filter
        positionErrDiff = (positionErr - positionErrPrev) * diffFactor
        positionErrPrev = positionErr
        # Naive solution: if too positive (too right), move left (minus on positionCmd), 
        # but this does not produce correct control.
        # The correct strategy is that if cart is too positive (too right),
        # produce lean to the left by introducing a positive set point angle leaning slightly to left, 
        # i.e. more positve positionErr makes more positive effective ANGLE_TARGET
        # End result is that sign of positionCmd is flipped
        # Also, if positionErr is increasing more, then we want even more lean, so D sign is also positive
        positionCmd = +(POSITION_KP * positionErr + POSITION_KD * positionErrDiff)
        if abs(positionErr) < 1:
            positionCmd = 0

    if timeNow - lastAngleControlTime >= ANGLE_CTRL_PERIOD_MS * .001:
        lastAngleControlTime = timeNow
        angleErr = ANGLE_SMOOTHING * (angle - ANGLE_TARGET) + (1.0 - ANGLE_SMOOTHING) * angleErrPrev  # First order low-pass filter
        angleErrDiff = (angleErr - angleErrPrev) * diffFactor  # correct for actual sample interval; if interval is too long, reduce diff error
        angleErrSum = + angleErr
        angleErrPrev = angleErr
        angleCmd = -(ANGLE_KP * angleErr + ANGLE_KD * angleErrDiff + ANGLE_KI * angleErrSum)  # if too CCW (pos error), move cart left

    motorCmd = int(round(angleCmd + positionCmd))  # change to plus for original, check that when cart is displayed, the KP term for cart position leans cart the correct direction
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

    if abs(stickPos) > JOYSTICK_DEADZONE:
        stickControl = True
        actualMotorCmd = int(round(stickPos * JOYSTICK_SCALING))
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

    p.set_motor(-actualMotorCmd)

    if loggingEnabled:
        csvwriter.writerow([elapsedTime, deltaTime * 1000, angle, position, ANGLE_TARGET, angleErr, positionTargetNow, positionErr, angleCmd, positionCmd, motorCmd, actualMotorCmd, stickControl, stickPos, measurement])

        # Print output
    printCount += 1
    if printCount >= (PRINT_PERIOD_MS / CONTROL_PERIOD_MS):
        printCount = 0
        print("\r a {:+4d} aErr {:+6.1f} p {:+6d} pErr {:+6.1f} aCmd {:+6d} pCmd {:+6d} mCmd {:+6d} dt {:.3f}ms  stick {:.3f}:{} meas={}        \r"
              .format(int(angle),
                      angleErr,
                      int(position),
                      positionErr,
                      int(round(angleCmd)),
                      int(round(positionCmd)),
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
