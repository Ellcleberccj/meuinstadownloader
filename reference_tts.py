import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import msgpack
import requests
from flask import Response, flash, redirect, render_template_string, request, url_for
from instaloader import Post

REF_TTS_FILENAME_RE = re.compile(r"^[a-f0-9]{32}\.mp3$")
REF_TTS_DIR = None
VOICES_FILE = None
LOCK = None
make_loader = None
iter_story_items = None
story_media_id = None
parse_story_link = None
parse_post_shortcode = None

RESULT_HTML = """
<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Áudio gerado</title>
<style>:root{color-scheme:dark}body{margin:0;font-family:Inter,system-ui,Arial;background:#0f1115;color:#f4f4f5}main{max-width:1050px;margin:auto;padding:42px 20px}.card{background:#171a21;border:1px solid #2b2f3a;border-radius:22px;padding:28px}h1{margin:0 0 10px;font-size:32px}p{color:#c7cbda;line-height:1.55}.btn{display:inline-block;text-align:center;text-decoration:none;margin-top:14px;padding:13px 16px;border:0;border-radius:14px;background:#f4f4f5;color:#111827;font-weight:800;font-size:15px}.btn2{background:#252a35;color:#f4f4f5;border:1px solid #3a3f4c}.actions{display:flex;gap:10px;flex-wrap:wrap}.transcript{white-space:pre-wrap;background:#101319;border:1px solid #2b2f3a;border-radius:14px;padding:14px;color:#e5e7eb}audio{width:100%;margin:16px 0}</style></head>
<body><main><div class="card"><h1>Áudio gerado</h1><p>Preview do MP3 criado pelo app.</p>
<audio controls preload="metadata" src="{{audio_url}}"></audio>
<div class="actions"><a class="btn" href="{{download_url}}">Baixar MP3</a><a class="btn btn2" href="{{url_for('index')}}">Voltar</a></div>
{% if reference_text %}<h2>Transcrição automática usada como referência</h2><div class="transcript">{{reference_text}}</div>{% endif %}
</div></main></body></html>
"""


def register(app, auth_required, data_dir, lock, loader_fn, story_iter_fn, story_id_fn, story_parser_fn, post_parser_fn):
    global REF_TTS_DIR, VOICES_FILE, LOCK, make_loader, iter_story_items, story_media_id, parse_story_link, parse_post_shortcode
    REF_TTS_DIR = Path(data_dir) / "ref_tts"
    REF_TTS_DIR.mkdir(parents=True, exist_ok=True)
    VOICES_FILE = REF_TTS_DIR / "voices.json"
    LOCK = lock
    make_loader = loader_fn
    iter_story_items = story_iter_fn
    story_media_id = story_id_fn
    parse_story_link = story_parser_fn
    parse_post_shortcode = post_parser_fn

    app.add_url_rule("/make-ref-tts", "make_ref_tts", auth_required(make_ref_tts), methods=["POST"])
    app.add_url_rule("/create-fish-voice", "create_fish_voice", auth_required(create_fish_voice), methods=["POST"])
    app.add_url_rule("/generate-fish-voice", "generate_fish_voice", auth_required(generate_fish_voice), methods=["POST"])
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


def fish_error_detail(response):
    detail = (response.text or "").strip()[:1000]
    return detail or "sem corpo de resposta"


def env_text(name, default):
    value = (os.getenv(name) or "").strip().strip('"').strip("'")
    return value or default


def env_int(name, default):
    try:
        return int((os.getenv(name) or "").strip())
    except (TypeError, ValueError):
        return default


def clamp_reference_seconds(seconds):
    return max(10, min(60, seconds))


def default_reference_seconds():
    return clamp_reference_seconds(env_int("FISH_REFERENCE_SECONDS", 30))


def parse_reference_seconds(value):
    if value in (None, ""):
        return default_reference_seconds()
    try:
        seconds = int(str(value).strip())
    except (TypeError, ValueError):
        return default_reference_seconds()
    return clamp_reference_seconds(seconds)


def reference_seconds_from_request(field="reference_seconds"):
    return parse_reference_seconds(request.form.get(field))


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


def extract_reference_audio(url, workdir, reference_seconds):
    source = download_reference_media(url, workdir)
    reference_audio = workdir / "reference.wav"
    run_checked([
        "ffmpeg", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "44100", "-t", str(reference_seconds), str(reference_audio)
    ], "Falha ao extrair áudio de referência")
    if not reference_audio.exists() or reference_audio.stat().st_size == 0:
        raise RuntimeError("Não foi possível gerar o áudio de referência.")
    return reference_audio


def fish_api_key():
    key = env_text("FISH_API_KEY", "")
    if not key:
        raise RuntimeError("Configure FISH_API_KEY nas variáveis de ambiente da Railway.")
    return key


def fish_asr(audio_path):
    audio_bytes = Path(audio_path).read_bytes()
    payload = {"audio": audio_bytes, "ignore_timestamps": True}
    response = requests.post(
        "https://api.fish.audio/v1/asr",
        headers={
            "Authorization": f"Bearer {fish_api_key()}",
            "Content-Type": "application/msgpack",
        },
        data=msgpack.packb(payload, use_bin_type=True),
        timeout=180,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Falha na transcrição automática pela Fish Audio: HTTP {response.status_code}. "
            f"Resposta: {fish_error_detail(response)}"
        )
    text = (response.json().get("text") or "").strip()
    if not text:
        raise RuntimeError("A Fish Audio não retornou transcrição para a referência. Use uma mídia com fala mais clara.")
    return text


def tts_headers():
    return {
        "Authorization": f"Bearer {fish_api_key()}",
        "Content-Type": "application/msgpack",
        "model": env_text("FISH_TTS_MODEL", "s2-pro"),
    }


def fish_tts_with_reference(target_text, reference_audio_path, reference_text):
    reference_audio = Path(reference_audio_path).read_bytes()
    payload = {
        "text": target_text,
        "references": [{"audio": reference_audio, "text": reference_text}],
        "format": "mp3",
        "sample_rate": 44100,
        "mp3_bitrate": 192,
        "latency": env_text("FISH_TTS_LATENCY", "normal"),
        "chunk_length": env_int("FISH_TTS_CHUNK_LENGTH", 200),
        "normalize": True,
    }
    response = requests.post(
        "https://api.fish.audio/v1/tts",
        headers=tts_headers(),
        data=msgpack.packb(payload, use_bin_type=True),
        timeout=300,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Falha ao gerar TTS pela Fish Audio: HTTP {response.status_code}. "
            f"Resposta: {fish_error_detail(response)}"
        )
    if not response.content:
        raise RuntimeError("A Fish Audio retornou uma resposta vazia para o TTS.")
    return response.content


def fish_tts_with_saved_voice(target_text, model_id):
    payload = {
        "text": target_text,
        "reference_id": model_id,
        "format": "mp3",
        "mp3_bitrate": 192,
        "latency": env_text("FISH_TTS_LATENCY", "normal"),
        "chunk_length": env_int("FISH_TTS_CHUNK_LENGTH", 200),
    }
    response = requests.post(
        "https://api.fish.audio/v1/tts",
        headers=tts_headers(),
        data=msgpack.packb(payload, use_bin_type=True),
        timeout=300,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Falha ao gerar TTS com voz salva pela Fish Audio: HTTP {response.status_code}. "
            f"Resposta: {fish_error_detail(response)}"
        )
    if not response.content:
        raise RuntimeError("A Fish Audio retornou uma resposta vazia para o TTS.")
    return response.content


def extract_model_id(payload):
    if not isinstance(payload, dict):
        return None
    for key in ("model_id", "id", "_id"):
        value = payload.get(key)
        if value:
            return str(value)
    for key in ("model", "data"):
        value = payload.get(key)
        if isinstance(value, dict):
            nested = extract_model_id(value)
            if nested:
                return nested
    return None


def create_fish_private_voice_model(name, reference_audio_path, reference_text=None):
    fields = [
        ("type", "tts"),
        ("train_mode", "fast"),
        ("title", name),
        ("visibility", "private"),
        ("description", "Modelo privado criado pelo app"),
        ("enhance_audio_quality", "true"),
    ]
    if reference_text:
        fields.append(("texts", reference_text))

    with open(reference_audio_path, "rb") as audio:
        response = requests.post(
            "https://api.fish.audio/model",
            headers={"Authorization": f"Bearer {fish_api_key()}"},
            data=fields,
            files={"voices": (reference_audio_path.name, audio, "audio/wav")},
            timeout=300,
        )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Falha ao criar voz privada na Fish Audio: HTTP {response.status_code}. "
            f"Resposta: {fish_error_detail(response)}"
        )
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError("A Fish Audio criou uma resposta inválida ao criar a voz privada.")
    model_id = extract_model_id(payload)
    if not model_id:
        raise RuntimeError(f"A Fish Audio não retornou model_id ao criar a voz. Resposta: {str(payload)[:1000]}")
    return model_id


def load_saved_voices():
    if VOICES_FILE is None or not VOICES_FILE.exists():
        return []
    try:
        data = json.loads(VOICES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and item.get("model_id")]


def save_voice(name, model_id, source):
    voices = load_saved_voices()
    entry = {
        "name": name,
        "model_id": model_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
    }
    voices = [voice for voice in voices if voice.get("model_id") != model_id]
    voices.append(entry)
    tmp = VOICES_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(voices, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(VOICES_FILE)
    return entry


def find_saved_voice(model_id):
    for voice in load_saved_voices():
        if voice.get("model_id") == model_id:
            return voice
    return None


def prune_ref_tts_outputs(max_age_seconds=24 * 60 * 60):
    cutoff = time.time() - max_age_seconds
    for file in REF_TTS_DIR.glob("*.mp3"):
        try:
            if file.stat().st_mtime < cutoff:
                file.unlink(missing_ok=True)
        except OSError:
            pass


def save_output_mp3(output_bytes):
    filename = f"{uuid.uuid4().hex}.mp3"
    output_path = REF_TTS_DIR / filename
    output_path.write_bytes(output_bytes)
    return filename


def render_audio_result(filename, reference_text=""):
    return render_template_string(
        RESULT_HTML,
        audio_url=url_for("ref_tts_output", filename=filename),
        download_url=url_for("ref_tts_output", filename=filename, download=1),
        reference_text=reference_text,
    )


def make_ref_tts():
    if request.form.get("consent") != "yes":
        flash("Confirme que esta é sua voz ou que você tem autorização para usá-la.", "error")
        return redirect(url_for("index"))
    media_url = (request.form.get("url") or "").strip()
    target_text = (request.form.get("text") or "").strip()
    reference_seconds = reference_seconds_from_request()
    if not media_url:
        flash("Informe o link da mídia de referência.", "error")
        return redirect(url_for("index"))
    if not target_text:
        flash("Informe o texto novo para gerar o áudio.", "error")
        return redirect(url_for("index"))

    workdir = Path(tempfile.mkdtemp(prefix="ref_tts_"))
    try:
        prune_ref_tts_outputs()
        reference_audio = extract_reference_audio(media_url, workdir, reference_seconds)
        reference_text = fish_asr(reference_audio)
        output_bytes = fish_tts_with_reference(target_text, reference_audio, reference_text)
        filename = save_output_mp3(output_bytes)
        return render_audio_result(filename, reference_text)
    except Exception as exc:
        flash(f"Erro ao gerar áudio com referência: {type(exc).__name__}: {exc}", "error")
        return redirect(url_for("index"))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def create_fish_voice():
    if request.form.get("consent") != "yes":
        flash("Confirme que esta é sua voz ou que você tem autorização para usá-la.", "error")
        return redirect(url_for("index"))
    media_url = (request.form.get("voice_url") or "").strip()
    voice_name = (request.form.get("voice_name") or "").strip()
    reference_seconds = reference_seconds_from_request()
    if not media_url:
        flash("Informe o link da mídia para criar a voz privada.", "error")
        return redirect(url_for("index"))
    if not voice_name:
        flash("Informe um nome para a voz privada.", "error")
        return redirect(url_for("index"))

    workdir = Path(tempfile.mkdtemp(prefix="fish_voice_"))
    try:
        reference_audio = extract_reference_audio(media_url, workdir, reference_seconds)
        try:
            reference_text = fish_asr(reference_audio)
        except Exception:
            reference_text = None
        model_id = create_fish_private_voice_model(voice_name, reference_audio, reference_text)
        save_voice(voice_name, model_id, media_url)
        flash(f"Voz privada criada com sucesso: {voice_name} ({model_id}).", "ok")
    except Exception as exc:
        flash(f"Erro ao criar voz privada: {type(exc).__name__}: {exc}", "error")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return redirect(url_for("index"))


def generate_fish_voice():
    model_id = (request.form.get("model_id") or "").strip()
    target_text = (request.form.get("text") or "").strip()
    if not model_id or not find_saved_voice(model_id):
        flash("Selecione uma voz salva válida.", "error")
        return redirect(url_for("index"))
    if not target_text:
        flash("Informe o texto que a voz deve falar.", "error")
        return redirect(url_for("index"))
    try:
        prune_ref_tts_outputs()
        output_bytes = fish_tts_with_saved_voice(target_text, model_id)
        filename = save_output_mp3(output_bytes)
        return render_audio_result(filename)
    except Exception as exc:
        flash(f"Erro ao gerar áudio com voz salva: {type(exc).__name__}: {exc}", "error")
        return redirect(url_for("index"))


def content_disposition(filename, download):
    disposition = "attachment" if download else "inline"
    return f'{disposition}; filename="{filename}"'


def parse_range_header(range_header, size):
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header or "")
    if not match:
        return None
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        return None
    if start_text:
        start = int(start_text)
        end = int(end_text) if end_text else size - 1
    else:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            return None
        start = max(size - suffix_length, 0)
        end = size - 1
    if start >= size or end < start:
        return None
    return start, min(end, size - 1)


def send_mp3_with_range(path, filename, download=False):
    size = path.stat().st_size
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": "audio/mpeg",
        "Content-Disposition": content_disposition(filename, download),
        "Cache-Control": "no-store",
    }
    range_header = request.headers.get("Range")
    if range_header:
        byte_range = parse_range_header(range_header, size)
        if byte_range is None:
            headers["Content-Range"] = f"bytes */{size}"
            return Response(status=416, headers=headers)
        start, end = byte_range
        length = end - start + 1
        with open(path, "rb") as audio:
            audio.seek(start)
            data = audio.read(length)
        headers.update({
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(length),
        })
        return Response(data, status=206, headers=headers)

    headers["Content-Length"] = str(size)
    return Response(path.read_bytes(), status=200, headers=headers)


def ref_tts_output(filename):
    if not REF_TTS_FILENAME_RE.fullmatch(filename or ""):
        return Response("Arquivo inválido.", 404)
    path = REF_TTS_DIR / filename
    if not path.exists():
        return Response("Arquivo não encontrado.", 404)
    return send_mp3_with_range(path, filename, download=request.args.get("download") == "1")
