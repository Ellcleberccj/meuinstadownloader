import base64
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
import zipfile
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, Response, flash, redirect, render_template_string, request, send_file, url_for
import instaloader
from instaloader import Profile, Post
from instaloader.exceptions import BadCredentialsException, ConnectionException, InstaloaderException, LoginException, LoginRequiredException, ProfileNotExistsException, TwoFactorAuthRequiredException
import reference_tts

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-me")
DATA_DIR = Path(os.getenv("DATA_DIR", "/data" if Path("/data").exists() else "./data"))
SESSION_DIR = DATA_DIR / "sessions"
MEDIA_AUDIO_DIR = DATA_DIR / "media_audio"
SESSION_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
LOCK = threading.Lock()
USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
LAST_LOGIN_STATUS = {"ok": None, "message": "Ainda não foi feito teste de login."}

CSS = """
<style>:root{color-scheme:dark}body{margin:0;font-family:Inter,system-ui,Arial;background:#0f1115;color:#f4f4f5}main{max-width:1050px;margin:auto;padding:42px 20px}.card{background:#171a21;border:1px solid #2b2f3a;border-radius:22px;padding:28px}h1{margin:0 0 10px;font-size:32px}p{color:#c7cbda;line-height:1.55}label{display:block;margin:22px 0 8px;font-weight:700}input,textarea,select{width:100%;box-sizing:border-box;padding:14px 16px;border-radius:14px;border:1px solid #3a3f4c;background:#0f1115;color:white;font-size:16px}button,.btn{display:inline-block;text-align:center;text-decoration:none;margin-top:14px;padding:13px 16px;border:0;border-radius:14px;background:#f4f4f5;color:#111827;font-weight:800;font-size:15px;cursor:pointer}.btn2{background:#252a35;color:#f4f4f5;border:1px solid #3a3f4c}.msg{padding:12px 14px;border-radius:14px;margin:16px 0;background:#312320;color:#ffd7c2;border:1px solid #744534}.ok{background:#172b1c;color:#c9f7d2;border-color:#2f6840}code{background:#0f1115;border:1px solid #2b2f3a;border-radius:8px;padding:2px 6px}a{color:#dbeafe}.note{font-size:14px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px;margin-top:22px}.story{background:#101319;border:1px solid #2b2f3a;border-radius:18px;padding:12px}.story img,.story video{width:100%;border-radius:14px;background:#050507;max-height:420px;object-fit:contain}.actions{display:flex;gap:10px;flex-wrap:wrap}.actions .btn,.actions button{flex:1}.small{font-size:13px;color:#9ca3af}.loading{display:none;margin:16px 0;padding:14px;border-radius:14px;background:#101319;border:1px solid #3a3f4c;color:#dbeafe}.spin{display:inline-block;width:15px;height:15px;border:2px solid #596273;border-top-color:white;border-radius:50%;animation:s .8s linear infinite;margin-right:8px;vertical-align:-2px}@keyframes s{to{transform:rotate(360deg)}}button[disabled]{opacity:.65;cursor:wait}textarea{min-height:130px;resize:vertical}.checkrow{display:flex;align-items:flex-start;gap:10px;margin-top:18px}.checkrow input{width:auto;margin-top:4px}.checkrow label{margin:0;font-weight:700}audio{width:100%;margin:16px 0}.transcript{white-space:pre-wrap;background:#101319;border:1px solid #2b2f3a;border-radius:14px;padding:14px;color:#e5e7eb}.tagbox{margin:12px 0 16px;padding:12px;background:#101319;border:1px solid #2b2f3a;border-radius:14px}.tagbox strong{display:block;margin-bottom:8px}.tagbox .small{margin:8px 0;color:#aeb4c4}.tagbtn,.presetbtn{width:auto;margin:5px 6px 0 0;padding:8px 10px;border-radius:10px;border:1px solid #3a3f4c;background:#252a35;color:#f4f4f5;font-weight:700;cursor:pointer}.presetbtn{background:#f4f4f5;color:#111827}.tagbtn:hover,.presetbtn:hover{filter:brightness(1.08)}</style><script>function textWithTag(text,start,end,tag){let before=text.slice(0,start);let after=text.slice(end);let insert=tag;if(before&&!/\s$/.test(before)){insert=' '+insert}if(after&&!/^\s/.test(after)){insert=insert+' '}if(!after){insert=insert+' '}return {text:before+insert+after,pos:(before+insert).length}}function insertTag(button,tag){let form=button.closest('form');let textarea=form?form.querySelector('textarea[name="text"],textarea[name="manual_target_text"],textarea'):null;if(!textarea){return}let hasFocus=document.activeElement===textarea;let start=hasFocus?textarea.selectionStart:textarea.value.length;let end=hasFocus?textarea.selectionEnd:textarea.value.length;let result=textWithTag(textarea.value,start,end,tag);textarea.value=result.text;textarea.focus();textarea.setSelectionRange(result.pos,result.pos)}function clearTags(button){let form=button.closest('form');let textarea=form?form.querySelector('textarea[name="text"],textarea[name="manual_target_text"],textarea'):null;if(!textarea){return}textarea.value=textarea.value.replace(/\s*(\[[^\]]+\]|\([A-Za-z][A-Za-z -]*\))\s*/g,' ').replace(/\s+/g,' ').trim();textarea.focus()}document.addEventListener('DOMContentLoaded',()=>{document.querySelectorAll('form').forEach(f=>f.addEventListener('submit',()=>{let b=f.querySelector('button');let l=document.getElementById('loadingBox');let oldText=b?b.innerHTML:'';let action=(f.getAttribute('action')||'');let isDownload=action.includes('download')&&!action.includes('make-ref-tts');if(b){b.disabled=true;b.innerHTML='<span class="spin"></span>Processando...'}if(l){l.style.display='block';l.innerHTML='<span class="spin"></span>'+(isDownload?'Preparando download. Ele deve iniciar em instantes.':'Preparando. Aguarde...')}if(isDownload){setTimeout(()=>{if(b){b.disabled=false;b.innerHTML=oldText}if(l){l.innerHTML='Download iniciado. Se nao abriu, tente clicar novamente.';setTimeout(()=>l.style.display='none',3500)}},9000)}}))})</script>
"""

HTML = """
<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Insta Downloader</title>""" + CSS + """</head>
<body><main><div class="card"><h1>Insta Downloader</h1><p>Baixe stories, posts e reels disponíveis para a conta logada.</p>
{% with messages=get_flashed_messages(with_categories=true) %}{% for c,m in messages %}<div class="msg {{'ok' if c=='ok' else ''}}">{{m}}</div>{% endfor %}{% endwith %}<div id="loadingBox" class="loading"></div>
<form method="get" action="{{url_for('preview')}}"><label>Usuário do Instagram para stories</label><input name="username" placeholder="exemplo: instagram" required><button>Ver preview dos stories</button></form>
<form method="post" action="{{url_for('download')}}"><label>Baixar todos os stories em ZIP</label><input name="username" placeholder="exemplo: instagram" required><button>Baixar todos os stories em ZIP</button></form>
<form method="get" action="{{url_for('download_from_link')}}"><label>Link de um story específico</label><input name="url" placeholder="https://www.instagram.com/stories/usuario/123456789/"><button>Baixar story pelo link</button></form>
<form method="get" action="{{url_for('download_post_link')}}"><label>Link de post/reels</label><input name="url" placeholder="https://www.instagram.com/reel/CODIGO/ ou https://www.instagram.com/p/CODIGO/" required><button>Baixar post/reels</button></form>
<form method="get" action="{{url_for('download_media_audio')}}"><label>Link de midia para MP3</label><input name="url" placeholder="Cole uma URL publica de midia propria/autorizada" required><button>Converter midia para MP3</button></form>
<form method="post" action="{{url_for('make_ref_tts')}}"><h2>Gerar audio com minha voz</h2><label>Link da midia propria ou autorizada</label><input name="url" placeholder="Story, post, reels ou URL publica/autorizada de video/midia" required><label>Texto novo para a voz falar</label><textarea name="text" placeholder="Digite aqui o texto que sera falado..." required></textarea><label>Duracao da referencia em segundos</label><input type="number" name="reference_seconds" value="30" min="10" max="60"><p class="small">Para melhor qualidade, use pelo menos 10 segundos de voz limpa. O ideal e 30-60 segundos, sem musica, sem ruido e com apenas uma pessoa falando.</p><div class="checkrow"><input id="consent" type="checkbox" name="consent" value="yes" required><label for="consent">Confirmo que esta e minha voz ou tenho autorizacao para usa-la.</label></div><button>Gerar audio com minha voz</button></form>
<form method="post" action="{{url_for('create_fish_voice')}}"><h2>Criar voz privada</h2><label>URL da midia propria/autorizada</label><input name="voice_url" placeholder="Story, post, reels ou URL publica/autorizada de video/midia" required><label>Nome da voz</label><input name="voice_name" placeholder="Exemplo: Minha voz" required><label>Duracao da referencia em segundos</label><input type="number" name="reference_seconds" value="30" min="10" max="60"><div class="checkrow"><input id="voice_consent" type="checkbox" name="consent" value="yes" required><label for="voice_consent">Confirmo que esta e minha voz ou tenho autorizacao para usa-la.</label></div><button>Criar voz</button></form>
<form method="post" action="{{url_for('generate_fish_voice')}}"><h2>Gerar com voz salva</h2><label>Voz salva</label><select name="model_id" required>{% if saved_voices %}{% for voice in saved_voices %}<option value="{{voice.model_id}}">{{voice.name}} - {{voice.model_id}}</option>{% endfor %}{% else %}<option value="" disabled selected>Nenhuma voz salva</option>{% endif %}</select><label>Texto que a voz deve falar</label><textarea name="text" placeholder="Digite aqui o texto que sera falado..." required></textarea><button>Gerar MP3</button></form>
<form method="post" action="{{url_for('test_login')}}"><button class="btn2">Testar login configurado</button></form>
<p class="note">Debug: <a href="{{url_for('debug_env')}}">/debug-env</a>. Após mudar variáveis na Railway, faça Redeploy.</p></div></main></body></html>
"""

PREVIEW_HTML = """
<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Preview stories</title>""" + CSS + """</head>
<body><main><div class="card"><h1>Stories de @{{username}}</h1><p>Escolha um story para baixar individualmente ou baixe todos em ZIP.</p><div id="loadingBox" class="loading"></div><div class="actions"><a class="btn btn2" href="{{url_for('index')}}">Voltar</a><form method="post" action="{{url_for('download')}}" style="flex:1"><input type="hidden" name="username" value="{{username}}"><button>Baixar todos em ZIP</button></form></div>
{% if not items %}<div class="msg">Nenhum story disponível encontrado.</div>{% endif %}<div class="grid">{% for s in items %}<div class="story">{% if s.is_video %}<video controls preload="metadata" src="{{s.preview_url}}"></video>{% else %}<img src="{{s.preview_url}}" alt="story {{loop.index}}">{% endif %}<p class="small">{{loop.index}} · {{s.kind}} · ID {{s.mediaid}}</p><div class="actions"><a class="btn" href="{{url_for('download_one', username=username, mediaid=s.mediaid)}}">Baixar este</a><a class="btn btn2" target="_blank" href="{{s.preview_url}}">Abrir mídia</a></div></div>{% endfor %}</div></div></main></body></html>
"""

def clean(name, default=""):
    v = os.getenv(name, default)
    return default if v is None else v.strip().strip('"').strip("'")

def auth_required(fn):
    u, p = os.getenv("APP_USERNAME"), os.getenv("APP_PASSWORD")
    if not u or not p:
        return fn
    @wraps(fn)
    def w(*a, **kw):
        auth = request.authorization
        if not auth or auth.username != u or auth.password != p:
            return Response("Autenticação necessária", 401, {"WWW-Authenticate": 'Basic realm="Insta Downloader"'})
        return fn(*a, **kw)
    return w

def normalize_user(v):
    v = (v or "").strip().strip('"').strip("'").removeprefix("@").strip("/")
    if "instagram.com/" in v:
        v = v.split("instagram.com/", 1)[1].split("/", 1)[0]
    if not USERNAME_RE.fullmatch(v):
        raise ValueError("Usuário inválido. Use apenas o @ ou a URL do perfil.")
    return v

def parse_story_link(link):
    parsed = urlparse((link or "").strip())
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 3 and parts[0] == "stories":
        return normalize_user(parts[1]), parts[2]
    raise ValueError("Link inválido. Use um link no formato https://www.instagram.com/stories/usuario/id/")

def parse_post_shortcode(link):
    parsed = urlparse((link or "").strip())
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[0] in {"p", "reel", "tv"}:
        return parts[1]
    raise ValueError("Link inválido. Use um link de post, reels ou IGTV do Instagram.")

def valid_media_url(url):
    parsed = urlparse((url or "").strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def ytdlp_cookie_args(workdir):
    cookies_b64 = (os.getenv("YTDLP_COOKIES_B64") or "").strip()
    if not cookies_b64:
        return []
    cookies_path = Path(workdir) / "yt_dlp_cookies.txt"
    try:
        cookies_path.write_bytes(base64.b64decode(cookies_b64))
    except Exception as exc:
        raise RuntimeError("YTDLP_COOKIES_B64 invalida. Gere um cookies.txt em formato Netscape e salve o conteudo em Base64.") from exc
    if not cookies_path.exists() or cookies_path.stat().st_size == 0:
        raise RuntimeError("YTDLP_COOKIES_B64 gerou um arquivo de cookies vazio. Exporte os cookies do YouTube em formato Netscape e converta para Base64.")
    return ["--cookies", str(cookies_path)]


def make_loader(root: Path):
    L = instaloader.Instaloader(dirname_pattern=str(root / "{target}"), filename_pattern="{date_utc}_UTC_{mediaid}", download_pictures=True, download_videos=True, download_video_thumbnails=False, download_geotags=False, download_comments=False, save_metadata=False, compress_json=False, quiet=True, request_timeout=120, max_connection_attempts=2, sanitize_paths=True)
    ig_user = clean("IG_USERNAME").removeprefix("@").strip()
    ig_pass = clean("IG_PASSWORD")
    if not ig_user:
        raise LoginRequiredException("IG_USERNAME não está chegando no app. Confira as variáveis no serviço correto da Railway e faça Redeploy.")
    session_path = SESSION_DIR / f"session-{ig_user}"
    if clean("IG_SESSION_B64") and not session_path.exists():
        session_path.write_bytes(base64.b64decode(clean("IG_SESSION_B64")))
    if session_path.exists():
        try:
            L.load_session_from_file(ig_user, str(session_path))
            if L.test_login():
                return L
            session_path.unlink(missing_ok=True)
        except Exception:
            session_path.unlink(missing_ok=True)
    if clean("IG_COOKIES_JSON"):
        cookies = json.loads(clean("IG_COOKIES_JSON"))
        if not cookies.get("sessionid") or not cookies.get("csrftoken"):
            raise LoginRequiredException('IG_COOKIES_JSON precisa conter pelo menos "sessionid" e "csrftoken".')
        L.load_session(ig_user, cookies)
        if not L.test_login():
            raise LoginRequiredException("Cookies carregados, mas o Instagram não confirmou login. Copie cookies novos do navegador.")
        return L
    if not ig_pass:
        raise LoginRequiredException("Configure IG_PASSWORD, IG_SESSION_B64 ou IG_COOKIES_JSON na Railway.")
    L.login(ig_user, ig_pass)
    logged = L.test_login()
    if not logged:
        raise LoginRequiredException("Senha carregada, mas o Instagram não confirmou login. Use IG_SESSION_B64 ou IG_COOKIES_JSON.")
    L.save_session_to_file(str(session_path))
    return L

def iter_story_items(L, username):
    profile = Profile.from_username(L.context, username)
    for story in L.get_stories(userids=[profile.userid]):
        for item in story.get_items():
            yield item

def story_media_id(item):
    return str(getattr(item, "mediaid", "") or getattr(item, "media_id", "") or getattr(item, "shortcode", ""))

def item_preview_url(item):
    return item.video_url if getattr(item, "is_video", False) else item.url

def media_files(root):
    return [f for f in root.rglob("*") if f.is_file() and f.suffix.lower() in [".jpg", ".jpeg", ".png", ".mp4"]]

def zip_dir(root):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in root.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(root))
    buf.seek(0)
    return buf

@app.get("/")
@auth_required
def index():
    return render_template_string(HTML, saved_voices=reference_tts.load_saved_voices())

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/debug-env")
@auth_required
def debug_env():
    return {"IG_USERNAME_configurado": bool(os.getenv("IG_USERNAME")), "IG_USERNAME_normalizado": (clean("IG_USERNAME").removeprefix("@").strip()[:2] + "***") if os.getenv("IG_USERNAME") else None, "IG_PASSWORD_configurado": bool(os.getenv("IG_PASSWORD")), "IG_PASSWORD_tamanho": len(clean("IG_PASSWORD")) if os.getenv("IG_PASSWORD") else 0, "IG_SESSION_B64_configurado": bool(os.getenv("IG_SESSION_B64")), "IG_COOKIES_JSON_configurado": bool(os.getenv("IG_COOKIES_JSON")), "DATA_DIR": str(DATA_DIR), "SESSION_DIR_existe": SESSION_DIR.exists(), "ultimo_teste_login": LAST_LOGIN_STATUS}

@app.post("/test-login")
@auth_required
def test_login():
    root = Path(tempfile.mkdtemp(prefix="test_login_"))
    try:
        with LOCK:
            L = make_loader(root)
            user = L.test_login()
        LAST_LOGIN_STATUS.update({"ok": True, "message": f"Login confirmado como @{user}."})
        flash(f"Login confirmado como @{user}.", "ok")
    except Exception as e:
        LAST_LOGIN_STATUS.update({"ok": False, "message": f"{type(e).__name__}: {e}"})
        flash(f"Falha no teste de login: {type(e).__name__}: {e}", "error")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return redirect(url_for("index"))

@app.get("/preview")
@auth_required
def preview():
    root = Path(tempfile.mkdtemp(prefix="preview_"))
    try:
        username = normalize_user(request.args.get("username", ""))
        with LOCK:
            L = make_loader(root)
            items = []
            for item in iter_story_items(L, username):
                mid = story_media_id(item)
                if mid:
                    items.append({"mediaid": mid, "is_video": bool(getattr(item, "is_video", False)), "kind": "vídeo" if getattr(item, "is_video", False) else "foto", "preview_url": item_preview_url(item)})
        return render_template_string(PREVIEW_HTML, username=username, items=items)
    except Exception as e:
        flash(f"Erro ao gerar preview: {type(e).__name__}: {e}", "error")
        return redirect(url_for("index"))
    finally:
        shutil.rmtree(root, ignore_errors=True)

@app.get("/download-one/<username>/<mediaid>")
@auth_required
def download_one(username, mediaid):
    root = Path(tempfile.mkdtemp(prefix="story_one_"))
    try:
        username = normalize_user(username)
        with LOCK:
            L = make_loader(root)
            found = None
            for item in iter_story_items(L, username):
                if story_media_id(item) == str(mediaid):
                    found = item
                    break
            if not found:
                flash("Story não encontrado. Ele pode ter expirado ou não estar mais disponível.", "error")
                return redirect(url_for("preview", username=username))
            L.download_storyitem(found, target=username)
        files = media_files(root)
        if not files:
            flash("Não consegui encontrar o arquivo baixado.", "error")
            return redirect(url_for("preview", username=username))
        return send_file(files[0], as_attachment=True, download_name=files[0].name, max_age=0)
    except Exception as e:
        flash(f"Erro ao baixar story: {type(e).__name__}: {e}", "error")
        return redirect(url_for("index"))

@app.get("/download-link")
@auth_required
def download_from_link():
    try:
        username, mediaid = parse_story_link(request.args.get("url", ""))
        return redirect(url_for("download_one", username=username, mediaid=mediaid))
    except Exception as e:
        flash(str(e), "error")
        return redirect(url_for("index"))

@app.get("/download-post")
@auth_required
def download_post_link():
    root = Path(tempfile.mkdtemp(prefix="post_"))
    try:
        shortcode = parse_post_shortcode(request.args.get("url", ""))
        with LOCK:
            L = make_loader(root)
            post = Post.from_shortcode(L.context, shortcode)
            L.download_post(post, target=f"post_{shortcode}")
        files = media_files(root)
        if not files:
            flash("Não consegui encontrar mídia nesse post/reels.", "error")
            return redirect(url_for("index"))
        if len(files) == 1:
            return send_file(files[0], as_attachment=True, download_name=files[0].name, max_age=0)
        return send_file(zip_dir(root), mimetype="application/zip", as_attachment=True, download_name=f"post_{shortcode}.zip", max_age=0)
    except Exception as e:
        flash(f"Erro ao baixar post/reels: {type(e).__name__}: {e}", "error")
        return redirect(url_for("index"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


@app.get("/download-media-audio")
@auth_required
def download_media_audio():
    url = (request.args.get("url") or "").strip()
    if not valid_media_url(url):
        flash("Envie uma URL valida.", "error")
        return redirect(url_for("index"))
    workdir = MEDIA_AUDIO_DIR / uuid.uuid4().hex[:16]
    try:
        workdir.mkdir(parents=True, exist_ok=True)
        template = str(workdir / "source.%(ext)s")
        cmd = [
            "yt-dlp",
            *ytdlp_cookie_args(workdir),
            "--js-runtimes", "node",
            "--remote-components", "ejs:github",
            "--no-playlist",
            "--max-filesize", "250M",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "-o", template,
            url,
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=240)
        if result.returncode != 0:
            detail = result.stderr or result.stdout or "Erro desconhecido"
            if "Sign in to confirm" in detail or "not a bot" in detail:
                raise RuntimeError("O YouTube bloqueou o IP da Railway e pediu confirmacao de login/bot. Configure ou atualize YTDLP_COOKIES_B64, tente outro link, aguarde, ou use upload manual/arquivo ja baixado.")
            raise RuntimeError(detail[-1800:])
        files = list(workdir.glob("*.mp3"))
        if not files:
            raise RuntimeError("Nenhum MP3 foi encontrado depois do processamento.")
        return send_file(files[0], as_attachment=True, download_name=f"{workdir.name}.mp3", max_age=0)
    except Exception as e:
        flash(f"Erro ao converter midia para MP3: {type(e).__name__}: {e}", "error")
        return redirect(url_for("index"))


@app.post("/download")
@auth_required
def download():
    try:
        target = normalize_user(request.form.get("username", ""))
        root = Path(tempfile.mkdtemp(prefix="stories_"))
        with LOCK:
            L = make_loader(root)
            count = 0
            for item in iter_story_items(L, target):
                if L.download_storyitem(item, target=target):
                    count += 1
        if count == 0:
            flash("Nenhum story disponível foi encontrado para esse perfil pela conta logada.", "error")
            return redirect(url_for("index"))
        return send_file(zip_dir(root), mimetype="application/zip", as_attachment=True, download_name=f"{target}_stories.zip", max_age=0)
    except ValueError as e:
        flash(str(e), "error")
    except ProfileNotExistsException:
        flash("Perfil não encontrado.", "error")
    except TwoFactorAuthRequiredException:
        flash("Essa conta tem 2FA. Use IG_SESSION_B64 ou IG_COOKIES_JSON.", "error")
    except BadCredentialsException:
        flash("Falha no login: usuário ou senha recusados. Confira as variáveis e faça Redeploy.", "error")
    except (LoginException, LoginRequiredException, ConnectionException, InstaloaderException) as e:
        flash(f"Erro: {type(e).__name__}: {e}", "error")
    finally:
        if 'root' in locals():
            shutil.rmtree(root, ignore_errors=True)
    return redirect(url_for("index"))


@app.get("/make-ref-tts")
@auth_required
def make_ref_tts_get():
    flash("Use o formulario Gerar audio com minha voz na pagina inicial.", "error")
    return redirect(url_for("index"))


@app.get("/create-fish-voice")
@auth_required
def create_fish_voice_get():
    flash("Use o formulario Criar voz privada na pagina inicial.", "error")
    return redirect(url_for("index"))


@app.get("/generate-fish-voice")
@auth_required
def generate_fish_voice_get():
    flash("Use o formulario Gerar com voz salva na pagina inicial.", "error")
    return redirect(url_for("index"))


reference_tts.register(
    app,
    auth_required,
    DATA_DIR,
    LOCK,
    make_loader,
    iter_story_items,
    story_media_id,
    parse_story_link,
    parse_post_shortcode,
)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
