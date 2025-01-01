import time
from adafruit_servokit import ServoKit

# Initialize ServoKit for 16 channels
kit = ServoKit(channels=16)

# Define servo and continuous servo channels for the quadropod
leg_servo_channels = [0, 1, 2, 3]  # Servos for lifting legs
foot_servo_channels = [8, 9, 10, 11]  # Continuous servos for moving feet

# Define walking gait positions
# Angles for lifting legs and moving feet
LIFT_ANGLE = 45
LOWER_ANGLE = 90
FOOT_FORWARD = 1
FOOT_BACKWARD = -1
STOP_THROTTLE = 0

# Define helper functions
def move_leg(channel, angle, delay=0.3):
    """Move the servo on the given channel to a specific angle."""
    kit.servo[channel].angle = angle
    time.sleep(delay)

def move_foot(channel, throttle, delay=0.3):
    """Move the continuous servo on the given channel with the specified throttle."""
    kit.continuous_servo[channel].throttle = throttle
    time.sleep(delay)

def stop_foot(channel):
    """Stop the continuous servo on the given channel."""
    kit.continuous_servo[channel].throttle = STOP_THROTTLE

# Walking sequence
def quadropod_walk(steps=5, step_delay=0.5):
    """Simulate a walking motion for the quadropod."""
    for _ in range(steps):
        # Step 1: Move diagonal legs (front-left and back-right)
        move_leg(0, LIFT_ANGLE)  # Lift front-left leg
        move_foot(8, FOOT_FORWARD)  # Move front-left foot forward
        move_leg(3, LIFT_ANGLE)  # Lift back-right leg
        move_foot(11, FOOT_BACKWARD)  # Move back-right foot backward
        time.sleep(step_delay)

        move_leg(0, LOWER_ANGLE)  # Lower front-left leg
        stop_foot(8)  # Stop front-left foot
        move_leg(3, LOWER_ANGLE)  # Lower back-right leg
        stop_foot(11)  # Stop back-right foot

        # Step 2: Move the other diagonal legs (front-right and back-left)
        move_leg(1, LIFT_ANGLE)  # Lift front-right leg
        move_foot(9, FOOT_FORWARD)  # Move front-right foot forward
        move_leg(2, LIFT_ANGLE)  # Lift back-left leg
        move_foot(10, FOOT_BACKWARD)  # Move back-left foot backward
        time.sleep(step_delay)

        move_leg(1, LOWER_ANGLE)  # Lower front-right leg
        stop_foot(9)  # Stop front-right foot
        move_leg(2, LOWER_ANGLE)  # Lower back-left leg
        stop_foot(10)  # Stop back-left foot

        # Small pause between steps for stability
        time.sleep(step_delay)

# Stop all servos and reset
def stop_all():
    """Stop all continuous servos and reset angles."""
    for channel in foot_servo_channels:
        stop_foot(channel)
    for channel in leg_servo_channels:
        kit.servo[channel].angle = None

# Run the walking sequence
try:
    quadropod_walk(steps=10, step_delay=0.7)
finally:
    stop_all()
