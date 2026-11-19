"""Project settings read from .env (next to this file) and the process environment.

Real environment variables win over .env, so a one-off `$env:NAME = ...` still overrides the file.
Secrets such as API keys stay in the environment or .env; .env is git-ignored.
"""
import glob
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def load_env_file(path=os.path.join(HERE, ".env"), environ=os.environ):
    """Load KEY=VALUE lines without overriding variables that are already set."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8-sig") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            elif " #" in value:
                value = value.split(" #", 1)[0].rstrip()
            if key and key not in environ:
                environ[key] = value


load_env_file()


def get(name, default=None):
    value = os.environ.get(name, "")
    return value if value != "" else default


def get_int(name, default):
    try:
        return int(get(name, default))
    except (TypeError, ValueError):
        return default


def project_path(value):
    return value if os.path.isabs(value) else os.path.join(HERE, value)


# Speech to text (faster-whisper)
WHISPER_MODEL = get("WHISPER_MODEL", "large-v3")
WHISPER_DEVICE = get("WHISPER_DEVICE", "cuda")             # cuda | cpu
WHISPER_COMPUTE_TYPE = get("WHISPER_COMPUTE_TYPE", "float16")

# Rendering
VIDEO_ENCODER = get("VIDEO_ENCODER", "h264_nvenc")          # h264_nvenc | libx264
CLIP_LEN = get_int("CLIP_LEN", 30)
OUTPUT_DIR = project_path(get("OUTPUT_DIR", "output"))

# Local LLM (Ollama) for titles and descriptions
OLLAMA_URL = get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = get("OLLAMA_MODEL", "qwen3:14b")

# YouTube Shorts upload
YOUTUBE_PRIVACY = get("YOUTUBE_PRIVACY", "private")         # private | unlisted | public
YOUTUBE_CATEGORY_ID = get("YOUTUBE_CATEGORY_ID", "20")      # 20 = Gaming
YOUTUBE_CLIENT_SECRET = project_path(get("YOUTUBE_CLIENT_SECRET", "client_secret.json"))
YOUTUBE_TOKEN = project_path(get("YOUTUBE_TOKEN", "token.json"))
SHORTS_MAX_SECONDS = get_int("SHORTS_MAX_SECONDS", 59)


def setup_cuda_dlls():
    """Make pip-installed CUDA libraries (nvidia-cublas-cu12, nvidia-cudnn-cu12) loadable.

    CTranslate2 looks the DLLs up on PATH on Windows, so add_dll_directory alone is not enough.
    """
    try:
        import nvidia
    except ImportError:
        return
    for root in list(getattr(nvidia, "__path__", [])):
        for folder in glob.glob(os.path.join(root, "*", "bin")) + glob.glob(os.path.join(root, "*", "lib")):
            if folder not in os.environ.get("PATH", ""):
                os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(folder)
                except OSError:
                    pass
