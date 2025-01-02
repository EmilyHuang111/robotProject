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

# Default positions
DEFAULT_FORWARD_ANGLE = 90  # Neutral position (adjust if needed)
DEFAULT_BACKWARD_ANGLE = 90  # Neutral position (adjust if needed)

# Forward and backward movement angles
FORWARD_ANGLE = 30  # Angle to move leg forward (within 0-180)
BACKWARD_ANGLE = 150  # Angle to move leg backward (within 0-180)

def setup():
    """Initialize default servo positions."""
    set_all_servos(DEFAULT_FORWARD_ANGLE)

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

def move_leg_forward(forward_channel, backward_channel):
    """Move a single leg forward."""
    kit.servo[forward_channel].angle = FORWARD_ANGLE
    kit.servo[backward_channel].angle = DEFAULT_BACKWARD_ANGLE
    time.sleep(0.1)  # Adjust delay for smoother movement

def move_leg_backward(forward_channel, backward_channel):
    """Move a single leg backward."""
    kit.servo[forward_channel].angle = DEFAULT_FORWARD_ANGLE
    kit.servo[backward_channel].angle = BACKWARD_ANGLE
    time.sleep(0.1)

def walk_forward():
    """Make the robot walk forward with a simple gait."""
    # Step 1: Move Front Left and Back Right forward
    move_leg_forward(LEG1F_CHANNEL, LEG1B_CHANNEL)
    move_leg_forward(LEG4F_CHANNEL, LEG4B_CHANNEL)

    # Step 2: Move Front Right and Back Left backward
    move_leg_backward(LEG2F_CHANNEL, LEG2B_CHANNEL)
    move_leg_backward(LEG3F_CHANNEL, LEG3B_CHANNEL)

    # Step 3: Move Front Left and Back Right backward
    move_leg_backward(LEG1F_CHANNEL, LEG1B_CHANNEL)
    move_leg_backward(LEG4F_CHANNEL, LEG4B_CHANNEL)

    # Step 4: Move Front Right and Back Left forward
    move_leg_forward(LEG2F_CHANNEL, LEG2B_CHANNEL)
    move_leg_forward(LEG3F_CHANNEL, LEG3B_CHANNEL)

if __name__ == "__main__":
    setup()
    print("Starting to walk forward...")
    while True:
        walk_forward()
