import time
from adafruit_servokit import ServoKit

# Initialize ServoKit with 16 channels
kit = ServoKit(channels=16)

# Define servo channels
LEG1F_CHANNEL = 0  # Front Left Forward
LEG1B_CHANNEL = 1  # Front Left Backward
LEG2F_CHANNEL = 8  # Front Right Forward
LEG2B_CHANNEL = 9  # Front Right Backward
LEG3F_CHANNEL = 2  # Back Left Forward
LEG3B_CHANNEL = 3  # Back Left Backward
LEG4F_CHANNEL = 10 # Back Right Forward
LEG4B_CHANNEL = 11 # Back Right Backward

def setup():
    """Initialize default servo positions."""
    set_all_servos(90)

def set_all_servos(angle):
    """Set all servos to the same angle."""
    kit.servo[LEG1F_CHANNEL].angle = angle
    kit.servo[LEG1B_CHANNEL].angle = angle
    kit.servo[LEG2F_CHANNEL].angle = angle
    kit.servo[LEG2B_CHANNEL].angle = angle
    kit.servo[LEG3F_CHANNEL].angle = angle
    kit.servo[LEG3B_CHANNEL].angle = angle
    kit.servo[LEG4F_CHANNEL].angle = angle
    kit.servo[LEG4B_CHANNEL].angle = angle

if __name__ == "__main__":
    setup()
