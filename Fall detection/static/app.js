'use strict';
const $ = id => document.getElementById(id);
let camera = null, liveUrl = null, lastSeq = 0, eventIds = new Set(), pollTimer = null;
let audioCtx = null, alarmTimer = null, alarmMuted = false, activeAlarm = false;
let tracks = [], alarmSince = 0, statusBusy = false, operationBusy = false;

function notice(text='') { $('message').textContent = text; $('message').hidden = !text; }
async function api(path, opts={}) {
  const response = await fetch(path, {credentials:'same-origin', cache:'no-store', ...opts});
  if(response.status===401) { location.href='/login'; throw Error('Cần đăng nhập lại.'); }
  if(!response.ok) {
    const result = await response.json().catch(()=>({}));
    throw Error(result.detail || `Lỗi máy chủ: ${response.status}`);
  }
  return response.json();
}
async function action(path, data=null) {
  if(operationBusy) return;
  operationBusy=true;
  try {
    await api(path, {method:'POST', headers:data?{'Content-Type':'application/json'}:{}, body:data?JSON.stringify(data):undefined});
    notice(''); await refresh();
  } catch(e) { notice(e.message); }
  finally { operationBusy=false; }
}
function statusText(title, detail, danger=false) {
  $('statusTitle').textContent=title; $('statusDescription').textContent=detail;
  $('statusIcon').textContent=danger?'!':'◌';
  $('statusIcon').style.color=danger?'#b72d38':'';
}
async function ensureAudio() {
  try {
    const Audio=window.AudioContext||window.webkitAudioContext;
    if(!Audio) return;
    audioCtx ||= new Audio(); await audioCtx.resume();
  } catch (_) {}
}
function beep(){
  if(!audioCtx||audioCtx.state!=='running')return;
  const osc=audioCtx.createOscillator(),g=audioCtx.createGain(),t=audioCtx.currentTime;
  osc.frequency.value=830;g.gain.setValueAtTime(0.08,t);g.gain.exponentialRampToValueAtTime(.001,t+.23);
  osc.connect(g);g.connect(audioCtx.destination);osc.start(t);osc.stop(t+.23);
}
function alarm(on){
  if(!on){alarmMuted=false;}
  activeAlarm=on;$('alertBanner').hidden=!on;
  const sound=on&&!alarmMuted&&$('sound').checked;
  if(sound&&!alarmTimer){beep();alarmTimer=setInterval(beep,2300);}
  if(!sound&&alarmTimer){clearInterval(alarmTimer);alarmTimer=null;}
}
function renderTracks(){
  const canvas=$('output'), img=$('cctvImage'), wrap=$('viewport');
  if(img.hidden||!camera?.analysis_enabled||!tracks.length){canvas.hidden=true;return;}
  canvas.hidden=false;const ctx=canvas.getContext('2d');
  const w=wrap.clientWidth,h=wrap.clientHeight;
  if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}
  ctx.clearRect(0,0,w,h);
  const iw=img.naturalWidth||16,ih=img.naturalHeight||9,scale=Math.min(w/iw,h/ih);
  const vw=iw*scale,vh=ih*scale,ox=(w-vw)/2,oy=(h-vh)/2;
  ctx.font='bold 12px sans-serif';ctx.lineWidth=2.5;
  for(const t of tracks){
    const b=t.box;if(!Array.isArray(b)||b.length!==4)continue;
    const x=ox+b[0]*vw,y=oy+b[1]*vh,bw=(b[2]-b[0])*vw,bh=(b[3]-b[1])*vh;
    const color=t.danger?'#ff4e59':t.pending?'#ffc34d':'#40db9f';
    ctx.strokeStyle=color;ctx.strokeRect(x,y,bw,bh);
    const label=t.danger?'ĐÃ XÁC NHẬN NGÃ':t.pending?`Đang xác nhận ${Number(t.fall_elapsed||0).toFixed(1)} / 5s`:`Người #${t.id}`;
    const labelWidth=ctx.measureText(label).width+14;
    ctx.fillStyle='#10242bcc';ctx.fillRect(x,Math.max(0,y-24),labelWidth,22);
    ctx.fillStyle=color;ctx.fillText(label,x+7,Math.max(15,y-8));
  }
}
function displayEvents(events){
  const container=$('events');container.replaceChildren();
  $('eventCount').textContent=String(events.length);$('eventsEmpty').hidden=events.length>0;
  for(const e of events){
    const li=document.createElement('li'),icon=document.createElement('span'),text=document.createElement('div'),label=document.createElement('strong'),time=document.createElement('small');
    icon.className='event-mark';icon.textContent='!';text.className='event-info';
    label.textContent=`${e.source||'Camera'} · Người #${e.id}`;
    time.textContent=`${new Date(e.time).toLocaleString('vi-VN')} · độ tin cậy ${Math.round((e.score||0)*100)}%`;
    const delivery=document.createElement('small');
    const deliveryLabels={queued:'Đang xếp hàng',sending:'Đang gửi',sent:'Đã gửi Telegram',retrying:'Đang thử lại',error:'Lỗi gửi Telegram',not_configured:'Thiếu Gateway',cooldown:'Đã gửi gần đây'};
    delivery.textContent='Telegram: '+(deliveryLabels[e.telegram]||'Chưa rõ');
    text.append(label,time,delivery);li.append(icon,text);container.append(li);
  }
}
async function refresh(){
  if(statusBusy)return;statusBusy=true;
  try{
    const data=await api('/api/cctv/view'); camera=data.camera;
    const s=camera.state;
    const stateLabel={stopped:'Chưa kết nối',connecting:'Đang kết nối',connected:'Đang xem trực tiếp',reconnecting:'Mất hình · đang kết nối lại'}[s]||s;
    $('cctvName').textContent=camera.name;
    $('cctvState').textContent=stateLabel;$('cameraTitle').textContent=`${camera.name} · ${stateLabel}`;
    $('cameraDot').classList.toggle('active',s==='connected');
    $('serverDot').classList.add('ready');$('serverState').textContent='Server đã kết nối';
    $('start').disabled=!camera.configured||camera.enabled;
    $('stop').disabled=!camera.enabled;
    $('aiAnalysis').checked=Boolean(camera.analysis_enabled);
    $('aiAnalysisText').textContent=camera.analysis_enabled?'AI đang bật':'AI đã tắt';
    $('thresholdValue').textContent=`${Math.round(camera.threshold*100)}%`;
    $('confirmFrames').textContent=`${camera.confirmations} lần nhận diện`;
    $('testTelegram').disabled=camera.telegram==='not_configured';
    $('telegramState').textContent=({not_configured:'Chưa cấu hình',configured:'Sẵn sàng',sending:'Đang gửi',sent:'Đã gửi',retrying:'Đang thử lại',error:'Lỗi',cooldown:'Chống gửi lặp'})[camera.telegram]||camera.telegram;
    $('telegramDetail').textContent=camera.telegram_detail||'';
    $('feedState').textContent=s==='connected'?'Đang nhận hình ảnh':stateLabel;
    $('frameAge').textContent=camera.frame_age==null?'Chưa có khung hình':`Khung hình cách đây ${Number(camera.frame_age).toFixed(1)} giây`;
    const live=s==='connected';$('emptyCamera').hidden=live;
    $('cctvImage').hidden=!live;$('frameTag').hidden=!live;
    $('fullscreenCamera').disabled=!live;
    $('frameText').textContent=camera.analysis_enabled?'LIVE · AI đang phân tích':'LIVE · Chỉ xem';
    tracks=(!camera.analysis_enabled||!live||!data.view||data.view.age>2)?[]:data.view.tracks;
    const danger=tracks.some(t=>t.danger);
    alarm(danger&&!document.hidden);
    if(!live)statusText('Chưa có tín hiệu','Kiểm tra Streamlabs / Larix và MediaMTX.');
    else if(!camera.analysis_enabled)statusText('Chỉ xem trực tiếp','AI đang tắt, hình ảnh vẫn truyền bình thường.');
    else if(danger)statusText('Đã xác nhận ngã','Người nằm/ngã liên tục ít nhất 5 giây.',true);
    else if(tracks.some(t=>t.pending)){
      const elapsed=Math.max(...tracks.filter(t=>t.pending).map(t=>Number(t.fall_elapsed)||0));
      statusText('Đang kiểm tra tư thế',`Phát hiện nghi ngã ${elapsed.toFixed(1)}/5.0 giây. Chưa gửi cảnh báo.`);
    }else statusText('Đang phân tích',tracks.length? 'Chưa xác nhận ngã.':'Chưa phát hiện người.');
    $('peopleCount').textContent=camera.analysis_enabled?String(tracks.length):'—';
    displayEvents(data.events||[]);renderTracks();
  }catch(e){$('serverDot').classList.remove('ready');$('serverState').textContent='Mất kết nối';notice(e.message);}
  finally{statusBusy=false;}
}
async function pollVideo(){
  try{
    if(camera?.state==='connected'){
      const response=await fetch(`/api/cctv/frame?seq=${lastSeq}`, {cache:'no-store',signal:AbortSignal.timeout(5500)});
      if(response.status===401){location.href='/login';return;}
      if(response.ok&&response.status===200){
        const blob=await response.blob(),url=URL.createObjectURL(blob),img=$('cctvImage');
        img.onload=()=>{const old=liveUrl;liveUrl=url;if(old)URL.revokeObjectURL(old);renderTracks();};
        img.src=url;img.hidden=false;
        lastSeq=Number(response.headers.get('X-Frame-Sequence')||lastSeq);
        if(img.naturalWidth&&img.naturalHeight)$('viewport').style.setProperty('--video-ratio',`${img.naturalWidth} / ${img.naturalHeight}`);
      }
    }
  }catch(_){}
  finally{setTimeout(pollVideo,250);}
}
$('start').onclick=()=>action('/api/cctv/start');
$('stop').onclick=()=>action('/api/cctv/stop');
$('aiAnalysis').onchange=async e=>{await ensureAudio();await action('/api/cctv/analysis',{enabled:e.target.checked});};
$('acknowledge').onclick=()=>{alarmMuted=true;alarm(activeAlarm);};
$('sound').onchange=async()=>{await ensureAudio();alarm(activeAlarm);};
$('testSound').onclick=async()=>{await ensureAudio();beep();};
$('testTelegram').onclick=async()=>{
  if(operationBusy)return;operationBusy=true;
  try{const result=await api('/api/telegram/test',{method:'POST'});
    notice(`Đã gửi tin thử đến ${result.recipients||0} người đăng ký.`);
  }catch(e){notice('Kiểm tra Telegram thất bại: '+e.message);}
  finally{operationBusy=false;await refresh();}
};
$('fullscreenCamera').onclick=()=>{const v=$('viewport');v.classList.add('expanded');document.body.classList.add('camera-expanded');renderTracks();};
$('closeFullscreen').onclick=()=>{const v=$('viewport');v.classList.remove('expanded');document.body.classList.remove('camera-expanded');renderTracks();};
document.addEventListener('visibilitychange',()=>{if(document.hidden)alarm(false);});
window.addEventListener('resize',renderTracks);
window.addEventListener('pagehide',()=>{if(liveUrl)URL.revokeObjectURL(liveUrl);if(alarmTimer)clearInterval(alarmTimer);});
refresh();setInterval(refresh,900);pollVideo();
