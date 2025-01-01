import time
from adafruit_servokit import ServoKit

kit = ServoKit(channels=16)

kit.servo[8].angle = 180
kit.continuous_servo[9].throttle = 1
time.sleep(1)

kit.continuous_servo[9].throttle = -1
time.sleep(1)

kit.servo[8].angle = 0
kit.continuous_servo[9].throttle = 0
time.sleep(1)

kit.servo[8].angle = None

def stop_signal(kit, channel):
    pwm = kit._pca
    pwm.channels[channel].duty_cycle = 0 

stop_signal(kit, 9)
