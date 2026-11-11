"""Fit any sound to one of the camera's sound slots.

python make_sounds.py my_jingle.wav 05      -> out/slot05.wav (+ preview)

Converts any WAV to the slot's format (16-bit PCM, 16 kHz mono, or 22.05 kHz
stereo for slot 01), trims or pads with silence to the exact slot length,
fades the last few ms so a trim never clicks, and normalises to -1 dBFS.
Also writes slotNN_preview.wav: band-limited roughly like the camera's tiny
speaker, so you can hear it before it goes on the camera.
"""
import os
import sys
import wave

import numpy as np
from scipy import signal

SLOTS = {  # slot: (exact sample frames, rate, channels) - from the stock WAVs
    '01': (838, 22050, 2), '02': (944, 16000, 1), '03': (1297, 16000, 1),
    '04': (1009, 16000, 1), '05': (29222, 16000, 1), '06': (25890, 16000, 1),
    '07': (6626, 16000, 1),
}


def read_wav(path):
    with wave.open(path) as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    dt = {1: np.uint8, 2: np.int16, 4: np.int32}[sw]
    a = np.frombuffer(raw, dt).astype(np.float64)
    if sw == 1:
        a = (a - 128) / 128
    else:
        a /= float(2 ** (8 * sw - 1))
    return a.reshape(-1, ch), sr


def write_wav(path, a, sr):
    a = np.clip(a, -1, 1)
    with wave.open(path, 'wb') as w:
        w.setnchannels(a.shape[1]); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((a * 32767).astype('<i2').tobytes())


def fit(path, slot, out='out'):
    n, rate, ch = SLOTS[slot]
    secs = round(n / rate, 3)
    a, sr = read_wav(path)
    a = a.mean(axis=1, keepdims=True) if ch == 1 else (
        np.repeat(a, 2, axis=1) if a.shape[1] == 1 else a[:, :2])
    a = signal.resample_poly(a, rate, sr, axis=0)
    a = a[:n] if len(a) >= n else np.vstack([a, np.zeros((n - len(a), ch))])
    fade = min(n, int(rate * 0.004))
    a[-fade:] *= np.linspace(1, 0, fade)[:, None]
    peak = np.abs(a).max()
    if peak > 0:
        a *= 10 ** (-1 / 20) / peak
    os.makedirs(out, exist_ok=True)
    write_wav(os.path.join(out, f'slot{slot}.wav'), a, rate)
    b, c = signal.butter(2, [450, min(7500, rate / 2 - 100)], 'bandpass', fs=rate)
    write_wav(os.path.join(out, f'slot{slot}_preview.wav'), signal.lfilter(b, c, a, axis=0), rate)
    print(f'slot {slot}: {secs}s @ {rate} Hz x{ch} <- {os.path.basename(path)}')


if __name__ == '__main__':
    fit(sys.argv[1], sys.argv[2].zfill(2))
