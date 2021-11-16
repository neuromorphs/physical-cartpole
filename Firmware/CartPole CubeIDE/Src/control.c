#include "angle.h"
#include "encoder.h"
#include "motor.h"
#include "led.h"
#include "usart.h"
#include "control.h"
#include "timer.h"

#include <stdlib.h>

// Command set
#define SERIAL_MAX_PKT_LENGTH		32
#define SERIAL_SOF					0xAA
#define CMD_PING					0xC0
#define CMD_STREAM_ON               0xC1
#define CMD_CALIBRATE				0xC2
#define CMD_CONTROL_MODE			0xC3
#define CMD_SET_ANGLE_CONFIG		0xC4
#define CMD_GET_ANGLE_CONFIG		0xC5
#define CMD_SET_POSITION_CONFIG		0xC6
#define CMD_GET_POSITION_CONFIG		0xC7
#define CMD_SET_MOTOR				0xC8
#define CMD_STATE					0xCC

bool            streamEnable        = false;
short  			angle_setPoint		= CONTROL_ANGLE_SET_POINT;
unsigned short	angle_averageLen	= CONTROL_ANGLE_AVERAGE_LEN;
float 			angle_smoothing		= CONTROL_ANGLE_SMOOTHING;
float 			angle_KP			= CONTROL_ANGLE_KP;
float 			angle_KI			= CONTROL_ANGLE_KI;
float 			angle_KD			= CONTROL_ANGLE_KD;
short  			position_setPoint	= CONTROL_POSITION_SET_POINT;
unsigned short	position_ctrlPeriod	= (CONTROL_POSITION_PERIOD_MS / CONTROL_LOOP_PERIOD_MS);
float 			position_smoothing	= CONTROL_POSITION_SMOOTHING;
float 			position_KP			= CONTROL_POSITION_KP;
float 			position_KI			= CONTROL_POSITION_KI;
float 			position_KD			= CONTROL_POSITION_KD;

volatile bool 	controlEnabled;
int 			controlLatencyUs = 0;		// used to simulate Latency
bool			controlLatencyEnable = false;
int	 			controlLatencyTimestampUs = 0;
int 			controlCommand = 0;
bool			controlSynch = true;		// apply motor command at next loop
bool            isCalibrated = true;
unsigned short  ledPeriod;
int  			angleSamples[64];
int  			angleSamplesTimestamp[64];
unsigned short 	angleSampIndex 	= 0;
short			angleErrPrev;
short			positionErrPrev;
unsigned short 	positionPeriodCnt;
int				positionCentre;
int				positionLimitLeft;
int				positionLimitRight;
int				encoderDirection = 1;
unsigned int	timeSent = 0, timeReceived = 0;
float 			angle_I = 0, position_I = 0;

static unsigned char rxBuffer[SERIAL_MAX_PKT_LENGTH];
static unsigned char txBuffer[32];

unsigned char 	crc(const unsigned char * message, unsigned int len);
bool 			crcIsValid(const unsigned char * buff, unsigned int len, unsigned char crcVal);
void 			cmd_Ping(const unsigned char * buff, unsigned int len);
void            cmd_StreamOutput(bool en);
void            cmd_Calibrate(const unsigned char * buff, unsigned int len);
void 			cmd_ControlMode(bool en);
void 			cmd_SetAngleConfig(const unsigned char * config);
void 			cmd_GetAngleConfig(void);
void 			cmd_SetPositionConfig(const unsigned char * config);
void 			cmd_GetPositionConfig(void);
void 			cmd_SetMotor(int motorCmd);

void CONTROL_Init(void)
{
	controlEnabled		= false;
    isCalibrated        = false;
    ledPeriod           = 500/CONTROL_LOOP_PERIOD_MS;
	angleErrPrev		= 0;
	positionErrPrev		= 0;
	positionPeriodCnt 	= position_ctrlPeriod - 1;
    positionCentre      = (short)ENCODER_Read(); // assume starting position is near center
    positionLimitLeft   = positionCentre + 2400;
    positionLimitRight  = positionCentre - 2400; // guess defaults based on 7000-8000 counts at limits
}

void CONTROL_ToggleState(void)
{
	cmd_ControlMode(!controlEnabled);
}

const int ADC_RANGE = 4096;

int wrapLocal(int angle) {
    if (angle >= ADC_RANGE/2)
		return angle - ADC_RANGE;
	if (angle <= -ADC_RANGE/2)
		return angle + ADC_RANGE;
	else
		return angle;
}
int unwrapLocal(int previous, int current) {
	int diff = current-previous;

	if (diff > 2000)
		return current - ADC_RANGE;
	if (diff < -2000)
		return current + ADC_RANGE;
	else
		return current;
}

int wrap(int current) {
	if(current > 0)
		return current - ADC_RANGE * (current / ADC_RANGE);
	else
		return current + ADC_RANGE * (current / ADC_RANGE + 1);
}

int unwrap(int previous, int current) {
    int diff = previous-current;
	if (diff>0)
    	return current + ADC_RANGE * (((2 * diff) / ADC_RANGE + 1) / 2);
	else
    	return current + ADC_RANGE * (((2 * diff) / ADC_RANGE - 1) / 2);
}

// Called from Timer interrupt every CONTROL_LOOP_PERIOD_MS ms
void CONTROL_Loop(void)
{
	static unsigned short 	ledPeriodCnt	= 0;
	static bool				ledState 		= false;
    static int				angleCmd        = 0;
    static int              positionCmd     = 0;
    static unsigned char	packetCnt       = 0;
    static unsigned int     stopCnt         = 0;
	static unsigned char	buffer[30];
	static int 				prevAngle = 0;
	static int 				angleD = 0;
	static unsigned char    frozen = 0;
	int 					angle, angleErr;
	short 					positionRaw, position, positionErr;
	float 					angleErrDiff;
	float 					positionErrDiff;
	int   					command;
	int angle_mean = 0;

	// sum/min/max of buffer
	int angle_sum = 0;
	int angle_min = angleSamples[0];
	int angle_max = angleSamples[0];
	for (int i = 0; i < angle_averageLen; i++) {
		int curr = angleSamples[(angleSampIndex + i) % angle_averageLen];

		angle_min = (curr < angle_min ? curr : angle_min);
		angle_max = (curr > angle_max ? curr : angle_max);
		angle_sum += curr;
	}

	// Averaging & Median Filter: exclude min/max values from average
	if (angle_averageLen > 2)
		angle_mean = (short)((angle_sum - angle_min - angle_max) / (angle_averageLen-2));
	else
		angle_mean = angle_sum / angle_averageLen;

	// Detect invalid steps
	#define MAX_ADC_STEP 40
	#define MAX_INVALID_STEPS 2

	int invalid_step = 0;
	for (int i = 0; i < angle_averageLen; i++) {
		// start at oldest value (since angleSampIndex is not yet overwritten)
		int curr = angleSamples[(angleSampIndex + i) % angle_averageLen];
		//int dt = angleSamplesTimestamp[] - angleSamplesTimestamp

		int prev = angleSamples[(angleSampIndex + i + angle_averageLen - 1) % angle_averageLen];
		// previous value for oldest value not existing
		if(i != 0 && abs(curr-prev) > MAX_ADC_STEP)
			invalid_step++;
	}

	// Anomaly Detection: discard buffer if too many invalid steps (allow 2 for 1 outlier/popcorn noise)
	if (invalid_step <= MAX_INVALID_STEPS) {
		angle = angle_mean;
		angleD = wrapLocal(angle - prevAngle) / (1 + frozen);
		prevAngle = angle;
		frozen = 0;
	}
	else {
		angle = prevAngle;
		frozen ++;
	}

	positionRaw = positionCentre + encoderDirection * ((short)ENCODER_Read() - positionCentre);
    position    = (positionRaw - positionCentre);

	// Microcontroller Control Routine
	if (controlEnabled)	{
		// Angle PD control
        angleErr = angle - angle_setPoint;
        angleErrDiff = angleD;
		angleCmd	 = -(angle_KP*angleErr + angle_KD*angleErrDiff);

		// Position PD control
		if (++positionPeriodCnt >= position_ctrlPeriod) {
			positionPeriodCnt = 0;
			positionErr = position - position_setPoint;
			if(position_smoothing < 1.0)
				positionErrDiff = (position_smoothing*positionErr) + ((1.0 - position_smoothing)*positionErrPrev);
			else
				positionErrDiff = positionErr - positionErrPrev;
			positionErrPrev	= positionErr;
			position_I += positionErr;
			positionCmd		= -(position_KP*positionErr + position_KD*positionErrDiff);
		}

		// Limit the motor speed
		// This will reduce the numerical range of command from an int to a short
		command = angleCmd + positionCmd; // was minus before postionCmd, but error seemed wrong sign
		if      (command >  CONTROL_MOTOR_MAX_SPEED) command =  CONTROL_MOTOR_MAX_SPEED;
		else if (command < -CONTROL_MOTOR_MAX_SPEED) command = -CONTROL_MOTOR_MAX_SPEED;

        // Disable motor if falls hard on either limit
        if ((command < 0) && (positionRaw < (positionLimitLeft + 20))) {
            command = 0;
            stopCnt++;
        } else if ((command > 0) && (positionRaw > (positionLimitRight - 20))) {
            command = 0;
            stopCnt++;
        } else {
            stopCnt = 0;
        }

        // Quit control if pendulum has continously been at the end for 500 ms
        if (stopCnt == 500/CONTROL_LOOP_PERIOD_MS) {
            cmd_ControlMode(false);
            MOTOR_SetSpeed(0);
            stopCnt = 0;
        } else {
        	if(controlLatencyUs) {
        		controlLatencyTimestampUs = TIMER1_getSystemTime_Us() + controlLatencyUs;
        		controlCommand = command;
        		controlLatencyEnable = true;
        	}
        	else
        		MOTOR_SetSpeed(-command);
        }
	}
	else
	{
		if(controlSynch) {
            MOTOR_SetSpeed(controlCommand);
		} else {
			command = 0;
	        stopCnt = 0;
		}
	}

	// Send latest state to the PC
    if (streamEnable)
    {
        //float latency = timeSent - timeReceived;
        buffer[ 0] = SERIAL_SOF;
        buffer[ 1] = CMD_STATE;
        buffer[ 2] = 20;
        buffer[ 3] = packetCnt++;
        *((short *)&buffer[4]) = angle;
        *((short *)&buffer[6]) = angleD;
        *((short *)&buffer[8]) = position;
        *((unsigned char *)&buffer[10]) = frozen;
        *((unsigned int *)&buffer[11]) = timeSent;
        *((unsigned int *)&buffer[15]) = timeReceived;

        buffer[19] = crc(buffer, 19);
        USART_SendBuffer(buffer, 20);
        timeSent = TIMER1_getSystemTime_Us();
    }

	// Flash LED every second (500 ms on, 500 ms off)
	ledPeriodCnt++;
	if (ledPeriodCnt >= ledPeriod)
	{
		ledPeriodCnt	= 0;
		ledState 		= !ledState;
		Led_Enable(ledState);
	}
}

void CONTROL_BackgroundTask(void)
{
	static unsigned int 	rxCnt			= 0;
	unsigned int			i;
	unsigned int 			idx;
	unsigned int			pktLen;
	short					motorCmd;
	static int				lastRead = 0;

	///////////////////////////////////////////////////
	// Collect samples of angular displacement
	///////////////////////////////////////////////////
	unsigned long now = TIMER1_getSystemTime_Us();

	// int-overflow after 1h
	if (now < lastRead) {
		lastRead = now;
	}
	// read every 100us
	else if (now > lastRead + CONTROL_ANGLE_MEASUREMENT_INTERVAL_US) {
		// conversion takes 18us
		angleSamples[angleSampIndex] = ANGLE_Read();

		angleSamplesTimestamp[angleSampIndex] = now;
		angleSampIndex = (++angleSampIndex >= angle_averageLen ? 0 : angleSampIndex);

		lastRead = now;
	}

	///////////////////////////////////////////////////
	// Apoply Delayed Control Command
	///////////////////////////////////////////////////
	if (controlLatencyEnable && controlLatencyTimestampUs >= TIMER1_getSystemTime_Us()) {
		MOTOR_SetSpeed(controlCommand);
		controlLatencyEnable = false;
	}

	///////////////////////////////////////////////////
	// Process Commands from PC
	///////////////////////////////////////////////////
	if (USART_ReceiveAsync(&rxBuffer[rxCnt]))
		rxCnt++;

	// Buffer should have at least 4 bytes
	if (rxCnt >= 4)
	{
		idx = 0;

		// Message must start with SOF character
    	if (rxBuffer[0] == SERIAL_SOF)
		{
			// Packet length must be less than the max
			pktLen = rxBuffer[2];
			if ((pktLen <= SERIAL_MAX_PKT_LENGTH) && (pktLen >= 4))
			{
				// Receive entire message packet (including CRC)
				if (rxCnt >= pktLen)
				{
					// Validate message integrity
					if (crcIsValid(rxBuffer, pktLen-1, rxBuffer[pktLen-1]))
					{
						// Process message
						switch (rxBuffer[1])
						{
							case CMD_PING:
							{
								cmd_Ping(rxBuffer, pktLen);
								break;
							}

                            case CMD_STREAM_ON:
                            {
                                if (pktLen == 5)
								{
									cmd_StreamOutput(rxBuffer[3] != 0);
								}
                                break;
                            }

							case CMD_CALIBRATE:
							{
								if (pktLen == 4)
								{
									cmd_Calibrate(rxBuffer, pktLen);
								}
								break;
							}

							case CMD_CONTROL_MODE:
							{
								if (pktLen == 5)
								{
									cmd_ControlMode(rxBuffer[3] != 0);
								}
								break;
							}

							case CMD_SET_ANGLE_CONFIG:
							{
								if (pktLen == 29)
								{
									cmd_SetAngleConfig(&rxBuffer[3]);
								}
								break;
							}

							case CMD_GET_ANGLE_CONFIG:
							{
								if (pktLen == 4)
								{
									cmd_GetAngleConfig();
								}
								break;
							}

							case CMD_SET_POSITION_CONFIG:
							{
								if (pktLen == 20)
								{
									cmd_SetPositionConfig(&rxBuffer[3]);
								}
								break;
							}

							case CMD_GET_POSITION_CONFIG:
							{
								if (pktLen == 4)
								{
									cmd_GetPositionConfig();
								}
								break;
							}

							case CMD_SET_MOTOR:
							{
								if (pktLen == 6)
								{
									timeReceived = TIMER1_getSystemTime_Us();
									motorCmd = (((short)rxBuffer[4])<<8) | ((short)rxBuffer[3]);
									if(controlSynch)
										controlCommand = motorCmd;
									else
										cmd_SetMotor(motorCmd);
								}
								break;
							}

							default:
							{
								break;
							}
						}

						idx = pktLen;   // Trim message
					}
					else
					{
						idx = 1;  // Trim SOF and start looking for the next packet
					}
				}
			}
			else
			{
				idx = 1;  // Trim SOF and start looking for the next packet
			}
		}
		else
		{
			idx = 1;  // Trim SOF and start looking for the next packet
		}

		// Shift buffer until first character is SOF
		if (idx != 0)
		{
			for (; idx < rxCnt; idx++)
			{
				if (rxBuffer[idx] == SERIAL_SOF)
				{
					break;
				}
			}

			rxCnt -= idx;
			for (i = 0; i < rxCnt; i++)
			{
				rxBuffer[i] = rxBuffer[idx+i];
			}
		}
	}
}

void cmd_Ping(const unsigned char * buff, unsigned int len)
{
	__disable_irq();
	USART_SendBuffer(buff, len);
	__enable_irq();
}

void cmd_StreamOutput(bool en)
{
	__disable_irq();
	streamEnable = en;
	__enable_irq();
}

void cmd_Calibrate(const unsigned char * buff, unsigned int len)
{
	#define SPEED 3000
	int pos;
	int diff;
	float fDiff;

	__disable_irq();
	MOTOR_Stop();
	Led_Enable(true);

	// Get left limit
	SYS_DelayMS(100);
	positionLimitLeft = ENCODER_Read();
	MOTOR_SetSpeed(-SPEED);

	do {
		SYS_DelayMS(100);
		pos  = ENCODER_Read();
		diff = pos - positionLimitLeft;
		positionLimitLeft = pos;

		// if we don't move enough, must have hit limit
	} while(abs(diff) > 8);

	MOTOR_Stop();
	Led_Enable(false);

	// Get right limit
	SYS_DelayMS(100);
	positionLimitRight = ENCODER_Read();
	MOTOR_SetSpeed(SPEED);

	do {
		SYS_DelayMS(100);
		pos  = ENCODER_Read();
		diff = pos - positionLimitRight;
		positionLimitRight = pos;

		// if we don't move enough, must have hit limit
	} while(abs(diff) > 8);

	MOTOR_Stop();

	// Move pendulum to the centre (roughly)
	Led_Enable(true);
	SYS_DelayMS(200);
	// invert reading for original motor
	if (positionLimitRight < positionLimitLeft) {
		int temp = positionLimitRight;
		positionLimitRight = positionLimitLeft;
		positionLimitLeft = temp;
		encoderDirection = -1;
	} else
		encoderDirection = 1;
	positionCentre = (positionLimitRight + positionLimitLeft) / 2;			// average limits

	// Slower to get back to middle
	MOTOR_SetSpeed(-SPEED/2);
	do {
		fDiff = 2.0 * abs(ENCODER_Read() - positionCentre) / abs(positionLimitRight - positionLimitLeft);
		// Slow Down even more to get more accurately to the middle
		if(fDiff < 1e-1) {
			MOTOR_SetSpeed(-SPEED/4);
		}
	} while(fDiff > 5e-4);
	MOTOR_Stop();

	SYS_DelayMS(100);
	USART_SendBuffer(buff, len);
	isCalibrated = true;
	Led_Enable(false);
	__enable_irq();
}

void cmd_ControlMode(bool en)
{
    if(en && !isCalibrated) {
    	cmd_Calibrate(0, 0);
    }
    __disable_irq();
	if (en && !controlEnabled)
	{
		angleErrPrev		= 0;
		positionErrPrev		= 0;
		positionPeriodCnt 	= position_ctrlPeriod - 1;
        ledPeriod           = 100/CONTROL_LOOP_PERIOD_MS;
	}
	else if (!en && controlEnabled)
	{
		MOTOR_Stop();
        ledPeriod           = 500/CONTROL_LOOP_PERIOD_MS;
	}

	controlEnabled = en;
	__enable_irq();
}

void cmd_SetAngleConfig(const unsigned char * config)
{
	__disable_irq();
    angle_setPoint      = *((short          *)&config[ 0]);
    angle_averageLen    = *((unsigned short *)&config[ 2]);
    angle_smoothing     = *((float          *)&config[ 4]);
    angle_KP            = *((float          *)&config[ 8]);
    angle_KI            = *((float          *)&config[12]);
    angle_KD            = *((float          *)&config[16]);
    controlLatencyUs    = *((int            *)&config[20]);
    controlSynch		= *((bool	        *)&config[24]);
	angleErrPrev		= 0;
	__enable_irq();
}

void cmd_GetAngleConfig(void)
{
	txBuffer[ 0] = SERIAL_SOF;
	txBuffer[ 1] = CMD_GET_ANGLE_CONFIG;
	txBuffer[ 2] = 28;
    *((short          *)&txBuffer[ 3]) = angle_setPoint;
	*((unsigned short *)&txBuffer[ 5]) = angle_averageLen;
    *((float          *)&txBuffer[ 7]) = angle_smoothing;
    *((float          *)&txBuffer[11]) = angle_KP;
    *((float          *)&txBuffer[15]) = angle_KI;
    *((float          *)&txBuffer[19]) = angle_KD;
    *((float          *)&txBuffer[23]) = controlLatencyUs;
    *((bool           *)&txBuffer[27]) = controlSynch;
	txBuffer[28] = crc(txBuffer, 28);

	__disable_irq();
	USART_SendBuffer(txBuffer, 29);
	__enable_irq();
}

void cmd_SetPositionConfig(const unsigned char * config)
{
	__disable_irq();
    position_setPoint   = *((short          *)&config[ 0]);
    position_ctrlPeriod = *((unsigned short *)&config[ 2]);
    position_smoothing  = *((float          *)&config[ 4]);
    position_KP         = *((float          *)&config[ 8]);
    position_KD         = *((float          *)&config[12]);
	positionErrPrev		= 0;
	position_ctrlPeriod	= position_ctrlPeriod / CONTROL_LOOP_PERIOD_MS;
	positionPeriodCnt	= position_ctrlPeriod - 1;
	__enable_irq();
}

void cmd_GetPositionConfig(void)
{
	unsigned short temp;

	temp = position_ctrlPeriod * CONTROL_LOOP_PERIOD_MS;

	txBuffer[ 0] = SERIAL_SOF;
	txBuffer[ 1] = CMD_GET_POSITION_CONFIG;
	txBuffer[ 2] = 20;
    *((short          *)&txBuffer[ 3]) = position_setPoint;
	*((unsigned short *)&txBuffer[ 5]) = temp;
    *((float          *)&txBuffer[ 7]) = position_smoothing;
    *((float          *)&txBuffer[11]) = position_KP;
    *((float          *)&txBuffer[15]) = position_KD;
	txBuffer[19] = crc(txBuffer, 19);

	__disable_irq();
	USART_SendBuffer(txBuffer, 20);
	__enable_irq();
}

void cmd_SetMotor(int speed)
{
		int position;

	//	MOTOR_SetSpeed(speed);
	// Only command the motor if the on-board control routine is disabled
	if (!controlEnabled){
				position = ENCODER_Read();

				// Disable motor if falls hard on either limit
				if ((speed < 0) && (position < (positionLimitLeft + 10)))
				{
						MOTOR_Stop();
				}
				else if ((speed > 0) && (position > (positionLimitRight - 10)))
				{
						MOTOR_Stop();
				}
		else{
				MOTOR_SetSpeed(speed);
		}
	}
}

unsigned char crc(const unsigned char * buff, unsigned int len)
{
    unsigned char crc8 = 0x00;
	unsigned char val;
	unsigned char sum;
	unsigned int  i;

    while (len--)
    {
        val = *buff++;
        for (i = 0; i < 8; i++)
        {
            sum = (crc8 ^ val) & 0x01;
            crc8 >>= 1;
            if (sum > 0)
            {
                crc8 ^= 0x8C;
            }
            val >>= 1;
        }
    }
    return crc8;
}

bool crcIsValid(const unsigned char * buff, unsigned int len, unsigned char crcVal)
{
    return crcVal == crc(buff, len);
}
