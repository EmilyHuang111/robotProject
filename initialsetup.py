import time
from adafruit_servokit import ServoKit

# Initialize ServoKit with 16 channels
kit = ServoKit(channels=16)

# Define servo channels
LEG1B_CHANNEL = 0  
LEG1F_CHANNEL = 1 
LEG2B_CHANNEL = 8  
LEG2F_CHANNEL = 9  
LEG3B_CHANNEL = 2 
LEG3F_CHANNEL = 3  
LEG4F_CHANNEL = 10 
LEG4B_CHANNEL = 11 

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
