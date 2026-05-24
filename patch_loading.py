from pathlib import Path

p = Path('app.py')
s = p.read_text()

old = """document.addEventListener('DOMContentLoaded',()=>{document.querySelectorAll('form').forEach(f=>f.addEventListener('submit',()=>{let b=f.querySelector('button');let l=document.getElementById('loadingBox');if(b){b.disabled=true;b.innerHTML='<span class=\"spin\"></span>Processando...'}if(l){l.style.display='block';l.innerHTML='<span class=\"spin\"></span>Preparando. Aguarde, o download ou preview vai abrir automaticamente.'}}))})"""
new = """document.addEventListener('DOMContentLoaded',()=>{document.querySelectorAll('form').forEach(f=>f.addEventListener('submit',()=>{let b=f.querySelector('button');let l=document.getElementById('loadingBox');let oldText=b?b.innerHTML:'';let isDownload=(f.getAttribute('action')||'').includes('download');if(b){b.disabled=true;b.innerHTML='<span class=\"spin\"></span>Processando...'}if(l){l.style.display='block';l.innerHTML='<span class=\"spin\"></span>'+(isDownload?'Preparando download. Ele deve iniciar em instantes.':'Preparando preview. Aguarde...')}if(isDownload){setTimeout(()=>{if(b){b.disabled=false;b.innerHTML=oldText}if(l){l.innerHTML='Download iniciado. Se não abriu, tente clicar novamente.';setTimeout(()=>l.style.display='none',3500)}},9000)}}))})"""
s = s.replace(old, new)

if 'import subprocess' not in s:
    s = s.replace('import zipfile\n', 'import zipfile\nimport subprocess\nimport uuid\n')

if 'MEDIA_AUDIO_DIR' not in s:
    s = s.replace('SESSION_DIR = DATA_DIR / "sessions"\n', 'SESSION_DIR = DATA_DIR / "sessions"\nMEDIA_AUDIO_DIR = DATA_DIR / "media_audio"\nMEDIA_AUDIO_DIR.mkdir(parents=True, exist_ok=True)\n')

if 'download_media_audio' not in s:
    marker = '<form method="post" action="{{url_for(\'test_login\')}}"><button class="btn2">Testar login configurado</button></form>'
    form = '<form method="get" action="{{url_for(\'download_media_audio\')}}"><label>Link de mídia para MP3</label><input name="url" placeholder="Cole uma URL pública de mídia própria/autorizada" required><button>Converter mídia para MP3</button></form>\n' + marker
    s = s.replace(marker, form)

    route = '''

def valid_media_url(url):
    parsed = urlparse((url or "").strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)

@app.get("/download-media-audio")
@auth_required
def download_media_audio():
    url = (request.args.get("url") or "").strip()
    if not valid_media_url(url):
        flash("Envie uma URL valida.", "error")
        return redirect(url_for("index"))
    try:
        jid = uuid.uuid4().hex[:16]
        workdir = MEDIA_AUDIO_DIR / jid
        workdir.mkdir(parents=True, exist_ok=True)
        template = str(workdir / "source.%(ext)s")
        cmd = ["yt-dlp", "--no-playlist", "--max-filesize", "250M", "-x", "--audio-format", "mp3", "--audio-quality", "0", "-o", template, url]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=240)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "Erro desconhecido")[-1800:])
        files = list(workdir.glob("*.mp3"))
        if not files:
            raise RuntimeError("Nenhum MP3 foi encontrado depois do processamento.")
        return send_file(files[0], as_attachment=True, download_name=f"{jid}.mp3", max_age=0)
    except Exception as e:
        flash(f"Erro ao converter mídia para MP3: {type(e).__name__}: {e}", "error")
        return redirect(url_for("index"))
'''
    s = s.replace('\n@app.post("/download")', route + '\n@app.post("/download")')

p.write_text(s)
