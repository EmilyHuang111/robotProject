from flask import Flask, render_template_string
from threading import Thread
import time
from adafruit_servokit import ServoKit

# Initialize Flask app
app = Flask(__name__)

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
DEFAULT_FORWARD_ANGLE = 90
DEFAULT_BACKWARD_ANGLE = 90

# Movement angles
FORWARD_ANGLE = 60
BACKWARD_ANGLE = 120

# Movement control flag
movement_flag = {'forward': False}

# Setup the default positions
def setup():
    print("Setting all servos to default positions...")
    set_all_servos(DEFAULT_FORWARD_ANGLE)

def set_all_servos(angle):
    kit.servo[LEG1F_CHANNEL].angle = angle
    kit.servo[LEG1B_CHANNEL].angle = angle
    kit.servo[LEG2F_CHANNEL].angle = angle
    kit.servo[LEG2B_CHANNEL].angle = angle
    kit.servo[LEG3F_CHANNEL].angle = angle
    kit.servo[LEG3B_CHANNEL].angle = angle
    kit.servo[LEG4F_CHANNEL].angle = angle
    kit.servo[LEG4B_CHANNEL].angle = angle
    time.sleep(1)

# Movement angles (adjusted for stronger motion)
FORWARD_ANGLE = 45  # Increase forward reach
BACKWARD_ANGLE = 135  # Increase backward reach

# Leg movement functions (updated timing for stronger movement)
def move_leg_forward(forward_channel, backward_channel):
    kit.servo[forward_channel].angle = FORWARD_ANGLE
    kit.servo[backward_channel].angle = DEFAULT_BACKWARD_ANGLE
    time.sleep(0.3)  # Adjust timing for servo to fully execute motion

def move_leg_backward(forward_channel, backward_channel):
    kit.servo[forward_channel].angle = DEFAULT_FORWARD_ANGLE
    kit.servo[backward_channel].angle = BACKWARD_ANGLE
    time.sleep(0.3)  # Adjust timing for servo to fully execute motion

# Gait functions (optimized for stronger forward movement)
def walk_forward():
    print("Walking forward...")
    while movement_flag['forward']:
        # Move legs in pairs: diagonal pairs move together
        move_leg_forward(LEG1F_CHANNEL, LEG1B_CHANNEL)  # Front left forward
        move_leg_forward(LEG4F_CHANNEL, LEG4B_CHANNEL)  # Back right forward
        time.sleep(0.2)  # Brief pause for stability

        move_leg_backward(LEG2F_CHANNEL, LEG2B_CHANNEL)  # Front right backward
        move_leg_backward(LEG3F_CHANNEL, LEG3B_CHANNEL)  # Back left backward
        time.sleep(0.2)  # Brief pause for stability

        # Return legs to default positions to complete the step
        move_leg_backward(LEG1F_CHANNEL, LEG1B_CHANNEL)
        move_leg_backward(LEG4F_CHANNEL, LEG4B_CHANNEL)
        time.sleep(0.2)

        move_leg_forward(LEG2F_CHANNEL, LEG2B_CHANNEL)
        move_leg_forward(LEG3F_CHANNEL, LEG3B_CHANNEL)
        time.sleep(0.2)

        print("Step complete.")


# Flask endpoints
@app.route('/')
def index():
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Robot Movement Control</title>
        <style>
            body { text-align: center; font-family: Arial, sans-serif; }
            button { font-size: 20px; margin: 10px; padding: 15px; }
            .stop-btn { background-color: red; color: white; }
        </style>
    </head>
    <body>
        <h1>Robot Movement Control</h1>
        <button onclick="sendCommand('forward')">Move Forward</button><br>
        <button onclick="sendCommand('left')">Turn Left</button>
        <button onclick="sendCommand('right')">Turn Right</button><br>
        <button onclick="sendCommand('backward')">Move Backward</button><br>
        <button class="stop-btn" onclick="sendCommand('stop')">Stop</button>
        <script>
            function sendCommand(command) {
                fetch('/' + command);
            }
        </script>
    </body>
    </html>
    ''')

@app.route('/forward')
def forward():
    movement_flag['forward'] = True
    Thread(target=walk_forward).start()
    return "Moving forward!"

@app.route('/stop')
def stop():
    movement_flag['forward'] = False
    set_all_servos(DEFAULT_FORWARD_ANGLE)
    return "Stopping all movements!"

if __name__ == "__main__":
    setup()
    app.run(host='0.0.0.0', port=5000)
