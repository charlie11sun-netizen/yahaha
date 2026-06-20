"""可运行游戏 bundle 模板 + 创意→bundle 的启发式选择。

游戏代码移植自项目设计稿 handoff（gamedata.js）。生产中 Coder 节点接真实
模型时，只需把这里的模板替换为模型产出的 HTML5 即可，其余链路（打包/上传/
Play 加载）保持不变。
"""
import re


def shell(title: str, accent: str, body: str, script: str) -> str:
    css = (
        "*{margin:0;padding:0;box-sizing:border-box}"
        'html,body{height:100%;overflow:hidden;font-family:"IBM Plex Mono",ui-monospace,monospace;'
        "background:#181613;color:#faf8f3;-webkit-user-select:none;user-select:none;touch-action:none}"
        "#stage{position:absolute;inset:0;display:block}"
        ".hud{position:absolute;top:14px;left:16px;right:16px;display:flex;justify-content:space-between;"
        "font-size:14px;letter-spacing:.04em;pointer-events:none;z-index:3;text-shadow:0 1px 2px rgba(0,0,0,.5)}"
        ".hud b{color:" + accent + "}"
        ".over{position:absolute;inset:0;display:none;flex-direction:column;align-items:center;"
        "justify-content:center;gap:18px;background:rgba(24,22,19,.86);z-index:5;text-align:center;padding:24px}"
        ".over.show{display:flex}"
        ".over h2{font-size:30px;font-weight:800;letter-spacing:-.01em}"
        ".over p{font-size:15px;opacity:.8}"
        ".over .sc{font-size:46px;font-weight:800;color:" + accent + "}"
        ".btn{pointer-events:auto;cursor:pointer;border:none;background:" + accent + ";color:#181613;"
        "font-family:inherit;font-weight:700;font-size:15px;padding:12px 26px;border-radius:10px;letter-spacing:.03em}"
        ".btn:active{transform:translateY(1px)}"
        ".hint{position:absolute;bottom:16px;left:0;right:0;text-align:center;font-size:12px;opacity:.55;z-index:3}"
    )
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>" + title + "</title>"
        "<style>" + css + "</style></head><body>"
        + body
        + "<script>" + script + "</script>"
        "</body></html>"
    )


# ---------- Star Catcher ----------
_STAR_BODY = (
    '<canvas id="stage"></canvas>'
    '<div class="hud"><div>SCORE <b id="sc">0</b></div><div>TIME <b id="tm">40</b></div></div>'
    '<div class="hint">move the mouse / drag to catch the stars</div>'
    '<div class="over" id="over"><h2 id="ot">Time!</h2><div class="sc" id="of">0</div>'
    '<p>stars collected</p><button class="btn" id="rs">Play again</button></div>'
)
_STAR_JS = r'''var c=document.getElementById("stage"),x=c.getContext("2d"),W,H;function rs(){W=c.width=innerWidth;H=c.height=innerHeight}rs();onresize=rs;
var px=W/2,score=0,time=40,stars=[],parts=[],run=true,tmr;
function star(){return{x:Math.random()*W,y:-20,v:.75+Math.random()*.85,r:12+Math.random()*7,bad:score>4&&Math.random()<0.10,a:Math.random()*6}}
for(var i=0;i<5;i++){var s=star();s.y=Math.random()*H;stars.push(s)}
onmousemove=function(e){px=e.clientX};ontouchmove=function(e){px=e.touches[0].clientX;e.preventDefault()};
function poly(cx,cy,r,a,col){x.fillStyle=col;x.beginPath();for(var i=0;i<10;i++){var rr=i%2?r*.45:r,an=a+i*Math.PI/5;x.lineTo(cx+Math.cos(an)*rr,cy+Math.sin(an)*rr)}x.closePath();x.fill()}
var _lt=0;function loop(t){if(!run)return;requestAnimationFrame(loop);if(t-_lt<15)return;_lt=t;x.clearRect(0,0,W,H);
var by=H-46;
for(var i=stars.length-1;i>=0;i--){var s=stars[i];s.y+=s.v;s.a+=.05;poly(s.x,s.y,s.r,s.a,s.bad?"#e2483d":"#ffd54a");
if(s.y>by-18&&s.y<by+30&&Math.abs(s.x-px)<74){if(s.bad){score=Math.max(0,score-2)}else{score++;for(var p=0;p<8;p++)parts.push({x:s.x,y:s.y,vx:(Math.random()-.5)*5,vy:(Math.random()-.5)*5,l:18})}stars.splice(i,1);stars.push(star());document.getElementById("sc").textContent=score}
else if(s.y>H+30){stars.splice(i,1);stars.push(star())}}
for(var p=parts.length-1;p>=0;p--){var q=parts[p];q.x+=q.vx;q.y+=q.vy;q.l--;x.globalAlpha=q.l/18;x.fillStyle="#ff6b35";x.fillRect(q.x,q.y,4,4);x.globalAlpha=1;if(q.l<=0)parts.splice(p,1)}
x.fillStyle="#ff6b35";x.beginPath();x.moveTo(px-64,by+18);x.lineTo(px+64,by+18);x.lineTo(px+50,by-14);x.lineTo(px-50,by-14);x.closePath();x.fill();x.fillStyle="#181613";x.fillRect(px-50,by-14,100,6)}
loop();tmr=setInterval(function(){time--;document.getElementById("tm").textContent=time;if(time<=0){run=false;clearInterval(tmr);document.getElementById("of").textContent=score;document.getElementById("over").classList.add("show")}},1000);
document.getElementById("rs").onclick=function(){score=0;time=40;stars=[];for(var i=0;i<5;i++)stars.push(star());document.getElementById("sc").textContent=0;document.getElementById("tm").textContent=40;document.getElementById("over").classList.remove("show");run=true;loop();tmr=setInterval(function(){time--;document.getElementById("tm").textContent=time;if(time<=0){run=false;clearInterval(tmr);document.getElementById("of").textContent=score;document.getElementById("over").classList.add("show")}},1000)};'''

# ---------- Neon Dodge ----------
_NEON_BODY = (
    '<canvas id="stage"></canvas>'
    '<div class="hud"><div>DIST <b id="sc">0</b>m</div><div>BEST <b id="bs">0</b></div></div>'
    '<div class="hint">A / D or arrow keys / tap left-right to switch lanes</div>'
    '<div class="over" id="over"><h2>Crashed</h2><div class="sc" id="of">0</div>'
    '<p>metres survived</p><button class="btn" id="rs">Retry</button></div>'
)
_NEON_JS = r'''var c=document.getElementById("stage"),x=c.getContext("2d"),W,H;function rs(){W=c.width=innerWidth;H=c.height=innerHeight}rs();onresize=rs;
var lanes,lane,obs,dist,spd,run,best=0,raf;
function lx(i){return W/2+(i-1)*Math.min(120,W*0.26)}
function reset(){lane=1;obs=[];dist=0;spd=2.25;run=true;document.getElementById("over").classList.remove("show");loop()}
function key(d){lane=Math.max(0,Math.min(2,lane+d))}
onkeydown=function(e){if(e.key=="a"||e.key=="ArrowLeft")key(-1);if(e.key=="d"||e.key=="ArrowRight")key(1)};
c.onpointerdown=function(e){key(e.clientX<W/2?-1:1)};
var t=0,_lt=0;function loop(ts){if(!run)return;raf=requestAnimationFrame(loop);if(ts-_lt<15)return;_lt=ts;x.fillStyle="#10151a";x.fillRect(0,0,W,H);
t+=spd;dist+=spd/36;spd+=0.00065;
x.strokeStyle="rgba(34,211,238,.18)";x.lineWidth=2;for(var i=0;i<3;i++){x.beginPath();x.moveTo(lx(i),0);x.lineTo(lx(i),H);x.stroke()}
for(var y=-((t)%80);y<H;y+=80){x.fillStyle="rgba(34,211,238,.10)";x.fillRect(0,y,W,2)}
if((obs.length===0||obs[obs.length-1].y>230)&&Math.random()<0.035+dist/14000)obs.push({l:Math.floor(Math.random()*3),y:-40});
var py=H-90;
for(var i=obs.length-1;i>=0;i--){var o=obs[i];o.y+=spd;x.fillStyle="#ff3ea5";x.shadowColor="#ff3ea5";x.shadowBlur=16;x.fillRect(lx(o.l)-26,o.y,52,40);x.shadowBlur=0;
if(o.l==lane&&o.y+40>py&&o.y<py+44){run=false;cancelAnimationFrame(raf);best=Math.max(best,Math.floor(dist));document.getElementById("bs").textContent=best;document.getElementById("of").textContent=Math.floor(dist);document.getElementById("over").classList.add("show")}
if(o.y>H+40)obs.splice(i,1)}
x.fillStyle="#22d3ee";x.shadowColor="#22d3ee";x.shadowBlur=20;x.beginPath();x.moveTo(lx(lane),py-4);x.lineTo(lx(lane)-24,py+40);x.lineTo(lx(lane)+24,py+40);x.closePath();x.fill();x.shadowBlur=0;
document.getElementById("sc").textContent=Math.floor(dist)}
document.getElementById("rs").onclick=reset;reset();'''

# ---------- Color Match (Simon) ----------
_COLOR_BODY = (
    '<div class="hud"><div>ROUND <b id="sc">0</b></div><div id="st">watch</div></div>'
    '<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center">'
    '<div id="grid" style="display:grid;grid-template-columns:1fr 1fr;gap:14px;width:min(78vmin,420px);aspect-ratio:1"></div></div>'
    '<div class="hint">repeat the sequence by tapping the pads</div>'
    '<div class="over" id="over"><h2>Missed it</h2><div class="sc" id="of">0</div>'
    '<p>rounds cleared</p><button class="btn" id="rs">Again</button></div>'
)
_COLOR_JS = r'''var cols=["#ff6b35","#22d3ee","#39ff88","#ff3ea5"],pads=[],seq=[],step=0,round=0,playing=false;
var g=document.getElementById("grid");for(var i=0;i<4;i++){(function(i){var d=document.createElement("div");d.style.cssText="border-radius:18px;background:"+cols[i]+";opacity:.32;cursor:pointer;transition:opacity .12s,transform .12s";d.onpointerdown=function(){if(playing)tap(i)};pads.push(d);g.appendChild(d)})(i)}
function flash(i,cb){pads[i].style.opacity=1;pads[i].style.transform="scale(.96)";setTimeout(function(){pads[i].style.opacity=.32;pads[i].style.transform="none";cb&&cb()},480)}
function show(){playing=false;document.getElementById("st").textContent="watch";var i=0;(function n(){if(i>=seq.length){playing=true;step=0;document.getElementById("st").textContent="your turn";return}flash(seq[i],function(){setTimeout(n,220)});i++})()}
function next(){round++;document.getElementById("sc").textContent=round;seq.push(Math.floor(Math.random()*4));setTimeout(show,700)}
function tap(i){flash(i);if(i!==seq[step]){playing=false;document.getElementById("of").textContent=round-1<0?0:round-1;document.getElementById("over").classList.add("show");return}step++;if(step>=seq.length){playing=false;next()}}
function reset(){seq=[];round=0;step=0;document.getElementById("sc").textContent=0;document.getElementById("over").classList.remove("show");next()}
document.getElementById("rs").onclick=reset;reset();'''


BUNDLES = {
    "starcatch": shell("Star Catcher", "#ff6b35", _STAR_BODY, _STAR_JS),
    "neondodge": shell("Neon Dodge", "#22d3ee", _NEON_BODY, _NEON_JS),
    "colormatch": shell("Color Match", "#7c5cff", _COLOR_BODY, _COLOR_JS),
}


def pick_bundle(idea: str) -> dict:
    t = idea.lower()
    if re.search(r"dodge|race|run|avoid|躲|赛|跑", t):
        return {"bundle": "neondodge", "genre": "ENDLESS RUNNER",
                "cover": "linear-gradient(135deg,#0ea5b7,#4f46e5)", "tags": ["Arcade", "Endless"]}
    if re.search(r"memory|match|color|simon|记忆|颜色|配对", t):
        return {"bundle": "colormatch", "genre": "MEMORY PUZZLE",
                "cover": "linear-gradient(135deg,#7c5cff,#c026d3)", "tags": ["Puzzle", "Memory"]}
    return {"bundle": "starcatch", "genre": "CASUAL · COZY",
            "cover": "linear-gradient(135deg,#ff8a3d,#ff3ea5)", "tags": ["Casual", "Cozy"]}


def title_from(idea: str) -> str:
    t = idea.lower()
    if re.search(r"star|catch|星|接", t):
        return "Star Drift"
    if re.search(r"dodge|race|run|躲|赛|跑", t):
        return "Lane Breaker"
    if re.search(r"memory|color|记忆|颜色", t):
        return "Echo Tiles"
    w = " ".join(idea.strip().split()[:2])
    return (w[:1].upper() + w[1:]) if w else "Untitled Game"


# ---------- Moonlit Koi ----------
_KOI_BODY = (
    '<canvas id="stage"></canvas>'
    '<div class="hud"><div>GLOW <b id="sc">0</b></div><div>LIVES <b id="lv">4</b></div></div>'
    '<div class="hint">guide the koi with mouse / touch. collect lantern petals, avoid ink ripples</div>'
    '<div class="over" id="over"><h2>Pond quiets</h2><div class="sc" id="of">0</div>'
    '<p>lantern petals gathered</p><button class="btn" id="rs">Swim again</button></div>'
)
_KOI_JS = r'''var c=document.getElementById("stage"),x=c.getContext("2d"),W,H;function size(){W=c.width=innerWidth;H=c.height=innerHeight}size();onresize=size;
var koi={x:W*.5,y:H*.58,tx:W*.5,ty:H*.58},score=0,lives=4,petals=[],ripples=[],sparks=[],run=true,last=0;
function spawnPetal(){return{x:40+Math.random()*(W-80),y:40+Math.random()*(H-120),r:9+Math.random()*5,a:Math.random()*6,t:0}}
function spawnRipple(){var e=Math.floor(Math.random()*4),p={r:20,t:0};if(e==0){p.x=-30;p.y=Math.random()*H}else if(e==1){p.x=W+30;p.y=Math.random()*H}else if(e==2){p.x=Math.random()*W;p.y=-30}else{p.x=Math.random()*W;p.y=H+30}p.vx=(W/2-p.x)/380;p.vy=(H/2-p.y)/380;return p}
for(var i=0;i<11;i++)petals.push(spawnPetal());for(var i=0;i<2;i++)ripples.push(spawnRipple());
onpointermove=function(e){koi.tx=e.clientX;koi.ty=e.clientY};onpointerdown=onpointermove;
function petal(p){x.save();x.translate(p.x,p.y);x.rotate(p.a);x.fillStyle="#ffd980";for(var i=0;i<5;i++){x.rotate(Math.PI*2/5);x.beginPath();x.ellipse(0,-p.r,p.r*.36,p.r,0,0,Math.PI*2);x.fill()}x.restore()}
function end(){run=false;document.getElementById("of").textContent=score;document.getElementById("over").classList.add("show")}
function loop(t){if(!run)return;requestAnimationFrame(loop);var dt=Math.min(32,t-last||16);last=t;x.clearRect(0,0,W,H);
var g=x.createRadialGradient(W*.52,H*.42,20,W*.52,H*.42,Math.max(W,H));g.addColorStop(0,"#18345a");g.addColorStop(.52,"#0b2233");g.addColorStop(1,"#071015");x.fillStyle=g;x.fillRect(0,0,W,H);
for(var i=0;i<34;i++){x.strokeStyle="rgba(142,220,255,.05)";x.beginPath();x.arc((i*97+t*.012)%W,(i*53)%H,38+(i%5)*19,0,Math.PI*2);x.stroke()}
koi.x+=(koi.tx-koi.x)*.075;koi.y+=(koi.ty-koi.y)*.075;
for(var i=petals.length-1;i>=0;i--){var p=petals[i];p.a+=.012;p.t+=dt;petal(p);if(Math.hypot(p.x-koi.x,p.y-koi.y)<38){score++;document.getElementById("sc").textContent=score;for(var s=0;s<10;s++)sparks.push({x:p.x,y:p.y,vx:(Math.random()-.5)*3,vy:(Math.random()-.5)*3,l:26});petals.splice(i,1);petals.push(spawnPetal())}}
for(var i=ripples.length-1;i>=0;i--){var r=ripples[i];r.x+=r.vx*dt*.12;r.y+=r.vy*dt*.12;r.t+=dt;x.strokeStyle="rgba(7,10,18,.82)";x.lineWidth=5;x.beginPath();x.arc(r.x,r.y,20+Math.sin(r.t*.01)*5,0,Math.PI*2);x.stroke();if(Math.hypot(r.x-koi.x,r.y-koi.y)<26){lives--;document.getElementById("lv").textContent=lives;ripples.splice(i,1);ripples.push(spawnRipple());if(lives<=0)end()}else if(r.x<-80||r.x>W+80||r.y<-80||r.y>H+80){ripples.splice(i,1);ripples.push(spawnRipple())}}
for(var i=sparks.length-1;i>=0;i--){var s=sparks[i];s.x+=s.vx;s.y+=s.vy;s.l--;x.globalAlpha=s.l/26;x.fillStyle="#a8fff0";x.fillRect(s.x,s.y,3,3);x.globalAlpha=1;if(s.l<=0)sparks.splice(i,1)}
x.save();x.translate(koi.x,koi.y);x.rotate(Math.atan2(koi.ty-koi.y,koi.tx-koi.x));x.shadowColor="#8ef4ff";x.shadowBlur=18;x.fillStyle="#ff8a5b";x.beginPath();x.ellipse(0,0,26,13,0,0,Math.PI*2);x.fill();x.fillStyle="#ffd7a8";x.beginPath();x.ellipse(10,0,10,8,0,0,Math.PI*2);x.fill();x.fillStyle="#ff5d6c";x.beginPath();x.moveTo(-24,0);x.lineTo(-44,-15);x.lineTo(-38,0);x.lineTo(-44,15);x.closePath();x.fill();x.restore()}
document.getElementById("rs").onclick=function(){score=0;lives=4;petals=[];ripples=[];sparks=[];for(var i=0;i<11;i++)petals.push(spawnPetal());for(var i=0;i<2;i++)ripples.push(spawnRipple());document.getElementById("sc").textContent=0;document.getElementById("lv").textContent=4;document.getElementById("over").classList.remove("show");run=true;last=0;loop(0)};loop(0);'''

# ---------- Rune Circuit ----------
_RUNE_BODY = (
    '<div class="hud"><div>LEVEL <b id="lv">1</b></div><div>MOVES <b id="mv">0</b></div></div>'
    '<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center">'
    '<div id="board" style="display:grid;grid-template-columns:repeat(5,1fr);gap:9px;width:min(80vmin,460px);aspect-ratio:1"></div></div>'
    '<div class="hint">rotate glyphs to carry light from left to right</div>'
    '<div class="over" id="over"><h2>Circuit lit</h2><div class="sc" id="of">0</div>'
    '<p>moves this level</p><button class="btn" id="rs">Next circuit</button></div>'
)
_RUNE_JS = r'''var N=5,tiles=[],level=1,moves=0,board=document.getElementById("board");
var base=[[5,5,6,5,6],[3,0,3,0,3],[3,5,15,5,10],[3,0,3,0,0],[9,5,12,5,12]];
function rot(mask){return((mask&1)<<1)|((mask&2)<<1)|((mask&4)<<1)|((mask&8)>>3)}
function svg(m,on){var c=on?"#9fffd0":"#8da0c8",s='<svg viewBox="0 0 100 100" width="100%" height="100%"><circle cx="50" cy="50" r="9" fill="'+c+'"/>';if(m&1)s+='<path d="M50 50V5" stroke="'+c+'" stroke-width="9" stroke-linecap="round"/>';if(m&2)s+='<path d="M50 50h45" stroke="'+c+'" stroke-width="9" stroke-linecap="round"/>';if(m&4)s+='<path d="M50 50v45" stroke="'+c+'" stroke-width="9" stroke-linecap="round"/>';if(m&8)s+='<path d="M50 50H5" stroke="'+c+'" stroke-width="9" stroke-linecap="round"/>';return s+'</svg>'}
function flow(){var q=[10],seen=new Set([10]);while(q.length){var i=q.shift(),r=Math.floor(i/N),c=i%N,m=tiles[i];[[1,-N],[2,1],[4,N],[8,-1]].forEach(function(a){var bit=a[0],di=a[1],j=i+di;if(!(m&bit)||j<0||j>=N*N)return;if(bit==2&&c==N-1)return;if(bit==8&&c==0)return;if(bit==1&&r==0)return;if(bit==4&&r==N-1)return;var opp={1:4,2:8,4:1,8:2}[bit];if((tiles[j]&opp)&&!seen.has(j)){seen.add(j);q.push(j)}})}return seen}
function win(){return flow().has(14)}
function draw(){board.innerHTML="";var lit=flow();for(var i=0;i<N*N;i++){var d=document.createElement("button"),on=lit.has(i),m=tiles[i];d.style.cssText="border:1px solid "+(on?"#9fffd0":"rgba(255,255,255,.12)")+";border-radius:14px;background:"+(on?"rgba(57,255,136,.18)":"rgba(255,255,255,.07)")+";box-shadow:"+(on?"0 0 24px rgba(57,255,136,.22)":"none")+";cursor:pointer;position:relative";d.innerHTML=svg(m,on);(function(i){d.onclick=function(){tiles[i]=rot(tiles[i]);moves++;document.getElementById("mv").textContent=moves;draw();if(win()){document.getElementById("of").textContent=moves;document.getElementById("over").classList.add("show")}}})(i);board.appendChild(d)}}
function reset(){tiles=[];for(var r=0;r<N;r++)for(var c=0;c<N;c++){var m=base[r][c],k=(Math.floor(Math.random()*4)+level)%4;while(k--)m=rot(m);tiles.push(m)}moves=0;document.getElementById("mv").textContent=0;document.getElementById("lv").textContent=level;document.getElementById("over").classList.remove("show");draw()}
document.body.style.background="radial-gradient(circle at 50% 30%,#21325f,#0b1020 70%)";document.getElementById("rs").onclick=function(){level++;reset()};reset();'''

# ---------- Cloud Courier ----------
_CLOUD_BODY = (
    '<canvas id="stage"></canvas>'
    '<div class="hud"><div>MAIL <b id="sc">0</b>/10</div><div>SHIELD <b id="hp">4</b></div></div>'
    '<div class="hint">hold / arrow up to rise, release to glide</div>'
    '<div class="over" id="over"><h2 id="ot">Delivered</h2><div class="sc" id="of">0</div>'
    '<p id="op">letters delivered</p><button class="btn" id="rs">Fly again</button></div>'
)
_CLOUD_JS = r'''var c=document.getElementById("stage"),x=c.getContext("2d"),W,H;function rs(){W=c.width=innerWidth;H=c.height=innerHeight}rs();onresize=rs;
var y=H/2,vy=0,up=false,mail=0,hp=4,objs=[],run=true,t=0,last=0;onkeydown=function(e){if(e.key=="ArrowUp"||e.key==" ")up=true};onkeyup=function(){up=false};onpointerdown=function(){up=true};onpointerup=function(){up=false};
function spawn(){objs.push({x:W+40,y:70+Math.random()*(H-160),v:1.6+Math.random()*.9,type:Math.random()<.64?"mail":"storm"})}
function end(ok){run=false;document.getElementById("ot").textContent=ok?"Delivered":"Grounded";document.getElementById("of").textContent=mail;document.getElementById("op").textContent=ok?"letters delivered":"letters before landing";document.getElementById("over").classList.add("show")}
function loop(ts){if(!run)return;requestAnimationFrame(loop);var dt=Math.min(32,ts-last||16);last=ts;t+=dt;x.clearRect(0,0,W,H);var g=x.createLinearGradient(0,0,0,H);g.addColorStop(0,"#7dd3fc");g.addColorStop(.55,"#c7f0ff");g.addColorStop(1,"#fff2d1");x.fillStyle=g;x.fillRect(0,0,W,H);
for(var i=0;i<10;i++){x.fillStyle="rgba(255,255,255,.35)";x.beginPath();x.ellipse((i*170-t*.025)%(W+180)-90,90+(i%5)*72,70,22,0,0,Math.PI*2);x.fill()}if(t>1200&&Math.random()<.022)spawn();vy+=(up?-.24:.17);vy*=.99;y+=vy;y=Math.max(40,Math.min(H-50,y));
for(var i=objs.length-1;i>=0;i--){var o=objs[i];o.x-=o.v;if(o.type=="mail"){x.fillStyle="#fff7d6";x.fillRect(o.x-15,o.y-11,30,22);x.strokeStyle="#c28a2c";x.strokeRect(o.x-15,o.y-11,30,22);x.beginPath();x.moveTo(o.x-15,o.y-11);x.lineTo(o.x,o.y+2);x.lineTo(o.x+15,o.y-11);x.stroke()}else{x.fillStyle="#334155";x.beginPath();x.ellipse(o.x,o.y,28,19,0,0,Math.PI*2);x.fill();x.strokeStyle="#8b5cf6";x.beginPath();x.moveTo(o.x-8,o.y+20);x.lineTo(o.x-20,o.y+45);x.moveTo(o.x+10,o.y+18);x.lineTo(o.x,o.y+42);x.stroke()}var hit=Math.hypot(o.x-120,o.y-y);if((o.type=="mail"&&hit<46)||(o.type=="storm"&&hit<28)){if(o.type=="mail"){mail++;document.getElementById("sc").textContent=mail;if(mail>=10)end(true)}else{hp--;document.getElementById("hp").textContent=hp;if(hp<=0)end(false)}objs.splice(i,1)}else if(o.x<-50)objs.splice(i,1)}
x.save();x.translate(120,y);x.rotate(vy*.035);x.fillStyle="#ff7a59";x.beginPath();x.moveTo(30,0);x.lineTo(-26,-16);x.lineTo(-14,0);x.lineTo(-26,16);x.closePath();x.fill();x.fillStyle="#fff";x.beginPath();x.ellipse(-2,0,22,10,0,0,Math.PI*2);x.fill();x.restore()}
document.getElementById("rs").onclick=function(){y=H/2;vy=0;mail=0;hp=4;objs=[];run=true;t=0;last=0;document.getElementById("sc").textContent=0;document.getElementById("hp").textContent=4;document.getElementById("over").classList.remove("show");loop(0)};loop(0);'''

# ---------- Orbit Bloom ----------
_ORBIT_BODY = (
    '<canvas id="stage"></canvas>'
    '<div class="hud"><div>BLOOMS <b id="sc">0</b></div><div>CHAIN <b id="ch">1x</b></div></div>'
    '<div class="hint">tap / space to switch orbit. collect blossoms, avoid thorns</div>'
    '<div class="over" id="over"><h2>Garden fades</h2><div class="sc" id="of">0</div>'
    '<p>blooms awakened</p><button class="btn" id="rs">Bloom again</button></div>'
)
_ORBIT_JS = r'''var c=document.getElementById("stage"),x=c.getContext("2d"),W,H;function rs(){W=c.width=innerWidth;H=c.height=innerHeight}rs();onresize=rs;
var cx,cy,rad=90,ang=0,score=0,chain=1,items=[],run=true;function spawn(){var a=Math.random()*Math.PI*2,r=Math.random()<.5?Math.min(W,H)*.19:Math.min(W,H)*.31;return{a:a,r:r,bad:score>4&&Math.random()<.13,t:0}}
function swap(){rad=rad<Math.min(W,H)*.25?Math.min(W,H)*.31:Math.min(W,H)*.19}onpointerdown=swap;onkeydown=function(e){if(e.key==" "||e.key=="ArrowUp")swap()};
function loop(){if(!run)return;requestAnimationFrame(loop);cx=W/2;cy=H/2;ang+=.015+.00035*score;x.clearRect(0,0,W,H);var g=x.createRadialGradient(cx,cy,20,cx,cy,Math.max(W,H)*.65);g.addColorStop(0,"#193b2d");g.addColorStop(1,"#07130f");x.fillStyle=g;x.fillRect(0,0,W,H);[Math.min(W,H)*.19,Math.min(W,H)*.31].forEach(function(r){x.strokeStyle="rgba(180,255,206,.16)";x.lineWidth=2;x.beginPath();x.arc(cx,cy,r,0,Math.PI*2);x.stroke()});var px=cx+Math.cos(ang)*rad,py=cy+Math.sin(ang)*rad;
for(var i=items.length-1;i>=0;i--){var it=items[i],ix=cx+Math.cos(it.a)*it.r,iy=cy+Math.sin(it.a)*it.r;it.t+=.04;if(it.bad){x.fillStyle="#ef4444";x.beginPath();for(var k=0;k<8;k++){var rr=k%2?8:17,aa=it.a+k*Math.PI/4;x.lineTo(ix+Math.cos(aa)*rr,iy+Math.sin(aa)*rr)}x.fill()}else{x.fillStyle="#ffd166";for(var k=0;k<6;k++){var aa=it.t+k*Math.PI/3;x.beginPath();x.ellipse(ix+Math.cos(aa)*8,iy+Math.sin(aa)*8,6,12,aa,0,Math.PI*2);x.fill()}}var hit=Math.hypot(ix-px,iy-py);if((it.bad&&hit<17)||(!it.bad&&hit<30)){if(it.bad){run=false;document.getElementById("of").textContent=score;document.getElementById("over").classList.add("show")}else{score+=chain;chain=Math.min(9,chain+1);document.getElementById("sc").textContent=score;document.getElementById("ch").textContent=chain+"x";items.splice(i,1);items.push(spawn())}}}
x.fillStyle="#a7f3d0";x.shadowColor="#a7f3d0";x.shadowBlur=22;x.beginPath();x.arc(px,py,12,0,Math.PI*2);x.fill();x.shadowBlur=0;x.fillStyle="rgba(255,255,255,.75)";x.beginPath();x.arc(cx,cy,18,0,Math.PI*2);x.fill()}
function reset(){cx=W/2;cy=H/2;rad=Math.min(W,H)*.19;ang=0;score=0;chain=1;items=[];for(var i=0;i<12;i++)items.push(spawn());document.getElementById("sc").textContent=0;document.getElementById("ch").textContent="1x";document.getElementById("over").classList.remove("show");run=true;loop()}document.getElementById("rs").onclick=reset;reset();'''

BUNDLES.update({
    "moonlitkoi": shell("Moonlit Koi", "#8ef4ff", _KOI_BODY, _KOI_JS),
    "runecircuit": shell("Rune Circuit", "#39ff88", _RUNE_BODY, _RUNE_JS),
    "cloudcourier": shell("Cloud Courier", "#38bdf8", _CLOUD_BODY, _CLOUD_JS),
    "orbitbloom": shell("Orbit Bloom", "#a7f3d0", _ORBIT_BODY, _ORBIT_JS),
})


def pick_bundle(idea: str) -> dict:
    t = idea.lower()
    if re.search(r"dodge|race|run|avoid|lane", t):
        return {"bundle": "neondodge", "genre": "ENDLESS RUNNER",
                "cover": "/playforge/covers/neon-drift-dodge.jpg", "tags": ["Arcade", "Endless"]}
    if re.search(r"memory|match|color|simon", t):
        return {"bundle": "colormatch", "genre": "MEMORY PUZZLE",
                "cover": "/playforge/covers/color-echo.jpg", "tags": ["Puzzle", "Memory"]}
    if re.search(r"koi|fish|pond|water", t):
        return {"bundle": "moonlitkoi", "genre": "ZEN ARCADE",
                "cover": "/playforge/covers/moonlit-koi.jpg", "tags": ["Arcade", "Zen"]}
    if re.search(r"rune|circuit|pipe|connect", t):
        return {"bundle": "runecircuit", "genre": "LOGIC PUZZLE",
                "cover": "/playforge/covers/rune-circuit.jpg", "tags": ["Puzzle", "Logic"]}
    if re.search(r"cloud|fly|courier|mail", t):
        return {"bundle": "cloudcourier", "genre": "SKY ARCADE",
                "cover": "/playforge/covers/cloud-courier.jpg", "tags": ["Arcade", "Flight"]}
    if re.search(r"orbit|bloom|flower|garden", t):
        return {"bundle": "orbitbloom", "genre": "ONE-TAP ARCADE",
                "cover": "/playforge/covers/orbit-bloom.jpg", "tags": ["Arcade", "Timing"]}
    return {"bundle": "starcatch", "genre": "CASUAL COZY",
            "cover": "/playforge/covers/star-catcher.jpg", "tags": ["Casual", "Cozy"]}


def title_from(idea: str) -> str:
    t = idea.lower()
    if re.search(r"star|catch", t):
        return "Star Drift"
    if re.search(r"dodge|race|run|lane", t):
        return "Lane Breaker"
    if re.search(r"memory|color", t):
        return "Echo Tiles"
    if re.search(r"koi|fish|pond|water", t):
        return "Moonlit Koi"
    if re.search(r"rune|circuit|pipe|connect", t):
        return "Rune Circuit"
    if re.search(r"cloud|fly|courier|mail", t):
        return "Cloud Courier"
    if re.search(r"orbit|bloom|flower|garden", t):
        return "Orbit Bloom"
    w = " ".join(idea.strip().split()[:2])
    return (w[:1].upper() + w[1:]) if w else "Untitled Game"


# ---------------------------------------------------------------------------
# 3D (Three.js / WebGL) 参考实现 —— dimension=="3d" 的 few-shot 质量基线。
# 这些是给模型看的"结构 + 手感"参考(本身不入校验);真实产物由模型生成。
# index.html 通过同源相对路径 <script src="three.min.js"> 引入引擎,全局 THREE。
# ---------------------------------------------------------------------------
def shell_3d(title: str, accent: str, body: str, script: str) -> str:
    css = (
        "*{margin:0;padding:0;box-sizing:border-box}"
        "html,body{height:100%;overflow:hidden;font-family:'Segoe UI',system-ui,ui-sans-serif,sans-serif;"
        "background:#05070f;color:#eaf2ff;-webkit-user-select:none;user-select:none;touch-action:none}"
        "canvas{display:block;position:absolute;inset:0}"
        ".vig{position:absolute;inset:0;z-index:2;pointer-events:none;"
        "background:radial-gradient(120% 100% at 50% 46%,rgba(0,0,0,0) 54%,rgba(2,3,12,.66) 100%)}"
        ".hud{position:absolute;top:16px;left:0;right:0;display:flex;justify-content:space-between;align-items:flex-start;"
        "padding:0 22px;font-variant-numeric:tabular-nums;letter-spacing:.02em;pointer-events:none;z-index:3;"
        "text-shadow:0 2px 10px rgba(0,0,0,.6)}"
        ".hud>div{display:flex;flex-direction:column;gap:2px}.hud>div:last-child{align-items:flex-end}"
        ".hud b{font-size:26px;font-weight:800;color:" + accent + ";line-height:1}"
        "#cross{position:absolute;left:50%;top:50%;width:22px;height:22px;transform:translate(-50%,-50%);z-index:3;pointer-events:none}"
        "#cross:before,#cross:after{content:'';position:absolute;background:" + accent + ";box-shadow:0 0 6px " + accent + ";opacity:.9}"
        "#cross:before{left:10px;top:0;width:2px;height:22px}#cross:after{top:10px;left:0;height:2px;width:22px}"
        ".hint{position:absolute;bottom:16px;left:0;right:0;text-align:center;font-size:12px;opacity:.55;letter-spacing:.03em;z-index:3}"
        ".over{position:absolute;inset:0;display:none;flex-direction:column;align-items:center;justify-content:center;"
        "gap:16px;z-index:6;text-align:center;padding:28px;"
        "background:radial-gradient(120% 100% at 50% 40%,rgba(8,10,30,.55),rgba(3,4,12,.93))}"
        ".over.show{display:flex}"
        ".over h2{font-size:40px;font-weight:900;letter-spacing:-.01em;"
        "background:linear-gradient(95deg," + accent + ",#8f7bff 60%,#ff7ad5);"
        "-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;"
        "text-shadow:0 0 44px rgba(120,140,255,.4)}"
        ".over p{opacity:.74;font-size:15px;max-width:34ch;line-height:1.55}"
        ".over .sc{font-size:58px;font-weight:900;color:" + accent + ";text-shadow:0 0 34px " + accent + ";line-height:1}"
        ".btn{pointer-events:auto;cursor:pointer;border:none;color:#05070f;font-family:inherit;font-weight:800;"
        "font-size:15px;letter-spacing:.04em;padding:13px 30px;border-radius:999px;"
        "background:linear-gradient(95deg," + accent + ",#8f7bff);box-shadow:0 12px 32px rgba(120,140,255,.4)}"
        ".btn:active{transform:translateY(1px)}"
    )
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>" + title + "</title>"
        "<style>" + css + "</style></head><body>"
        '<div class="vig"></div>'
        + body
        + '<script src="three.min.js"></script>'
        + "<script>" + script + "</script>"
        "</body></html>"
    )


# ---------- Ion Arena (first-person wave shooter) ----------
_FPS_BODY = (
    '<div class="hud"><div>SCORE <b id="sc">0</b></div><div>WAVE <b id="wv">1</b> &middot; HP <b id="hp">100</b></div></div>'
    '<div id="cross"></div>'
    '<div class="hint">click to lock mouse &middot; WASD move &middot; mouse aim &middot; click to shoot</div>'
    '<div class="over" id="over"><h2>Overrun</h2><div class="sc" id="of">0</div>'
    '<p>targets destroyed</p><button class="btn" id="rs">Redeploy</button></div>'
)
_FPS_JS = r'''var renderer=new THREE.WebGLRenderer({antialias:true});
renderer.setPixelRatio(Math.min(2,window.devicePixelRatio||1));renderer.setSize(innerWidth,innerHeight);document.body.appendChild(renderer.domElement);
var scene=new THREE.Scene();scene.background=new THREE.Color(0x070a14);scene.fog=new THREE.Fog(0x070a14,16,95);
var camera=new THREE.PerspectiveCamera(74,innerWidth/innerHeight,0.1,300);camera.rotation.order="YXZ";camera.position.set(0,1.7,0);
addEventListener("resize",function(){camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight)});
scene.add(new THREE.HemisphereLight(0x9fc4ff,0x202840,0.9));var dir=new THREE.DirectionalLight(0xffffff,0.9);dir.position.set(8,20,6);scene.add(dir);
var R=42;var floor=new THREE.Mesh(new THREE.CircleGeometry(R,64),new THREE.MeshStandardMaterial({color:0x121a2e,metalness:0.2,roughness:0.85}));floor.rotation.x=-Math.PI/2;scene.add(floor);
var grid=new THREE.GridHelper(R*2,40,0x22d3ee,0x16304a);grid.position.y=0.02;scene.add(grid);
var AC=window.AudioContext||window.webkitAudioContext,ac=AC?new AC():null;
function beep(f,d,t){if(!ac)return;if(ac.state==="suspended")ac.resume();var o=ac.createOscillator(),g=ac.createGain();o.type=t||"square";o.frequency.value=f;o.connect(g);g.connect(ac.destination);g.gain.setValueAtTime(0.12,ac.currentTime);g.gain.exponentialRampToValueAtTime(0.001,ac.currentTime+d);o.start();o.stop(ac.currentTime+d)}
var keys={},yaw=0,pitch=0,locked=false,center=new THREE.Vector2(0,0);
var enemies=[],bursts=[],score=0,wave=1,hp=100,run=true,shake=0;
var raycaster=new THREE.Raycaster(),clock=new THREE.Clock();
addEventListener("keydown",function(e){keys[e.code]=true});addEventListener("keyup",function(e){keys[e.code]=false});
renderer.domElement.addEventListener("click",function(){if(ac&&ac.state==="suspended")ac.resume();if(!locked){renderer.domElement.requestPointerLock();}else{shoot();}});
document.addEventListener("pointerlockchange",function(){locked=document.pointerLockElement===renderer.domElement});
addEventListener("mousemove",function(e){if(!locked)return;yaw-=e.movementX*0.0022;pitch-=e.movementY*0.0022;pitch=Math.max(-1.2,Math.min(1.2,pitch))});
function enemy(){var g=new THREE.Group();var body=new THREE.Mesh(new THREE.IcosahedronGeometry(0.9,0),new THREE.MeshStandardMaterial({color:0xff3e6a,emissive:0x551020,roughness:0.4}));g.add(body);var eye=new THREE.Mesh(new THREE.SphereGeometry(0.22,12,12),new THREE.MeshBasicMaterial({color:0xffd166}));eye.position.set(0,0,0.78);g.add(eye);var a=Math.random()*Math.PI*2,d=R*0.85;g.position.set(Math.cos(a)*d,1.0,Math.sin(a)*d);g.userData.body=body;scene.add(g);enemies.push(g)}
function spawnWave(){for(var i=0;i<3+wave*2;i++)enemy()}
function clearWaveIfEmpty(){if(!enemies.length){wave++;document.getElementById("wv").textContent=wave;spawnWave()}}
function burst(pos,color){for(var i=0;i<14;i++){var m=new THREE.Mesh(new THREE.BoxGeometry(0.16,0.16,0.16),new THREE.MeshBasicMaterial({color:color}));m.position.copy(pos);m.userData.v=new THREE.Vector3((Math.random()-0.5)*8,Math.random()*7,(Math.random()-0.5)*8);m.userData.l=1;scene.add(m);bursts.push(m)}}
function shoot(){beep(720,0.08,"square");shake=0.5;raycaster.setFromCamera(center,camera);var meshes=enemies.map(function(e){return e.userData.body});var hit=raycaster.intersectObjects(meshes,false);if(hit.length){var grp=hit[0].object.parent;burst(grp.position,0xff7a90);scene.remove(grp);enemies.splice(enemies.indexOf(grp),1);score+=10;document.getElementById("sc").textContent=score;beep(180,0.16,"sawtooth");clearWaveIfEmpty()}}
function damage(n){hp-=n;document.getElementById("hp").textContent=Math.max(0,Math.round(hp));if(hp<=0)end()}
function end(){run=false;if(document.pointerLockElement)document.exitPointerLock();document.getElementById("of").textContent=score;document.getElementById("over").classList.add("show");try{window.parent.postMessage({type:"playforge:score",points:score},"*")}catch(e){}}
var fwd=new THREE.Vector3(),right=new THREE.Vector3(),mv=new THREE.Vector3();
function frame(){if(!run)return;requestAnimationFrame(frame);var dt=Math.min(0.05,clock.getDelta());
camera.rotation.y=yaw;camera.rotation.x=pitch;fwd.set(-Math.sin(yaw),0,-Math.cos(yaw));right.set(Math.cos(yaw),0,-Math.sin(yaw));mv.set(0,0,0);
if(keys.KeyW||keys.ArrowUp)mv.add(fwd);if(keys.KeyS||keys.ArrowDown)mv.sub(fwd);if(keys.KeyD||keys.ArrowRight)mv.add(right);if(keys.KeyA||keys.ArrowLeft)mv.sub(right);
if(mv.lengthSq()>0){mv.normalize().multiplyScalar(9*dt);camera.position.add(mv)}
var dd=Math.hypot(camera.position.x,camera.position.z);if(dd>R-1.5){var s=(R-1.5)/dd;camera.position.x*=s;camera.position.z*=s}
for(var i=enemies.length-1;i>=0;i--){var e=enemies[i],dx=camera.position.x-e.position.x,dz=camera.position.z-e.position.z,dl=Math.hypot(dx,dz)||1,sp=(2.2+wave*0.25)*dt;e.position.x+=dx/dl*sp;e.position.z+=dz/dl*sp;e.lookAt(camera.position.x,1.0,camera.position.z);e.userData.body.rotation.y+=dt*2;if(dl<1.6){damage(18);burst(e.position,0xff3e6a);scene.remove(e);enemies.splice(i,1);clearWaveIfEmpty()}}
for(var i=bursts.length-1;i>=0;i--){var b=bursts[i];b.userData.l-=dt*1.6;if(b.userData.l<=0){scene.remove(b);bursts.splice(i,1);continue}b.userData.v.y-=12*dt;b.position.addScaledVector(b.userData.v,dt);b.scale.setScalar(Math.max(0.02,b.userData.l))}
if(shake>0){shake=Math.max(0,shake-dt*3);camera.position.x+=(Math.random()-0.5)*shake*0.18;camera.position.z+=(Math.random()-0.5)*shake*0.18}
renderer.render(scene,camera)}
spawnWave();frame();
document.getElementById("rs").onclick=function(){for(var i=0;i<enemies.length;i++)scene.remove(enemies[i]);for(var i=0;i<bursts.length;i++)scene.remove(bursts[i]);enemies=[];bursts=[];score=0;wave=1;hp=100;document.getElementById("sc").textContent=0;document.getElementById("wv").textContent=1;document.getElementById("hp").textContent=100;document.getElementById("over").classList.remove("show");camera.position.set(0,1.7,0);yaw=0;pitch=0;run=true;clock.getDelta();spawnWave();frame()};'''

# ---------- Vector Rush (third-person 3D runner) ----------
_RUNNER_BODY = (
    '<div class="hud"><div>SCORE <b id="sc">0</b></div><div>DIST <b id="ds">0</b>m</div></div>'
    '<div class="hint">A / D or arrows switch lanes &middot; Space / up to jump &middot; tap left / right</div>'
    '<div class="over" id="over"><h2>Wiped out</h2><div class="sc" id="of">0</div>'
    '<p>orbs collected</p><button class="btn" id="rs">Run again</button></div>'
)
_RUNNER_JS = r'''var renderer=new THREE.WebGLRenderer({antialias:true});
renderer.setPixelRatio(Math.min(2,window.devicePixelRatio||1));renderer.setSize(innerWidth,innerHeight);document.body.appendChild(renderer.domElement);
var scene=new THREE.Scene();scene.background=new THREE.Color(0x0a1026);scene.fog=new THREE.Fog(0x0a1026,22,72);
var camera=new THREE.PerspectiveCamera(70,innerWidth/innerHeight,0.1,200);camera.position.set(0,4.4,8);camera.lookAt(0,1,-6);
addEventListener("resize",function(){camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight)});
scene.add(new THREE.HemisphereLight(0xbcd3ff,0x10162e,1.0));var dir=new THREE.DirectionalLight(0xffffff,0.8);dir.position.set(-6,12,4);scene.add(dir);
var LANES=[-2.4,0,2.4];
var track=new THREE.Mesh(new THREE.PlaneGeometry(9,400),new THREE.MeshStandardMaterial({color:0x141d3a,roughness:0.95}));track.rotation.x=-Math.PI/2;track.position.z=-180;scene.add(track);
var dashes=[];for(var i=0;i<40;i++){var d=new THREE.Mesh(new THREE.BoxGeometry(0.12,0.02,2),new THREE.MeshBasicMaterial({color:0x2b3c6b}));d.position.set(0,0.03,-i*5);scene.add(d);dashes.push(d)}
var player=new THREE.Group();var ship=new THREE.Mesh(new THREE.ConeGeometry(0.6,1.6,6),new THREE.MeshStandardMaterial({color:0x34f5c5,emissive:0x07323b,roughness:0.4}));ship.rotation.x=Math.PI/2;player.add(ship);player.position.set(0,0.9,4);scene.add(player);
var AC=window.AudioContext||window.webkitAudioContext,ac=AC?new AC():null;
function beep(f,d,t){if(!ac)return;if(ac.state==="suspended")ac.resume();var o=ac.createOscillator(),g=ac.createGain();o.type=t||"triangle";o.frequency.value=f;o.connect(g);g.connect(ac.destination);g.gain.setValueAtTime(0.1,ac.currentTime);g.gain.exponentialRampToValueAtTime(0.001,ac.currentTime+d);o.start();o.stop(ac.currentTime+d)}
var lane=1,targetX=0,vy=0,jumping=false,items=[],speed=22,dist=0,score=0,run=true,clock=new THREE.Clock();
function setLane(n){lane=Math.max(0,Math.min(2,n));targetX=LANES[lane];beep(520,0.05)}
addEventListener("keydown",function(e){if(e.code==="ArrowLeft"||e.code==="KeyA")setLane(lane-1);else if(e.code==="ArrowRight"||e.code==="KeyD")setLane(lane+1);else if((e.code==="Space"||e.code==="ArrowUp"||e.code==="KeyW")&&!jumping){jumping=true;vy=9;beep(680,0.12)}});
addEventListener("pointerdown",function(e){if(e.clientX<innerWidth*0.5)setLane(lane-1);else setLane(lane+1)});
function obstacle(z){var bad=Math.random()<0.62,m;if(bad){m=new THREE.Mesh(new THREE.BoxGeometry(1.4,1.4,1.4),new THREE.MeshStandardMaterial({color:0xff3e6a,emissive:0x4a0d1d,roughness:0.5}));m.position.y=0.7}else{m=new THREE.Mesh(new THREE.TorusGeometry(0.45,0.16,10,18),new THREE.MeshStandardMaterial({color:0xffd166,emissive:0x4a3a00}));m.position.y=1;m.rotation.x=Math.PI/2}m.position.x=LANES[Math.floor(Math.random()*3)];m.position.z=z;m.userData.bad=bad;scene.add(m);items.push(m)}
for(var i=0;i<6;i++)obstacle(-20-i*14);
function end(){run=false;document.getElementById("of").textContent=score;document.getElementById("over").classList.add("show");try{window.parent.postMessage({type:"playforge:score",points:score},"*")}catch(e){}}
function frame(){if(!run)return;requestAnimationFrame(frame);var dt=Math.min(0.05,clock.getDelta());speed+=dt*0.6;dist+=speed*dt;
player.position.x+=(targetX-player.position.x)*Math.min(1,dt*12);
if(jumping){vy-=26*dt;player.position.y+=vy*dt;if(player.position.y<=0.9){player.position.y=0.9;jumping=false;vy=0}}
player.rotation.z=(targetX-player.position.x)*0.4;ship.rotation.z+=dt*3;
for(var i=0;i<dashes.length;i++){dashes[i].position.z+=speed*dt;if(dashes[i].position.z>10)dashes[i].position.z-=200}
for(var i=items.length-1;i>=0;i--){var o=items[i];o.position.z+=speed*dt;if(!o.userData.bad)o.rotation.z+=dt*4;
if(o.position.z>6){scene.remove(o);items.splice(i,1);obstacle(-150-Math.random()*20);continue}
var near=Math.abs(o.position.z-player.position.z)<1.0&&Math.abs(o.position.x-player.position.x)<1.0;
if(near){if(o.userData.bad){if(player.position.y<1.6){end();return}}else{score+=5;document.getElementById("sc").textContent=score;beep(880,0.08);scene.remove(o);items.splice(i,1);obstacle(-150-Math.random()*20);continue}}}
document.getElementById("ds").textContent=Math.floor(dist);renderer.render(scene,camera)}
frame();
document.getElementById("rs").onclick=function(){for(var i=0;i<items.length;i++)scene.remove(items[i]);items=[];lane=1;targetX=0;player.position.set(0,0.9,4);vy=0;jumping=false;speed=22;dist=0;score=0;document.getElementById("sc").textContent=0;document.getElementById("over").classList.remove("show");run=true;clock.getDelta();for(var i=0;i<6;i++)obstacle(-20-i*14);frame()};'''

BUNDLES.update({
    "three_fps": shell_3d("Ion Arena", "#22d3ee", _FPS_BODY, _FPS_JS),
    "three_runner": shell_3d("Vector Rush", "#34f5c5", _RUNNER_BODY, _RUNNER_JS),
})


# ---------------------------------------------------------------------------
# Curated flagship games (hand-authored, not model output). Kept as standalone
# HTML files under agents/curated/ so the large game source stays readable and
# free of Python string-escaping. Registered into BUNDLES like any other bundle.
#   prismbreak — 2D juicy neon brick-breaker (single self-contained file)
#   warpspire  — 3D neon tunnel flyer; loads three.min.js via same-prefix
#                relative <script src> (seed uploads the engine alongside it,
#                NEEDS_ENGINE marks bundles that require this).
# ---------------------------------------------------------------------------
import os as _os

_CURATED_DIR = _os.path.join(_os.path.dirname(__file__), "curated")
NEEDS_ENGINE = {"warpspire"}


def _load_curated(name: str, filename: str) -> None:
    path = _os.path.join(_CURATED_DIR, filename)
    with open(path, "r", encoding="utf-8") as fh:
        BUNDLES[name] = fh.read()


_load_curated("prismbreak", "prism-break.html")
_load_curated("warpspire", "warp-spire.html")
