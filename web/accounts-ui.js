const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function request(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Fuel-App':'1'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error);return d}
try{
 const response=await fetch('/api/auth/me');const auth=await response.json();
 if(auth.enabled&&!auth.user)location.replace('/login.html');
 if(auth.enabled&&auth.user){
  window.fuelUser=auth.user;
  const panel=document.createElement('div');panel.className='card';panel.style.marginBottom='20px';
  panel.innerHTML=`<div class="split-title"><div><strong>Perfil: ${esc(auth.user.name)}</strong><br><small>Usuario ${esc(auth.user.username)} · Cambios guardados en tu espacio independiente</small></div><div>${auth.user.admin?'<button id="invite-user">Invitar a probar</button> ':''}<button id="account-password">Cambiar contraseña</button> <button id="account-logout">Cerrar sesión</button></div></div>`;
  document.querySelector('main').prepend(panel);
  document.querySelector('.sidebar-foot').innerHTML='<span class="local-dot"></span> Perfil personal<small>Datos y cambios persistentes</small>';
  document.querySelector('#account-logout').onclick=async()=>{await request('/api/auth/logout',{});location.replace('/login.html')};
  function dialog(content){const d=document.createElement('dialog');d.innerHTML=content+'<button type="button" class="close-account">Cerrar</button>';document.body.append(d);d.querySelector('.close-account').onclick=()=>{d.close();d.remove()};d.showModal();return d}
  if(auth.user.admin)document.querySelector('#invite-user').onclick=()=>{
   const d=dialog('<h1>Invitar a probar la plataforma</h1><p>Crearemos una copia de tus datos actuales y sus documentos originales. Los cambios de esa persona se guardarán en su propio perfil.</p><form><label>Nombre del perfil<input name="name" required maxlength="100" placeholder="Nombre de tu amigo"></label><p><button class="primary">Crear enlace de invitación</button></p><div role="alert"></div></form>');
   d.querySelector('form').onsubmit=async ev=>{ev.preventDefault();const f=ev.target,b=f.querySelector('button');b.disabled=true;try{const r=await request('/api/auth/invite',{name:f.elements.name.value});const link=new URL(r.invitation,location.origin).href;f.innerHTML=`<p>Enlace válido por 48 horas y para un solo registro. Compártelo únicamente con la persona invitada; podrá elegir su contraseña.</p><label>Invitación<input readonly value="${esc(link)}"></label><p><button type="button">Copiar enlace</button></p>`;f.querySelector('button').onclick=async()=>{try{await navigator.clipboard.writeText(link);f.querySelector('button').textContent='Copiado'}catch{f.querySelector('input').select()}}}catch(err){f.querySelector('[role=alert]').textContent=err.message;b.disabled=false}};
  };
  document.querySelector('#account-password').onclick=()=>{
   const d=dialog('<h1>Cambiar contraseña</h1><form><label>Contraseña actual<input name="password" type="password" autocomplete="current-password" required></label><label>Nueva contraseña<input name="new_password" type="password" autocomplete="new-password" minlength="12" maxlength="200" required></label><p>Se cerrarán las sesiones abiertas. Tus datos se conservarán.</p><button class="primary">Guardar contraseña</button><p role="alert"></p></form>');
   d.querySelector('form').onsubmit=async ev=>{ev.preventDefault();try{await request('/api/auth/password',Object.fromEntries(new FormData(ev.target)));location.replace('/login.html')}catch(err){d.querySelector('[role=alert]').textContent=err.message}};
  };
 }
}catch(err){console.error('No se pudo consultar la cuenta',err)}
