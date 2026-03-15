# Osu — AIY Voice Kit Reference
*How to control the button, LED, and speaker on the Google AIY Voice Kit*

---

## Overview

The Google AIY Voice Kit is a Raspberry Pi-based hardware kit with three things Osu cares about: a button, an RGB LED inside that button, and a speaker. All processing happens on your computer. The Pi's only job is to detect button presses and produce light and sound in response to signals it receives over WiFi.

Google ships a Python library called `aiy` that is pre-installed on the kit's SD card image. This library handles all low-level GPIO and audio driver communication — you never touch hardware registers directly.

---

## V1 vs V2 — Know Which Kit You Have

The AIY Voice Kit has two hardware versions with different LED APIs.

|  | V1 (Voice HAT) | V2 (Voice Bonnet) |
|---|---|---|
| Board | Voice HAT | Voice Bonnet |
| Pi | Raspberry Pi 3 | Raspberry Pi Zero |
| LED type | Single color | Full RGB |
| LED API | `aiy.board.Led` | `aiy.leds.Leds` |
| Colors | On/Off only | Any RGB color |

If you bought the kit recently, you almost certainly have V2. Check the board attached to the Raspberry Pi — it will say Voice HAT or Voice Bonnet.

---

## Setup and Connection

### First Boot

Flash the AIY system image to the SD card using balenaEtcher. The `aiy` Python library is pre-installed — you don't need to install anything manually for basic use.

### Connecting via SSH

```bash
ssh pi@aiy.local
# default password: raspberry
# change it: passwd
```

If `aiy.local` doesn't resolve, use the AIY Projects app (Android) to find the IP, or check your router's DHCP table.

### Where to Put Your Code

Write Python on your computer, copy it to the Pi, run it over SSH.

```bash
# Copy script to Pi
scp osu_pi.py pi@aiy.local:/home/pi/

# SSH in and run it
ssh pi@aiy.local
python3 /home/pi/osu_pi.py
```

---

## The Button

Import `Board` from `aiy.board`. Use it as a context manager. The board object gives you `button` and `led`.

### Blocking Wait

```python
from aiy.board import Board, Led

with Board() as board:
    board.button.wait_for_press()
    print('Button pressed!')
    board.button.wait_for_release()
    print('Button released!')
```

### Callback Pattern (use this for Osu)

```python
from aiy.board import Board, Led
import requests, signal

def on_press():
    board.led.state = Led.PULSE_SLOW
    requests.post('http://your-computer.local:5000/commit')

with Board() as board:
    board.button.when_pressed = on_press
    signal.pause()  # keep alive
```

---

## LED Control — V1 Kit (Voice HAT)

V1 uses `aiy.board.Led` with preset states. Access via `board.led.state`.

| State | Code | What It Looks Like |
|---|---|---|
| Off | `Led.OFF` | Completely dark |
| Solid on | `Led.ON` | Steady glow |
| Blink | `Led.BLINK` | Fast on/off |
| Blink 3x | `Led.BLINK_3` | Three quick blinks then off |
| Beacon | `Led.BEACON` | Slow pulse, stays dim between |
| Beacon dark | `Led.BEACON_DARK` | Mostly off, brief flash |
| Slow pulse | `Led.PULSE_SLOW` | Breathes slowly in and out |
| Quick pulse | `Led.PULSE_QUICK` | Breathes quickly in and out |
| Decay | `Led.DECAY` | Fades out slowly |

```python
from aiy.board import Board, Led

with Board() as board:
    board.led.state = Led.PULSE_SLOW   # working
    # ... do something ...
    board.led.state = Led.ON           # done
    import time; time.sleep(2)
    board.led.state = Led.OFF          # idle
```

---

## LED Control — V2 Kit (Voice Bonnet)

V2 has a full RGB LED. Use `aiy.leds.Leds` and `aiy.leds.Color`.

### Solid Colors

```python
from aiy.leds import Leds, Color

with Leds() as leds:
    leds.update(Leds.rgb_on(Color.RED))
    leds.update(Leds.rgb_on(Color.GREEN))
    leds.update(Leds.rgb_on(Color.BLUE))
    leds.update(Leds.rgb_on(Color.YELLOW))
    leds.update(Leds.rgb_on(Color.WHITE))
    leds.update(Leds.rgb_off())
```

### Custom RGB Colors

```python
ORANGE = (255, 140, 0)
PURPLE = (128, 0, 128)
TEAL   = (0, 180, 180)

leds.update(Leds.rgb_on(ORANGE))
```

### Patterns — Blink and Breathe

```python
from aiy.leds import Leds, Color, Pattern

with Leds() as leds:
    # Blink (hard on/off)
    leds.pattern = Pattern.blink(400)         # 400ms period
    leds.update(Leds.rgb_pattern(Color.BLUE))

    # Breathe (smooth fade in/out)
    leds.pattern = Pattern.breathe(800)       # 800ms period
    leds.update(Leds.rgb_pattern(Color.RED))

    import time; time.sleep(5)
    leds.update(Leds.rgb_off())
```

---

## Osu LED Color Language

| Event | Color | Pattern | Meaning |
|---|---|---|---|
| Idle | Off | — | Waiting for button press |
| Button pressed | Yellow | Pulse slow | Request received |
| Agent working | Blue | Breathe (800ms) | Computer running Codex |
| Codex turn done | Green | Single flash then off | Agent finished a turn |
| Commit pushed | Green | Solid 2s then off | Git push succeeded |
| Error | Red | Blink (400ms) | Something failed |
| Waiting for approval | White | Beacon | Codex needs your input |

---

## Speaker and Audio

### Playing a WAV File

```python
from aiy.voice.audio import play_wav

play_wav('/home/pi/sounds/chime.wav')
```

### Text to Speech

```python
from aiy.voice.tts import say

say('Commit pushed successfully')
say('Codex instance 3 is done')
```

> Note: `say()` requires internet and Google Cloud credentials. For offline audio, use `play_wav` with pre-recorded files.

### Recommended Sounds

| Event | Sound |
|---|---|
| Commit done | Short ascending chime |
| Codex turn done | Single soft tone (fires often — keep subtle) |
| Error | Low double buzz |
| Approval needed | Two ascending tones |

---

## Complete Pi Script

```python
#!/usr/bin/env python3
# /home/pi/osu.py

from flask import Flask, request
from aiy.board import Board, Led
from aiy.leds import Leds, Color, Pattern
from aiy.voice.audio import play_wav
import requests, signal, time

app = Flask(__name__)
COMPUTER_URL = 'http://your-computer.local:5000'
SOUNDS = {
    'commit': '/home/pi/sounds/commit.wav',
    'done':   '/home/pi/sounds/done.wav',
    'error':  '/home/pi/sounds/error.wav',
}

board = Board()
leds  = Leds()

# --- Button ---
def on_press():
    leds.pattern = Pattern.breathe(800)
    leds.update(Leds.rgb_on(Color.YELLOW))
    try:
        requests.post(f'{COMPUTER_URL}/commit', timeout=60)
    except Exception as e:
        print(f'Error: {e}')
        leds.pattern = Pattern.blink(400)
        leds.update(Leds.rgb_pattern(Color.RED))

board.button.when_pressed = on_press

# --- Endpoints called by your computer ---
@app.route('/done', methods=['POST'])
def done():
    leds.update(Leds.rgb_on(Color.GREEN))
    play_wav(SOUNDS['commit'])
    time.sleep(2)
    leds.update(Leds.rgb_off())
    return 'ok'

@app.route('/notify', methods=['POST'])
def notify():
    # Codex agent turn complete
    leds.update(Leds.rgb_on(Color.GREEN))
    play_wav(SOUNDS['done'])
    time.sleep(1)
    leds.update(Leds.rgb_off())
    return 'ok'

@app.route('/error', methods=['POST'])
def error():
    leds.pattern = Pattern.blink(400)
    leds.update(Leds.rgb_pattern(Color.RED))
    play_wav(SOUNDS['error'])
    time.sleep(3)
    leds.update(Leds.rgb_off())
    return 'ok'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
```

---

## Running on Boot (systemd)

```ini
# /etc/systemd/system/osu.service
[Unit]
Description=Osu AIY Controller
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/osu.py
WorkingDirectory=/home/pi
User=pi
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable osu
sudo systemctl start osu

# Check status
sudo systemctl status osu

# View logs
journalctl -u osu -f
```

---

## Common Issues

| Problem | Fix |
|---|---|
| LED does not light up | Run one of the official demo scripts first — the LED driver sometimes needs to be initialized before custom code works |
| `ImportError: No module named aiy` | You're not on the AIY system image. Flash the official image or install the `aiy` package manually |
| Audio not working | Run `/home/pi/AIY-projects-python/checkpoints/check_audio.py` to verify the sound card |
| SSH not connecting | Wait 4 minutes after power-on for the Pi Zero to boot. LED stops blinking when ready |
| `aiy.local` not resolving | Use the AIY Projects Android app to find the IP, or check your router |
