"""Write a title, description and hashtags for rendered clips with a local Ollama model.

Usage:  python llm_metadata.py output\\gta-CLIP-ID [more clips ...] [--force]

Reads each clip's JSON (transcript, stream title), asks the local model for metadata, and saves it
back into the JSON. The model is unloaded right after each request (keep_alive=0), so its VRAM is
free again for the next step. Nothing is published here.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import requests

import config

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "description", "hashtags"],
}

PROMPT = """You write metadata for a YouTube Short: a vertical gameplay highlight clip.
Use ONLY the facts below. Do not invent events, reactions, people, views or game features that the
transcript or stream title do not support. If the transcript is empty, keep the title general.
Write everything in English using Latin letters only (Hinglish words in Latin letters are fine).

Stream or file title: {stream_title}
Spoken words in the clip (may be empty, may be Hinglish): {transcript}

Return JSON with:
- title: catchy, at most 80 characters, no hashtags, no quotes, no clickbait lies
- description: 1-2 short sentences about the clip
- hashtags: 3-6 relevant tags without spaces, each starting with #, always including #Shorts{avoid}"""


def clip_paths(arg):
    base = Path(arg)
    if base.suffix.lower() in {".mp4", ".json"}:
        base = base.with_suffix("")
    return base.with_suffix(".mp4"), base.with_suffix(".json")


def clean_tag(tag):
    tag = re.sub(r"[^\w]", "", str(tag).lstrip("#"))
    return f"#{tag}" if tag else None


CJK = re.compile(r"[　-〿぀-ヿ㐀-䶿一-鿿가-힯＀-￯]+")


def latin_only(text):
    """Qwen models sometimes slip Chinese words into English text; drop them."""
    return re.sub(r"[ \t]{2,}", " ", CJK.sub(" ", str(text))).strip()


def finalize(raw, metadata):
    """Normalise model output and make sure #Shorts and any source credit are present."""
    raw = {"title": latin_only(raw.get("title", "")), "description": latin_only(raw.get("description", "")),
           "hashtags": [latin_only(t) for t in raw.get("hashtags") or []]}
    title = re.sub(r"\s+", " ", raw["title"]).strip().strip("\"'")
    title = re.sub(r"#\w+", "", title).strip() or (metadata.get("stream_title") or "Gameplay highlight")
    tags = []
    for tag in raw.get("hashtags") or []:
        tag = clean_tag(tag)
        if tag and tag.lower() not in {t.lower() for t in tags}:
            tags.append(tag)
    if "#shorts" not in {t.lower() for t in tags}:
        tags.insert(0, "#Shorts")
    tags = tags[:8]
    title = title[:100]                       # YouTube's title limit; #Shorts goes in the description
    description = str(raw.get("description", "")).strip()
    if metadata.get("credit"):
        description += f"\n\nCredit: {metadata['credit']}"
        if metadata.get("source_url", "").startswith("http"):
            description += f" ({metadata['source_url']})"
    if metadata.get("music_credit"):
        description += f"\nMusic: {metadata['music_credit']}"
    description = (description + "\n\n" + " ".join(tags)).strip()
    return title, description[:4900], tags


def ask_ollama(metadata, model=None, url=None, timeout=300, used_titles=()):
    avoid = ""
    if used_titles:
        avoid = ("\n\nOther clips from the same stream already use these titles. Write a clearly different "
                 "title and description (different wording and angle), still true to the facts:\n- "
                 + "\n- ".join(used_titles))
    prompt = PROMPT.format(stream_title=metadata.get("stream_title") or "unknown",
                           transcript=(metadata.get("transcript") or "").strip()[:2000] or "(none)", avoid=avoid)
    response = requests.post(f"{url or config.OLLAMA_URL}/api/chat", json={
        "model": model or config.OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "format": SCHEMA,
        "stream": False,
        "think": False,
        "keep_alive": 0,                      # unload right away so VRAM is free for the next model
        "options": {"temperature": 0.6, "num_ctx": 4096},
    }, timeout=timeout)
    response.raise_for_status()
    return json.loads(response.json()["message"]["content"])


def write_metadata(json_path, force=False, used_titles=()):
    metadata = json.loads(json_path.read_text(encoding="utf-8"))
    if metadata.get("title") and not force:
        print(f"{json_path.stem}: already has a title (use --force to regenerate)")
        return metadata
    title, description, tags = finalize(ask_ollama(metadata, used_titles=used_titles), metadata)
    metadata.update({
        "title": title, "youtube_description": description, "hashtags": tags,
        "instagram_caption": description, "metadata_model": f"ollama:{config.OLLAMA_MODEL}",
    })
    json_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{json_path.stem}: {title}")
    return metadata


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("clips", nargs="+", help="clip path without extension, or its .mp4/.json")
    parser.add_argument("--force", action="store_true", help="regenerate even if a title exists")
    args = parser.parse_args()
    failed = 0
    used_titles = []
    for arg in args.clips:
        _, json_path = clip_paths(arg)
        if not json_path.is_file():
            print(f"{json_path}: not found")
            failed += 1
            continue
        try:
            metadata = write_metadata(json_path, args.force, used_titles)
            if metadata.get("title"):
                used_titles.append(metadata["title"])
        except requests.RequestException as error:
            sys.exit(f"Ollama request failed ({error}). Is Ollama running and is {config.OLLAMA_MODEL} pulled?")
        except (KeyError, ValueError) as error:
            print(f"{json_path.stem}: model returned unusable output ({error})")
            failed += 1
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
