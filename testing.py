import time
from adafruit_servokit import ServoKit

kit = ServoKit(channels=16)


LEG1F_CHANNEL = 0  
LEG1B_CHANNEL = 1 
LEG2F_CHANNEL = 8  
LEG2B_CHANNEL = 9  
LEG3F_CHANNEL = 2  
LEG3B_CHANNEL = 3  
LEG4F_CHANNEL = 10 
LEG4B_CHANNEL = 11 

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
    print(f"Testing {channel_name} on channel {channel} with angle {angle}")
    kit.servo[channel].angle = angle
    time.sleep(2)  # Wait for 2 seconds to observe the servo movement

if __name__ == "__main__":
    for name, channel in servo_channels.items():
        print(f"Testing {name} (channel {channel})")
        
        test_servo(name, channel, 90)

        test_servo(name, channel, 0)

        test_servo(name, channel, 180)

    print("Servo testing complete.")
