"""Audio helpers: pick a music track and build ffmpeg filters that replace a clip's audio.

Music files: put royalty-free tracks (e.g. from YouTube Studio > Audio Library) in music/.
If a track needs attribution, put the credit text in a .txt file with the same name
(e.g. music/Track.mp3 + music/Track.txt); it is added to the clip's description.
"""
import os
import random
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
MUSIC_DIR = os.path.join(HERE, "music")
MUSIC_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"}


def music_tracks(path=None):
    """All music files at path (a file or folder), sorted for a stable rotation."""
    path = path or MUSIC_DIR
    if os.path.isfile(path):
        return [os.path.abspath(path)]
    if not os.path.isdir(path):
        return []
    return sorted(os.path.join(path, name) for name in os.listdir(path)
                  if os.path.splitext(name)[1].lower() in MUSIC_EXTENSIONS)


def music_credit(track):
    """Attribution text from the track's .txt sidecar, or None."""
    sidecar = os.path.splitext(track)[0] + ".txt"
    if os.path.isfile(sidecar):
        with open(sidecar, encoding="utf-8-sig") as file:
            text = " ".join(file.read().split())
        return text or None
    return None


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def pick_music(tracks, index, length, rng=random):
    """Rotate through tracks; start at a random point so every clip sounds different."""
    track = tracks[index % len(tracks)]
    room = duration(track) - length - 1
    offset = round(rng.uniform(0, room), 2) if room > 5 else 0.0
    return track, offset


def music_input(track, offset):
    """ffmpeg input args for a looping music track starting at offset seconds."""
    return ["-stream_loop", "-1", "-ss", f"{offset:.2f}", "-i", track]


def silence_input():
    return ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]


def fit(label, length, volume=1.0, fade_out=True):
    """Trim/pad an input's audio to exactly length seconds, with optional fades."""
    chain = f"[{label}]aresample=48000,apad,atrim=0:{length},asetpts=PTS-STARTPTS,volume={volume:g}"
    if fade_out and length > 3:
        chain += f",afade=t=in:d=0.5,afade=t=out:st={length - 1.5:.2f}:d=1.5"
    return chain


def music_filter(music_label, length, volume=0.8, out="aout"):
    return fit(music_label, length, volume) + f"[{out}]"


def silence_filter(label, length, out="aout"):
    return fit(label, length, fade_out=False) + f"[{out}]"


def mix_filter(length, voice_label=None, music_label=None, game_label=None,
               voice_volume=1.0, music_volume=0.15, game_volume=0.0, out="aout"):
    """Mix voice-over, music bed and (quiet) original game audio into one track."""
    parts, names = [], []
    for label, volume, name, fade in ((voice_label, voice_volume, "vo", False),
                                      (music_label, music_volume, "bg", True),
                                      (game_label, game_volume, "gm", False)):
        if label is not None and volume > 0:
            parts.append(fit(label, length, volume, fade_out=fade) + f"[{name}]")
            names.append(f"[{name}]")
    if not names:
        raise ValueError("nothing to mix")
    if len(names) == 1:
        parts[-1] = parts[-1].rsplit("[", 1)[0] + f"[{out}]"
    else:
        parts.append("".join(names) + f"amix=inputs={len(names)}:duration=first:normalize=0,"
                     f"alimiter=limit=0.95[{out}]")
    return ";".join(parts)
