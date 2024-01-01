#ifndef BUTTONS_AND_SWITCHES_H
#define BUTTONS_AND_SWITCHES_H

#include "xgpiops.h"
#include "xparameters.h"
#include "xscugic.h"
#include "xil_exception.h"

extern XScuGic XScuGicInstance; // The Instance of the Interrupt Controller Driver

#define PS_BTN_4            50 // Button GPIO
#define PS_BTN_5            51 // Button GPIO

#define GPIO_DEVICE_ID      XPAR_XGPIOPS_0_DEVICE_ID
#define GPIO_INTERRUPT_ID   XPAR_XGPIOPS_0_INTR

typedef void (*ActionHandler)(void);
ActionHandler btn4_action_handler;
ActionHandler btn5_action_handler;

void Buttons_And_Switches_Init(void);
void Button_SetAction(unsigned int key, ActionHandler action);

#endif // BUTTONS_AND_SWITCHES_H

