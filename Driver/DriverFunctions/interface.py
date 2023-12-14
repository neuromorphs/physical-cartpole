import serial
import struct
import time

PING_TIMEOUT            = 1.0       # Seconds
CALIBRATE_TIMEOUT       = 10.0      # Seconds
READ_STATE_TIMEOUT      = 1.0      # Seconds
SERIAL_SOF              = 0xAA
CMD_PING                = 0xC0
CMD_STREAM_ON           = 0xC1
CMD_CALIBRATE           = 0xC2
CMD_CONTROL_MODE        = 0xC3
CMD_SET_PID_CONFIG      = 0xC4
CMD_GET_PID_CONFIG      = 0xC5
CMD_SET_CONTROL_CONFIG  = 0xC6
CMD_GET_CONTROL_CONFIG  = 0xC7
CMD_SET_MOTOR           = 0xC8
CMD_FREE_TO_USE         = 0xC9
CMD_COLLECT_RAW_ANGLE   = 0xCA
CMD_STATE               = 0xCC

def get_serial_port(serial_port_number=''):
    import platform
    import subprocess
    serial_port_number = str(serial_port_number)
    SERIAL_PORT = None
    try:
        system = platform.system()
        if system == 'Darwin':  # Mac
            SERIAL_PORT = subprocess.check_output('ls -a /dev/tty.usbserial*', shell=True).decode("utf-8").strip()  # Probably '/dev/tty.usbserial-110'
        elif system == 'Linux':
            SERIAL_PORT = '/dev/ttyUSB' + serial_port_number  # You might need to change the USB number
        elif system == 'Windows':
            SERIAL_PORT = 'COM' + serial_port_number
        else:
            raise NotImplementedError('For system={} connection to serial port is not implemented.')
    except Exception as err:
        print(err)

    return SERIAL_PORT

class Interface:
    def __init__(self):
        self.device         = None
        self.msg            = []
        self.prevPktNum     = 1000
        self.start = None
        self.end = None

        self.encoderDirection = None

    def open(self, port, baud):
        self.port = port
        self.baud = baud
        self.device = serial.Serial(port, baudrate=baud, timeout=None)
        self.device.reset_input_buffer()

    def close(self):
        if self.device:
            self.control_mode(False)
            self.set_motor(0)
            time.sleep(2)
            self.device.close()
            self.device = None

    def clear_read_buffer(self):
        self.device.reset_input_buffer()
        self.prevPktNum = 1000

    def ping(self):
        msg = [SERIAL_SOF, CMD_PING, 4]
        msg.append(self._crc(msg))
        self.device.write(bytearray(msg))
        self.device.flush()
        self.prevPktNum = 1000
        return self._receive_reply(CMD_PING, 4, PING_TIMEOUT) == msg

    def stream_output(self, en):
        msg = [SERIAL_SOF, CMD_STREAM_ON, 5, en]
        msg.append(self._crc(msg))
        self.device.write(bytearray(msg))
        self.device.flush()
        self.clear_read_buffer()

    def calibrate(self):
        msg = [SERIAL_SOF, CMD_CALIBRATE, 4]
        msg.append(self._crc(msg))
        self.device.write(bytearray(msg))
        self.device.flush()

        self.clear_read_buffer()

        reply = self._receive_reply(CMD_CALIBRATE, 5, CALIBRATE_TIMEOUT)
        self.encoderDirection = struct.unpack('b', bytes(reply[3:4]))[0]

        return True

    def control_mode(self, en):
        msg = [SERIAL_SOF, CMD_CONTROL_MODE, 5, 1 if en else 0]
        msg.append(self._crc(msg))
        self.device.write(bytearray(msg))
        self.device.flush()

    def set_config_PID(self, setPoint, smoothing, position_KP, position_KI, position_KD, angle_KP, angle_KI, angle_KD):
        msg = [SERIAL_SOF, CMD_SET_PID_CONFIG, 34]
        msg += list(struct.pack('h', setPoint))
        msg += list(struct.pack('f', smoothing))
        
        msg += list(struct.pack('f', position_KP))
        msg += list(struct.pack('f', position_KI))
        msg += list(struct.pack('f', position_KD))
        
        msg += list(struct.pack('f', angle_KP))
        msg += list(struct.pack('f', angle_KI))
        msg += list(struct.pack('f', angle_KD))

        msg.append(self._crc(msg))
        self.device.write(bytearray(msg))
        self.device.flush()

    def get_config_PID(self):
        msg = [SERIAL_SOF, CMD_GET_PID_CONFIG, 4]
        msg.append(self._crc(msg))
        self.device.write(bytearray(msg))
        self.device.flush()
        reply = self._receive_reply(CMD_GET_PID_CONFIG, 34)
        (setPoint, smoothing, position_KP, position_KI, position_KD, angle_KP, angle_KI, angle_KD) = struct.unpack('h7f', bytes(reply[3:33]))
        return setPoint, smoothing, position_KP, position_KI, position_KD, angle_KP, angle_KI, angle_KD

    def set_config_control(self, controlLoopPeriodMs, controlSync, controlLatencyUs, setPoint, avgLen):
        msg = [SERIAL_SOF, CMD_SET_CONTROL_CONFIG, 15]
        msg += list(struct.pack('H', controlLoopPeriodMs))
        msg += list(struct.pack('?', controlSync))
        msg += list(struct.pack('i', controlLatencyUs))
        msg += list(struct.pack('h', setPoint))
        msg += list(struct.pack('H', avgLen))
        msg.append(self._crc(msg))
        self.device.write(bytearray(msg))
        self.device.flush()

    def get_config_control(self):
        msg = [SERIAL_SOF, CMD_GET_CONTROL_CONFIG, 4]
        msg.append(self._crc(msg))
        self.device.write(bytearray(msg))
        self.device.flush()
        reply = self._receive_reply(CMD_GET_CONTROL_CONFIG, 15)
        (controlLoopPeriodMs, controlSync, controlLatencyUs, setPoint, avgLen) = struct.unpack('H?ihH', bytes(reply[3:14]))
        return controlLoopPeriodMs, controlSync, controlLatencyUs, setPoint, avgLen

    def set_motor(self, speed):
        msg  = [SERIAL_SOF, CMD_SET_MOTOR, 6, speed & 0xFF, (speed >> 8) & 0xFF]
        msg.append(self._crc(msg))
        self.device.write(bytearray(msg))
        self.device.flush()

    def collect_raw_angle(self, lenght=100, interval_us=100):
        msg = [SERIAL_SOF, CMD_COLLECT_RAW_ANGLE, 8,  lenght % 256, lenght // 256, interval_us % 256, interval_us // 256]
        msg.append(self._crc(msg))
        self.device.write(bytearray(msg))
        self.device.flush()
        reply = self._receive_reply(CMD_COLLECT_RAW_ANGLE, 4 + 2*lenght, crc=False, timeout=100)
        return struct.unpack(str(lenght)+'H', bytes(reply[3:3+2*lenght]))

    def read_state(self):
        self.clear_read_buffer()
        message_length = 27
        reply = self._receive_reply(CMD_STATE, message_length, READ_STATE_TIMEOUT)

        (angle, angleD, position, positionD, command, invalid_steps, time_difference, sent, latency, latency_violation) = struct.unpack('=5hB2I2H', bytes(reply[3:message_length-1]))

        return angle, angleD, position, positionD, command, invalid_steps, time_difference/1e6, sent/1e6, latency/1e5, latency_violation

    def _receive_reply(self, cmd, cmdLen, timeout=None, crc=True):
        self.device.timeout = timeout
        self.start = False

        while True:
            c = self.device.read()
            # Timeout: reopen device, start stream, reset msg and try again
            if len(c) == 0:
                print('\nReconnecting.')
                self.device.close()
                self.device = serial.Serial(self.port, baudrate=self.baud, timeout=timeout)
                self.clear_read_buffer()
                time.sleep(1)
                self.stream_output(True)
                self.msg = []
                self.start = False
            else:
                self.msg.append(ord(c))
                if self.start == False:
                    self.start = time.time()

            while len(self.msg) >= cmdLen:
                # print('I am looping! Hurra!')
                # Message must start with SOF character
                if self.msg[0] != SERIAL_SOF:
                    #print('\nMissed SERIAL_SOF')
                    del self.msg[0]
                    continue

                # Check command
                if self.msg[1] != cmd:
                    print('\nMissed CMD.')
                    del self.msg[0]
                    continue

                # Check message packet length
                if self.msg[2] != cmdLen and cmdLen < 256:
                    print('\nWrong Packet Length.')
                    del self.msg[0]
                    continue

                # Verify integrity of message
                if crc and self.msg[cmdLen-1] != self._crc(self.msg[:cmdLen-1]):
                    print('\nCRC Failed.')
                    del self.msg[0]
                    continue

                self.device.timeout = None
                reply = self.msg[:cmdLen]
                del self.msg[:cmdLen]
                return reply

    def _crc(self, msg):
        crc8 = 0x00

        for i in range(len(msg)):
            val = msg[i]
            for b in range(8):
                sum = (crc8 ^ val) & 0x01
                crc8 >>= 1
                if sum > 0:
                    crc8 ^= 0x8C
                val >>= 1

        return crc8