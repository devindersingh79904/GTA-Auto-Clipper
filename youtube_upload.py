"""Upload rendered clips to your YouTube channel as Shorts (YouTube Data API v3).

Usage:
  python youtube_upload.py output\\gta-CLIP-ID              # dry run: checks only, uploads nothing
  python youtube_upload.py output\\gta-CLIP-ID --publish    # upload with YOUTUBE_PRIVACY (default private)

First run opens a browser to log in; the refresh token is saved to token.json so later runs need no
login. OAuth client: client_secret.json in the project root (both files are git-ignored).
Each clip must be vertical 9:16, under SHORTS_MAX_SECONDS, have a title, and not be a --test clip.
Non-private uploads also need "approved": true in the JSON, or --unattended with GTA_UNATTENDED_POSTS=1.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import config

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
PRIVACY_VALUES = {"private", "unlisted", "public"}


def clip_paths(arg):
    base = Path(arg)
    if base.suffix.lower() in {".mp4", ".json"}:
        base = base.with_suffix("")
    return base.with_suffix(".mp4"), base.with_suffix(".json")


def probe(video_path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height:format=duration", "-of", "json", str(video_path)],
                       capture_output=True, text=True)
    if r.returncode:
        raise ValueError(f"ffprobe could not read {video_path.name}")
    data = json.loads(r.stdout)
    stream = data["streams"][0]
    return int(stream["width"]), int(stream["height"]), float(data["format"]["duration"])


def check_short(width, height, duration, max_seconds=None):
    """Return a list of problems; empty means the file qualifies as a Short."""
    max_seconds = max_seconds or config.SHORTS_MAX_SECONDS
    problems = []
    if height <= width or abs(width / height - 9 / 16) > 0.01:
        problems.append(f"not vertical 9:16 ({width}x{height})")
    if duration > max_seconds:
        problems.append(f"{duration:.1f}s is longer than {max_seconds}s")
    return problems


def check_metadata(metadata, privacy, unattended=False):
    problems = []
    if metadata.get("test"):
        problems.append("test clips cannot be published")
    if not metadata.get("title") or not metadata.get("youtube_description"):
        problems.append("no title/description yet: run llm_metadata.py first")
    if metadata.get("youtube_video_id"):
        problems.append(f"already uploaded as {metadata['youtube_video_id']}")
    if privacy != "private" and not metadata.get("approved"):
        if not unattended:
            problems.append(f"'{privacy}' upload needs \"approved\": true in the JSON (or --unattended)")
        elif os.environ.get("GTA_UNATTENDED_POSTS") != "1":
            problems.append("--unattended needs GTA_UNATTENDED_POSTS=1 in your private environment")
    return problems


def ensure_shorts_tag(description):
    return description if "#shorts" in description.lower() else (description.rstrip() + "\n\n#Shorts").strip()


def request_body(metadata, privacy):
    tags = [t.lstrip("#") for t in metadata.get("hashtags") or [] if t]
    return {
        "snippet": {
            "title": metadata["title"][:100],
            "description": ensure_shorts_tag(metadata["youtube_description"])[:5000],
            "tags": tags[:15],
            "categoryId": config.YOUTUBE_CATEGORY_ID,
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }


def youtube_client():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if os.path.isfile(config.YOUTUBE_TOKEN):
        creds = Credentials.from_authorized_user_file(config.YOUTUBE_TOKEN, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:                     # revoked or expired refresh token: log in again
            creds = None
    if not creds or not creds.valid:
        if not os.path.isfile(config.YOUTUBE_CLIENT_SECRET):
            sys.exit(f"Missing {config.YOUTUBE_CLIENT_SECRET}. Download the OAuth client (Desktop app) "
                     "from Google Cloud Console and save it there.")
        flow = InstalledAppFlow.from_client_secrets_file(config.YOUTUBE_CLIENT_SECRET, SCOPES)
        print("Opening a browser to log in to YouTube (pick the channel to upload to) ...")
        creds = flow.run_local_server(port=0, open_browser=True)
        with open(config.YOUTUBE_TOKEN, "w", encoding="utf-8") as file:
            file.write(creds.to_json())
        print(f"Saved login to {os.path.basename(config.YOUTUBE_TOKEN)}; later runs will not ask again.")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload(youtube, video_path, body):
    from googleapiclient.http import MediaFileUpload
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  uploaded {int(status.progress() * 100)}%")
    return response


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("clips", nargs="+", help="clip path without extension, or its .mp4/.json")
    parser.add_argument("--publish", action="store_true", help="really upload; otherwise only check")
    parser.add_argument("--privacy", choices=sorted(PRIVACY_VALUES), default=None,
                        help=f"override YOUTUBE_PRIVACY (now: {config.YOUTUBE_PRIVACY})")
    parser.add_argument("--unattended", action="store_true",
                        help="allow non-private upload of unapproved clips (needs GTA_UNATTENDED_POSTS=1)")
    args = parser.parse_args()
    privacy = args.privacy or config.YOUTUBE_PRIVACY
    if privacy not in PRIVACY_VALUES:
        sys.exit(f"YOUTUBE_PRIVACY must be one of {sorted(PRIVACY_VALUES)}, not {privacy!r}")

    ready = []
    for arg in args.clips:
        video_path, json_path = clip_paths(arg)
        if not video_path.is_file() or not json_path.is_file():
            print(f"{video_path.stem}: SKIP - matching .mp4 and .json not found")
            continue
        metadata = json.loads(json_path.read_text(encoding="utf-8"))
        try:
            problems = check_short(*probe(video_path)) + check_metadata(metadata, privacy, args.unattended)
        except (ValueError, KeyError, IndexError) as error:
            problems = [str(error)]
        if problems:
            print(f"{video_path.stem}: SKIP - " + "; ".join(problems))
            continue
        print(f"{video_path.stem}: ready -> YouTube ({privacy}) \"{metadata['title']}\"")
        ready.append((video_path, json_path, metadata))

    if not args.publish:
        print("Dry run: nothing uploaded. Add --publish to upload." if ready else "Nothing to upload.")
        return
    if not ready:
        sys.exit(1)
    youtube = youtube_client()
    from googleapiclient.errors import HttpError
    for video_path, json_path, metadata in ready:
        print(f"uploading {video_path.name} ...")
        try:
            response = upload(youtube, video_path, request_body(metadata, privacy))
        except HttpError as error:
            status = getattr(error.resp, "status", "?")
            print(f"  YouTube returned HTTP {status}: {error.reason if hasattr(error, 'reason') else error}")
            print("  Check YouTube Studio before retrying, in case the video was created.")
            continue
        metadata["youtube_video_id"] = response["id"]
        metadata["youtube_privacy"] = response.get("status", {}).get("privacyStatus", privacy)
        metadata.setdefault("posted", {})["youtube"] = f"https://youtube.com/shorts/{response['id']}"
        json_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  done: https://youtube.com/shorts/{response['id']} ({metadata['youtube_privacy']})")


if __name__ == "__main__":
    main()
