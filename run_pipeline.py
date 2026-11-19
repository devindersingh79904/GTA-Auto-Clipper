"""Run the whole pipeline: clip -> local-LLM metadata -> YouTube Shorts upload.

Each stage runs as its own process, so only one model is ever in VRAM:
  1. clip.py          faster-whisper on the GPU (freed when the process exits)
  2. llm_metadata.py  Ollama model (unloaded after every request)
  3. youtube_upload.py

Usage (your own recording):
  python run_pipeline.py --file "D:\\Videos\\gta.mp4" --own-footage --top 2            # clip + metadata + dry run
  python run_pipeline.py --file "D:\\Videos\\gta.mp4" --own-footage --top 2 --upload   # ... and upload
Any argument not listed below is passed straight to clip.py.
"""
import argparse
import glob
import os
import subprocess
import sys
import time

import config

HERE = os.path.dirname(os.path.abspath(__file__))


def step(title, cmd):
    print(f"\n=== {title} ===", flush=True)
    return subprocess.run([sys.executable, *cmd], cwd=HERE).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--upload", action="store_true", help="upload the new clips (otherwise dry run)")
    parser.add_argument("--privacy", choices=("private", "unlisted", "public"), default=None)
    parser.add_argument("--unattended", action="store_true", help="passed to youtube_upload.py")
    args, clip_args = parser.parse_known_args()
    if "--output-dir" in clip_args:
        out_dir = os.path.abspath(clip_args[clip_args.index("--output-dir") + 1])
    else:
        out_dir = config.OUTPUT_DIR

    started = time.time()
    if step("1/3 clip (speech model on GPU)", ["clip.py", *clip_args]) != 0:
        sys.exit("clip.py failed; nothing else was run.")
    new = sorted(p[:-5] for p in glob.glob(os.path.join(out_dir, "*.json")) if os.path.getmtime(p) >= started - 1)
    if not new:
        sys.exit(f"No new clips in {out_dir}. (--test clips go to test_out/ and are never uploaded.)")

    if step("2/3 titles + descriptions (local LLM)", ["llm_metadata.py", *new]) != 0:
        print("Some clips have no metadata; the upload step will skip them.")

    upload_cmd = ["youtube_upload.py", *new]
    if args.upload:
        upload_cmd.append("--publish")
    if args.privacy:
        upload_cmd += ["--privacy", args.privacy]
    if args.unattended:
        upload_cmd.append("--unattended")
    sys.exit(step("3/3 YouTube Shorts upload" + ("" if args.upload else " (dry run)"), upload_cmd))


if __name__ == "__main__":
    main()
