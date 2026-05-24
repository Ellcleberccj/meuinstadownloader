from pathlib import Path

p = Path('app.py')
s = p.read_text()
old = """document.addEventListener('DOMContentLoaded',()=>{document.querySelectorAll('form').forEach(f=>f.addEventListener('submit',()=>{let b=f.querySelector('button');let l=document.getElementById('loadingBox');if(b){b.disabled=true;b.innerHTML='<span class=\"spin\"></span>Processando...'}if(l){l.style.display='block';l.innerHTML='<span class=\"spin\"></span>Preparando. Aguarde, o download ou preview vai abrir automaticamente.'}}))})"""
new = """document.addEventListener('DOMContentLoaded',()=>{document.querySelectorAll('form').forEach(f=>f.addEventListener('submit',()=>{let b=f.querySelector('button');let l=document.getElementById('loadingBox');let oldText=b?b.innerHTML:'';let isDownload=(f.getAttribute('action')||'').includes('download');if(b){b.disabled=true;b.innerHTML='<span class=\"spin\"></span>Processando...'}if(l){l.style.display='block';l.innerHTML='<span class=\"spin\"></span>'+(isDownload?'Preparando download. Ele deve iniciar em instantes.':'Preparando preview. Aguarde...')}if(isDownload){setTimeout(()=>{if(b){b.disabled=false;b.innerHTML=oldText}if(l){l.innerHTML='Download iniciado. Se não abriu, tente clicar novamente.';setTimeout(()=>l.style.display='none',3500)}},9000)}}))})"""
if old in s:
    p.write_text(s.replace(old, new))
