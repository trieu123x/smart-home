'use strict';
const form=document.querySelector('#loginForm');
const notice=document.querySelector('#notice');
function show(t){notice.hidden=!t;notice.textContent=t;}
fetch('/api/auth/session').then(r=>r.json()).then(info=>{
  if(!info.configured) show('Máy chủ chưa cấu hình mật khẩu. Trên máy tính server, tạo file .env và đặt FALLGUARD_PASSWORD có ít nhất 12 ký tự, sau đó khởi động lại.');
}).catch(()=>show('Không liên hệ được server.'));
form.addEventListener('submit',async event=>{
  event.preventDefault();show('');
  const button=document.querySelector('#submit');button.disabled=true;
  try{
    const response=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:document.querySelector('#password').value})});
    if(!response.ok){const data=await response.json();throw new Error(data.detail||'Đăng nhập không thành công.');}
    const next=new URLSearchParams(location.search).get('next');
    location.replace('/');
  }catch(e){show(e.message);}finally{button.disabled=false;}
});
