/*
 * hardware_pid.c
 *
 *  Created on: 19 Dec 2023
 *      Author: marcinpaluch
 */

#include "hardware_bridge.h"
#include "communication_with_PC.h"
#include "hardware_pid.h"
#include <stdio.h>
#include <math.h>

float ANGLE_KP      =          18.0f;
float ANGLE_KI      =          38.0f	;
float ANGLE_KD      =          4.0f;

float POSITION_KP   =          22.0f;
float POSITION_KI   =          1.0f;
float POSITION_KD   =          12.0f;

float POSITION_ONLY_KP   =     4.0f;
float POSITION_ONLY_KI   =     0.0f;
float POSITION_ONLY_KD   =     0.0f;

float sensitivity_pP_gain = 1.0;
float sensitivity_pI_gain = 1.0;
float sensitivity_pD_gain = 0.01;

float sensitivity_aP_gain = 1.0;
float sensitivity_aI_gain = 1.0;
float sensitivity_aD_gain = 0.01;

// Error and previous error variables
float position_error = 0.0;

// Last time variable
float time_last = -1.0;

PIDState pid_state_angle = {0.0, 0.0};
PIDState pid_state_position = {0.0, 0.0};
PIDState pid_position_state_position = {0.0, 0.0};

// PID step function
float pid_step(float angle, float angleD, float position, float positionD, float target_position, float time) {

	float time_difference;
    float Q_position, Q_angle, Q;
    // Time difference calculation
    if (time_last < 0.0) {
        time_difference = 0.0;
    } else {
        time_difference = time - time_last;
    }

    if (time_difference > 0.1) {
        time_difference = 0.0;
    }

    time_last = time;

    // Position PID
    position_error = position - target_position;
    float I_clip = 1.0/POSITION_KI;
    Q_position = pid_core(&pid_state_position, position_error, time_difference, POSITION_KP, POSITION_KI, POSITION_KD, sensitivity_pP_gain, sensitivity_pI_gain, sensitivity_pD_gain, I_clip);

    // Angle PID
    I_clip = 1.0/ANGLE_KI;
    Q_angle = pid_core(&pid_state_angle, angle, time_difference, -ANGLE_KP, -ANGLE_KI, -ANGLE_KD, sensitivity_aP_gain, sensitivity_aI_gain, sensitivity_aD_gain, I_clip);

    Q = Q_angle + Q_position;

    return Q;
}


float pid_position_step(float angle, float angleD, float position, float positionD, float target_position, float time) {

	float time_difference;
    float Q;
    // Time difference calculation
    if (time_last < 0.0) {
        time_difference = 0.0;
    } else {
        time_difference = time - time_last;
    }

    if (time_difference > 0.1) {
        time_difference = 0.0;
    }

    time_last = time;

    // Position PID
    position_error = position - target_position;

    float I_clip = 0.0005;
    Q = pid_core(&pid_position_state_position, position_error, time_difference, -POSITION_ONLY_KP, -POSITION_ONLY_KI, -POSITION_ONLY_KD, sensitivity_pP_gain, sensitivity_pI_gain, sensitivity_pD_gain, I_clip);

    return Q;
}


float pid_core(PIDState *pid_state, float error, float time_difference,
		float KP, float KI, float KD,
		float sensitivity_P_gain, float sensitivity_I_gain, float sensitivity_D_gain,
		float I_clip
)
{
    float error_diff = 0.0;

    if (time_difference > 0.0001) {
        error_diff = (error - pid_state->error_previous) / time_difference;
    } else {
        error_diff = 0.0;
    }

    pid_state->error_previous = error;

	pid_state->error_integral += error * time_difference;
	// Clipping; dividing with KI gain prevents error_integral becoming big and destabilizing the system
	if (KI != 0) {
	    pid_state->error_integral = fmax(fmin(pid_state->error_integral, fabs(I_clip)), -fabs(I_clip));
	} else {
	    pid_state->error_integral = 0; // or handle the zero case as needed
	}

    float aP = KP * error * sensitivity_P_gain;
    float aI = KI * pid_state->error_integral * sensitivity_I_gain;
    float aD = KD * error_diff * sensitivity_D_gain;

    float control_signal = aP + aI + aD;

    return control_signal;
}


void cmd_SetPIDConfig(const unsigned char * config)
{
	disable_irq();

	POSITION_KP         = *((float          *)&config[ 0]);
	POSITION_KI         = *((float          *)&config[ 4]);
	POSITION_KD         = *((float          *)&config[8]);

	ANGLE_KP            = *((float          *)&config[ 12]);
	ANGLE_KI            = *((float          *)&config[ 16]);
	ANGLE_KD            = *((float          *)&config[20]);

	enable_irq();
}


void cmd_GetPIDConfig(unsigned char * txBuffer)
{
	prepare_message_to_PC_config_PID(txBuffer, POSITION_KP, POSITION_KI, POSITION_KD, ANGLE_KP, ANGLE_KI, ANGLE_KD);

	disable_irq();
	Message_SendToPC(txBuffer, 34);
	enable_irq();
}

