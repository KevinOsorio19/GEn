const form=document.querySelector('#login-form');
const invitation=new URLSearchParams(location.hash.slice(1)).get('invite');
if(invitation){
 history.replaceState(null,'',location.pathname);
 document.querySelector('#login-title').textContent='Crear tu acceso privado';
 document.querySelector('#login-help').textContent='Tu perfil ya incluye una copia de los datos compartidos. Elige tu usuario y una contraseña de al menos 12 caracteres. Tus cambios serán independientes.';
 document.querySelector('#confirm-label').hidden=false;form.elements.confirm.required=true;
 form.elements.password.autocomplete='new-password';document.querySelector('#login-submit').textContent='Crear cuenta';
}
form.onsubmit=async ev=>{
 ev.preventDefault();const error=document.querySelector('#login-error'),button=document.querySelector('#login-submit');error.textContent='';
 if(invitation&&form.elements.password.value!==form.elements.confirm.value){error.textContent='Las contraseñas no coinciden';return}
 button.disabled=true;
 try{
  const r=await fetch('/api/auth/'+(invitation?'accept':'login'),{method:'POST',headers:{'Content-Type':'application/json','X-Fuel-App':'1'},body:JSON.stringify({token:invitation,username:form.elements.username.value,password:form.elements.password.value})});
  const data=await r.json();if(!r.ok)throw Error(data.error);location.replace('/#dashboard');
 }catch(err){error.textContent=err.message}finally{button.disabled=false}
};
