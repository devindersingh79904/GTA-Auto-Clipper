# Local GPU setup (RTX 50-series, Windows)

Everything AI runs locally: faster-whisper on the GPU, Ollama for titles/descriptions, NVENC for encoding.
The only network calls are YouTube (search/chat with an API key, upload with OAuth).

## One-time install

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt          # includes CUDA 12 cuBLAS/cuDNN wheels for faster-whisper
ollama pull qwen3:14b                    # ~9.3 GB, fits in 16 GB VRAM
Copy-Item .env.example .env              # then edit settings
```

PyTorch is not needed: faster-whisper runs on CTranslate2.

Check the GPU path:

```powershell
nvidia-smi
ffmpeg -hide_banner -encoders | findstr nvenc
python clip.py --file "C:\path\video.mp4" --test --clip-len 30    # should print "speech model: large-v3 on cuda (float16)"
```

## YouTube upload setup

1. Google Cloud project with **YouTube Data API v3** enabled.
2. Google Auth Platform: audience **External**, add your Gmail under **Test users**.
3. Clients -> Create client -> **Desktop app** -> download JSON -> save as `client_secret.json` in this folder.
4. The first upload opens a browser; pick the channel. The refresh token is saved to `token.json`.

`client_secret.json`, `token.json` and `.env` are git-ignored. Never commit or share them.
Uploads from an unverified API project stay **private** until Google approves an API audit.

Optional, for `find_streams.py` and live-chat scoring (stored for your Windows user):

```powershell
[Environment]::SetEnvironmentVariable("YOUTUBE_API_KEY", "YOUR_KEY", "User")
```

## Run the pipeline

Your own recording, clip + metadata + upload check (dry run):

```powershell
python run_pipeline.py --file "D:\Videos\gta.mp4" --own-footage --top 2
```

Same, and upload as private:

```powershell
python run_pipeline.py --file "D:\Videos\gta.mp4" --own-footage --top 2 --upload
```

Steps one at a time:

```powershell
python clip.py --file "D:\Videos\gta.mp4" --own-footage --top 2
python llm_metadata.py output\gta-CLIP-ID
python youtube_upload.py output\gta-CLIP-ID            # dry run
python youtube_upload.py output\gta-CLIP-ID --publish  # upload
```

Each stage is its own process, so only one model is in VRAM at a time: Whisper is freed when
`clip.py` exits, and Ollama is called with `keep_alive=0` so it unloads after every request.

`--own-footage` is for recordings you made and may publish. `--test` clips go to `test_out/` and
are never uploaded. Non-private uploads need `"approved": true` in the clip JSON, or `--unattended`
with `GTA_UNATTENDED_POSTS=1`.

## Settings (`.env`)

| Variable | Default | Purpose |
| --- | --- | --- |
| `WHISPER_MODEL` | `large-v3` | faster-whisper model (`medium`/`small` use less VRAM) |
| `WHISPER_DEVICE` | `cuda` | `cuda` or `cpu`; falls back to CPU if CUDA fails |
| `WHISPER_COMPUTE_TYPE` | `float16` | `float16`, `int8_float16`, `int8` |
| `VIDEO_ENCODER` | `h264_nvenc` | falls back to `libx264` if NVENC fails |
| `CLIP_LEN` | `30` | clip length in seconds |
| `OUTPUT_DIR` | `output` | where publishable clips go |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama server |
| `OLLAMA_MODEL` | `qwen3:14b` | smaller option: `qwen3:8b` |
| `YOUTUBE_PRIVACY` | `private` | `private`, `unlisted`, `public` |
| `YOUTUBE_CATEGORY_ID` | `20` | 20 = Gaming |
| `YOUTUBE_CLIENT_SECRET` | `client_secret.json` | OAuth client file |
| `YOUTUBE_TOKEN` | `token.json` | saved login |
| `SHORTS_MAX_SECONDS` | `59` | uploads longer than this are refused |

Real environment variables override `.env`.

## Problems hit during setup

- **`Library cublas64_12.dll is not found`**: the pip CUDA wheels put DLLs in
  `.venv\Lib\site-packages\nvidia\*\bin`, which is not on PATH, and CTranslate2 ignores
  `os.add_dll_directory`. `config.setup_cuda_dlls()` adds those folders to PATH before Whisper loads.
- **Installed Ollama models were 27B / 17 GB**: too big for 16 GB VRAM; switched to `qwen3:14b` (Q4, 9.3 GB).
- **Qwen put Chinese words in English descriptions**: the prompt now asks for Latin letters only,
  and `llm_metadata.py` strips any remaining CJK characters.
- **Local files could not be published** (`--file` required `--test`): added `--own-footage`.
- **H.264 "Missing reference picture" warnings** while sampling `.ts` chunks are harmless decoder noise.
