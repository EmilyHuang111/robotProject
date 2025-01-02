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

# Variables for angles
TOLeg1F, TOLeg1B, TOLeg2F, TOLeg2B = 90,90,90,90
TOLeg3F, TOLeg3B, TOLeg4F, TOLeg4B = 90,90,90,90

LALeg1F, LALeg1B, LALeg2F, LALeg2B = 90,90,90,90
LALeg3F, LALeg3B, LALeg4F, LALeg4B = 90,90,90,90

# Walking parameters
walkF = [
    [124, 146, 177, 150, 132, 115, 115],
    [94, 132, 178, 139, 112, 84, 84],
    [37, 112, 179, 139, 95, 42, 42],
    [22, 95, 150, 115, 78, 30, 30],
    [11, 78, 124, 92, 59, 13, 13],
    [13, 59, 92, 58, 36, 2, 2]
]
Fheight = 5
Bheight = 5
walkstep = 1
walkstep2 = 4
smoothdelay = 2  # Smooth movement delay (milliseconds)

def setup():
    # Initialize default positions
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

def walk_forward():
    global walkstep, walkstep2, TOLeg1F, TOLeg1B, TOLeg2F, TOLeg2B
    global TOLeg3F, TOLeg3B, TOLeg4F, TOLeg4B

    # Update step positions
    walkstep = walkstep + 1 if walkstep < 7 else 1
    walkstep2 = walkstep + 3 if walkstep + 3 <= 7 else walkstep + 3 - 7

    # Update leg angles for this step
    TOLeg1F = walkF[Fheight][walkstep - 1]
    TOLeg1B = walkF[Fheight][walkstep2 - 1]
    TOLeg4F = 180 - walkF[Bheight][walkstep - 1]
    TOLeg4B = 180 - walkF[Bheight][walkstep2 - 1]

    TOLeg2F = 180 - walkF[Fheight][walkstep2 - 1]
    TOLeg2B = 180 - walkF[Fheight][walkstep - 1]
    TOLeg3F = walkF[Bheight][walkstep - 1]
    TOLeg3B = walkF[Bheight][walkstep2 - 1]

    # Smooth transition for servo movement
    smooth_move()

def smooth_move():
    """Smoothly move servos to target positions."""
    global LALeg1F, LALeg1B, LALeg2F, LALeg2B
    global LALeg3F, LALeg3B, LALeg4F, LALeg4B

    # Calculate max steps for smooth movement
    maxstep = max(
        abs(LALeg1F - TOLeg1F),
        abs(LALeg1B - TOLeg1B),
        abs(LALeg2F - TOLeg2F),
        abs(LALeg2B - TOLeg2B),
        abs(LALeg3F - TOLeg3F),
        abs(LALeg3B - TOLeg3B),
        abs(LALeg4F - TOLeg4F),
        abs(LALeg4B - TOLeg4B)
    )

    # Ensure maxstep is an integer
    maxstep = int(maxstep)

    if maxstep > 0:
        stepLeg1F = (TOLeg1F - LALeg1F) / maxstep
        stepLeg1B = (TOLeg1B - LALeg1B) / maxstep
        stepLeg2F = (TOLeg2F - LALeg2F) / maxstep
        stepLeg2B = (TOLeg2B - LALeg2B) / maxstep
        stepLeg3F = (TOLeg3F - LALeg3F) / maxstep
        stepLeg3B = (TOLeg3B - LALeg3B) / maxstep
        stepLeg4F = (TOLeg4F - LALeg4F) / maxstep
        stepLeg4B = (TOLeg4B - LALeg4B) / maxstep

        for _ in range(maxstep):
            LALeg1F += stepLeg1F
            LALeg1B += stepLeg1B
            LALeg2F += stepLeg2F
            LALeg2B += stepLeg2B
            LALeg3F += stepLeg3F
            LALeg3B += stepLeg3B
            LALeg4F += stepLeg4F
            LALeg4B += stepLeg4B

            kit.servo[LEG1F_CHANNEL].angle = LALeg1F
            kit.servo[LEG1B_CHANNEL].angle = LALeg1B
            kit.servo[LEG2F_CHANNEL].angle = LALeg2F
            kit.servo[LEG2B_CHANNEL].angle = LALeg2B
            kit.servo[LEG3F_CHANNEL].angle = LALeg3F
            kit.servo[LEG3B_CHANNEL].angle = LALeg3B
            kit.servo[LEG4F_CHANNEL].angle = LALeg4F
            kit.servo[LEG4B_CHANNEL].angle = LALeg4B

            time.sleep(smoothdelay / 1000.0)  # Convert ms to seconds

def loop():
    # Continuous walking forward
    while True:
        walk_forward()
        time.sleep(0.5)  # Delay between steps

if __name__ == "__main__":
    setup()
    loop()
