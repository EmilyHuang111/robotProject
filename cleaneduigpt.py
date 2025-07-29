from flask import Flask, render_template_string, request, jsonify
from threading import Thread, Event
import time
import os
import re
import subprocess
import tempfile
import requests

from adafruit_servokit import ServoKit
from gtts import gTTS

# ===================== Keys / Config =====================
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY")
if not DEEPGRAM_API_KEY:
    print("[WARN] DEEPGRAM_API_KEY not set; set it with: export DEEPGRAM_API_KEY='YOUR_KEY'")

SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
if not SERPAPI_KEY:
    print("[WARN] SERPAPI_KEY not set; set it with: export SERPAPI_KEY='YOUR_KEY'")

# Path to local audio of 24K Magic (username-agnostic default)
SONG_24K_PATH = os.path.expanduser(
    os.environ.get("SONG_24K_PATH", os.path.join("~", "media", "24k_magic.mp3"))
)

# OpenAI client (uses the modern SDK)
try:
    from openai import OpenAI
    _openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
except Exception as e:
    _openai_client = None
    print("OpenAI client not available:", e)

# ===================== Global control (generation/TTS) =====================
_generation_cancel = Event()   # set() to cancel in-flight generation
_tts_proc = None               # mpg123 process for TTS audio

def cancel_generation():
    """Signal any in-flight generation to stop and silence TTS."""
    _generation_cancel.set()
    tts_stop()

# ===================== Media (music) playback =====================
_media_proc = None

def media_is_playing() -> bool:
    global _media_proc
    return _media_proc is not None and _media_proc.poll() is None

def media_stop():
    """Stop any currently playing media."""
    global _media_proc
    if _media_proc is not None and _media_proc.poll() is None:
        try:
            _media_proc.terminate()
            try:
                _media_proc.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                _media_proc.kill()
        except Exception as e:
            print("media_stop error:", e)
    _media_proc = None

def media_play_file(path: str):
    """Play a file with mpg123 (non-blocking)."""
    global _media_proc
    media_stop()  # stop any previous playback
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        print(f"[MEDIA] File not found: {path}")
        return False
    try:
        _media_proc = subprocess.Popen(
            ['mpg123', '-q', path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return True
    except Exception as e:
        print("media_play_file error:", e)
        _media_proc = None
        return False

def media_play_24k():
    ok = media_play_file(SONG_24K_PATH)
    return "Playing 24K Magic." if ok else "24K Magic file not found or could not be played."

# ===================== TTS =====================
def tts_stop():
    """Stop any in-progress TTS playback."""
    global _tts_proc
    if _tts_proc is not None and _tts_proc.poll() is None:
        try:
            _tts_proc.terminate()
            try:
                _tts_proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                _tts_proc.kill()
        except Exception as e:
            print("tts_stop error:", e)
    _tts_proc = None

def speak_async(text: str, interrupt_music: bool = True):
    """Speak text in the background using gTTS + mpg123."""
    if not text:
        return

    def _run():
        global _tts_proc
        try:
            if _generation_cancel.is_set():
                return
            if interrupt_music:
                media_stop()
            tts = gTTS(text=text, lang='en')
            with tempfile.NamedTemporaryFile(delete=True, suffix='.mp3') as fp:
                tts.save(fp.name)
                if _generation_cancel.is_set():
                    return
                _tts_proc = subprocess.Popen(
                    ['mpg123', '-q', fp.name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                while True:
                    if _tts_proc.poll() is not None:
                        break
                    if _generation_cancel.is_set():
                        tts_stop()
                        break
                    time.sleep(0.05)
        except Exception as e:
            print("TTS error:", e)
        finally:
            _tts_proc = None

    Thread(target=_run, daemon=True).start()

# ===================== Language model =====================
def lm_reply(user_text: str) -> str:
    if not _openai_client:
        return "Language model is not configured. Please set OPENAI_API_KEY."
    try:
        resp = _openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system",
                 "content": "You are a concise assistant for a quadruped robot. Robot motion and media playback are handled by the app; keep confirmations brief."
                 },
                {"role": "user", "content": user_text},
            ],
            temperature=0.4,
            max_tokens=300,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return f"Error contacting language model: {e}"

# ===================== Deepgram STT =====================
def deepgram_transcribe(audio_bytes: bytes, mimetype: str = "audio/webm") -> str:
    if not DEEPGRAM_API_KEY:
        return ""
    url = "https://api.deepgram.com/v1/listen"
    headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}", "Content-Type": mimetype}
    params = {"model": "nova-2", "smart_format": "true", "language": "en-US", "punctuate": "true"}
    try:
        r = requests.post(url, headers=headers, params=params, data=audio_bytes, timeout=30)
        r.raise_for_status()
        jd = r.json()
        try:
            return jd["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
        except Exception:
            pass
        if isinstance(jd, dict) and "transcript" in jd:
            return (jd["transcript"] or "").strip()
        return ""
    except Exception as e:
        print("Deepgram error:", e)
        return ""

# ===================== SerpAPI Web Browse =====================
SERP_ENDPOINT = "https://serpapi.com/search.json"

def _shorten(txt: str, n: int = 350) -> str:
    txt = (txt or "").strip()
    return txt if len(txt) <= n else (txt[:n-1].rstrip() + "…")

def _s(v):
    """Sanitize any SerpAPI value to a readable string."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float, bool)):
        return str(v)
    if isinstance(v, dict):
        # Common fields we might want to display
        for k in ("name", "source", "publisher", "title", "text", "value"):
            if k in v and isinstance(v[k], str):
                return v[k]
        # If dict has 'link' and 'title', show title
        if "title" in v and isinstance(v["title"], str):
            return v["title"]
        return ""
    if isinstance(v, list):
        parts = [_s(x) for x in v]
        parts = [p for p in parts if p]
        return ", ".join(parts)
    return str(v)

def serp_request(params: dict, timeout: int = 15) -> dict:
    if not SERPAPI_KEY:
        return {"error": "SerpAPI key not set"}
    try:
        params = dict(params or {})
        params["api_key"] = SERPAPI_KEY
        r = requests.get(SERP_ENDPOINT, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": f"SerpAPI error: {e}"}

def serp_search(query: str, num: int = 5) -> str:
    data = serp_request({"engine": "google", "q": query, "num": num})
    if "error" in data:
        return data["error"]

    ab = data.get("answer_box") or {}
    head = None
    if ab:
        for k in ("answer", "snippet", "result"):
            if ab.get(k):
                head = f"Answer: {_shorten(_s(ab.get(k)), 280)}"
                break

    lines = []
    if head:
        lines.append(head)

    org = data.get("organic_results") or []
    for i, item in enumerate(org[:num], start=1):
        title = _s(item.get("title")) or _s(item.get("link"))
        # snippets / extensions can be lists or dicts; sanitize everything
        snippets = []
        if item.get("snippet"):
            snippets.append(_s(item["snippet"]))
        ext = (((item.get("rich_snippet") or {}).get("top") or {}).get("extensions") or [])
        if ext:
            snippets.append(_s(ext))
        snippet = _shorten(" — ".join([s for s in snippets if s]), 220) if snippets else ""
        link = _s(item.get("link"))
        lines.append(f"{i}. {title}" + (f" — {snippet}" if snippet else "") + (f" [{link}]" if link else ""))

    return "\n".join(lines) if lines else "No results found."

def serp_news(query: str, num: int = 6) -> str:
    """News via SerpAPI (google_news engine preferred)."""
    q = query or ""
    params = {"engine": "google_news"}
    if q:
        params["q"] = q
    data = serp_request(params)
    if "error" in data:
        return data["error"]

    news = data.get("news_results") or data.get("stories_results") or []
    if not news:
        # Fallback to google + tbm=nws
        data = serp_request({"engine": "google", "q": (q or "top news"), "tbm": "nws"})
        news = data.get("news_results") or []
        if not news:
            return "No recent news found."

    lines = [f"News{(' for: ' + q) if q else ''}"]
    for i, item in enumerate(news[:num], start=1):
        title = _s(item.get("title"))
        # source may be string or object; date sometimes object/string
        source = _s(item.get("source"))
        date = _s(item.get("date") or item.get("snippet_date"))
        link = _s(item.get("link"))
        snip = _shorten(_s(item.get("snippet") or item.get("content")), 220)
        meta_parts = [p for p in (source, date) if p]
        meta = " • ".join(meta_parts) if meta_parts else ""
        lines.append(
            f"{i}. {title}"
            + (f" ({meta})" if meta else "")
            + (f" — {snip}" if snip else "")
            + (f" [{link}]" if link else "")
        )
    return "\n".join(lines)

def serp_weather(location: str) -> str:
    q = f"weather {location}".strip()
    data = serp_request({"engine": "google", "q": q})
    if "error" in data:
        return data["error"]
    ab = data.get("answer_box") or {}
    loc = _s(ab.get("location")) or (location or "Weather")
    temp = _s(ab.get("temperature"))
    unit = _s(ab.get("unit")) or "°"
    desc = _s(ab.get("weather") or ab.get("condition") or ab.get("result"))
    precip = _s(ab.get("precipitation"))
    humidity = _s(ab.get("humidity"))
    wind = _s(ab.get("wind"))
    parts = []
    if temp:
        parts.append(f"{temp}{unit}")
    if desc:
        parts.append(desc)
    if precip:
        parts.append(f"Precipitation: {precip}")
    if humidity:
        parts.append(f"Humidity: {humidity}")
    if wind:
        parts.append(f"Wind: {wind}")
    if parts:
        return f"{loc}: " + ", ".join(parts)
    # Fallback to organic
    org = data.get("organic_results") or []
    if org:
        top = org[0]
        title = _s(top.get("title"))
        snip = _s(top.get("snippet"))
        link = _s(top.get("link"))
        return f"{title} — {_shorten(snip, 220)} [{link}]"
    return "Couldn't retrieve weather right now."

def detect_web_intent(text: str):
    """Return {'type': 'search'|'news'|'weather', 'query': str} or None."""
    t = (text or "").lower().strip()

    # Explicit search
    m = re.match(r'^(search|look\s*up|google)\s+(for\s+)?(.+)$', t)
    if m:
        return {"type": "search", "query": m.group(3).strip()}

    # Weather
    if "weather" in t:
        m = re.search(r'weather\s+(in|for)\s+(.+)$', t)
        return {"type": "weather", "query": m.group(2).strip() if m else ""}

    # News (broadened)
    if ("news" in t) or ("headlines" in t) or ("top stories" in t) or ("what's happening" in t) or ("whats happening" in t) or ("what's the news" in t):
        m = re.search(r'(news|headlines|top stories)\s+(about|on|regarding)\s+(.+)$', t)
        if m:
            return {"type": "news", "query": m.group(3).strip()}
        return {"type": "news", "query": ""}  # default to top news

    return None

def do_web_intent(intent: dict) -> str:
    if not intent:
        return ""
    if not SERPAPI_KEY:
        return "Web search is not configured (set SERPAPI_KEY)."

    kind = intent.get("type")
    q = (intent.get("query") or "").strip()
    try:
        if kind == "weather":
            loc = q if q else ""
            result = serp_weather(loc)
        elif kind == "news":
            topic = q if q else ""
            result = serp_news(topic)
        else:
            topic = q if q else "top stories"
            result = serp_search(topic)
        return result
    except Exception as e:
        return f"Web error: {e}"

# ===================== Flask & ServoKit =====================
app = Flask(__name__)
kit = ServoKit(channels=16)

# ===================== Channel Mapping (your wiring) =====================
LEG1F_CHANNEL = 0
LEG1B_CHANNEL = 1
LEG2F_CHANNEL = 8
LEG2B_CHANNEL = 9
LEG3F_CHANNEL = 2
LEG3B_CHANNEL = 3
LEG4F_CHANNEL = 10
LEG4B_CHANNEL = 11

LF_HIP, LF_KNEE = LEG1F_CHANNEL, LEG1B_CHANNEL
RF_HIP, RF_KNEE = LEG2F_CHANNEL, LEG2B_CHANNEL
LR_HIP, LR_KNEE = LEG3F_CHANNEL, LEG3B_CHANNEL
RR_HIP, RR_KNEE = LEG4F_CHANNEL, LEG4B_CHANNEL

ALL_HIPS  = [LF_HIP, RF_HIP, LR_HIP, RR_HIP]
ALL_KNEES = [LF_KNEE, RF_KNEE, LR_KNEE, RR_KNEE]

# Diagonal pairs
DIAG_A = [(LF_HIP, LF_KNEE), (RR_HIP, RR_KNEE)]
DIAG_B = [(RF_HIP, RF_KNEE), (LR_HIP, LR_KNEE)]

# ===================== Tuning =====================
INVERT_HIP  = {LF_HIP: False, RF_HIP: True,  LR_HIP: False, RR_HIP: True}
INVERT_KNEE = {LF_KNEE: False, RF_KNEE: True, LR_KNEE: False, RR_KNEE: True}

HIP_NEUTRAL = 90
HIP_FWD     = 65
HIP_BACK    = 145

KNEE_DOWN   = 124
KNEE_UP     = 86

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

# ===================== Helpers =====================
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
    curs, targs = [], []
    for ch, t_raw in zip(ch_list, target_raw_list):
        t = _apply_invert(ch, t_raw, invert_map)
        c = _current_angle(ch, t_raw, invert_map)
        curs.append(c)
        targs.append(t)
    deltas = [abs(t - c) for c, t in zip(curs, targs)]
    max_steps = 0 if not deltas else max((d + step - 1) // step for d in deltas)
    for _ in range(max_steps):
        for idx, ch in enumerate(ch_list):
            c, t = curs[idx], targs[idx]
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
    _ramp_sync(chs, [angle, angle], INVERT_HIP)
def set_knee_pair(pair, angle):
    chs = [pair[0][1], pair[1][1]]
    _ramp_sync(chs, [angle, angle], INVERT_KNEE)
def set_hips_all_sync(angle):
    _ramp_sync(ALL_HIPS, [angle]*4, INVERT_HIP)
def set_knees_all_sync(angle):
    _ramp_sync(ALL_KNEES, [angle]*4, INVERT_KNEE)

# ===================== Posture =====================
def plant_all():
    set_knees_all_sync(KNEE_DOWN)
def hips_all(angle=HIP_NEUTRAL):
    set_hips_all_sync(angle)
def setup():
    print("Setup: knees down, hips neutral...")
    plant_all()
    hips_all(HIP_NEUTRAL)
    time.sleep(0.2)

# ===================== Motion building blocks =====================
def leg_lift(hip, knee):           set_knee(knee, KNEE_UP)
def leg_lower(hip, knee):          set_knee(knee, KNEE_DOWN)
def leg_swing_forward(hip, knee):  set_hip(hip, HIP_FWD)
def leg_swing_backward(hip, knee): set_hip(hip, HIP_BACK)
def weight_shift_for_pair(swing_pair):
    stance_pair = DIAG_B if swing_pair == DIAG_A else DIAG_A
    set_knee_pair(stance_pair, KNEE_DOWN + PRESS_DELTA)
    set_knee_pair(swing_pair,   KNEE_DOWN + LIGHTEN_DELTA)
    time.sleep(TROT_DWELL)
def clear_weight_shift():
    set_knees_all_sync(KNEE_DOWN)

# ===================== Crawl (used for backward) =====================
def setup_pose_bias_back():
    plant_all()
    hips_all(HIP_NEUTRAL)
    _ramp_sync(ALL_HIPS, [ (HIP_NEUTRAL + HIP_BACK)//2 ]*4, INVERT_HIP)
    time.sleep(0.2)
def swing_backward_sequence(hip, knee):
    weight_shift_for_pair(DIAG_B if (hip, knee) in DIAG_A else DIAG_A)
    leg_lift(hip, knee);   time.sleep(DWELL)
    leg_swing_backward(hip, knee); time.sleep(DWELL)
    leg_lower(hip, knee);  time.sleep(DWELL)
    clear_weight_shift()
def stance_push_all_forward():
    set_hips_all_sync(HIP_FWD);  time.sleep(DWELL)
def crawl_step_backward(order):
    for hip, knee in order:
        swing_backward_sequence(hip, knee)
        stance_push_all_forward()
def walk_backward_loop():
    print("Crawl (backward)")
    setup_pose_bias_back()
    order = [(LF_HIP, LF_KNEE), (RR_HIP, RR_KNEE), (RF_HIP, RF_KNEE), (LR_HIP, LR_KNEE)]
    while movement_flag['backward']:
        crawl_step_backward(order)
    setup(); print("Backward stopped.")

# ===================== Locked‑sync trot (Forward) =====================
def trot_step_forward_sync(stance_pair, swing_pair):
    weight_shift_for_pair(swing_pair)
    set_knee_pair(swing_pair, KNEE_UP); time.sleep(TROT_DWELL)
    set_hip_pair(swing_pair, HIP_FWD);  time.sleep(TROT_DWELL)
    set_knee_pair(swing_pair, KNEE_DOWN); time.sleep(TROT_DWELL)
    clear_weight_shift()
    set_hips_all_sync(HIP_BACK); time.sleep(TROT_DWELL)
def trot_forward_loop_sync():
    print("Locked‑sync trot (forward)")
    setup_pose_bias_back()
    stance, swing = DIAG_A, DIAG_B
    while movement_flag['trot_sync']:
        trot_step_forward_sync(stance, swing)
        stance, swing = swing, stance
    setup(); print("Trot (sync) stopped.")

# ===================== Simple in‑place turns =====================
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

# ===================== Natural-language parsing =====================
COMMAND_PATTERNS = [
    # Generation / TTS control
    (r'\b(stop|cancel|quiet|shut\s*up)\b.*\b(speaking|talking|voice|tts|response|reply|generate|generating)\b',
        lambda: ('gen/stop',)),
    # Web browse triggers
    (r'^\b(search|look\s*up|google)\b',              lambda: ('web/intent',)),
    (r'\bnews\b',                                     lambda: ('web/intent',)),
    (r'\bheadlines\b',                                lambda: ('web/intent',)),
    (r'\btop stories\b',                              lambda: ('web/intent',)),
    (r"what'?s happening",                            lambda: ('web/intent',)),
    (r"what'?s the news",                             lambda: ('web/intent',)),
    # Music control
    (r'\b(stop|pause|halt)\b.*\b(music|song|audio|playback)\b', lambda: ('media/stop',)),
    (r'\bplay\b.*\b(24\s?k|twenty[\s-]*four\s?k)\b.*\bmagic\b', lambda: ('media/play_24k',)),
    (r'\bplay\b.*\bmagic\b.*\b(24\s?k|twenty[\s-]*four\s?k)\b', lambda: ('media/play_24k',)),
    # Robot motion
    (r'\b(stop|halt|park)\b',                        lambda: ('stop',)),
    (r'\b(trot sync|sync trot|locked trot)\b',       lambda: ('forward',)),
    (r'\bforward\b',                                 lambda: ('forward',)),
    (r'\bbackward|reverse\b',                        lambda: ('backward',)),
    (r'\bleft\b',                                    lambda: ('left',)),
    (r'\bright\b',                                   lambda: ('right',)),
    (r'\bneutral|home|reset\b',                      lambda: ('diag/neutral',)),
]

def parse_robot_command(text: str):
    text = (text or "").lower().strip()
    if text.startswith("robot "):
        text = text.split(" ", 1)[1]
    for pattern, builder in COMMAND_PATTERNS:
        if re.search(pattern, text):
            return builder()[0]
    return None

def execute_robot_action(action: str):
    if action == 'gen/stop':
        cancel_generation()
        return "Stopped speaking."
    if action == 'web/intent':
        return None
    if action == 'media/play_24k':
        return media_play_24k()
    if action == 'media/stop':
        media_stop()
        return "Stopped music."
    if action == 'stop':
        cancel_generation()
        return stop()
    elif action == 'forward':
        return forward()
    elif action == 'backward':
        return backward()
    elif action == 'left':
        return left()
    elif action == 'right':
        return right()
    elif action == 'diag/neutral':
        return diag_neutral()
    else:
        return "Unknown action."

# ===================== UI (speech bubbles + mic button) =====================
HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Quadruped Controller</title>
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <style>
    :root{
      --bg: #f4f5f7;
      --card: #ffffff;
      --text: #1f2937;
      --muted: #6b7280;
      --shadow: 0 8px 24px rgba(0,0,0,.06);
      --radius: 12px;
      --neutral: #f1f3f5;
      --neutral-hover: #e9ecef;
      --neutral-border: #dfe3e8;
      --neutral-text: #2c3e50;
      --blue: #2563eb;
      --blue-600: #2563eb;
      --blue-glow: rgba(59,130,246,.35);
      --blue-border: #3b82f6;
      --danger: #b91c1c;
      --danger-hover: #991b1b;
    }
    *{box-sizing:border-box}
    body{font-family: ui-sans-serif,-apple-system,Segoe UI,Roboto,Helvetica,Arial;background:linear-gradient(180deg,#f8f9fa 0%,var(--bg) 100%);color:var(--text);margin:0;padding:28px;display:flex;justify-content:center;}
    .container{ width:min(1080px,100%); display:grid; gap:18px; }
    .card{ background:var(--card); border-radius:12px; box-shadow:0 8px 24px rgba(0,0,0,.06); border:1px solid #eef0f2; padding:18px; }
    .header{ display:flex; align-items:center; justify-content:space-between; gap:12px; }
    .title{ font-size:20px; font-weight:700; letter-spacing:.2px; }
    .controls{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin-top:12px; }
    .btn{ appearance:none; cursor:pointer; user-select:none; border:1px solid var(--neutral-border); padding:12px 14px; border-radius:10px; font-size:16px; font-weight:600; letter-spacing:.2px; background:var(--neutral); color:var(--neutral-text); transition:transform .06s, box-shadow .18s, background .18s, border-color .18s, filter .18s; box-shadow:0 2px 10px rgba(0,0,0,.05); outline:none; }
    .btn:hover{ background:var(--neutral-hover); transform:translateY(-1px); }
    .btn:active{ transform:translateY(0); }
    .btn:focus-visible{ box-shadow:0 0 0 4px var(--blue-glow); border-color:var(--blue-border); }
    .btn-danger{ background:var(--danger); color:#fff; border-color:var(--danger); }
    .btn-danger:hover{ background:var(--danger-hover); border-color:var(--danger-hover); }
    #chatbox{ height:320px; border:1px solid #e5e7eb; border-radius:12px; padding:12px; overflow:auto; background:#fcfcfd; display:flex; flex-direction:column; gap:8px; }
    .row{ display:flex; gap:10px; align-items:center; }
    .chat-input{ flex:1; padding:12px 14px; border:1px solid #dadada; border-radius:12px; font-size:16px; outline:none; background:#fff; transition: box-shadow .18s, border-color .18s; }
    .chat-input:focus{ border-color:var(--blue-border); box-shadow:0 0 0 4px var(--blue-glow); }
    .msg{ max-width:75%; padding:10px 12px; border-radius:14px; line-height:1.35; word-wrap:break-word; box-shadow:0 1px 4px rgba(0,0,0,.06); }
    .msg.user{ margin-left:auto; background:var(--neutral); color:var(--neutral-text); border:1px solid var(--neutral-border); }
    .msg.bot{ margin-right:auto; background:var(--blue); color:#fff; border:1px solid var(--blue-600); }
    .msg.system{ margin-right:auto; background:#eef2ff; color:#1e3a8a; border:1px solid #c7d2fe; }
    .icon-btn{ display:inline-flex; align-items:center; justify-content:center; width:46px; height:46px; border-radius:50%; border:1px solid transparent; background:#3a3a3a; color:#fff; box-shadow:0 2px 10px rgba(0,0,0,.10); cursor:pointer; transition: transform .06s, background .2s, box-shadow .2s, border-color .2s; outline:none; }
    .icon-btn:hover{ background:#2f2f2f; transform:translateY(-1px); }
    .icon-btn:active{ transform:translateY(0); }
    .icon-btn:focus-visible{ box-shadow:0 0 0 4px var(--blue-glow); border-color:var(--blue-border); }
    .icon{ width:22px; height:22px; display:block; }
    .icon-btn.mic.active{ background:#ef4444; }
  </style>
</head>
<body>
  <div class="container">
    <div class="card">
      <div class="header"><div class="title">Robot Movement</div></div>
      <div class="controls">
        <button class="btn" onclick="sendCmd('forward')">Forward</button>
        <button class="btn" onclick="sendCmd('backward')">Backward</button>
        <button class="btn" onclick="sendCmd('left')">Left</button>
        <button class="btn" onclick="sendCmd('right')">Right</button>
        <button class="btn btn-danger" onclick="sendCmd('stop')">Stop</button>
      </div>
    </div>

    <div class="card">
      <div class="header"><div class="title">Chat</div></div>
      <div id="chatbox"></div>
      <div class="row" style="margin-top:10px;">
        <input id="msg" class="chat-input" type="text" placeholder="Ask a question or give a command" />
        <button id="micBtn" class="icon-btn mic" onclick="toggleRec()" aria-label="Record voice">
          <svg class="icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M12 3a3 3 0 00-3 3v6a3 3 0 006 0V6a3 3 0 00-3-3z" stroke="white" stroke-width="2" stroke-linecap="round"/>
            <path d="M5 11a7 7 0 0014 0M12 18v3" stroke="white" stroke-width="2" stroke-linecap="round"/>
          </svg>
        </button>
        <button class="icon-btn" onclick="ask()" aria-label="Send">
          <svg class="icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M12 19V5M12 5l-6 6M12 5l6 6" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </button>
      </div>
    </div>
  </div>

  <script>
    function sendCmd(path){
      fetch('/' + path);
      appendBubble('system', 'Executing: ' + path);
    }
    function appendBubble(kind, text){
      const box = document.getElementById('chatbox');
      const div = document.createElement('div');
      div.className = 'msg ' + (kind || 'bot');
      div.textContent = text;
      box.appendChild(div);
      box.scrollTop = box.scrollHeight;
    }
    async function ask(){
      const input = document.getElementById('msg');
      const text = input.value.trim();
      if(!text) return;
      appendBubble('user', text);
      input.value = '';
      const resp = await fetch('/ask', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({text})});
      const data = await resp.json();
      if (data.robot_action) appendBubble('system', 'Executing: ' + data.robot_action);
      appendBubble('bot', data.reply || '(no response)');
    }
    document.getElementById('msg').addEventListener('keydown', (e)=>{ if(e.key === 'Enter') ask(); });

    // ======== Voice (MediaRecorder -> /voice_ask) ========
    let mediaRecorder = null, chunks = [], streamRef = null, recording = false;
    function pickSupportedMime(){
      const candidates = ['audio/webm;codecs=opus','audio/webm','audio/mp4'];
      for (const t of candidates){
        if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(t)) return t;
      }
      return '';
    }
    async function toggleRec(){
      if (recording){ stopRec(); } else { await startRec(); }
    }
    async function startRec(){
      const micBtn = document.getElementById('micBtn');
      try {
        const mimeType = pickSupportedMime();
        streamRef = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(streamRef, mimeType ? { mimeType } : undefined);
        chunks = [];
        mediaRecorder.ondataavailable = e => { if (e.data && e.data.size > 0) chunks.push(e.data); };
        mediaRecorder.onstop = async () => {
          const chosenType = mediaRecorder.mimeType || 'audio/webm';
          const blob = new Blob(chunks, { type: chosenType });
          chunks = [];
          await sendVoiceBlob(blob);
          cleanupStream();
        };
        mediaRecorder.start();
        recording = true;
        micBtn.classList.add('active');
      } catch (err) {
        appendBubble('system', 'Microphone error: ' + err);
        cleanupStream();
      }
    }
    function stopRec(){
      const micBtn = document.getElementById('micBtn');
      if (mediaRecorder && mediaRecorder.state === 'recording') { mediaRecorder.stop(); }
      else { cleanupStream(); }
      recording = false;
      micBtn.classList.remove('active');
    }
    function cleanupStream(){
      if (streamRef){ streamRef.getTracks().forEach(t => t.stop()); streamRef = null; }
      mediaRecorder = null;
    }
    async function sendVoiceBlob(blob){
      const form = new FormData();
      form.append('audio', blob, 'voice');
      try {
        const resp = await fetch('/voice_ask', { method: 'POST', body: form });
        const data = await resp.json();
        if (data.transcript) appendBubble('user', data.transcript);
        if (data.robot_action) appendBubble('system', 'Executing: ' + data.robot_action);
        appendBubble('bot', data.reply || '(no response)');
      } catch (e){
        appendBubble('system', 'Voice send error: ' + e);
      }
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
    movement_flag['trot_sync'] = True
    Thread(target=trot_forward_loop_sync, daemon=True).start()
    return "Moving forward (locked-sync trot)..."

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

@app.route('/stop')
def stop():
    _stop_all_flags()
    setup()
    return "Stopping and parking neutral."

@app.route('/diag_neutral')
def diag_neutral():
    setup()
    return "Neutral posture set."

# ----- Music routes (optional) -----
@app.route('/media_play_24k')
def media_play_24k_route():
    return media_play_24k()

@app.route('/media_stop')
def media_stop_route():
    media_stop()
    return "Stopped music."

# ===================== Chat endpoints (media/gen/web-aware) =====================
@app.route('/ask', methods=['POST'])
def ask():
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get('text') or "").strip()
    _generation_cancel.clear()

    action = parse_robot_command(text)
    robot_msg = None
    if action:
        robot_msg = execute_robot_action(action)
        if action == 'gen/stop':
            return jsonify({"reply": robot_msg, "robot_action": action, "robot_message": robot_msg})
        if action and action.startswith('media/'):
            reply = robot_msg or "OK."
            if action == 'media/stop':
                speak_async(reply, interrupt_music=False)
            return jsonify({"reply": reply, "robot_action": action, "robot_message": robot_msg})

    # Web intent?
    intent = detect_web_intent(text)
    if intent or (action == 'web/intent'):
        if not intent:
            intent = {"type": "news", "query": ""}
        reply = do_web_intent(intent)
        to_say = reply.splitlines()[0] if reply else ""
        speak_async(_shorten(to_say, 180), interrupt_music=False)
        return jsonify({"reply": reply, "robot_action": "web/intent", "robot_message": robot_msg})

    # Normal LM
    reply = lm_reply(text)
    if _generation_cancel.is_set():
        return jsonify({"reply": "(stopped)", "robot_action": action, "robot_message": robot_msg})
    speak_async(reply, interrupt_music=True)
    return jsonify({"reply": reply, "robot_action": action, "robot_message": robot_msg})

@app.route('/voice_ask', methods=['POST'])
def voice_ask():
    f = request.files.get('audio')
    if not f:
        return jsonify({"error": "No audio provided"}), 400
    _generation_cancel.clear()

    audio_bytes = f.read()
    mimetype = f.mimetype or "audio/webm"
    transcript = deepgram_transcribe(audio_bytes, mimetype=mimetype)
    if not transcript:
        reply = "I didn't catch that. Please try again."
        speak_async(reply, interrupt_music=True)
        return jsonify({"transcript": "", "reply": reply, "robot_action": None})

    action = parse_robot_command(transcript)
    robot_msg = None
    if action:
        robot_msg = execute_robot_action(action)
        if action == 'gen/stop':
            return jsonify({"transcript": transcript, "reply": robot_msg,
                            "robot_action": action, "robot_message": robot_msg})
        if action and action.startswith('media/'):
            reply = robot_msg or "OK."
            if action == 'media/stop':
                speak_async(reply, interrupt_music=False)
            return jsonify({"transcript": transcript, "reply": reply,
                            "robot_action": action, "robot_message": robot_msg})

    intent = detect_web_intent(transcript)
    if intent or (action == 'web/intent'):
        if not intent:
            intent = {"type": "news", "query": ""}
        reply = do_web_intent(intent)
        to_say = reply.splitlines()[0] if reply else ""
        speak_async(_shorten(to_say, 180), interrupt_music=False)
        return jsonify({"transcript": transcript, "reply": reply,
                        "robot_action": "web/intent", "robot_message": robot_msg})

    reply = lm_reply(transcript)
    if _generation_cancel.is_set():
        return jsonify({"transcript": transcript, "reply": "(stopped)",
                        "robot_action": action, "robot_message": robot_msg})
    speak_async(reply, interrupt_music=True)
    return jsonify({"transcript": transcript, "reply": reply,
                    "robot_action": action, "robot_message": robot_msg})

# ===================== Main =====================
if __name__ == "__main__":
    try:
        default_dir = os.path.dirname(os.path.expanduser(SONG_24K_PATH))
        if default_dir and not os.path.exists(default_dir):
            os.makedirs(default_dir, exist_ok=True)
    except Exception as e:
        print("Warning: could not ensure media directory:", e)

    setup()
    # Optional per-servo calibration
    # for ch in [LF_HIP, RF_HIP, LR_HIP, RR_HIP, LF_KNEE, RF_KNEE, LR_KNEE, RR_KNEE]:
    #     kit.servo[ch].set_pulse_width_range(500, 2500)
    app.run(host='0.0.0.0', port=5000)
