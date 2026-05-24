import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import msgpack
import requests
from flask import Response, flash, redirect, render_template_string, request, send_file, url_for
from instaloader import Post

REF_TTS_FILENAME_RE = re.compile(r"^[a-f0-9]{32}\.mp3$")
REF_TTS_DIR = None
LOCK = None
make_loader = None
iter_story_items = None
story_media_id = None
parse_story_link = None
parse_post_shortcode = None

RESULT_HTML = """
<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Áudio gerado</title>
<style>:root{color-scheme:dark}body{margin:0;font-family:Inter,system-ui,Arial;background:#0f1115;color:#f4f4f5}main{max-width:1050px;margin:auto;padding:42px 20px}.card{background:#171a21;border:1px solid #2b2f3a;border-radius:22px;padding:28px}h1{margin:0 0 10px;font-size:32px}p{color:#c7cbda;line-height:1.55}.btn{display:inline-block;text-align:center;text-decoration:none;margin-top:14px;padding:13px 16px;border:0;border-radius:14px;background:#f4f4f5;color:#111827;font-weight:800;font-size:15px}.btn2{background:#252a35;color:#f4f4f5;border:1px solid #3a3f4c}.actions{display:flex;gap:10px;flex-wrap:wrap}.transcript{white-space:pre-wrap;background:#101319;border:1px solid #2b2f3a;border-radius:14px;padding:14px;color:#e5e7eb}audio{width:100%;margin:16px 0}</style></head>
<body><main><div class="card"><h1>Áudio gerado</h1><p>Preview do MP3 criado com referência temporária.</p>
<audio controls src="{{audio_url}}"></audio>
<div class="actions"><a class="btn" href="{{download_url}}">Baixar MP3</a><a class="btn btn2" href="{{url_for('index')}}">Voltar</a></div>
<h2>Transcrição automática usada como referência</h2><div class="transcript">{{reference_text}}</div>
</div></main></body></html>
"""


def register(app, auth_required, data_dir, lock, loader_fn, story_iter_fn, story_id_fn, story_parser_fn, post_parser_fn):
    global REF_TTS_DIR, LOCK, make_loader, iter_story_items, story_media_id, parse_story_link, parse_post_shortcode
    REF_TTS_DIR = Path(data_dir) / "ref_tts"
    REF_TTS_DIR.mkdir(parents=True, exist_ok=True)
    LOCK = lock
    make_loader = loader_fn
    iter_story_items = story_iter_fn
    story_media_id = story_id_fn
    parse_story_link = story_parser_fn
    parse_post_shortcode = post_parser_fn

    app.add_url_rule("/make-ref-tts", "make_ref_tts", auth_required(make_ref_tts), methods=["POST"])
    app.add_url_rule("/ref-tts-output/<filename>", "ref_tts_output", auth_required(ref_tts_output), methods=["GET"])


def run_checked(command, friendly_error):
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        raise RuntimeError(f"{friendly_error}: dependência não encontrada no ambiente.")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{friendly_error}: tempo limite excedido.")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip().splitlines()
        suffix = f" Detalhe: {detail[-1]}" if detail else ""
        raise RuntimeError(f"{friendly_error}.{suffix}")


def audio_source_files(root):
    suffixes = [".mp4", ".mov", ".mkv", ".webm", ".m4a", ".mp3", ".wav", ".aac", ".ogg", ".opus"]
    return [f for f in root.rglob("*") if f.is_file() and f.suffix.lower() in suffixes]


def pick_audio_source(workdir):
    files = audio_source_files(workdir)
    if not files:
        raise RuntimeError("Não encontrei áudio ou vídeo com faixa de áudio nessa mídia.")
    return max(files, key=lambda f: f.stat().st_size)


def download_reference_media(url, workdir):
    parsed = urlparse((url or "").strip())
    path = parsed.path.lower()
    host = parsed.netloc.lower()
    if "instagram.com" in host and "/stories/" in path:
        username, mediaid = parse_story_link(url)
        with LOCK:
            loader = make_loader(workdir)
            found = None
            for item in iter_story_items(loader, username):
                if story_media_id(item) == str(mediaid):
                    found = item
                    break
            if not found:
                raise RuntimeError("Story não encontrado. Ele pode ter expirado ou não estar disponível para a conta logada.")
            loader.download_storyitem(found, target=f"reference_story_{username}")
        return pick_audio_source(workdir)

    if "instagram.com" in host and any(prefix in path for prefix in ["/p/", "/reel/", "/tv/"]):
        shortcode = parse_post_shortcode(url)
        with LOCK:
            loader = make_loader(workdir)
            post = Post.from_shortcode(loader.context, shortcode)
            loader.download_post(post, target=f"reference_post_{shortcode}")
        return pick_audio_source(workdir)

    output_template = str(workdir / "generic_media.%(ext)s")
    run_checked(["yt-dlp", "--no-playlist", "--max-filesize", "250M", "-o", output_template, url], "Falha ao baixar a mídia pública/autorizada")
    return pick_audio_source(workdir)


def extract_reference_audio(url, workdir):
    source = download_reference_media(url, workdir)
    reference_audio = workdir / "reference.wav"
    run_checked([
        "ffmpeg", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "44100", "-t", "30", str(reference_audio)
    ], "Falha ao extrair até 30 segundos de áudio de referência")
    if not reference_audio.exists() or reference_audio.stat().st_size == 0:
        raise RuntimeError("Não foi possível gerar o áudio de referência.")
    return reference_audio


def fish_api_key():
    key = (os.getenv("FISH_API_KEY") or "").strip().strip('"').strip("'")
    if not key:
        raise RuntimeError("Configure FISH_API_KEY nas variáveis de ambiente da Railway.")
    return key


def fish_asr(audio_path):
    with open(audio_path, "rb") as audio:
        response = requests.post(
            "https://api.fish.audio/v1/asr",
            headers={"Authorization": f"Bearer {fish_api_key()}"},
            files={"audio": (audio_path.name, audio, "audio/wav")},
            data={"ignore_timestamps": "true"},
            timeout=180,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Falha na transcrição automática pela Fish Audio: HTTP {response.status_code}.")
    text = (response.json().get("text") or "").strip()
    if not text:
        raise RuntimeError("A Fish Audio não retornou transcrição para a referência. Use uma mídia com fala mais clara.")
    return text


def fish_tts_with_reference(target_text, reference_audio_path, reference_text):
    reference_audio = Path(reference_audio_path).read_bytes()
    payload = {
        "text": target_text,
        "references": [{"audio": reference_audio, "text": reference_text}],
        "format": "mp3",
        "sample_rate": 44100,
        "mp3_bitrate": 128,
        "latency": "normal",
        "normalize": True,
    }
    response = requests.post(
        "https://api.fish.audio/v1/tts",
        headers={
            "Authorization": f"Bearer {fish_api_key()}",
            "Content-Type": "application/msgpack",
            "model": "s2-pro",
        },
        data=msgpack.packb(payload, use_bin_type=True),
        timeout=300,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Falha ao gerar TTS pela Fish Audio: HTTP {response.status_code}.")
    if not response.content:
        raise RuntimeError("A Fish Audio retornou uma resposta vazia para o TTS.")
    return response.content


def prune_ref_tts_outputs(max_age_seconds=24 * 60 * 60):
    cutoff = time.time() - max_age_seconds
    for file in REF_TTS_DIR.glob("*.mp3"):
        try:
            if file.stat().st_mtime < cutoff:
                file.unlink(missing_ok=True)
        except OSError:
            pass


def make_ref_tts():
    if request.form.get("consent") != "yes":
        flash("Confirme que esta é sua voz ou que você tem autorização para usá-la.", "error")
        return redirect(url_for("index"))
    media_url = (request.form.get("url") or "").strip()
    target_text = (request.form.get("text") or "").strip()
    if not media_url:
        flash("Informe o link da mídia de referência.", "error")
        return redirect(url_for("index"))
    if not target_text:
        flash("Informe o texto novo para gerar o áudio.", "error")
        return redirect(url_for("index"))

    workdir = Path(tempfile.mkdtemp(prefix="ref_tts_"))
    try:
        prune_ref_tts_outputs()
        reference_audio = extract_reference_audio(media_url, workdir)
        reference_text = fish_asr(reference_audio)
        output_bytes = fish_tts_with_reference(target_text, reference_audio, reference_text)
        filename = f"{uuid.uuid4().hex}.mp3"
        output_path = REF_TTS_DIR / filename
        output_path.write_bytes(output_bytes)
        return render_template_string(
            RESULT_HTML,
            audio_url=url_for("ref_tts_output", filename=filename),
            download_url=url_for("ref_tts_output", filename=filename, download=1),
            reference_text=reference_text,
        )
    except Exception as exc:
        flash(f"Erro ao gerar áudio com referência: {type(exc).__name__}: {exc}", "error")
        return redirect(url_for("index"))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def ref_tts_output(filename):
    if not REF_TTS_FILENAME_RE.fullmatch(filename or ""):
        return Response("Arquivo inválido.", 404)
    path = REF_TTS_DIR / filename
    if not path.exists():
        return Response("Arquivo não encontrado.", 404)
    return send_file(path, mimetype="audio/mpeg", as_attachment=request.args.get("download") == "1", download_name=filename, max_age=0)
