# faster-whisper-voice-input

Local, offline, continuous voice dictation for Linux. Speak into any
focused window — a terminal, an IDE, a chat box — and it gets typed for
you, as if you'd typed it yourself. Runs fully offline via
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), no cloud API,
no internet required after setup.

## How it works

1. A background daemon keeps a Whisper model loaded in memory (avoids the
   multi-second model-load delay on every utterance).
2. Press a hotkey to start a **listening session** — microphone audio is
   captured continuously, straight into memory (no intermediate file).
3. While listening, a voice-activity detector (VAD) watches for pauses.
   Every time it detects a completed utterance (speech followed by a bit of
   trailing silence), that chunk is cut out and transcribed immediately —
   you can keep talking while the previous chunk is still being typed out.
4. Press the hotkey again to end the session — anything still pending gets
   flushed through as a final chunk.

You dictate in natural chunks and see each one land while you're still
talking, instead of speaking one long blob and waiting until you stop. It
also avoids the classic "last word got cut off" problem: chunk boundaries
come from real measured silence (VAD), not from guessing when you're about
to release a hotkey.

## Requirements

```bash
sudo apt install -y libnotify-bin pulseaudio-utils   # notify-send, paplay (sound cues)
pip install --user faster-whisper sounddevice
```

`sounddevice` needs the system PortAudio library — usually already present
on a stock Ubuntu/Mint install (`libportaudio2`); if not:
`sudo apt install -y libportaudio2`.

For typing the recognized text into the focused window, install whichever
matches your display server:

```bash
# Wayland (stock Ubuntu/GNOME)
sudo apt install -y wtype

# X11 (Cinnamon, MATE, Xfce, KDE/X, "Ubuntu on Xorg")
sudo apt install -y xdotool
```

`dictate-daemon.py` auto-detects which one to use via `$XDG_SESSION_TYPE`.

## Install

Before you start, make sure:

- The [Requirements](#requirements) above are installed (Python deps,
  `notify-send`/`paplay`, and `wtype` or `xdotool` depending on your
  display server).
- You've picked a hotkey to bind (see [Bind it to a hotkey](#bind-it-to-a-hotkey)).

**1. Set the constants in `dictate-daemon.py` for your own setup**, before
copying it anywhere:

| Constant | Default | Meaning |
|---|---|---|
| `MODEL_SIZE` | `"small"` | Whisper model size (`tiny`/`base`/`small`/`medium`/`large`) — bigger is more accurate but slower and heavier on RAM |
| `MODEL_DEVICE` | `"cpu"` | Passed straight to `WhisperModel(...)` — set to `"cuda"` if you have an NVIDIA GPU (see [Bigger/more accurate model](#biggermore-accurate-model)) |
| `MODEL_COMPUTE_TYPE` | `"int8"` | Passed straight to `WhisperModel(...)` — pair with `MODEL_DEVICE` (`"int8"` for CPU, `"float16"` for CUDA) |
| `LANGUAGE` | `"en"` | Fixed dictation language, passed straight to `transcribe()` |

**2. Install and enable the daemon:**

```bash
mkdir -p ~/bin/sounds
cp dictate-daemon.py dictate.py ~/bin/
cp sounds/*.wav ~/bin/sounds/
chmod +x ~/bin/dictate-daemon.py ~/bin/dictate.py

mkdir -p ~/.config/systemd/user
cp systemd/dictate.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now dictate.service
```

`systemd/dictate.service` hardcodes two X11-specific environment variables:

```
Environment=DISPLAY=:0
Environment=XAUTHORITY=%h/.Xauthority
```

They only matter if `xdotool` is the one typing your text (X11 session — see
[Requirements](#requirements)). On Wayland (`wtype`) they're unused and safe
to ignore. The reason they're pinned at all: a systemd `--user` service
doesn't reliably inherit `DISPLAY`/`XAUTHORITY` from your desktop session,
especially if it starts early at login/boot — `xdotool` then fails with
`Can't open display`.

Whether you need to change them depends on your setup — check from a
terminal *inside your desktop session* (not this systemd service):

```bash
echo $DISPLAY      # almost always :0 on a normal single-seat desktop
echo $XAUTHORITY   # ~/.Xauthority on most setups (LightDM, startx, …) —
                    # but GDM (stock Ubuntu/Fedora) often puts it somewhere
                    # under /run/user/<uid>/ instead
```

- If both match the defaults above (`:0` and `~/.Xauthority`, which `%h`
  expands to) — leave the file as-is, nothing to edit.
- If either differs, edit the corresponding `Environment=` line in your
  copy of `dictate.service` to match, then `systemctl --user daemon-reload
  && systemctl --user restart dictate.service`.

### Single language only

This daemon is built for dictating in one fixed language at a time —
set via `LANGUAGE` above. Multi-language (auto-detected) dictation isn't
supported out of the box. Adding it would mean replacing `LANGUAGE` with a
set of allowed languages and adding a `model.detect_language()` pass before
transcribing each chunk in `transcription_worker`. That roughly **doubles**
the encoder cost per chunk (detection runs the encoder once, transcription
runs it again), so expect dictation to run **~30-50% slower** — and
detection is per-chunk, so it only works reliably at silence-delimited
utterance boundaries, not mid-sentence code-switching.

### Bigger/more accurate model

By default the daemon runs on CPU (`MODEL_DEVICE = "cpu"`,
`MODEL_COMPUTE_TYPE = "int8"`) with `MODEL_SIZE = "small"` — no GPU or
extra drivers needed.

`MODEL_SIZE = "medium"` is noticeably more accurate, especially on
non-English languages and background noise, but ~5-7x slower on CPU and
uses roughly 3x the RAM of `small`. With the continuous chunked
architecture here, a model that's too slow relative to your talking pace
can make the transcription queue fall behind. Got a decent NVIDIA GPU? Set
`MODEL_DEVICE = "cuda"` and `MODEL_COMPUTE_TYPE = "float16"` — needs the
proprietary NVIDIA driver plus `nvidia-cublas-cu12`/`nvidia-cudnn-cu12` (no
full CUDA toolkit required).

## Bind it to a hotkey

Point any custom-shortcut mechanism at `~/bin/dictate.py` (absolute path).
On Cinnamon/GNOME: **Settings → Keyboard → Shortcuts → Custom Shortcuts →
Add**, command `~/bin/dictate.py`, key combo e.g. `Ctrl+Alt+D`.

## Maintenance

```bash
systemctl --user status dictate.service    # is the daemon alive?
systemctl --user restart dictate.service   # restart after editing the script
journalctl --user -u dictate.service -f    # live logs
```

## Tuning

These constants in `dictate-daemon.py` only matter if you want to tweak
segmentation behavior after trying it out:

| Constant | Default | Meaning |
|---|---|---|
| `SILENCE_MS` | `600` | Trailing silence (ms) that closes an utterance — raise it if pauses mid-sentence are getting split too eagerly |
| `MIN_SPEECH_MS` | `500` | Ignore detected speech shorter than this (coughs, mic pops) |
| `POLL_INTERVAL_S` | `0.25` | How often the segmenter re-checks the buffer |

## Credits

The two sound cues (`sounds/start.wav`, `sounds/stop.wav`) come from
freesound.org: [leviclaassen/sounds/107786](https://freesound.org/people/leviclaassen/sounds/107786/)
and [MATRIXXX_](https://freesound.org/people/MATRIXXX_/).
