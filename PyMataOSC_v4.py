#!/usr/bin/python

from __future__ import division

import time
import os
import sys
import signal
from PyMata.pymata import PyMata as pm
import socket
import OSC
import json

board = None
config = None
pathname = None
filename = None
led_pin = 13  # overwritten by config.json
midi_min = 0  # overwritten by config.json
midi_max = 127  # overwritten by config.json


"""
Trigger the 32U4_reset function (equivalent to pressing 32U4 RESET button on the Yun)
"""
def reset_yun():
	def writeFile(value, file):
		with open(file, "w") as f:
			f.write(value)

	writeFile("18",   "/sys/class/gpio/export")             # make GPIO18 available
	writeFile("high", "/sys/class/gpio/gpio18/direction")   # set pin 18 as output
	writeFile("1",    "/sys/class/gpio/gpio18/value")       # Set pin 18 high
	writeFile("0",    "/sys/class/gpio/gpio18/value")       # Set pin 18 low
	writeFile("18",   "/sys/class/gpio/unexport")           # close out GPIO18


"""
Handle Ctrl + C interrupts to stop the program
"""
def signal_handler(sig, frame):
	global board
	global config
	global pathname
	global filename

	print("Exiting ...")
	if config is not None:
		with open(os.path.join(pathname, filename), 'w') as config_file:
			config = json.dump(config, config_file, sort_keys=True, indent=4)
	if board is not None:
		board.close()
	sys.exit(0)


"""
Map the input range to a desired output range. Similar to the Arduino map() function.
"""
def map_value(x, lower, upper, min, max):
	return min + ((x - lower) / (upper - lower)) * (max - min)


"""
Generic handler for debugging purposes
"""
def debug_handler(addr, tags, data, client_address):
	global board
	global config
	
	txt = "OSCMessage '%s' from %s: " % (addr, client_address)
	txt += str(data)
	print(txt)


"""
Handle incoming midi note messages. Note messages are used to tell servos to move to maximum up or down position.
"""
def note_handler(addr, tags, data, client_address):
	global board
	global config

	txt = "OSCMessage '%s' from %s: " % (addr, client_address)
	txt += str(data)
	print(txt)

	chan = data[0]
	note = data[1]
	velocity = data[2]

	# Tell the servo where to go upon receipt of corresponding midi note value
	if board is not None:
		for c in config["servo"]:
			if note == c["note"]:
				servo_pos = map_value(velocity, midi_min, midi_max, c["pos"]["home"], c["pos"]["max"])
				if c["reverse_servo_direction"] == True:  # reverse the direction of the input
					servo_pos = map_value(servo_pos, c["pos"]["abs_min"], c["pos"]["abs_max"], c["pos"]["abs_max"],
										  c["pos"]["abs_min"])  
				board.analog_write(c["pwm_pin"], int(servo_pos)) # move servo


"""
Handle incoming control change messages. CC messages are used to adjust maximum up or down position of servos and adjust speed of steppers.
"""
def cc_handler(addr, tags, data, client_address):
	global board
	global config

	txt = "OSCMessage '%s' from %s: " % (addr, client_address)
	txt += str(data)
	print(txt)

	chan = data[0]
	ccNum = data[1]
	ccVal = data[2]

	# Cycle through all servo/stepper control change messages
	if board is not None:
		for c in config["servo"]: # Cycle through all defined servos
			if ccNum == c["cc"]["home"]: # Check if CC val matches identifing servo minimum value
				if c["reverse_home_direction"] == True:
					ccVal = map_value(ccVal, midi_min, midi_max, midi_max,
									  midi_min)  # reverse the direction of the input
				servo_pos = map_value(ccVal, midi_min, midi_max, c["pos"]["abs_min"], c["pos"]["abs_max"])
				c["pos"]["home"] = int(servo_pos)
				if c["reverse_servo_direction"] == True:
					servo_pos = map_value(servo_pos, c["pos"]["abs_min"], c["pos"]["abs_max"], c["pos"]["abs_max"],
										  c["pos"]["abs_min"])  # reverse the direction of the input
				board.analog_write(c["pwm_pin"], int(servo_pos))
			elif ccNum == c["cc"]["max"]: # Check if CC val matches identifing servo maximum value
				if c["reverse_max_direction"] == True:
					ccVal = map_value(ccVal, midi_min, midi_max, midi_max, midi_min)
				servo_pos = map_value(ccVal, midi_min, midi_max, c["pos"]["home"], c["pos"]["abs_max"])
				c["pos"]["max"] = int(servo_pos)
				if c["reverse_servo_direction"] == True:
					servo_pos = map_value(servo_pos, c["pos"]["abs_min"], c["pos"]["abs_max"], c["pos"]["abs_max"],
										  c["pos"]["abs_min"])  # reverse the direction of the input
				board.analog_write(c["pwm_pin"], int(servo_pos))

		if ccNum == config["stepper"]["cc"]["speed"]: # Check if CC val matches identifing stepper value
			stepper_speed = map_value(ccVal, midi_min, midi_max, config["stepper"]["move"]["min_speed"],
									  config["stepper"]["move"]["max_speed"])
			board.timerthree_set_frequency(int(stepper_speed))
			board.timerthree_pwm(step_pin, duty_cycle)


"""
return IP address so code can be reused between arduinos
"""
def getIPAddress():
	so = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	so.connect((config["router_ip"], 0))  # Connect to the router's IP address
	address = so.getsockname()[0]
	return address


"""
return IP address of 2nd port so code can be reused between arduinos
"""
def getIPAddress2(address):
	"""
    Takes in str of ip address.
    If orig port is wifi port, return new address increased by 1.  This is the address of the ethernet port.
    If orig port is ethernet port, return new address decreased by 1.  This is the address of the ethernet port.
    """

	endNum = int(address[-3:]) # grab last three numbers of ip address
	if endNum % 2 == 0:
		endNumNew = endNum + 1
	else:
		endNumNew = endNum - 1
	addressNew = '192.168.1.' + str(endNumNew)
	return addressNew

"""
Main
"""
if __name__ == "__main__":

	# Read the JSON configuration file
	pathname = os.path.dirname(os.path.realpath(__file__))
	filename = "config.json"
	print("Reading JSON file ...")
	with open(os.path.join(pathname, filename)) as config_file:
		config = json.load(config_file)

	# handle Ctrl + C messages
	signal.signal(signal.SIGINT, signal_handler)

	# Connect to the Atmega32u4
	print("Initializing board ...")
	try:
		board = pm("/dev/ttyATH0")  # connect to the Atmega32u4 on ATH0
	except Exception as inst:
		print(type(inst))
		print(inst.args)
		print(inst)
		sys.exit(0)  # Exit the script upon failure

	# Set the pwm pins as servo control pins
	for c in config["servo"]:
		board.servo_config(c["pwm_pin"])

	# Initialize board settings 
	midi_min = config["midi_min"]
	midi_max = config["midi_max"]

	direction_pin = config["stepper"]["direction_pin"]
	stepper_direction = config["stepper"]["move"]["direction"]
	step_pin = config["stepper"]["step_pin"]
	duty_cycle = 511  # 50% duty cycle (range 0 - 1023)

	stepper_min_speed = config["stepper"]["move"]["min_speed"]
	stepper_max_speed = config["stepper"]["move"]["max_speed"]

	led_pin = config["led_pin"]

	board.set_pin_mode(direction_pin, board.OUTPUT, board.DIGITAL)
	board.digital_write(direction_pin, stepper_direction)

	board.timerthree_initialize()
	board.timerthree_set_frequency(0)
	board.timerthree_pwm(step_pin, duty_cycle)

	print("Initializing server ...")

	# find board IP
	address1 = getIPAddress()
	address2 = getIPAddress2(address1)
	
	# WLAN ports are DHCP reserved as even numbers starting at 100, corresponding LAN ports are WLAN + 1
	if int(address1[-3:]) % 2 == 0:
		addressWLAN = address1
		addressLAN = address2
	else:
		addressWLAN = address2
		addressLAN = address1

	# Port to use is specified in startup script.  Use WLAN unless LAN is given as additional argument 
	if len(sys.argv) > 1 and sys.argv[1] == 'LAN':
		s = OSC.OSCServer((addressLAN, config["port"]))  # port 2346
	else:
		s = OSC.OSCServer((addressWLAN, config["port"]))  # port 2346

	#s.addMsgHandler('/test', note_handler)  # call handler() for OSC messages received with the /test address
	s.addMsgHandler('/note', note_handler)
	s.addMsgHandler('/cc', cc_handler)
	s.addMsgHandler('list', debug_handler)


	board.set_pin_mode(led_pin, board.OUTPUT, board.DIGITAL)
	board.digital_write(led_pin, 1)  # Turn on the builtin LED

	# Serve forever
	print("Serving ...")
	s.timed_out = False
	while not s.timed_out:
		s.handle_request()
		# s.serve_forever()
