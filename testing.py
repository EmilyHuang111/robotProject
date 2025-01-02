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

# List of all channels and their names for reference
servo_channels = {
    "LEG1F_CHANNEL": LEG1F_CHANNEL,
    "LEG1B_CHANNEL": LEG1B_CHANNEL,
    "LEG2F_CHANNEL": LEG2F_CHANNEL,
    "LEG2B_CHANNEL": LEG2B_CHANNEL,
    "LEG3F_CHANNEL": LEG3F_CHANNEL,
    "LEG3B_CHANNEL": LEG3B_CHANNEL,
    "LEG4F_CHANNEL": LEG4F_CHANNEL,
    "LEG4B_CHANNEL": LEG4B_CHANNEL
}

def test_servo(channel_name, channel, angle):
    """Test a single servo by setting it to a specific angle."""
    print(f"Testing {channel_name} on channel {channel} with angle {angle}")
    kit.servo[channel].angle = angle
    time.sleep(2)  # Wait for 2 seconds to observe the servo movement

if __name__ == "__main__":
    # Iterate through each servo channel
    for name, channel in servo_channels.items():
        print(f"Testing {name} (channel {channel})")
        
        # Test at 90° (neutral position)
        test_servo(name, channel, 90)
        
        # Test at 0° (minimum position)
        test_servo(name, channel, 0)
        
        # Test at 180° (maximum position)
        test_servo(name, channel, 180)

    print("Servo testing complete.")
