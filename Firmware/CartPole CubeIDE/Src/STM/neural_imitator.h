#ifndef __NEURAL_IMITATOR_H_
#define __NEURAL_IMITATOR_H_

void Neural_Imitator_Init();
void Neural_Imitator_Evaluate(unsigned char * network_input_buffer, unsigned char * network_output_buffer);
void Neural_Imitator_ReleaseResources();

float neural_imitator_cartpole_step(float angle, float angleD, float angle_cos, float angle_sin, float position, float positionD, float target_equilibrium, float target_position, float time);


#endif /*__NEURAL_IMITATOR_H_*/
