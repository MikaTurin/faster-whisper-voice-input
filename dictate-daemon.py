#!/usr/bin/env python3
import os
import queue
import subprocess
import threading
import time

import numpy as np
import sounddevice as sd
from faster_whisper.vad import VadOptions, get_speech_timestamps

FIFO = "/tmp/dictate.fifo"
MODEL_SIZE = "small"
MODEL_DEVICE = "cpu"
MODEL_COMPUTE_TYPE = "int8"
LANGUAGE = "en"
SAMPLE_RATE = 16000

SILENCE_MS = 600  # trailing silence that closes an utterance
MIN_SPEECH_MS = 500  # ignore shorter blips
POLL_INTERVAL_S = 0.25  # how often the segmenter re-checks the buffer

SOUND_START = os.path.expanduser("~/bin/sounds/start.wav")
SOUND_STOP = os.path.expanduser("~/bin/sounds/stop.wav")

VAD_OPTIONS = VadOptions(min_silence_duration_ms=SILENCE_MS)

transcribe_queue = queue.Queue()

buffer_lock = threading.Lock()
audio_chunks = []  # list of float32 mono chunks captured since session start
cut_point = 0  # samples already handed off to the transcription queue

stream = None
segmenter_thread = None
segmenter_stop = threading.Event()


def notify(text):
    subprocess.run(["notify-send", "Dictation", text], check=False)


def play_sound(path, wait=False):
    if wait:
        subprocess.run(["paplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(["paplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def audio_callback(indata, frames, time_info, status):
    with buffer_lock:
        audio_chunks.append(indata[:, 0].copy())


def try_cut(force=False):
    """Look at the audio captured since the last cut point; if a completed
    utterance is found (or `force` is set, e.g. on session stop), slice it
    out, advance the cut point, and queue it for transcription."""
    global cut_point

    with buffer_lock:
        full = np.concatenate(audio_chunks) if audio_chunks else np.empty(0, dtype=np.float32)
        new_audio = full[cut_point:]

        if len(new_audio) == 0:
            return

        if force:
            chunk_end = len(new_audio)
        else:
            speeches = get_speech_timestamps(new_audio, VAD_OPTIONS, sampling_rate=SAMPLE_RATE)
            if not speeches:
                return
            last = speeches[-1]
            trailing_silence_ms = (len(new_audio) - last["end"]) / SAMPLE_RATE * 1000
            if trailing_silence_ms < SILENCE_MS:
                return
            chunk_end = last["end"]

        if chunk_end < SAMPLE_RATE * MIN_SPEECH_MS / 1000 and not force:
            return

        chunk = new_audio[:chunk_end].copy()
        cut_point += chunk_end

    if len(chunk) > 0:
        transcribe_queue.put(chunk)


def segmenter_loop():
    while not segmenter_stop.is_set():
        try_cut(force=False)
        time.sleep(POLL_INTERVAL_S)


def transcription_worker(model):
    while True:
        chunk = transcribe_queue.get()
        segments, _ = model.transcribe(
            chunk, language=LANGUAGE, condition_on_previous_text=False, vad_filter=True
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        if text:
            subprocess.run(["xdotool", "type", "--clearmodifiers", "--", text + " "])
        transcribe_queue.task_done()


def start_session():
    global stream, segmenter_thread, cut_point

    play_sound(SOUND_START, wait=True)  # blocking so the beep itself isn't recorded

    with buffer_lock:
        audio_chunks.clear()
        cut_point = 0

    segmenter_stop.clear()
    stream = sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=audio_callback
    )
    stream.start()
    segmenter_thread = threading.Thread(target=segmenter_loop, daemon=True)
    segmenter_thread.start()
    notify("Listening...")


def stop_session():
    global stream

    stream.stop()
    stream.close()
    stream = None

    segmenter_stop.set()
    segmenter_thread.join(timeout=1)

    try_cut(force=True)  # flush whatever's left, even without a detected pause

    play_sound(SOUND_STOP, wait=False)


def main():
    from faster_whisper import WhisperModel

    notify("Loading model...")
    model = WhisperModel(MODEL_SIZE, device=MODEL_DEVICE, compute_type=MODEL_COMPUTE_TYPE)
    notify("Dictation daemon ready")

    threading.Thread(target=transcription_worker, args=(model,), daemon=True).start()

    if os.path.exists(FIFO):
        os.remove(FIFO)
    os.mkfifo(FIFO)

    while True:
        with open(FIFO) as f:
            cmd = f.readline().strip()
        if cmd != "toggle":
            continue
        if stream is None:
            start_session()
        else:
            stop_session()


if __name__ == "__main__":
    main()
