"""Bedienseite für Handy/Tablet – eine einzige Datei ohne externe Abhängigkeiten
(funktioniert auch ohne Internet im Veranstaltungs-WLAN)."""

PAGE = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#1b1d21">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>AkustikMess Fernbedienung</title>
<style>
:root{--bg:#1b1d21;--panel:#26282d;--line:#3e424a;--text:#e6e6e6;--dim:#9aa0a6;--red:#ff5555;
--blue:#55aaff;--green:#66dd66;--yellow:#ffcc33;--alarm:#c62828}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:var(--bg);color:var(--text);font:15px/1.35 -apple-system,Segoe UI,Roboto,sans-serif}
body{padding:env(safe-area-inset-top) 10px calc(env(safe-area-inset-bottom) + 10px)}
header{display:flex;align-items:center;gap:8px;padding:8px 0;flex-wrap:wrap}
#conn{width:10px;height:10px;border-radius:50%;background:var(--red);flex:none}
#conn.ok{background:var(--green)}
#title{font-weight:600;flex:1;min-width:120px}
#levels{font:12px ui-monospace,Consolas,monospace;color:var(--dim);width:100%}
.row{display:flex;gap:8px;margin:8px 0;flex-wrap:wrap}
button{flex:1;min-height:48px;border:1px solid var(--line);border-radius:10px;background:var(--panel);
color:var(--text);font-size:15px;font-weight:600;padding:6px 10px;touch-action:manipulation}
button:active{filter:brightness(1.4)}
button.on{background:#1d5a2a;border-color:#2e8b45}
button.mute{background:var(--alarm);border-color:#e53935;flex:0 0 96px}
button.small{flex:0 0 56px}
nav{display:flex;gap:4px;margin:6px 0}
nav button{min-height:40px;font-size:14px;border-radius:8px}
nav button.sel{background:#2a4d78;border-color:#3f73b3}
.tab{display:none}.tab.sel{display:block}
canvas{width:100%;display:block;background:#111317;border-radius:8px;touch-action:none}
.readout{font:13px ui-monospace,Consolas,monospace;min-height:20px;color:var(--yellow);margin:4px 2px}
input{flex:1;min-height:44px;border-radius:10px;border:1px solid var(--line);background:#111317;
color:var(--text);font-size:16px;padding:0 10px;min-width:0}
#msg{position:fixed;left:10px;right:10px;bottom:calc(env(safe-area-inset-bottom) + 12px);padding:12px;
border-radius:10px;background:#2a4d78;display:none;text-align:center;font-weight:600;z-index:9}
.big{font-size:84px;font-weight:700;text-align:center;line-height:1.05;margin:6px 0}
.dim{color:var(--dim);font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(105px,1fr));gap:6px}
.tile{background:var(--panel);border-radius:8px;padding:6px 8px}
.tile b{display:block;font-size:22px}
table{border-collapse:collapse;width:100%;font-size:13px}
td,th{border-bottom:1px solid var(--line);padding:5px 4px;text-align:right}
th:first-child,td:first-child{text-align:left}
.sti{font-size:22px;font-weight:700;margin:8px 0}
.legend span{margin-right:10px;font-size:12px;white-space:nowrap}
</style>
</head>
<body>
<header>
  <div id="conn"></div><div id="title">AkustikMess</div>
  <div id="levels"></div>
</header>

<div class="row">
  <button id="bGen">Generator</button>
  <button class="small" data-cmd="gen_level" data-delta="-3">−3</button>
  <button class="small" data-cmd="gen_level" data-delta="3">+3</button>
  <button class="mute" data-cmd="mute">STUMM</button>
</div>
<div class="dim" id="genInfo"></div>

<nav>
  <button data-tab="tf" class="sel">Übertragung</button>
  <button data-tab="spec">Spektrum</button>
  <button data-tab="spl">SPL</button>
  <button data-tab="ir">Impuls</button>
</nav>

<section class="tab sel" id="tab-tf">
  <div class="readout" id="roTf"></div>
  <canvas id="cMag" height="260"></canvas>
  <canvas id="cCoh" height="60" style="margin-top:4px"></canvas>
  <canvas id="cPh" height="130" style="margin-top:4px"></canvas>
  <div class="legend" id="legend"></div>
  <div class="row">
    <input id="posName" placeholder="Position, z. B. „Reihe 10 links“" maxlength="60">
  </div>
  <div class="row">
    <button data-cmd="capture_tf" data-name>Kurve speichern</button>
    <button data-cmd="find_delay">Laufzeit finden</button>
    <button data-cmd="reset_avg">Mittelung neu</button>
  </div>
  <div class="dim" id="tfInfo"></div>
</section>

<section class="tab" id="tab-spec">
  <div class="readout" id="roSpec"></div>
  <canvas id="cSpec" height="300"></canvas>
  <div class="dim" id="peak" style="margin-top:6px"></div>
  <div class="row"><button data-cmd="capture_spec" data-name>Spektrum speichern</button>
  <button data-cmd="reset_avg">Mittelung neu</button></div>
</section>

<section class="tab" id="tab-spl">
  <div class="dim" id="splName" style="text-align:center"></div>
  <div class="big" id="splMain">–</div>
  <div class="tiles" id="splTiles"></div>
  <div class="row"><input id="note" placeholder="Notiz, z. B. „Band startet“" maxlength="120">
  <button class="small" id="bNote" style="flex:0 0 90px">Notiz</button></div>
  <div class="dim" id="splNotes"></div>
</section>

<section class="tab" id="tab-ir">
  <div class="row"><button data-cmd="ir_measure" id="bIr">Impulsantwort messen</button></div>
  <div class="dim" id="irStatus"></div>
  <div class="sti" id="irSti"></div>
  <table id="irTable"></table>
</section>

<div id="msg"></div>

<script>
"use strict";
const TOKEN = new URLSearchParams(location.search).get("t") || "";
const $ = id => document.getElementById(id);
let S = null, tab = "tf", cursor = {};
const NAMES = {"Deutsch (H)":["C","C♯","D","D♯","E","F","F♯","G","G♯","A","B","H"],
               "International (B)":["C","C♯","D","D♯","E","F","F♯","G","G♯","A","A♯","B"]};

function fmtF(f){return f<100?f.toFixed(2)+" Hz":f<1000?f.toFixed(1)+" Hz":Math.round(f)+" Hz"}
function note(f){
  if(!S||!(f>0))return "";
  const m=69+12*Math.log2(f/S.a4), n=Math.round(m), c=Math.round(100*(m-n));
  const names=NAMES[S.naming]||NAMES["Deutsch (H)"];
  return names[((n%12)+12)%12]+(Math.floor(n/12)-1)+" "+(c>=0?"+":"")+c+" ct";
}
function toast(t,ok=true){const m=$("msg");m.textContent=t;m.style.background=ok?"#2a4d78":"#8e2424";
  m.style.display="block";clearTimeout(toast.h);toast.h=setTimeout(()=>m.style.display="none",2200)}

async function cmd(action,args={}){
  try{
    const r=await fetch("/api/cmd",{method:"POST",headers:{"Content-Type":"application/json","X-Token":TOKEN},
      body:JSON.stringify({action,args})});
    const j=await r.json();
    toast(j.message||(j.ok?"OK":"Fehler"),j.ok);
    if(navigator.vibrate&&j.ok)navigator.vibrate(30);
    return j;
  }catch(e){toast("Keine Verbindung zum Laptop",false)}
}

async function poll(){
  try{
    const r=await fetch("/api/state",{headers:{"X-Token":TOKEN},cache:"no-store"});
    if(!r.ok)throw 0;
    S=await r.json(); $("conn").className="ok"; render();
    setTimeout(poll,S.running?280:1000);
  }catch(e){$("conn").className="";setTimeout(poll,1500)}
}

/* ---------- Diagramme ---------- */
const FMIN=20,FMAX=20000,LMIN=Math.log10(FMIN),LSPAN=Math.log10(FMAX)-LMIN;
const GRID_F=[20,50,100,200,500,1000,2000,5000,10000,20000];
function setupCanvas(c){
  // Grundhöhe einmal merken: c.height wird unten auf Gerätepixel gesetzt und überschreibt das Attribut
  if(!c.dataset.h)c.dataset.h=c.getAttribute("height");
  const d=window.devicePixelRatio||1,w=c.clientWidth,h=+c.dataset.h;
  if(c.width!==Math.round(w*d)){c.width=Math.round(w*d);c.height=Math.round(h*d);c.style.height=h+"px"}
  const g=c.getContext("2d");g.setTransform(d,0,0,d,0,0);return [g,w,h];
}
function plot(c,series,ymin,ymax,ystep,unit,curF){
  const [g,w,h]=setupCanvas(c),L=30,R=4,T=4,B=16,pw=w-L-R,ph=h-T-B;
  const X=f=>L+pw*(Math.log10(f)-LMIN)/LSPAN, Y=v=>T+ph*(1-(v-ymin)/(ymax-ymin));
  g.clearRect(0,0,w,h);g.font="10px sans-serif";g.lineWidth=1;
  g.strokeStyle="#33373e";g.fillStyle="#8a9099";
  for(const f of GRID_F){const x=X(f);g.beginPath();g.moveTo(x,T);g.lineTo(x,T+ph);g.stroke();
    const lab=f>=1000?f/1000+"k":String(f),tw=g.measureText(lab).width;
    g.fillText(lab,Math.min(x-tw/2,w-tw-1),h-3)}
  for(let v=Math.ceil(ymin/ystep)*ystep;v<=ymax;v+=ystep){const y=Y(v);
    g.beginPath();g.moveTo(L,y);g.lineTo(L+pw,y);g.stroke();g.fillText(String(+v.toFixed(2)),2,y+3)}
  g.save();g.beginPath();g.rect(L,T,pw,ph);g.clip();
  for(const s of series){
    if(!s||!s.x||!s.x.length)continue;
    g.strokeStyle=s.color;g.lineWidth=s.width||1.5;
    if(s.fill){g.fillStyle=s.fill}
    g.beginPath();let pen=false;
    for(let i=0;i<s.y.length;i++){
      const v=s.y[i];if(v===null){pen=false;continue}
      const yy=Y(v);
      if(s.stepped){const x0=X(s.x[i]),x1=X(s.x[i+1]);
        if(!pen){g.moveTo(x0,yy);pen=true}else g.lineTo(x0,yy);g.lineTo(x1,yy)}
      else{const xx=X(s.x[i]);if(!pen){g.moveTo(xx,yy);pen=true}else g.lineTo(xx,yy)}
    }
    g.stroke();
    if(s.fill){g.lineTo(X(s.x[s.x.length-1]),T+ph);g.lineTo(X(s.x[0]),T+ph);g.closePath();g.fill()}
  }
  if(curF){g.strokeStyle="#ffffffaa";g.setLineDash([4,4]);g.beginPath();g.moveTo(X(curF),T);
    g.lineTo(X(curF),T+ph);g.stroke();g.setLineDash([])}
  g.restore();
  c._map={L,pw};
}
function valueAt(xs,ys,f,stepped){
  if(!xs||!xs.length)return null;
  if(stepped){for(let i=0;i<ys.length;i++)if(f>=xs[i]&&f<xs[i+1])return ys[i];return null}
  let best=0,bd=1e9;for(let i=0;i<xs.length;i++){const d=Math.abs(Math.log(xs[i]/f));if(d<bd){bd=d;best=i}}
  return ys[best];
}
function attachCursor(c,key){
  const h=e=>{const r=c.getBoundingClientRect(),t=e.touches?e.touches[0]:e,m=c._map;if(!m)return;
    const fr=Math.min(1,Math.max(0,(t.clientX-r.left-m.L)/m.pw));
    cursor[key]=Math.pow(10,LMIN+fr*LSPAN);render();e.preventDefault()};
  c.addEventListener("touchstart",h,{passive:false});c.addEventListener("touchmove",h,{passive:false});
  c.addEventListener("mousedown",h);
}
function autoRange(f,y,span){
  const v=[];for(let i=0;i<f.length;i++)if(y[i]!==null&&f[i]>200&&f[i]<5000)v.push(y[i]);
  if(!v.length)return [-30,15];v.sort((a,b)=>a-b);const m=Math.round(v[v.length>>1]/6)*6;
  return [m-span*0.6,m+span*0.4];
}

/* ---------- Darstellung ---------- */
let magRange=null;
function render(){
  if(!S)return;
  $("title").textContent="AkustikMess · "+(S.running?"misst":"Audio gestoppt");
  $("levels").textContent=(S.levels||[]).map((v,i)=>"E"+(i+1)+" "+v.toFixed(0)+(v>-0.5?" ÜBERSTEUERT":"")).join("   ");
  const gb=$("bGen");gb.textContent=S.gen.on?"Generator AUS":"Generator EIN";gb.className=S.gen.on?"on":"";
  $("genInfo").textContent=S.gen.name+" · "+S.gen.level.toFixed(1)+" dBFS (Grenze "+S.gen.limit+" dBFS)";
  if(tab==="tf")renderTf();else if(tab==="spec")renderSpec();else if(tab==="spl")renderSpl();else renderIr();
}
function renderTf(){
  const t=S.tf,tr=S.traces||[];
  if(!t){$("tfInfo").textContent=S.status||"Keine Übertragungsfunktion";return}
  if(!magRange||(S.now%5<0.3))magRange=autoRange(t.f,t.mag,48);
  const series=tr.map(x=>({x:x.f,y:x.mag,color:x.color,width:1}));
  series.push({x:t.f,y:t.mag,color:"#ff5555",width:2});
  const cf=cursor.tf;
  plot($("cMag"),series,magRange[0],magRange[1],6,"dB",cf);
  plot($("cCoh"),[{x:t.f,y:t.coh,color:"#ff5555",width:1}],0,1,0.5,"",cf);
  plot($("cPh"),[...tr.map(x=>({x:x.f,y:x.ph,color:x.color,width:1})),{x:t.f,y:t.ph,color:"#ff5555"}],-180,180,90,"°",cf);
  $("legend").innerHTML=tr.map(x=>'<span style="color:'+x.color+'">■ '+esc(x.name)+'</span>').join("");
  $("tfInfo").textContent=S.status||"";
  if(cf){const m=valueAt(t.f,t.mag,cf),c=valueAt(t.f,t.coh,cf);
    $("roTf").textContent=fmtF(cf)+" · "+note(cf)+" · "+(m===null?"–":m.toFixed(1)+" dB")+" · Koh. "+(c===null?"–":c.toFixed(2))}
  else $("roTf").textContent="Diagramm antippen: genaue Frequenz und Note";
}
function renderSpec(){
  const s=S.spec;if(!s)return;
  const top=Math.ceil(Math.max(...s.lv.filter(v=>v!==null))/10)*10+10;
  plot($("cSpec"),[{x:s.f,y:s.lv,color:"#55aaff",width:1.5,stepped:s.stepped,fill:"#55aaff33"}],top-90,top,10,s.unit,cursor.spec);
  $("peak").textContent=S.peak||"";
  if(cursor.spec){const v=valueAt(s.f,s.lv,cursor.spec,s.stepped);
    $("roSpec").textContent=fmtF(cursor.spec)+" · "+note(cursor.spec)+" · "+(v===null?"–":v.toFixed(1)+" "+s.unit)}
  else $("roSpec").textContent="Diagramm antippen: genaue Frequenz und Note";
}
function renderSpl(){
  const p=S.spl;if(!p)return;
  $("splName").textContent=p.main+" ["+p.unit+"]"+(p.calibrated?"":" – nicht kalibriert");
  const v=p.value,el=$("splMain");el.textContent=v===null?"–":v.toFixed(1);
  el.style.color=v===null?"#e6e6e6":v>=p.alarm?"#ff4444":v>=p.warn?"#ffcc33":"#66dd66";
  $("splTiles").innerHTML=p.tiles.map(t=>'<div class="tile"><span class="dim">'+esc(t[0])+'</span><b>'+
    (t[1]===null?"–":t[1].toFixed(1))+'</b></div>').join("");
  $("splNotes").innerHTML=(p.notes||[]).map(esc).join("<br>");
}
function renderIr(){
  const r=S.ir;if(!r)return;
  $("bIr").disabled=r.busy;$("bIr").textContent=r.busy?"Messung läuft …":"Impulsantwort messen";
  $("irStatus").textContent=r.status||"";$("irSti").textContent=r.sti||"";
  if(r.table){const b=r.table.bands;let h="<tr><th></th>"+b.map(x=>"<th>"+esc(x)+"</th>").join("")+"</tr>";
    for(const [name,vals] of r.table.rows)h+="<tr><td>"+esc(name)+"</td>"+vals.map(v=>"<td>"+(v===null?"–":v)+"</td>").join("")+"</tr>";
    $("irTable").innerHTML=h}
}
function esc(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}

/* ---------- Bedienung ---------- */
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>{
  tab=b.dataset.tab;document.querySelectorAll("nav button").forEach(x=>x.classList.toggle("sel",x===b));
  document.querySelectorAll(".tab").forEach(s=>s.classList.toggle("sel",s.id==="tab-"+tab));render()});
document.querySelectorAll("button[data-cmd]").forEach(b=>b.onclick=()=>{
  const a={};if(b.dataset.delta)a.delta=+b.dataset.delta;
  if("name" in b.dataset)a.name=$("posName").value.trim();
  cmd(b.dataset.cmd,a)});
$("bGen").onclick=()=>cmd("gen_toggle");
$("bNote").onclick=()=>{const t=$("note").value.trim();if(t){cmd("spl_note",{text:t});$("note").value=""}};
attachCursor($("cMag"),"tf");attachCursor($("cPh"),"tf");attachCursor($("cCoh"),"tf");attachCursor($("cSpec"),"spec");
window.addEventListener("resize",render);
if(!TOKEN)toast("Zugangsschlüssel fehlt – QR-Code in AkustikMess scannen",false);
poll();
</script>
</body>
</html>
"""
