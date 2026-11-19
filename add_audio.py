"""Replace the audio of finished reels with music and/or a voice-over. Never posts anything.

Usage:
  python add_audio.py output\\gta-CLIP-ID [more ...]                 # music only (music/ or generated beats)
  python add_audio.py output\\gta-CLIP-ID --voice my_take.m4a         # your commentary + quiet music bed
  python add_audio.py output\\gta-CLIP-ID --voice my_take.m4a --no-music --game-volume 0.2

Writes a new clip next to the original (gta-CLIP-ID-music / -voice .mp4 + .json) and leaves the original alone.
Music-only keeps the video untouched (no re-encode). A voice-over in English or Hindi gets pop-up captions from
your own speech. Titles are cleared in the new JSON so llm_metadata.py writes fresh ones.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import audio_mix
import config

CLEARED = ("title", "youtube_description", "instagram_caption", "metadata_model", "youtube_video_id",
           "youtube_privacy", "zernio_post_id", "idempotency_key")


def clip_paths(arg):
    base = Path(arg)
    if base.suffix.lower() in {".mp4", ".json"}:
        base = base.with_suffix("")
    return base.with_suffix(".mp4"), base.with_suffix(".json")


def ffmpeg(args, cwd=None):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                       cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[-400:])


def voice_captions(voice, ass_path, length, video_path):
    """Transcribe the voice-over and write pop-up captions. Returns (words, caption_language)."""
    import clip
    words = clip.whisper_words(clip.load_audio(voice))
    clip.release_whisper()
    margin = clip.caption_margin_for_video(str(video_path), crop=True)
    clip.write_ass(ass_path, words, 0.0, length, None, margin)
    return words, getattr(words, "caption_language", "none")


def remix(video_path, json_path, voice=None, music=None, index=0, music_volume=None, game_volume=0.0, suffix=None):
    metadata = json.loads(json_path.read_text(encoding="utf-8"))
    length = audio_mix.duration(str(video_path))
    if length <= 0:
        raise RuntimeError("could not read clip length")
    if voice and metadata.get("caption_language") not in (None, "none"):
        raise RuntimeError("this clip already has burned-in speech captions; re-render it with "
                           "clip.py --audio mute first, then add the voice-over")
    suffix = suffix or ("voice" if voice else "music")
    out_mp4 = video_path.with_name(f"{video_path.stem}-{suffix}.mp4")
    out_json = out_mp4.with_suffix(".json")

    inputs = ["-i", str(video_path)]
    labels = {}
    if voice:
        inputs += ["-i", os.path.abspath(voice)]
        labels["voice"] = f"{len(inputs) // 2 - 1}:a"
    track = None
    if music:
        track, offset = audio_mix.pick_music(music, index, length)
        inputs += audio_mix.music_input(track, offset)
        labels["music"] = f"{inputs.count('-i') - 1}:a"
    if not voice and not track:
        raise RuntimeError("nothing to add: give --voice and/or music")
    if music_volume is None:
        music_volume = 0.15 if voice else 0.8
    audio_filter = audio_mix.mix_filter(length, labels.get("voice"), labels.get("music"),
                                        "0:a" if game_volume > 0 else None,
                                        music_volume=music_volume, game_volume=game_volume)

    words, caption_language = None, "none"
    ass_name = None
    if voice:
        ass_name = f"cap_{out_mp4.stem}.ass"
        words, caption_language = voice_captions(os.path.abspath(voice), str(out_mp4.with_name(ass_name)),
                                                 length, video_path)
    if ass_name and caption_language != "none":
        import clip
        graph = f"[0:v]ass={ass_name}[vout];{audio_filter}"
        common = [*inputs, "-t", f"{length:.3f}", "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]"]
        tail = ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out_mp4.name]
        try:
            ffmpeg([*common, *clip.video_encoder_args(config.VIDEO_ENCODER), *tail], cwd=out_mp4.parent)
        except RuntimeError:
            ffmpeg([*common, *clip.video_encoder_args("libx264"), *tail], cwd=out_mp4.parent)
    else:
        ffmpeg([*inputs, "-t", f"{length:.3f}", "-filter_complex", audio_filter, "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out_mp4)])
    if ass_name and os.path.isfile(out_mp4.with_name(ass_name)):
        os.remove(out_mp4.with_name(ass_name))

    new = {k: v for k, v in metadata.items() if k not in CLEARED}
    new.update({
        "video": out_mp4.name, "remixed_from": video_path.name, "audio_mode": suffix,
        "music_track": os.path.basename(track) if track else None,
        "music_credit": audio_mix.music_credit(track) if track else None,
        "hashtags": [], "approved": False, "posted": {},
    })
    if voice:
        new.update({
            "voiceover": os.path.basename(voice),
            "voiceover_transcript": " ".join(w[2] for w in words or []),
            "caption_language": caption_language,
            "caption_fallback_reason": None if caption_language != "none" else "voice-over language not English/Hindi",
        })
    else:
        new.update({"caption_language": "none", "caption_fallback_reason": "original audio replaced (music)"})
    out_json.write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_mp4, track


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("clips", nargs="+", help="clip path without extension, or its .mp4/.json")
    parser.add_argument("--voice", help="voice-over audio file (one clip at a time)")
    parser.add_argument("--music", help="music file or folder (default: music/, generated beats if empty)")
    parser.add_argument("--no-music", action="store_true", help="voice-over only, no music bed")
    parser.add_argument("--music-volume", type=float, default=None, help="default 0.8 alone, 0.15 under a voice")
    parser.add_argument("--game-volume", type=float, default=0.0,
                        help="keep the original clip audio this quiet (0 = removed, default)")
    args = parser.parse_args()
    if args.voice and len(args.clips) != 1:
        sys.exit("--voice works on one clip at a time.")
    if args.voice and not os.path.isfile(args.voice):
        sys.exit(f"Voice file not found: {args.voice}")

    tracks = []
    if not args.no_music:
        tracks = audio_mix.music_tracks(args.music)
        if not tracks and args.music:
            sys.exit(f"No music files found at {args.music}")
        if not tracks:
            import music_gen
            print("music/ is empty: generating royalty-free beats ...")
            music_gen.ensure_tracks(audio_mix.MUSIC_DIR)
            tracks = audio_mix.music_tracks()

    failed = 0
    for index, arg in enumerate(args.clips):
        video_path, json_path = clip_paths(arg)
        if not video_path.is_file() or not json_path.is_file():
            print(f"{video_path.stem}: SKIP - matching .mp4 and .json not found")
            failed += 1
            continue
        try:
            out, track = remix(video_path, json_path, args.voice, tracks, index, args.music_volume, args.game_volume)
        except RuntimeError as error:
            print(f"{video_path.stem}: FAILED - {error}")
            failed += 1
            continue
        print(f"{video_path.stem}: -> {out.name}" + (f"  (music: {os.path.basename(track)})" if track else ""))
    print("Nothing posted.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
