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
    '<div class="hud"><div>SCORE <b id="sc">0</b></div><div>TIME <b id="tm">30</b></div></div>'
    '<div class="hint">move the mouse / drag to catch the stars</div>'
    '<div class="over" id="over"><h2 id="ot">Time!</h2><div class="sc" id="of">0</div>'
    '<p>stars collected</p><button class="btn" id="rs">Play again</button></div>'
)
_STAR_JS = r'''var c=document.getElementById("stage"),x=c.getContext("2d"),W,H;function rs(){W=c.width=innerWidth;H=c.height=innerHeight}rs();onresize=rs;
var px=W/2,score=0,time=30,stars=[],parts=[],run=true,tmr;
function star(){return{x:Math.random()*W,y:-20,v:1.2+Math.random()*1.3,r:11+Math.random()*7,bad:Math.random()<0.16,a:Math.random()*6}}
for(var i=0;i<6;i++){var s=star();s.y=Math.random()*H;stars.push(s)}
onmousemove=function(e){px=e.clientX};ontouchmove=function(e){px=e.touches[0].clientX;e.preventDefault()};
function poly(cx,cy,r,a,col){x.fillStyle=col;x.beginPath();for(var i=0;i<10;i++){var rr=i%2?r*.45:r,an=a+i*Math.PI/5;x.lineTo(cx+Math.cos(an)*rr,cy+Math.sin(an)*rr)}x.closePath();x.fill()}
var _lt=0;function loop(t){if(!run)return;requestAnimationFrame(loop);if(t-_lt<15)return;_lt=t;x.clearRect(0,0,W,H);
var by=H-46;
for(var i=stars.length-1;i>=0;i--){var s=stars[i];s.y+=s.v;s.a+=.05;poly(s.x,s.y,s.r,s.a,s.bad?"#e2483d":"#ffd54a");
if(s.y>by-18&&s.y<by+30&&Math.abs(s.x-px)<58){if(s.bad){score=Math.max(0,score-3)}else{score++;for(var p=0;p<8;p++)parts.push({x:s.x,y:s.y,vx:(Math.random()-.5)*6,vy:(Math.random()-.5)*6,l:18})}stars.splice(i,1);stars.push(star());document.getElementById("sc").textContent=score}
else if(s.y>H+30){stars.splice(i,1);stars.push(star())}}
for(var p=parts.length-1;p>=0;p--){var q=parts[p];q.x+=q.vx;q.y+=q.vy;q.l--;x.globalAlpha=q.l/18;x.fillStyle="#ff6b35";x.fillRect(q.x,q.y,4,4);x.globalAlpha=1;if(q.l<=0)parts.splice(p,1)}
x.fillStyle="#ff6b35";x.beginPath();x.moveTo(px-52,by+18);x.lineTo(px+52,by+18);x.lineTo(px+40,by-14);x.lineTo(px-40,by-14);x.closePath();x.fill();x.fillStyle="#181613";x.fillRect(px-40,by-14,80,6)}
loop();tmr=setInterval(function(){time--;document.getElementById("tm").textContent=time;if(time<=0){run=false;clearInterval(tmr);document.getElementById("of").textContent=score;document.getElementById("over").classList.add("show")}},1000);
document.getElementById("rs").onclick=function(){score=0;time=30;stars=[];for(var i=0;i<6;i++)stars.push(star());document.getElementById("sc").textContent=0;document.getElementById("tm").textContent=30;document.getElementById("over").classList.remove("show");run=true;loop();tmr=setInterval(function(){time--;document.getElementById("tm").textContent=time;if(time<=0){run=false;clearInterval(tmr);document.getElementById("of").textContent=score;document.getElementById("over").classList.add("show")}},1000)};'''

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
function reset(){lane=1;obs=[];dist=0;spd=3.4;run=true;document.getElementById("over").classList.remove("show");loop()}
function key(d){lane=Math.max(0,Math.min(2,lane+d))}
onkeydown=function(e){if(e.key=="a"||e.key=="ArrowLeft")key(-1);if(e.key=="d"||e.key=="ArrowRight")key(1)};
c.onpointerdown=function(e){key(e.clientX<W/2?-1:1)};
var t=0,_lt=0;function loop(ts){if(!run)return;raf=requestAnimationFrame(loop);if(ts-_lt<15)return;_lt=ts;x.fillStyle="#10151a";x.fillRect(0,0,W,H);
t+=spd;dist+=spd/30;spd+=0.0013;
x.strokeStyle="rgba(34,211,238,.18)";x.lineWidth=2;for(var i=0;i<3;i++){x.beginPath();x.moveTo(lx(i),0);x.lineTo(lx(i),H);x.stroke()}
for(var y=-((t)%80);y<H;y+=80){x.fillStyle="rgba(34,211,238,.10)";x.fillRect(0,y,W,2)}
if((obs.length===0||obs[obs.length-1].y>150)&&Math.random()<0.08+dist/8000)obs.push({l:Math.floor(Math.random()*3),y:-40});
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
function flash(i,cb){pads[i].style.opacity=1;pads[i].style.transform="scale(.96)";setTimeout(function(){pads[i].style.opacity=.32;pads[i].style.transform="none";cb&&cb()},340)}
function show(){playing=false;document.getElementById("st").textContent="watch";var i=0;(function n(){if(i>=seq.length){playing=true;step=0;document.getElementById("st").textContent="your turn";return}flash(seq[i],function(){setTimeout(n,140)});i++})()}
function next(){round++;document.getElementById("sc").textContent=round;seq.push(Math.floor(Math.random()*4));setTimeout(show,500)}
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
