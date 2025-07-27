from flask import Flask, render_template_string
from threading import Thread
import time
from adafruit_servokit import ServoKit

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
# Flip per servo if it moves opposite to what you expect on YOUR rig.
INVERT_HIP  = {LF_HIP: False, RF_HIP: True,  LR_HIP: False, RR_HIP: True}
INVERT_KNEE = {LF_KNEE: False, RF_KNEE: True, LR_KNEE: False, RR_KNEE: True}

# Hip angles (swing)
HIP_NEUTRAL = 90
HIP_FWD     = 65     # forward (protraction) — only while the foot is lifted
HIP_BACK    = 145    # back (retraction) — when foot is planted to push body forward

# Knee angles (lift/lower)
KNEE_DOWN   = 124    # planted; increase if foot doesn't press floor
KNEE_UP     = 86     # lifted; decrease if lift is too small

# Weight‑shift deltas (press stance legs, lighten swing diagonal)
PRESS_DELTA   = +8   # add load on stance pair (try 8–12 if slipping)
LIGHTEN_DELTA = -6   # unload swing pair before lifting

# Motion smoothing / timing
RAMP_STEP   = 3      # deg per increment (smaller = smoother)
RAMP_DELAY  = 0.01   # s between increments
DWELL       = 0.12   # small pause inside gait phases
TROT_DWELL  = 0.12   # trot phase dwell

# ===================== Movement flags =====================
movement_flag = {
    'forward':   False,
    'backward':  False,
    'left':      False,
    'right':     False,
    'trot':      False,
    'trot_sync': False,  # NEW: locked-synchronization trot
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
    """
    Advance all channels in ch_list toward their targets in lockstep.
    Each tick: move each by up to 'step' toward target, then sleep.
    """
    # Prepare current and target (commanded) angles
    curs = []
    targs = []
    for ch, t_raw in zip(ch_list, target_raw_list):
        t = _apply_invert(ch, t_raw, invert_map)
        c = _current_angle(ch, t_raw, invert_map)
        curs.append(c)
        targs.append(t)

    # Determine the maximum steps needed
    deltas = [abs(t - c) for c, t in zip(curs, targs)]
    max_steps = 0 if not deltas else max((d + step - 1) // step for d in deltas)

    for i in range(max_steps):
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

    # Snap exactly to targets
    for ch, t in zip(ch_list, targs):
        kit.servo[ch].angle = t

# Convenience wrappers
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

# ===================== Single‑leg primitives (kept for crawl/turn) =====================
def leg_lift(hip, knee):           set_knee(knee, KNEE_UP)
def leg_lower(hip, knee):          set_knee(knee, KNEE_DOWN)
def leg_swing_forward(hip, knee):  set_hip(hip, HIP_FWD)
def leg_swing_backward(hip, knee): set_hip(hip, HIP_BACK)
def leg_push_back(hip, knee):      set_hip(hip, HIP_BACK)
def leg_push_forward(hip, knee):   set_hip(hip, HIP_FWD)

# ===================== Weight shift =====================
def weight_shift_for_pair(swing_pair):
    """Press stance pair; lighten swing pair — both actions in pair‑sync."""
    stance_pair = DIAG_B if swing_pair == DIAG_A else DIAG_A
    # Press stance
    set_knee_pair(stance_pair, KNEE_DOWN + PRESS_DELTA)
    # Lighten swing
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

# ===================== Crawl gait (for completeness) =====================
def setup_pose_bias_back():
    plant_all()
    hips_all(HIP_NEUTRAL)
    # preload some "back" for stance
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

# ===================== STRICTLY-SYNCHRONIZED TROT (LOCKSTEP) =====================
def trot_step_forward_sync(stance_pair, swing_pair):
    """
    Locked synchronization:
      1) Weight shift: press stance pair, lighten swing pair (pair-sync).
      2) Lift swing pair (pair-sync).
      3) Swing swing-pair hips forward (pair-sync).
      4) Lower swing pair (pair-sync).
      5) Drive push: all planted hips to HIP_BACK together (four‑hip sync).
    """
    # 1) Weight shift
    weight_shift_for_pair(swing_pair)

    # 2) Lift swing pair (together)
    set_knee_pair(swing_pair, KNEE_UP); time.sleep(TROT_DWELL)

    # 3) Swing both swing hips forward (together)
    set_hip_pair(swing_pair, HIP_FWD);  time.sleep(TROT_DWELL)

    # 4) Lower swing pair (together)
    set_knee_pair(swing_pair, KNEE_DOWN); time.sleep(TROT_DWELL)

    # Clear weight shift
    clear_weight_shift()

    # 5) Drive push with all planted feet (no pulling planted legs forward)
    set_hips_all_sync(HIP_BACK); time.sleep(TROT_DWELL)

def trot_forward_loop_sync():
    print("Diagonal‑pair LOCKSTEP trot (forward): A supports while B swings, then alternate.")
    setup_pose_bias_back()
    stance, swing = DIAG_A, DIAG_B
    while movement_flag['trot_sync']:
        trot_step_forward_sync(stance, swing)
        stance, swing = swing, stance
    setup(); print("Trot (sync) stopped.")

# (Legacy non-locked trot if you still want it)
def trot_step_forward(stance_pair, swing_pair):
    weight_shift_for_pair(swing_pair)
    set_knee_pair(swing_pair, KNEE_UP); time.sleep(TROT_DWELL)
    _ramp_sync([swing_pair[0][0], swing_pair[1][0]], [HIP_FWD, HIP_FWD], INVERT_HIP)  # hips forward together
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

# ===================== Simple in‑place turn (LEFT/RIGHT) =====================
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

# ===================== Flask UI =====================
HTML = '''
<!DOCTYPE html>
<html>
<head>
  <title>Robot Movement Control</title>
  <style>
    body { text-align:center; font-family:Arial, sans-serif; }
    button { font-size:20px; margin:8px; padding:14px 18px; }
    .stop-btn { background-color:#c00; color:#fff; }
  </style>
</head>
<body>
  <h1>Robot Movement Control</h1>
  <div>
    <button onclick="send('forward')">Move Forward (Crawl)</button>
    <button onclick="send('backward')">Move Backward (Crawl)</button>
  </div>
  <div>
    <button onclick="send('left')">Turn Left</button>
    <button onclick="send('right')">Turn Right</button>
  </div>
  <div>
    <button onclick="send('trot_sync')">Trot (Locked Sync)</button>
    <button onclick="send('trot_sync_step')">Single Trot Step (Locked)</button>
  </div>
  <div>
    <button onclick="send('trot')">Trot (Legacy)</button>
    <button onclick="send('trot_step')">Single Trot Step (Legacy)</button>
  </div>
  <div>
    <button onclick="send('step')">Single Forward Step (Crawl)</button>
    <button class="stop-btn" onclick="send('stop')">Stop</button>
  </div>
  <h3>Diagnostics</h3>
  <div>
    <button onclick="send('diag/neutral')">Neutral Pose</button>
    <button onclick="send('diag/lf_push')">LF Push Test</button>
    <button onclick="send('diag/lf_step')">LF Weighted Step</button>
  </div>
  <script>
    function send(path){ fetch('/' + path); }
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
    trot_step_forward_sync(DIAG_A, DIAG_B)  # Phase 1
    trot_step_forward_sync(DIAG_B, DIAG_A)  # Phase 2
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

# ===================== Main =====================
if __name__ == "__main__":
    setup()
    # Optional: calibrate pulse ranges per your servo datasheet (often improves reach/torque and linearity)
    # for ch in [LF_HIP, RF_HIP, LR_HIP, RR_HIP, LF_KNEE, RF_KNEE, LR_KNEE, RR_KNEE]:
    #     kit.servo[ch].set_pulse_width_range(500, 2500)
    app.run(host='0.0.0.0', port=5000)
