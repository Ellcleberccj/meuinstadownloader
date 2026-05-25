import re
from pathlib import Path

OLD_UPLOAD_FORM = '''<form method="post" action="{{url_for('upload_ref_tts_r2')}}"><input type="hidden" name="filename" value="{{filename}}"><input type="hidden" name="reference_text" value="{{reference_text}}">{% if regenerate %}<input type="hidden" name="regenerate_action" value="{{regenerate.action_url}}">{% for name, value in regenerate.fields.items() %}<input type="hidden" name="regen_{{name}}" value="{{value}}">{% endfor %}{% endif %}<button class="btn" type="submit">Upload no Cloudflare R2 bucket</button></form>'''
NEW_UPLOAD_FORM = '''<form id="r2UploadForm" method="post" action="{{url_for('upload_ref_tts_r2')}}"><input type="hidden" name="filename" value="{{filename}}"><button class="btn" type="button" onclick="uploadR2(this)">Upload no Cloudflare R2 bucket</button></form>'''

OLD_R2_BOX = '''{% if r2_url %}<div class="cloudbox"><h2>Link público no Cloudflare R2</h2><input id="r2Link" readonly value="{{r2_url}}"><div class="actions"><a class="btn" href="{{r2_url}}" target="_blank" rel="noopener">Abrir link público</a><button class="btn btn2" type="button" onclick="copyR2Link()">Copiar link</button></div></div>{% endif %}'''
NEW_R2_BOX = '''<div id="r2Box" class="cloudbox" {% if not r2_url %}style="display:none"{% endif %}><h2>Link público no Cloudflare R2</h2><input id="r2Link" readonly value="{{r2_url}}"><div class="actions"><a id="r2OpenLink" class="btn" href="{{r2_url or '#'}}" target="_blank" rel="noopener">Abrir link público</a><button class="btn btn2" type="button" onclick="copyR2Link()">Copiar link</button></div><div id="r2Status" class="status"></div></div>'''

OLD_COPY_FN = "function copyR2Link(){const el=document.getElementById('r2Link');if(!el)return;el.select();el.setSelectionRange(0,99999);navigator.clipboard&&navigator.clipboard.writeText?navigator.clipboard.writeText(el.value):document.execCommand('copy')}"
NEW_R2_JS = """function setR2Link(url){const box=document.getElementById('r2Box');const input=document.getElementById('r2Link');const open=document.getElementById('r2OpenLink');const status=document.getElementById('r2Status');if(box)box.style.display='block';if(input)input.value=url;if(open)open.href=url;if(status)status.textContent='Upload concluído. Link público pronto para copiar.'}
async function uploadR2(button){const form=button.closest('form');const status=document.getElementById('r2Status');const original=button.innerHTML;try{button.disabled=true;button.innerHTML='<span class=\"spin\"></span>Enviando...';const box=document.getElementById('r2Box');if(box)box.style.display='block';if(status)status.textContent='Enviando para o Cloudflare R2...';const resp=await fetch(form.action,{method:'POST',body:new FormData(form),credentials:'same-origin',headers:{'Accept':'application/json','X-Requested-With':'fetch'}});const data=await resp.json().catch(()=>({}));if(!resp.ok||!data.ok){throw new Error(data.error||('HTTP '+resp.status))}setR2Link(data.url);copyR2Link()}catch(e){if(status)status.textContent='Erro ao enviar: '+e.message;alert('Erro ao enviar para o Cloudflare R2: '+e.message)}finally{button.disabled=false;button.innerHTML=original}}
function copyR2Link(){const el=document.getElementById('r2Link');const status=document.getElementById('r2Status');if(!el||!el.value)return;el.select();el.setSelectionRange(0,99999);if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(el.value).then(()=>{if(status)status.textContent='Link copiado.'}).catch(()=>document.execCommand('copy'))}else{document.execCommand('copy');if(status)status.textContent='Link copiado.'}}"""

UPLOAD_HELPERS = '''

def wants_json_response():
    accept = request.headers.get("Accept", "")
    requested_with = request.headers.get("X-Requested-With", "")
    return requested_with == "fetch" or "application/json" in accept


def r2_json_response(payload, status=200):
    return Response(json.dumps(payload, ensure_ascii=False), status=status, mimetype="application/json")

'''

UPLOAD_FUNCTION = '''def upload_ref_tts_r2():
    if request.method == "GET":
        flash("Use o botão Upload no Cloudflare R2 na página do áudio gerado.", "error")
        return redirect(url_for("index"))

    filename = (request.form.get("filename") or "").strip()
    path = ref_tts_path(filename)
    if path is None:
        if wants_json_response():
            return r2_json_response({"ok": False, "error": "MP3 gerado não encontrado para upload."}, 404)
        flash("MP3 gerado não encontrado para upload.", "error")
        return redirect(url_for("index"))
    try:
        r2_url = upload_mp3_to_r2(path, filename)
        if wants_json_response():
            return r2_json_response({"ok": True, "url": r2_url, "filename": filename})
        flash("Upload para o Cloudflare R2 concluído.", "ok")
        return render_audio_result(filename, "", None, r2_url)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        if wants_json_response():
            return r2_json_response({"ok": False, "error": message}, 500)
        flash(f"Erro ao enviar para o Cloudflare R2: {message}", "error")
        return render_audio_result(filename)
'''


def patch_reference_tts(text):
    text = text.replace(OLD_UPLOAD_FORM, NEW_UPLOAD_FORM)
    text = text.replace(OLD_R2_BOX, NEW_R2_BOX)
    text = text.replace(OLD_COPY_FN, NEW_R2_JS)
    text = text.replace(
        'app.add_url_rule("/upload-r2-audio", "upload_ref_tts_r2", auth_required(upload_ref_tts_r2), methods=["POST"])',
        'app.add_url_rule("/upload-r2-audio", "upload_ref_tts_r2", auth_required(upload_ref_tts_r2), methods=["GET", "POST"])',
    )
    if "def wants_json_response():" not in text:
        text = text.replace("\ndef upload_ref_tts_r2():", UPLOAD_HELPERS + "\ndef upload_ref_tts_r2():", 1)
    text = re.sub(
        r'def upload_ref_tts_r2\(\):\n.*?\n\ndef ref_tts_path\(filename\):',
        UPLOAD_FUNCTION + "\n\ndef ref_tts_path(filename):",
        text,
        count=1,
        flags=re.S,
    )
    return text


path = Path("reference_tts.py")
if path.exists():
    before = path.read_text(encoding="utf-8")
    after = patch_reference_tts(before)
    if after != before:
        path.write_text(after, encoding="utf-8")
        print("Patched R2 upload to inline JSON flow")

    final = path.read_text(encoding="utf-8")
    required = [
        'id="r2UploadForm"',
        'onclick="uploadR2(this)"',
        'def wants_json_response():',
        'methods=["GET", "POST"]',
        'return r2_json_response({"ok": True, "url": r2_url, "filename": filename})',
    ]
    missing = [item for item in required if item not in final]
    if missing:
        raise RuntimeError("Failed to patch R2 inline upload flow: " + ", ".join(missing))
