"""Generate original, royalty-free background beats (no samples, no downloads: pure synthesis).

Usage:  python music_gen.py [--count 6] [--seconds 90] [--out music]

Each track is a seeded mix of synthesized drums, bass and chord pads in a minor key, so every file is
different but reproducible. Nothing here is copied from existing music, so the tracks need no credit.
"""
import argparse
import os
import wave

import numpy as np

SR = 44100
STYLES = {                    # bpm range, swing, hat density, mood
    "trap": ((130, 150), 0.0, 16, "dark"),
    "drill": ((138, 146), 0.0, 16, "dark"),
    "lofi": ((80, 92), 0.18, 8, "warm"),
    "boombap": ((88, 96), 0.12, 8, "warm"),
    "house": ((120, 126), 0.0, 8, "bright"),
    "synthwave": ((100, 112), 0.0, 8, "bright"),
}
PROGRESSIONS = {              # scale degrees (semitones from the minor root) for 4-bar loops
    "dark": [[0, 3, 7], [8, 0, 3], [5, 8, 0], [7, 11, 2]],
    "warm": [[0, 3, 7, 10], [5, 8, 0, 3], [8, 0, 3, 7], [7, 10, 2, 5]],
    "bright": [[0, 3, 7], [8, 0, 3], [3, 7, 10], [10, 2, 5]],
}


def hz(semitones_from_a4):
    return 440.0 * 2 ** (semitones_from_a4 / 12)


def env(n, attack=0.005, decay=0.2):
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    return a * np.exp(-t / max(decay, 1e-4))


def lowpass(x, cutoff):
    """Zero-phase 12 dB/oct low-pass done in the frequency domain (fast, numpy only)."""
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    return np.fft.irfft(spectrum / (1 + (freqs / cutoff) ** 2), n=len(x))


def saw(freq, n, detune=0.0):
    t = np.arange(n) / SR
    f = freq * (1 + detune)
    return 2 * ((t * f) % 1.0) - 1


def kick(style):
    n = int(SR * (0.6 if style in {"trap", "drill"} else 0.35))
    t = np.arange(n) / SR
    f = 45 + 110 * np.exp(-t * 28)
    phase = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(phase) * np.exp(-t * (4 if style in {"trap", "drill"} else 9))
    click = np.random.randn(n) * np.exp(-t * 400) * 0.3
    return np.tanh((body + click) * 1.6)


def snare(rng):
    n = int(SR * 0.25)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    noise = noise - lowpass(noise, 1500)                       # crude high-pass
    tone = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 30)
    return (noise * np.exp(-t * 18) * 0.7 + tone * 0.5)


def hat(rng, open_=False):
    n = int(SR * (0.18 if open_ else 0.05))
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    noise = noise - lowpass(noise, 7000)
    return noise * np.exp(-t * (18 if open_ else 90)) * 0.35


def place(track, sound, at, gain=1.0):
    start = int(at * SR)
    if start >= len(track):
        return
    end = min(len(track), start + len(sound))
    track[start:end] += sound[:end - start] * gain


def generate(seed, seconds=90, style=None):
    rng = np.random.default_rng(seed)
    style = style or list(STYLES)[seed % len(STYLES)]
    (lo, hi), swing, hat_div, mood = STYLES[style]
    bpm = int(rng.integers(lo, hi + 1))
    beat = 60.0 / bpm
    bar = 4 * beat
    root = int(rng.integers(-24, -14))                          # minor root, A4-relative (low octave)
    prog = PROGRESSIONS[mood]
    bars = int(np.ceil(seconds / bar))
    n = int(SR * seconds)
    drums, bass, pads, duck = (np.zeros(n) for _ in range(4))
    k, s = kick(style), snare(rng)
    np.random.seed(seed)

    kick_pattern = {                                            # 16th-note positions in a bar
        "trap": [0, 10], "drill": [0, 7, 11], "lofi": [0, 7, 10], "boombap": [0, 7, 10],
        "house": [0, 4, 8, 12], "synthwave": [0, 8],
    }[style]
    snare_pos = [12] if style == "drill" else [4, 12]
    for b in range(bars):
        t0 = b * bar
        intro = b < 2
        for step in range(16):
            t = t0 + step * beat / 4 + (swing * beat / 4 if step % 2 else 0)
            if not intro and (step in kick_pattern or (style in {"trap", "drill"} and step == 14 and b % 2)):
                place(drums, k, t, 0.9)
                place(duck, np.ones(int(SR * beat * 0.5)) * np.linspace(1, 0, int(SR * beat * 0.5)), t)
            if not intro and step in snare_pos:
                place(drums, s, t, 0.6)
            div = 16 // hat_div
            if step % div == 0:
                roll = style in {"trap", "drill"} and b % 4 == 3 and step >= 12
                place(drums, hat(rng, open_=(style == "house" and step % 4 == 2)), t, 0.5)
                if roll:
                    place(drums, hat(rng), t + beat / 8, 0.4)
        chord = prog[b % len(prog)]
        # pad: detuned saws, filtered, slow attack
        pad_n = int(SR * bar)
        tone = sum(saw(hz(root + 24 + note), pad_n, d) for note in chord for d in (-0.004, 0.004))
        pad_env = np.minimum(1, np.arange(pad_n) / (SR * 0.25)) * np.minimum(1, (pad_n - np.arange(pad_n)) / (SR * 0.1))
        place(pads, tone * pad_env / (2 * len(chord)), t0, 0.5)
        # bass: root of the chord, 8th notes (house) or long 808 notes (trap)
        bass_root = hz(root + chord[0] - (12 if chord[0] > 6 else 0))
        if style in {"trap", "drill"}:
            for step in kick_pattern:
                bn = int(SR * beat * 1.5)
                tb = np.arange(bn) / SR
                note = np.sin(2 * np.pi * bass_root * tb) * np.exp(-tb * 1.5)
                place(bass, np.tanh(note * 2.2), t0 + step * beat / 4, 0.55)
        else:
            for eighth in range(8):
                bn = int(SR * beat / 2 * 0.9)
                note = (saw(bass_root, bn) * 0.5 + np.sin(2 * np.pi * bass_root * np.arange(bn) / SR)) * env(bn, 0.003, 0.25)
                place(bass, note, t0 + eighth * beat / 2, 0.35)

    pads = lowpass(pads, 900 if mood == "dark" else 1600)
    bass = lowpass(bass, 400)
    sidechain = 1 - 0.6 * np.clip(duck, 0, 1)
    mix = drums + (bass + pads) * sidechain
    fade = int(SR * 2)
    mix[:fade] *= np.linspace(0, 1, fade)
    mix[-fade:] *= np.linspace(1, 0, fade)
    mix = np.tanh(mix / (np.max(np.abs(mix)) + 1e-9) * 1.4) * 0.89
    width = lowpass(pads * sidechain, 1200) * 0.15
    stereo = np.stack([mix + width, mix - width], axis=1)
    stereo /= np.max(np.abs(stereo)) + 1e-9
    return (stereo * 0.89 * 32767).astype(np.int16), style, bpm


def write_wav(path, data):
    with wave.open(path, "wb") as file:
        file.setnchannels(2)
        file.setsampwidth(2)
        file.setframerate(SR)
        file.writeframes(data.tobytes())


def ensure_tracks(out_dir, count=6, seconds=90):
    """Create count generated tracks in out_dir (skips ones that already exist). Returns their paths."""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for seed in range(count):
        style = list(STYLES)[seed % len(STYLES)]
        path = os.path.join(out_dir, f"auto-{style}-{seed + 1:02d}.wav")
        if not os.path.isfile(path):
            data, style, bpm = generate(seed + 1, seconds, style)
            write_wav(path, data)
            print(f"  made {os.path.basename(path)} ({style}, {bpm} bpm)")
        paths.append(path)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument("--seconds", type=int, default=90)
    parser.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "music"))
    args = parser.parse_args()
    ensure_tracks(args.out, args.count, args.seconds)


if __name__ == "__main__":
    main()
