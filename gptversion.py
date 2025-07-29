from flask import Flask, render_template_string, request, jsonify
from threading import Thread
import time
import os
import re

from adafruit_servokit import ServoKit

# ===================== (NEW) Language model + TTS =====================
# OpenAI client (uses the modern SDK)
try:
    from openai import OpenAI
    _openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
except Exception as e:
    _openai_client = None
    print("OpenAI client not available:", e)

import subprocess

from gtts import gTTS
import tempfile

def speak_async(text: str):
    if not text:
        return
    def _run():
        try:
            tts = gTTS(text=text, lang='en')
            with tempfile.NamedTemporaryFile(delete=True, suffix='.mp3') as fp:
                tts.save(fp.name)
                subprocess.run(['mpg123', fp.name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print("TTS error:", e)
    Thread(target=_run, daemon=True).start()


def lm_reply(user_text: str) -> str:
    """
    Send user_text to the language model and return assistant's reply.
    Uses a short system prompt so the model stays concise and respectful.
    """
    if not _openai_client:
        return "Language model is not configured. Please set OPENAI_API_KEY."
    try:
        resp = _openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system",
                 "content": "You are a helpful, concise assistant controlling a small quadruped robot. Keep replies short."},
                {"role": "user", "content": user_text},
            ],
            temperature=0.4,
            max_tokens=300,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return f"Error contacting language model: {e}"

# ===================== Flask & ServoKit =====================
app = Flask(__name__)
kit = ServoKit(channels=16)

# ===================== Channel Mapping (your wiring) =====================
# Original labels from your code
LEG1F_CHANNEL = 0   # Front Left - HIP (forward/back swing)
LEG1B_CHANNEL = 1   # Front Left - KNEE (lift/lower)
LEG2F_CHANNEL = 8   # Front Right - HIP
LEG2B_CHANNEL = 9   # Front Right - KNEE
LEG3F_CHANNEL = 2   # Back Left - HIP
LEG3B_CHANNEL = 3   # Back Left - KNEE
LEG4F_CHANNEL = 10  # Back Right - HIP
LEG4B_CHANNEL = 11  # Back Right - KNEE

# Semantic names
LF_HIP, LF_KNEE = LEG1F_CHANNEL, LEG1B_CHANNEL  # Left Front
RF_HIP, RF_KNEE = LEG2F_CHANNEL, LEG2B_CHANNEL  # Right Front
LR_HIP, LR_KNEE = LEG3F_CHANNEL, LEG3B_CHANNEL  # Left Rear
RR_HIP, RR_KNEE = LEG4F_CHANNEL, LEG4B_CHANNEL  # Right Rear

ALL_HIPS  = [LF_HIP, RF_HIP, LR_HIP, RR_HIP]
ALL_KNEES = [LF_KNEE, RF_KNEE, LR_KNEE, RR_KNEE]

# Diagonal pairs
DIAG_A = [(LF_HIP, LF_KNEE), (RR_HIP, RR_KNEE)]  # LF + RR
DIAG_B = [(RF_HIP, RF_KNEE), (LR_HIP, LR_KNEE)]  # RF + LR

# ===================== Tuning (angles & inversion) =====================
INVERT_HIP  = {LF_HIP: False, RF_HIP: True,  LR_HIP: False, RR_HIP: True}
INVERT_KNEE = {LF_KNEE: False, RF_KNEE: True, LR_KNEE: False, RR_KNEE: True}

HIP_NEUTRAL = 90
HIP_FWD     = 65     # forward (protraction) — only while the foot is lifted
HIP_BACK    = 145    # back (retraction) — when foot is planted to push body forward

KNEE_DOWN   = 124    # planted; increase if foot doesn't press floor
KNEE_UP     = 86     # lifted; decrease if lift is too small

PRESS_DELTA   = +8
LIGHTEN_DELTA = -6

RAMP_STEP   = 3
RAMP_DELAY  = 0.01
DWELL       = 0.12
TROT_DWELL  = 0.12

# ===================== Movement flags =====================
movement_flag = {
    'forward':   False,
    'backward':  False,
    'left':      False,
    'right':     False,
    'trot':      False,
    'trot_sync': False,
}

# ===================== Low-level helpers (with inversion) =====================
def _apply_invert(ch, angle, invert_map):
    return 180 - angle if invert_map.get(ch, False) else angle

def _current_angle(ch, default_raw, invert_map):
    a = kit.servo[ch].angle
    return int(a) if a is not None else _apply_invert(ch, default_raw, invert_map)

def _ramp_to(ch, target_raw, invert_map, step=RAMP_STEP, delay=RAMP_DELAY):
    target = _apply_invert(ch, target_raw, invert_map)
    cur = _current_angle(ch, target_raw, invert_map)
    if cur == target:
        kit.servo[ch].angle = target
        return
    sgn = 1 if target > cur else -1
    for a in range(cur, target, sgn * step):
        kit.servo[ch].angle = a
        time.sleep(delay)
    kit.servo[ch].angle = target

def _ramp_sync(ch_list, target_raw_list, invert_map, step=RAMP_STEP, delay=RAMP_DELAY):
    curs = []
    targs = []
    for ch, t_raw in zip(ch_list, target_raw_list):
        t = _apply_invert(ch, t_raw, invert_map)
        c = _current_angle(ch, t_raw, invert_map)
        curs.append(c)
        targs.append(t)

    deltas = [abs(t - c) for c, t in zip(curs, targs)]
    max_steps = 0 if not deltas else max((d + step - 1) // step for d in deltas)

    for _ in range(max_steps):
        for idx, ch in enumerate(ch_list):
            c = curs[idx]; t = targs[idx]
            if c == t: 
                continue
            sgn = 1 if t > c else -1
            move = min(step, abs(t - c))
            c_new = c + sgn * move
            kit.servo[ch].angle = c_new
            curs[idx] = c_new
        time.sleep(delay)

    for ch, t in zip(ch_list, targs):
        kit.servo[ch].angle = t

def set_hip(ch, angle):  _ramp_to(ch, angle, INVERT_HIP)
def set_knee(ch, angle): _ramp_to(ch, angle, INVERT_KNEE)

def set_hip_pair(pair, angle):
    chs = [pair[0][0], pair[1][0]]
    tgs = [angle, angle]
    _ramp_sync(chs, tgs, INVERT_HIP)

def set_knee_pair(pair, angle):
    chs = [pair[0][1], pair[1][1]]
    tgs = [angle, angle]
    _ramp_sync(chs, tgs, INVERT_KNEE)

def set_hips_all_sync(angle):
    _ramp_sync(ALL_HIPS, [angle]*4, INVERT_HIP)

def set_knees_all_sync(angle):
    _ramp_sync(ALL_KNEES, [angle]*4, INVERT_KNEE)

# ===================== Posture helpers =====================
def plant_all():
    set_knees_all_sync(KNEE_DOWN)

def hips_all(angle=HIP_NEUTRAL):
    set_hips_all_sync(angle)

def setup():
    print("Setup: knees down, hips neutral...")
    plant_all()
    hips_all(HIP_NEUTRAL)
    time.sleep(0.2)

# ===================== Single‑leg primitives =====================
def leg_lift(hip, knee):           set_knee(knee, KNEE_UP)
def leg_lower(hip, knee):          set_knee(knee, KNEE_DOWN)
def leg_swing_forward(hip, knee):  set_hip(hip, HIP_FWD)
def leg_swing_backward(hip, knee): set_hip(hip, HIP_BACK)
def leg_push_back(hip, knee):      set_hip(hip, HIP_BACK)
def leg_push_forward(hip, knee):   set_hip(hip, HIP_FWD)

# ===================== Weight shift =====================
def weight_shift_for_pair(swing_pair):
    stance_pair = DIAG_B if swing_pair == DIAG_A else DIAG_A
    set_knee_pair(stance_pair, KNEE_DOWN + PRESS_DELTA)
    set_knee_pair(swing_pair,   KNEE_DOWN + LIGHTEN_DELTA)
    time.sleep(TROT_DWELL)

def clear_weight_shift():
    set_knees_all_sync(KNEE_DOWN)

# ===================== Diagnostics =====================
@app.route('/diag/neutral')
def diag_neutral():
    setup()
    return "Neutral: hips 90, knees down."

@app.route('/diag/lf_push')
def diag_lf_push():
    leg_lower(LF_HIP, LF_KNEE); time.sleep(0.2)
    leg_push_back(LF_HIP, LF_KNEE); time.sleep(0.6)
    set_hip(LF_HIP, HIP_FWD); time.sleep(0.4)
    set_hip(LF_HIP, HIP_NEUTRAL)
    return "LF push test complete."

@app.route('/diag/lf_step')
def diag_lf_step():
    weight_shift_for_pair(DIAG_B)
    leg_lift(LF_HIP, LF_KNEE);               time.sleep(DWELL)
    leg_swing_forward(LF_HIP, LF_KNEE);      time.sleep(DWELL + 0.1)
    leg_lower(LF_HIP, LF_KNEE);              time.sleep(DWELL)
    clear_weight_shift()
    leg_push_back(LF_HIP, LF_KNEE);          time.sleep(DWELL + 0.2)
    set_hip(LF_HIP, HIP_NEUTRAL)
    return "LF weighted step done."

# ===================== Crawl gait =====================
def setup_pose_bias_back():
    plant_all()
    hips_all(HIP_NEUTRAL)
    _ramp_sync(ALL_HIPS, [ (HIP_NEUTRAL + HIP_BACK)//2 ]*4, INVERT_HIP)
    time.sleep(0.2)

def swing_forward_sequence(hip, knee):
    weight_shift_for_pair(DIAG_B if (hip, knee) in DIAG_A else DIAG_A)
    leg_lift(hip, knee);   time.sleep(DWELL)
    leg_swing_forward(hip, knee); time.sleep(DWELL)
    leg_lower(hip, knee);  time.sleep(DWELL)
    clear_weight_shift()

def swing_backward_sequence(hip, knee):
    weight_shift_for_pair(DIAG_B if (hip, knee) in DIAG_A else DIAG_A)
    leg_lift(hip, knee);   time.sleep(DWELL)
    leg_swing_backward(hip, knee); time.sleep(DWELL)
    leg_lower(hip, knee);  time.sleep(DWELL)
    clear_weight_shift()

def stance_push_all_back():
    set_hips_all_sync(HIP_BACK); time.sleep(DWELL)

def stance_push_all_forward():
    set_hips_all_sync(HIP_FWD);  time.sleep(DWELL)

def crawl_step_forward(order):
    for hip, knee in order:
        swing_forward_sequence(hip, knee)
        stance_push_all_back()

def crawl_step_backward(order):
    for hip, knee in order:
        swing_backward_sequence(hip, knee)
        stance_push_all_forward()

def walk_forward_loop():
    print("BD‑inspired crawl (forward)")
    setup_pose_bias_back()
    order = [(LF_HIP, LF_KNEE), (RR_HIP, RR_KNEE), (RF_HIP, RF_KNEE), (LR_HIP, LR_KNEE)]
    while movement_flag['forward']:
        crawl_step_forward(order)
    setup(); print("Forward stopped.")

def walk_backward_loop():
    print("BD‑inspired crawl (backward)")
    setup_pose_bias_back()
    order = [(LF_HIP, LF_KNEE), (RR_HIP, RR_KNEE), (RF_HIP, RF_KNEE), (LR_HIP, LR_KNEE)]
    while movement_flag['backward']:
        crawl_step_backward(order)
    setup(); print("Backward stopped.")

# ===================== STRICTLY-SYNCHRONIZED TROT =====================
def trot_step_forward_sync(stance_pair, swing_pair):
    weight_shift_for_pair(swing_pair)
    set_knee_pair(swing_pair, KNEE_UP); time.sleep(TROT_DWELL)
    set_hip_pair(swing_pair, HIP_FWD);  time.sleep(TROT_DWELL)
    set_knee_pair(swing_pair, KNEE_DOWN); time.sleep(TROT_DWELL)
    clear_weight_shift()
    set_hips_all_sync(HIP_BACK); time.sleep(TROT_DWELL)

def trot_forward_loop_sync():
    print("Diagonal‑pair LOCKSTEP trot (forward): A supports while B swings, then alternate.")
    setup_pose_bias_back()
    stance, swing = DIAG_A, DIAG_B
    while movement_flag['trot_sync']:
        trot_step_forward_sync(stance, swing)
        stance, swing = swing, stance
    setup(); print("Trot (sync) stopped.")

# (Legacy non-locked trot)
def trot_step_forward(stance_pair, swing_pair):
    weight_shift_for_pair(swing_pair)
    set_knee_pair(swing_pair, KNEE_UP); time.sleep(TROT_DWELL)
    _ramp_sync([swing_pair[0][0], swing_pair[1][0]], [HIP_FWD, HIP_FWD], INVERT_HIP)
    time.sleep(TROT_DWELL)
    set_knee_pair(swing_pair, KNEE_DOWN); time.sleep(TROT_DWELL)
    clear_weight_shift()
    set_hips_all_sync(HIP_BACK); time.sleep(TROT_DWELL)

def trot_forward_loop():
    print("Diagonal‑pair trot (forward)")
    setup_pose_bias_back()
    stance, swing = DIAG_A, DIAG_B
    while movement_flag['trot']:
        trot_step_forward(stance, swing)
        stance, swing = swing, stance
    setup(); print("Trot stopped.")

# ===================== Simple in‑place turn =====================
def turn_left_loop():
    print("Turning left (in place)...")
    plant_all(); hips_all(HIP_NEUTRAL); time.sleep(0.2)
    while movement_flag['left']:
        _ramp_sync([LF_HIP, LR_HIP, RF_HIP, RR_HIP],
                   [HIP_BACK, HIP_BACK, HIP_FWD, HIP_FWD], INVERT_HIP)
        time.sleep(DWELL)
        set_knee(RF_KNEE, KNEE_UP); time.sleep(DWELL*0.6); set_knee(RF_KNEE, KNEE_DOWN)
        set_knee(LR_KNEE, KNEE_UP); time.sleep(DWELL*0.6); set_knee(LR_KNEE, KNEE_DOWN)
        hips_all(HIP_NEUTRAL); time.sleep(DWELL*0.5)
    setup(); print("Left turn stopped.")

def turn_right_loop():
    print("Turning right (in place)...")
    plant_all(); hips_all(HIP_NEUTRAL); time.sleep(0.2)
    while movement_flag['right']:
        _ramp_sync([RF_HIP, RR_HIP, LF_HIP, LR_HIP],
                   [HIP_BACK, HIP_BACK, HIP_FWD, HIP_FWD], INVERT_HIP)
        time.sleep(DWELL)
        set_knee(LF_KNEE, KNEE_UP); time.sleep(DWELL*0.6); set_knee(LF_KNEE, KNEE_DOWN)
        set_knee(RR_KNEE, KNEE_UP); time.sleep(DWELL*0.6); set_knee(RR_KNEE, KNEE_DOWN)
        hips_all(HIP_NEUTRAL); time.sleep(DWELL*0.5)
    setup(); print("Right turn stopped.")

# ===================== Flask UI (UPDATED) =====================
HTML = '''
<!DOCTYPE html>
<html>
<head>
  <title>Robot Movement & Chat</title>
  <style>
    body { text-align:center; font-family:Arial, sans-serif; max-width:900px; margin:auto; }
    button { font-size:20px; margin:8px; padding:14px 18px; }
    .stop-btn { background-color:#c00; color:#fff; }
    .row { display:flex; flex-wrap:wrap; justify-content:center; gap:8px; }
    #chatbox { width:95%; height:260px; margin:16px auto; padding:10px; border:1px solid #ccc; overflow:auto; text-align:left; }
    #user, #bot { margin:6px 0; }
    #user { color:#333; }
    #bot { color:#0a4; }
    input[type="text"] { width:75%; padding:12px; font-size:18px; }
  </style>
</head>
<body>
  <h1>Robot Movement Control</h1>
  <div class="row">
    <button onclick="send('forward')">Move Forward (Crawl)</button>
    <button onclick="send('backward')">Move Backward (Crawl)</button>
  </div>
  <div class="row">
    <button onclick="send('left')">Turn Left</button>
    <button onclick="send('right')">Turn Right</button>
  </div>
  <div class="row">
    <button onclick="send('trot_sync')">Trot (Locked Sync)</button>
    <button onclick="send('trot_sync_step')">Single Trot Step (Locked)</button>
  </div>
  <div class="row">
    <button onclick="send('trot')">Trot (Legacy)</button>
    <button onclick="send('trot_step')">Single Trot Step (Legacy)</button>
  </div>
  <div class="row">
    <button onclick="send('step')">Single Forward Step (Crawl)</button>
    <button class="stop-btn" onclick="send('stop')">Stop</button>
  </div>

  <h2>Chat with the Robot</h2>
  <div id="chatbox"></div>
  <div>
    <input id="msg" type="text" placeholder="Ask a question or type commands like: robot forward, robot trot sync, robot stop" />
    <button onclick="ask()">Send</button>
  </div>

  <h3>Diagnostics</h3>
  <div class="row">
    <button onclick="send('diag/neutral')">Neutral Pose</button>
    <button onclick="send('diag/lf_push')">LF Push Test</button>
    <button onclick="send('diag/lf_step')">LF Weighted Step</button>
  </div>

  <script>
    function send(path){ fetch('/' + path); }

    function append(role, text){
      const box = document.getElementById('chatbox');
      const div = document.createElement('div');
      div.id = role;
      div.textContent = (role === 'user' ? 'You: ' : 'Bot: ') + text;
      box.appendChild(div);
      box.scrollTop = box.scrollHeight;
    }

    async function ask(){
      const input = document.getElementById('msg');
      const text = input.value.trim();
      if(!text) return;
      append('user', text);
      input.value = '';

      const resp = await fetch('/ask', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({text})});
      const data = await resp.json();
      if (data.robot_action) append('bot', '[Executing] ' + data.robot_action);
      append('bot', data.reply || '(no response)');
    }
  </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML)

# ---- Start/Stop endpoints ----
def _stop_all_flags():
    for k in movement_flag.keys():
        movement_flag[k] = False

@app.route('/forward')
def forward():
    if any(movement_flag.values()):
        _stop_all_flags(); time.sleep(0.1)
    movement_flag['forward'] = True
    Thread(target=walk_forward_loop, daemon=True).start()
    return "Moving forward (crawl gait)..."

@app.route('/backward')
def backward():
    if any(movement_flag.values()):
        _stop_all_flags(); time.sleep(0.1)
    movement_flag['backward'] = True
    Thread(target=walk_backward_loop, daemon=True).start()
    return "Moving backward (crawl gait)..."

@app.route('/left')
def left():
    if any(movement_flag.values()):
        _stop_all_flags(); time.sleep(0.1)
    movement_flag['left'] = True
    Thread(target=turn_left_loop, daemon=True).start()
    return "Turning left..."

@app.route('/right')
def right():
    if any(movement_flag.values()):
        _stop_all_flags(); time.sleep(0.1)
    movement_flag['right'] = True
    Thread(target=turn_right_loop, daemon=True).start()
    return "Turning right..."

@app.route('/trot_sync')
def trot_sync():
    if any(movement_flag.values()):
        _stop_all_flags(); time.sleep(0.1)
    movement_flag['trot_sync'] = True
    Thread(target=trot_forward_loop_sync, daemon=True).start()
    return "Trot (locked synchronization) started..."

@app.route('/trot_sync_step')
def trot_sync_step():
    _stop_all_flags(); time.sleep(0.05)
    setup_pose_bias_back()
    trot_step_forward_sync(DIAG_A, DIAG_B)
    trot_step_forward_sync(DIAG_B, DIAG_A)
    setup()
    return "Single locked-synchronization trot cycle done."

@app.route('/trot')
def trot():
    if any(movement_flag.values()):
        _stop_all_flags(); time.sleep(0.1)
    movement_flag['trot'] = True
    Thread(target=trot_forward_loop, daemon=True).start()
    return "Trot (legacy) started..."

@app.route('/trot_step')
def trot_step():
    _stop_all_flags(); time.sleep(0.05)
    setup_pose_bias_back()
    trot_step_forward(DIAG_A, DIAG_B)
    trot_step_forward(DIAG_B, DIAG_A)
    setup()
    return "Single trot cycle (legacy) done."

@app.route('/step')
def step():
    _stop_all_flags(); time.sleep(0.05)
    order = [(LF_HIP, LF_KNEE), (RR_HIP, RR_KNEE), (RF_HIP, RF_KNEE), (LR_HIP, LR_KNEE)]
    crawl_step_forward(order)
    return "Single forward step (crawl) done."

@app.route('/stop')
def stop():
    _stop_all_flags()
    setup()
    return "Stopping and parking neutral."

# ===================== (NEW) Natural-language command parsing =====================
COMMAND_PATTERNS = [
    (r'\b(stop|halt|park)\b',                        lambda: ('stop',)),
    (r'\b(trot sync|sync trot|locked trot)\b',       lambda: ('trot_sync',)),
    (r'\b(trot)\b',                                  lambda: ('trot',)),
    (r'\bforward\b',                                 lambda: ('forward',)),
    (r'\bbackward|reverse\b',                        lambda: ('backward',)),
    (r'\bleft\b',                                    lambda: ('left',)),
    (r'\bright\b',                                   lambda: ('right',)),
    (r'\bneutral|home|reset\b',                      lambda: ('diag/neutral',)),
]

def parse_robot_command(text: str):
    text = (text or "").lower().strip()
    # Only parse if user intends to command robot, e.g., starts with "robot"
    if text.startswith("robot "):
        text = text.split(" ", 1)[1]
    elif not text.startswith("robot"):
        # Still allow obvious commands even without the prefix
        pass

    for pattern, builder in COMMAND_PATTERNS:
        if re.search(pattern, text):
            return builder()[0]
    return None

def execute_robot_action(action: str):
    # Map action string to the same routes you already expose
    if action == 'stop':
        return stop()
    elif action == 'forward':
        return forward()
    elif action == 'backward':
        return backward()
    elif action == 'left':
        return left()
    elif action == 'right':
        return right()
    elif action == 'trot_sync':
        return trot_sync()
    elif action == 'trot':
        return trot()
    elif action == 'diag/neutral':
        return diag_neutral()
    else:
        return "Unknown action."

# ===================== (NEW) Chat endpoint =====================
@app.route('/ask', methods=['POST'])
def ask():
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get('text') or "").strip()

    # 1) Try to detect and execute robot commands
    action = parse_robot_command(text)
    robot_msg = None
    if action:
        robot_msg = execute_robot_action(action)

    # 2) Get a model reply (general question or confirmation/assist)
    reply = lm_reply(text)

    # 3) Speak the reply aloud
    speak_async(reply)

    return jsonify({"reply": reply, "robot_action": action, "robot_message": robot_msg})

# ===================== Main =====================
if __name__ == "__main__":
    setup()
    # Optional: calibrate pulse ranges per your servo datasheet
    # for ch in [LF_HIP, RF_HIP, LR_HIP, RR_HIP, LF_KNEE, RF_KNEE, LR_KNEE, RR_KNEE]:
    #     kit.servo[ch].set_pulse_width_range(500, 2500)
    app.run(host='0.0.0.0', port=5000)
