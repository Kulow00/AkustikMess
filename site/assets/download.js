// Download-Bereich der Startseite: Betriebssystem erkennen, passende Datei und Patch Notes anzeigen.
// Liest releases.json (signiert; die Signatur prüft das Programm, hier nur Anzeige).
"use strict";
const LABEL={windows:"Windows",macos:"macOS",linux:"Linux"};
const HINT={
 windows:"Nach dem Download die Datei starten. Es werden keine Administratorrechte benötigt; Updates installiert "+
   "das Programm danach selbst (nach deiner Zustimmung beim ersten Start). Bei einer ganz neuen Version kann "+
   "SmartScreen „Der Computer wurde durch Windows geschützt“ melden: <b>Weitere Informationen → Trotzdem ausführen</b>.",
 macos:"Nach dem Download die <code>.pkg</code>-Datei öffnen. Falls macOS den Start blockiert: "+
   "<b>Rechtsklick → Öffnen</b> bzw. Systemeinstellungen → Datenschutz &amp; Sicherheit → „Dennoch öffnen“. "+
   "Beim ersten Start den Mikrofonzugriff erlauben.",
 linux:"Für Linux gibt es noch kein Installationspaket."};
let data=null,channel="stable";
function detectOS(){
  const p=(navigator.userAgentData&&navigator.userAgentData.platform)||navigator.platform||"";
  const ua=navigator.userAgent;
  if(/win/i.test(p)||/Windows/.test(ua))return "windows";
  if(/mac/i.test(p)||/Mac OS X/.test(ua))return /iPhone|iPad/.test(ua)?"ios":"macos";
  if(/Android/.test(ua))return "android";
  if(/linux/i.test(p))return "linux";
  return "windows";
}
const OS=detectOS();
function vkey(v){const m=v.match(/^(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?$/);if(!m)return [0];
  return [+m[1],+m[2],+m[3],{alpha:0,beta:1,rc:2}[m[4]]??3,+(m[5]||0)]}
function cmp(a,b){a=vkey(a);b=vkey(b);for(let i=0;i<5;i++){if((a[i]||0)!==(b[i]||0))return (a[i]||0)-(b[i]||0)}return 0}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function md(t){ // sehr kleines Markdown: Überschriften, Listen, Fett
  const out=[];let list=false;
  for(const raw of (t||"").split("\n")){const l=raw.trim();
    if(/^[-*] /.test(l)){if(!list){out.push("<ul>");list=true}out.push("<li>"+inl(l.slice(2))+"</li>");continue}
    if(list){out.push("</ul>");list=false}
    if(/^#{1,4} /.test(l))out.push("<p><b>"+inl(l.replace(/^#+ /,""))+"</b></p>");else if(l)out.push("<p>"+inl(l)+"</p>")}
  if(list)out.push("</ul>");return out.join("")}
function inl(s){return esc(s).replace(/\*\*(.+?)\*\*/g,"<b>$1</b>").replace(/`(.+?)`/g,"<code>$1</code>")}
function fmtSize(b){return b?(b/1048576).toFixed(0)+" MB":""}
function newest(chans,platform){
  let best=null;
  for(const r of data.releases){if(!chans.includes(r.channel))continue;
    const a=r.assets&&r.assets[platform];if(!a||!a.url)continue;
    if(!best||cmp(r.version,best.version)>0)best=r}
  return best}
function render(){
  const chans=channel==="beta"?["stable","beta"]:["stable"];
  const os=LABEL[OS]?OS:"windows";
  const rel=newest(chans,os),dl=document.getElementById("dl");
  if(rel){const a=rel.assets[os];dl.href=a.url;dl.className="primary";
    dl.innerHTML="Für "+LABEL[os]+" herunterladen &nbsp;·&nbsp; Version "+esc(rel.version)+(rel.channel==="beta"?' <span class="badge">Beta</span>':"");
    document.getElementById("meta").innerHTML=esc(a.file)+" · "+fmtSize(a.size)+" · "+esc(rel.date)+
      "<br>SHA-256: <code>"+esc(a.sha256)+"</code>"}
  else{dl.className="primary disabled";dl.textContent="Für "+LABEL[os]+" noch nicht verfügbar";
    document.getElementById("meta").textContent=""}
  if(OS==="ios"||OS==="android")document.getElementById("meta").innerHTML+=
    "<br><b>Hinweis:</b> AkustikMess läuft auf Windows und macOS. Auf dem Handy dient es als Fernbedienung (QR-Code im Programm).";
  const others=[];
  for(const p of ["windows","macos","linux"]){if(p===os)continue;const r=newest(chans,p);
    if(r)others.push('<a href="'+esc(r.assets[p].url)+'">'+LABEL[p]+" (Version "+esc(r.version)+")</a>")}
  document.getElementById("others").innerHTML=others.length?"Andere Systeme: "+others.join(""):"";
  document.getElementById("hint").innerHTML=HINT[os];
  const notes=data.releases.filter(r=>chans.includes(r.channel)).sort((a,b)=>cmp(b.version,a.version)).slice(0,12);
  document.getElementById("notes").innerHTML=notes.map(r=>"<h3>"+esc(r.version)+(r.channel==="beta"?' <span class="badge">Beta</span>':"")+
    ' <span class="date">'+esc(r.date)+"</span></h3>"+md(r.notes)).join("")||"–";
  document.getElementById("tStable").className=channel==="stable"?"sel":"";
  document.getElementById("tBeta").className=channel==="beta"?"sel":"";
}
document.getElementById("tStable").onclick=()=>{channel="stable";render()};
document.getElementById("tBeta").onclick=()=>{channel="beta";render()};
fetch("releases.json",{cache:"no-store"}).then(r=>r.json()).then(o=>{data=JSON.parse(o.signed);
  // noch keine stabile Version für dieses System → direkt die Beta anbieten
  const os=LABEL[OS]?OS:"windows";
  if(!newest(["stable"],os)&&newest(["stable","beta"],os))channel="beta";
  render()})
 .catch(()=>{document.getElementById("dl").textContent="Release-Verzeichnis nicht erreichbar"});
