# physical-cartpole
Work related to the Inverted Pendulum Hardware

The Inverted Pendulum is powered by a ST32F103C8T6 microcontroller. `FactoryFirmwareImage.bin` contains the fimrware image as shipped by the factory. It was pulled directly from the micro using a debugger.

The new firmware built during the workshop enables the following features:
* PD control of balance and position can be run on either the micro or on a PC.
* USB interface to a PC (send angle and position, receive motor velocity).
* Real-time tunable gains on the micro.
* Motor safety cut off - prevents the motor from melting if the cart hits a limit.

# Requirements to Build/Program the Micro
Jerome Jeanine found a way to program the Aliexpress ST micro using open source tools. See [his thesis MPPI on a physical cartpole](https://drive.google.com/file/d/1nSxp6x9yCe-Xci26lOERq7qKkFW_sD_q/view?usp=sharing). 


* KEIL MDK development environment.
* STLink debugger.

# Installation

Preferable way to install python packages:
`pip install -r requirements.txt` in a conda env or pip venv.

# Running
The main module is [control.py](Driver/control.py).

Parameters are distributed in [globals.py](Driver/globals.py) and [config_CPP.yml](Drivers/config_CPP.yml).

# Notes

## Firmware
The [firmware](Firmware) folder has the ST firmware.

## Modes of Operation

The pendulum microcontroller firmware has two modes of operation:

_(1) Self-Contained Mode_  
In this mode, the pendulum is controlled directly by the firmware using an onboard basic PD control scheme. A PC is not required at all for this mode. However you can use the PC to adjust the control parameters on-the-fly, as well as read out set points and other useful values generated by the on-board control algorithm in real time. If you want 'factory mode', just boot up the controller and set it running.

_(2) PC Control Mode_  
In this mode, the pendulum firmware runs as an interface to the physical hardware. Control is performed over USB by an algorithm running on another connected device (PC, FPGA, etc). The firmware outputs the current pendulum angle and cart position at regular intervals, and accepts motor speed and direction as input. The frequency of the control loop running on the PC is governed by the period set for outputting angle/position from the pendulum micro (currently hardcoded to 5 ms).

In either mode, when enabling control of the pendulum for the first time, the firmware will automatically run a calibration routine. During this routine, the cart will slowly move from left to right in order to determine the maximum limits of movement.

## Buttons

Two buttons are used by the firmware

_S1_  
This is the CPU's hard reset.

_S2_  
Used to switch between the 2 modes of operation in the pendulum firmware.

## LEDs

There is a blue LED (L2) that flashes periodically, fast or slow depending on which mode the firmware is operating in. Fast (200 ms period) -> Self-contained mode. Slow (1 s period) -> PC control mode.

## PC Interface

The interface to the pendulum firmware is through the `pendulum.py` module, which provides a series of high-level functions to configure and command various things on the microcontroller. `control.py` contains an example implementation of a PD controller running the PC and interfacing directly with the pendulum firmware.

## Parameters

Parameters that can be adjusted via the PC are listed below. Note that raw values are used for set points and control gains.
* Angle set point (~3110 is vertical).
* Angle average length (number of samples to average over when determining current angle).
* Angle smoothing factor (0 to 1.0 - used in 1st order low-pass filter).
* Angle control gains (P and D).
* Position set point (0: centre, <0: left, >0: right).
* Position control period (as a multiple of Angle control period - 5 ms).
* Position smoothing factor (0 to 1.0 - used in 1st order low-pass filter).
* Position control gains (P and D).

## Output

If enabled, the following data is streamed to the PC at regular 5 ms intervals:
* Current pendulum angle.
* Current cart position.
* Motor speed command calculated by onboard controller (0 when running in PC-control mode).
