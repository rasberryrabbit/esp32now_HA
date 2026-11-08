"""
web_pages.py - 웹 대시보드 HTML 페이지 (모듈)
================================================
게이트웨이 웹 서버가 사용하는 HTML 페이지들을 정의.
espnow_mesh_pro.py 에서 import 하여 사용.

사용법:
  import web_pages
  html = web_pages.INDEX_HTML
"""

INDEX_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>ESP32 Mesh Dashboard</title>
<style>
*{box-sizing:border-box}
body{font-family:system-ui,sans-serif;background:#1a1a2e;color:#e0e0e0;margin:0;padding:20px}
h1{color:#0ff;text-align:center;border-bottom:2px solid #0ff;padding-bottom:10px}
.nav{text-align:center;margin:10px 0 20px}
.nav a{display:inline-block;padding:8px 16px;margin:0 4px;background:#0f3460;color:#0ff;border-radius:4px;text-decoration:none;font-size:14px}
.nav a.active{background:#e94560;color:#fff}
.nav a:hover{background:#16213e}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:20px 0}
.card{background:#16213e;padding:15px;border-radius:8px;border:1px solid #0f3460}
.card h2{color:#e94560;margin-top:0;font-size:16px}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{padding:6px 8px;border-bottom:1px solid #0f3460;text-align:left}
th{color:#0ff}
.stat{font-size:24px;font-weight:bold;color:#0ff}
input,button{padding:8px;font-size:14px;border-radius:4px;border:1px solid #0f3460;background:#0f3460;color:#fff}
input{flex:1}
.send-form{display:flex;gap:8px;margin-top:10px}
pre{font-family:monospace;font-size:11px;color:#0f0;white-space:pre-wrap;background:#0a1428;padding:10px;border-radius:4px;min-height:40px;max-height:200px;overflow-y:auto}
</style>
</head>
<body>
<h1>ESP32 Mesh Network</h1>
<div class="nav">
  <a href="/" class="active">Dashboard</a>
  <a href="/stats">Stats</a>
  <a href="/config">Config</a>
</div>
<div style="text-align:center;color:#0f0;font-size:14px;margin-bottom:10px">
  IP: <strong id="gw-ip">...</strong> | SSID: <strong id="gw-ssid">...</strong> | Role: <strong id="gw-role">...</strong>
</div>
<div id="ap-warning" style="display:none;text-align:center;background:#5a2d2d;color:#ffb;border:1px solid #e94560;padding:10px;margin-bottom:15px;border-radius:4px">
  <strong>AP 모드 (인터넷 연결 안 됨)</strong><br>
  Wi-Fi AP '<span id="ap-ssid-name"></span>' 에 연결하세요. <a href="/config" style="color:#0ff">Config 페이지</a>에서 Wi-Fi 설정 후 저장하고 재부팅하세요.
</div>
<div class="grid">
  <div class="card">
    <h2>Nodes</h2>
    <table id="nodes-table">
      <thead><tr><th>ID</th><th>Nick</th><th>Role</th><th>Active</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
  <div class="card">
    <h2>Sensors</h2>
    <div id="sensors"></div>
  </div>
  <div class="card" style="grid-column:1 / -1">
    <h2>Device Control Panel</h2>
    <div style="color:#888;font-size:12px;margin-bottom:10px">Control sensors/GPIO/PWM devices on all nodes</div>
    <div id="devices-panel"></div>
  </div>
  <div class="card" style="grid-column:1 / -1">
    <h2>Automation Rules</h2>
    <div style="color:#888;font-size:12px;margin-bottom:10px">Automation rules and execution log</div>
    <div id="automation-rules"></div>
    <h3 style="margin-top:15px;color:#0ff;font-size:13px">Execution Log</h3>
    <pre id="automation-log" style="max-height:150px"></pre>
  </div>
  <div class="card" style="grid-column:1 / -1">
    <h2>Control Log</h2>
    <pre id="debug-log"></pre>
  </div>
</div>
<div style="text-align:center;color:#444;font-size:11px;margin-top:15px">Mesh Dashboard v2.1</div>
<script>
function addLog(msg){
  var el=document.getElementById("debug-log");
  var ts=new Date().toLocaleTimeString();
  el.textContent+="["+ts+"] "+msg+String.fromCharCode(10);
  el.scrollTop=el.scrollHeight;
}
async function fetchJSON(url){
  try{
    var r=await fetch(url);
    if(!r.ok){return null}
    return await r.json();
  }catch(e){
    return null;
  }
}
var _gwInfoLoaded=false;
var _nodesCache=null;
var _rulesCache=null;
var _rulesCacheTime=0;
var _autoLogCacheTime=0;
var _fetching=false;
async function fetchData(){
  // 중복 폴링 방지
  if(_fetching)return;
  _fetching=true;
  try{
    // 상단 정보(IP/SSID/Role)는 최초 1회만 로드
    if(!_gwInfoLoaded){
      var cfg=await fetchJSON("/api/config");
      if(cfg){
        document.getElementById("gw-ip").textContent=cfg.ip||"?";
        document.getElementById("gw-ssid").textContent=cfg.gateway_ssid||"(none)";
        document.getElementById("gw-role").textContent=cfg.node_role||"?";
        if(cfg.ap_mode){
          var warn=document.getElementById("ap-warning");
          if(warn){
            warn.style.display="block";
            var nameEl=document.getElementById("ap-ssid-name");
            if(nameEl)nameEl.textContent=cfg.ap_ssid||"ESP32-Mesh";
          }
          document.getElementById("gw-ssid").textContent="(AP: "+(cfg.ap_ssid||"")+")";
        }
        _gwInfoLoaded=true;
      }
    }

    // 핵심 API (매 폴링): 센서 + 장치만
    // 노드 목록과 자동화 규칙은 15초마다만 갱신 (발열 저감)
    var nowSec=Date.now()/1000;
    var apiCalls=[
      fetchJSON("/api/sensors"),
      fetchJSON("/api/devices"),
    ];
    var needNodes=(!_nodesCache)||(nowSec-_rulesCacheTime>15);
    var needRules=(!_rulesCache)||(nowSec-_rulesCacheTime>15);
    var needLog=(nowSec-_autoLogCacheTime>10);
    if(needNodes)apiCalls.push(fetchJSON("/api/nodes"));
    if(needRules)apiCalls.push(fetchJSON("/api/automation?action=list"));
    if(needLog)apiCalls.push(fetchJSON("/api/automation?action=log&limit=20"));
    var results=await Promise.all(apiCalls);
    var idx=0;
    var sensors=results[idx++];
    var d=results[idx++];
    var nodes=needNodes?results[idx++]:_nodesCache;
    if(needNodes)_nodesCache=nodes;
    var rules=needRules?results[idx++]:_rulesCache;
    if(needRules){_rulesCache=rules;_rulesCacheTime=nowSec}
    var autoLog=needLog?results[idx++]:null;
    if(needLog)_autoLogCacheTime=nowSec;

    if(nodes&&Array.isArray(nodes)){
      var html="";
      nodes.forEach(function(n){
        var age=n.age_sec!==undefined?n.age_sec:0;
        html+="<tr><td>"+n.id+"</td><td>"+n.nick+"</td><td>"+n.role+"</td><td>"+age+"s</td></tr>";
      });
      document.querySelector("#nodes-table tbody").innerHTML=html;
    }

    if(sensors){
      var sh="<table><tr><th>Node</th><th>Sensor</th><th>Value</th><th>Unit</th></tr>";
      for(var src in sensors){
        for(var sname in sensors[src]){
          if(sname==="nick")continue;
          var sd=sensors[src][sname];
          if(sd&&sd.data&&sd.data.length){
            sh+="<tr><td>"+src+"</td><td>"+sname+"</td><td>"+sd.data[sd.data.length-1][1]+"</td><td>"+sd.unit+"</td></tr>";
          }
        }
      }
      sh+="</table>";
      document.getElementById("sensors").innerHTML=sh;
    }

    renderDevices(d);
    renderAutomation(rules,autoLog);
  }catch(e){
    console.log("[fetchData] error:",e);
  }finally{
    _fetching=false;
  }
}
async function controlDevice(name,value){
  addLog("GPIO 제어: "+name+" → "+value+" (요청)");
  console.log("[controlDevice] name=",name,"value=",value);
  var r=await fetchJSON("/api/control?name="+encodeURIComponent(name)+"&value="+value);
  console.log("[controlDevice] response=",r);
  if(r&&r.status==="ok"&&r.device){
    // 로컬 장치: 서버가 방금 읽은 상태를 즉시 UI에 반영
    applyDeviceState(r.node_id,r.device);
    var dev=r.device;
    var stateStr;
    if(dev.state!==null&&dev.state!==undefined){
      stateStr=dev.state===1?"ON":"OFF";
    }else if(dev.duty!==null&&dev.duty!==undefined){
      stateStr=Math.round(dev.duty/10.23)+"%";
    }else{
      stateStr="?";
    }
    addLog("GPIO 적용: "+name+" = "+stateStr+" (로컬 "+(r.nick||r.node_id)+")");
  }else if(r&&r.status==="sent"&&r.is_self===false){
    // 원격 노드 장치: 명령 전송됨. 해당 노드가 device_info 브로드캐스트할 때까지
    // 잠시 대기 후 /api/devices 재폴링하여 갱신된 상태 표시
    var tgt=r.target_node||"";
    addLog("GPIO 전송: "+name+" → "+value+" (원격 "+tgt+", 상태 대기 중)");
    setTimeout(function(){fetchData();},300);
    setTimeout(function(){fetchData();},700);
    setTimeout(function(){
      fetchData();
      addLog("GPIO 갱신: "+name+" (원격 응답 수신)");
    },1200);
  }else{
    console.log("[controlDevice] unexpected response, falling back to fetchData");
    addLog("GPIO 오류: "+name+" (응답: "+JSON.stringify(r)+")");
    fetchData();
  }
}
async function toggleGpio(name,state){
  await controlDevice(name,state?0:1);
}
async function setNeopixel(name,hexColor){
  // hexColor: "#RRGGBB" → 0xRRGGBB 정수로 변환
  var hex=parseInt(hexColor.replace("#",""),16);
  await controlDevice(name,"0x"+hex.toString(16).toUpperCase());
}
// 장치 상태를 화면에 즉시 반영 (DOM을 직접 갱신하여 폴링 대기 없이 표시)
function applyDeviceState(nodeId,device){
  console.log("[applyDeviceState] nodeId=",nodeId,"device=",device);
  var nodes=document.getElementById("devices-panel").children;
  var found=false;
  for(var i=0;i<nodes.length;i++){
    var nodeEl=nodes[i];
    var domNodeId=nodeEl.getAttribute("data-node-id");
    console.log("[applyDeviceState] check node",i,"data-node-id=",domNodeId,"vs",nodeId);
    if(domNodeId!==nodeId)continue;
    found=true;
    var devEls=nodeEl.querySelectorAll("[data-dev-name]");
    for(var j=0;j<devEls.length;j++){
      var el=devEls[j];
      if(el.getAttribute("data-dev-name")===device.name){
        var type=el.getAttribute("data-dev-type");
        console.log("[applyDeviceState] matched device",device.name,"type",type);
        if(type==="gpio"){
          var st=device.state===null?0:device.state;
          var btn=el.querySelector("button");
          if(btn){
            btn.style.background=st===1?"#e94560":"#0f3460";
            btn.textContent=st===1?"ON":"OFF";
            btn.setAttribute("onclick","toggleGpio("+JSON.stringify(device.name)+","+st+")");
            console.log("[applyDeviceState] button updated: ON=",st);
          }
        }else if(type==="pwm"){
          var duty=device.duty===null?0:device.duty;
          var pct=Math.round(duty/10.23);
          var rng=el.querySelector("input[type=range]");
          var lbl=el.querySelector("span");
          if(rng)rng.value=pct;
          if(lbl)lbl.textContent=pct+"%";
          console.log("[applyDeviceState] slider updated: pct=",pct);
        }else if(type==="neopixel"){
          // NeoPixel 색상 즉시 갱신
          var hexColor=device.color||0;
          var hexStr="#"+("000000"+hexColor.toString(16)).slice(-6).toUpperCase();
          var cl=el.querySelector("input[type=color]");
          var lbl=el.querySelector("span");
          if(cl)cl.value=hexStr;
          if(lbl)lbl.textContent=hexStr;
        }
      }
    }
  }
  if(!found){
    console.log("[applyDeviceState] WARNING: node not found in DOM, nodeId=",nodeId);
    // DOM에 노드가 없으면 전체 재렌더링
    fetchData();
  }
}
function renderDevices(d){
  var c=document.getElementById("devices-panel");
  if(!d||!d.nodes||d.nodes.length===0){
    c.innerHTML="<p style='color:#888;text-align:center'>No devices</p>";
    return;
  }
  // 장치 목록 구조가 같으면 상태 값만 업데이트 (깜빡임/상태 손실 방지)
  var needsFullRender=false;
  // 각 노드의 장치 목록이 기존 DOM과 같은지 확인
  var existingNodes=c.querySelectorAll("[data-node-id]");
  if(existingNodes.length!==d.nodes.length){
    needsFullRender=true;
  }else{
    for(var i=0;i<d.nodes.length;i++){
      var nodeEl=existingNodes[i];
      if(nodeEl.getAttribute("data-node-id")!=d.nodes[i].node_id){
        needsFullRender=true;
        break;
      }
      var existingDevs=nodeEl.querySelectorAll("[data-dev-name]");
      var newDevs=d.nodes[i].devices||[];
      if(existingDevs.length!==newDevs.length){
        needsFullRender=true;
        break;
      }
      for(var j=0;j<newDevs.length;j++){
        if(existingDevs[j].getAttribute("data-dev-name")!=newDevs[j].name||
           existingDevs[j].getAttribute("data-dev-type")!=newDevs[j].type){
          needsFullRender=true;
          break;
        }
      }
      if(needsFullRender)break;
    }
  }

  if(needsFullRender){
    // 전체 렌더링 (장치 추가/제거/순서 변경 시)
    var html="";
    d.nodes.forEach(function(node){
      var badge=node.is_self?" <span style='color:#0f0'>(self)</span>":"";
      html+="<div data-node-id="+JSON.stringify(node.node_id)+" style='margin-bottom:15px;border:2px solid #0f3460;padding:10px;border-radius:6px'>";
      html+="<div style='color:#e94560;font-weight:bold;margin-bottom:8px'>"+node.nick+" <span style='color:#888;font-size:11px'>["+node.node_id+"]"+badge+"</span></div>";
      if(node.devices.length===0){
        html+="<p style='color:#666;font-size:12px'>No devices</p>";
      }else{
        node.devices.forEach(function(dev){
          html+="<div data-dev-name="+JSON.stringify(dev.name)+" data-dev-type="+JSON.stringify(dev.type)+" style='display:flex;align-items:center;gap:10px;margin:4px 0;padding:6px;background:#0a1428;border-radius:4px'>";
          html+="<div style='flex:1'><div style='color:#e0e0e0'>"+dev.name+"</div>";
          var tl=dev.type;
          if(dev.unit)tl+=" / "+dev.unit;
          html+="<div style='color:#888;font-size:11px'>"+tl+"</div></div>";
          if(dev.type==="gpio"){
            var st=dev.current_state||0;
            var bc=st===1?"#e94560":"#0f3460";
            var bt=st===1?"ON":"OFF";
            html+="<button onclick='toggleGpio("+JSON.stringify(dev.name)+","+st+")' style='background:"+bc+";color:white;border:none;padding:6px 14px;border-radius:4px;cursor:pointer;font-weight:bold;min-width:50px'>"+bt+"</button>";
          }else if(dev.type==="pwm"){
            var pct=Math.round((dev.current_duty||0)/10.23);
            html+="<input type='range' min='0' max='100' value="+pct+" onchange='controlDevice("+JSON.stringify(dev.name)+",this.value)' style='width:120px'>";
            html+="<span style='color:#0ff;font-size:12px;min-width:35px'>"+pct+"%</span>";
          }else if(dev.type==="neopixel"){
            var cr=dev.current_r||0;
            var cg=dev.current_g||0;
            var cb=dev.current_b||0;
            var hexColor=cr<<16|cg<<8|cb;
            var hexStr="#"+("000000"+hexColor.toString(16)).slice(-6).toUpperCase();
            html+="<input type='color' value='"+hexStr+"' onchange='setNeopixel("+JSON.stringify(dev.name)+",this.value)' style='width:40px;height:30px;border:none;border-radius:4px;cursor:pointer;background:transparent'>";
            html+="<button onclick='controlDevice("+JSON.stringify(dev.name)+",0)' style='background:#0f3460;color:white;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px'>OFF</button>";
            html+="<span style='color:#0ff;font-size:11px;min-width:60px'>"+hexStr+"</span>";
          }else{
            html+="<span style='color:#0f0;font-size:13px'>&#128225;</span>";
          }
          html+="</div>";
        });
      }
      html+="</div>";
    });
    c.innerHTML=html;
  }else{
    // 상태 값만 업데이트 (구조 유지)
    for(var i=0;i<d.nodes.length;i++){
      var nodeEl=existingNodes[i];
      var existingDevs=nodeEl.querySelectorAll("[data-dev-name]");
      var newDevs=d.nodes[i].devices||[];
      for(var j=0;j<newDevs.length;j++){
        var el=existingDevs[j];
        var dev=newDevs[j];
        if(dev.type==="gpio"){
          var st=dev.current_state||0;
          var btn=el.querySelector("button");
          if(btn){
            btn.style.background=st===1?"#e94560":"#0f3460";
            btn.textContent=st===1?"ON":"OFF";
            btn.setAttribute("onclick","toggleGpio("+JSON.stringify(dev.name)+","+st+")");
          }
        }else if(dev.type==="pwm"){
          var pct=Math.round((dev.current_duty||0)/10.23);
          var rng=el.querySelector("input[type=range]");
          var lbl=el.querySelector("span");
          if(rng)rng.value=pct;
          if(lbl)lbl.textContent=pct+"%";
        }else if(dev.type==="neopixel"){
          var cr=dev.current_r||0;
          var cg=dev.current_g||0;
          var cb=dev.current_b||0;
          var hexColor=cr<<16|cg<<8|cb;
          var hexStr="#"+("000000"+hexColor.toString(16)).slice(-6).toUpperCase();
          var cl=el.querySelector("input[type=color]");
          var lbl=el.querySelector("span");
          if(cl)cl.value=hexStr;
          if(lbl)lbl.textContent=hexStr;
        }
      }
    }
  }
}
function renderAutomation(rules,autoLog){
  var c=document.getElementById("automation-rules");
  if(!c)return;
  if(!rules||!rules.rules||Object.keys(rules.rules).length===0){
    c.innerHTML="<p style='color:#888;text-align:center'>No automation rules</p>";
  }else{
    var html="<table><tr><th>Name</th><th>Type</th><th>Condition</th><th>Action</th><th>State</th></tr>";
    for(var rid in rules.rules){
      var r=rules.rules[rid];
      var cond="";
      if(r.sensor){cond=r.sensor+" "+r.operator+" "+r.value}
      else if(r.hysteresis){cond+=" (±"+r.hysteresis+")"}
      var stateColor=r.last_state?"#0f0":"#888";
      var stateText=r.last_state?"TRIGGERED":"idle";
      html+="<tr><td>"+(r.name||rid)+"</td><td>"+(r.sensor||"-")+"</td><td>"+cond+"</td>";
      html+="<td>"+(r.action_device||"-")+"="+ (r.action_value||"-")+"</td>";
      html+="<td style='color:"+stateColor+"'>"+stateText+"</td></tr>";
    }
    html+="</table>";
    c.innerHTML=html;
  }
  var logEl=document.getElementById("automation-log");
  if(logEl&&autoLog&&autoLog.log){
    var logHtml="";
    autoLog.log.forEach(function(entry){
      var actionStr=entry.action==="on"?"TRIGGER":"RELEASE";
      var resultStr=entry.result==="ok"?"OK":entry.result;
      var color=entry.result==="ok"?"#0f0":"#888";
      logHtml+="["+entry.ts_str+"] "+actionStr+" "+entry.rule_name+" → "+entry.device+"="+entry.value+" ("+resultStr+")"+String.fromCharCode(10);
    });
    if(logHtml==="")logHtml="(no execution log)";
    logEl.textContent=logHtml;
    logEl.scrollTop=logEl.scrollHeight;
  }
}
fetchData();
setInterval(fetchData,3000);
console.log("[MESH] Dashboard v2.1 loaded");
</script>
</body>
</html>"""


STATS_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<title>ESP32 Mesh Stats</title>
<style>
*{box-sizing:border-box}
body{font-family:system-ui,sans-serif;background:#1a1a2e;color:#e0e0e0;margin:0;padding:20px}
h1{color:#0ff;text-align:center;border-bottom:2px solid #0ff;padding-bottom:10px}
.nav{text-align:center;margin:10px 0 20px}
.nav a{display:inline-block;padding:8px 16px;margin:0 4px;background:#0f3460;color:#0ff;border-radius:4px;text-decoration:none;font-size:14px}
.nav a.active{background:#e94560;color:#fff}
.nav a:hover{background:#16213e}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:20px 0}
.card{background:#16213e;padding:15px;border-radius:8px;border:1px solid #0f3460}
.card h2{color:#e94560;margin-top:0;font-size:16px}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{padding:6px 8px;border-bottom:1px solid #0f3460;text-align:left}
th{color:#0ff}
.stat{font-size:24px;font-weight:bold;color:#0ff}
</style>
</head>
<body>
<h1>Network Stats</h1>
<div class="nav">
  <a href="/">Dashboard</a>
  <a href="/stats" class="active">Stats</a>
  <a href="/config">Config</a>
</div>
<div class="grid">
  <div class="card" style="grid-column:1 / -1">
    <h2>Statistics</h2>
    <div id="stats"></div>
  </div>
</div>
<div style="text-align:center;color:#444;font-size:11px;margin-top:15px">Mesh Dashboard v2.1</div>
<script>
async function fetchJSON(url){
  try{
    var r=await fetch(url);
    if(!r.ok){return null}
    return await r.json();
  }catch(e){
    return null;
  }
}
var _fetching=false;
async function fetchStats(){
  if(_fetching)return;
  _fetching=true;
  try{
    var stats=await fetchJSON("/api/stats");
    if(stats){
      var s="<table>";
      for(var k in stats){
        var val=stats[k];
        var display=val;
        if(k==="chip_temp"&&val>0){display=val+" °C"}
        else if(k==="cpu_freq_mhz"){display=val+" MHz"}
        else if(k==="free_heap"){display=val.toLocaleString()+" bytes"}
        s+="<tr><td>"+k+"</td><td class='stat'>"+display+"</td></tr>";
      }
      s+="</table>";
      document.getElementById("stats").innerHTML=s;
    }
  }catch(e){
    console.log("[fetchStats] error:",e);
  }finally{
    _fetching=false;
  }
}
fetchStats();
setInterval(fetchStats,5000);
</script>
</body>
</html>"""


CONFIG_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<title>ESP32 Mesh Config</title>
<style>
*{box-sizing:border-box}
body{font-family:system-ui,sans-serif;background:#1a1a2e;color:#e0e0e0;margin:0;padding:20px}
h1{color:#0ff;text-align:center;border-bottom:2px solid #0ff;padding-bottom:10px}
.nav{text-align:center;margin:10px 0 20px}
.nav a{display:inline-block;padding:8px 16px;margin:0 4px;background:#0f3460;color:#0ff;border-radius:4px;text-decoration:none;font-size:14px}
.nav a.active{background:#e94560;color:#fff}
.nav a:hover{background:#16213e}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:20px 0}
.card{background:#16213e;padding:15px;border-radius:8px;border:1px solid #0f3460}
.card h2{color:#e94560;margin-top:0;font-size:16px}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{padding:6px 8px;border-bottom:1px solid #0f3460;text-align:left}
th{color:#0ff}
input,button{padding:8px;font-size:14px;border-radius:4px;border:1px solid #0f3460;background:#0f3460;color:#fff}
input{flex:1}
.send-form{display:flex;gap:8px;margin-top:10px}
</style>
</head>
<body>
<h1>Gateway Config</h1>
<div class="nav">
  <a href="/">Dashboard</a>
  <a href="/stats">Stats</a>
  <a href="/config" class="active">Config</a>
</div>
<div class="grid">
  <div class="card" style="grid-column:1 / -1">
    <div id="ap-warning" style="display:none;background:#5a2d2d;color:#ffb;border:1px solid #e94560;padding:12px;border-radius:4px;margin-bottom:15px">
      <strong>AP 모드 (인터넷 연결 안 됨)</strong><br>
      현재 AP '<span id="ap-ssid-name"></span>' 로 동작 중.<br>
      아래에서 올바른 Wi-Fi 설정 후 Save 하고, 재부팅하세요.
    </div>
  </div>
  <div class="card">
    <h2>Current Configuration</h2>
    <div id="config-info">Loading...</div>
  </div>
  <div class="card">
    <h2>Wi-Fi Settings</h2>
    <div class="send-form">
      <input id="ssid-input" type="text" placeholder="SSID">
    </div>
    <div class="send-form" style="margin-top:8px">
      <input id="pass-input" type="password" placeholder="Password">
      <button onclick="saveConfig()">Save</button>
    </div>
    <div id="config-result" style="margin-top:8px;color:#0f0;font-size:12px"></div>
  </div>
  <div class="card">
    <h2>Time Settings</h2>
    <div style="color:#888;font-size:12px;margin-bottom:8px">NTP가 실패하면 수동으로 시간 설정</div>
    <div id="current-time" style="color:#0ff;font-size:14px;margin-bottom:8px">Loading...</div>
    <div class="send-form">
      <input id="time-input" type="datetime-local" style="flex:1">
      <button onclick="setTime()">Set</button>
    </div>
    <button onclick="syncBrowserTime()" style="margin-top:8px;background:#0f3460;color:white;border:none;padding:6px 14px;border-radius:4px;cursor:pointer;font-size:12px">Use Browser Time</button>
    <div id="time-result" style="margin-top:8px;color:#0f0;font-size:12px"></div>
  </div>
</div>
<div style="text-align:center;color:#444;font-size:11px;margin-top:15px">Mesh Dashboard v2.1</div>
<script>
async function fetchJSON(url){
  try{
    var r=await fetch(url);
    if(!r.ok){return null}
    return await r.json();
  }catch(e){
    return null;
  }
}
async function loadConfig(){
  var cfg=await fetchJSON("/api/config");
  if(cfg){
    var ch="<table>";
    ch+="<tr><td>Node ID</td><td>"+(cfg.node_id||"?")+"</td></tr>";
    ch+="<tr><td>Nick</td><td>"+(cfg.nickname||"?")+"</td></tr>";
    ch+="<tr><td>Role</td><td>"+(cfg.node_role||"?")+"</td></tr>";
    ch+="<tr><td>SSID</td><td>"+(cfg.gateway_ssid||"(none)")+"</td></tr>";
    ch+="<tr><td>Password</td><td>"+(cfg.gateway_password_set?"set":"unset")+"</td></tr>";
    ch+="<tr><td>MQTT</td><td>"+(cfg.mqtt_broker||"?")+":"+(cfg.mqtt_port||"?")+"</td></tr>";
    ch+="<tr><td>Group</td><td>"+(cfg.gateway_group_id||"?")+"</td></tr>";
    ch+="<tr><td>IP</td><td>"+(cfg.ip||"?")+"</td></tr>";
    ch+="<tr><td>Mode</td><td>"+(cfg.ap_mode?"AP Mode (no internet)":"STA Mode (connected)")+"</td></tr>";
    ch+="</table>";
    document.getElementById("config-info").innerHTML=ch;
    document.getElementById("ssid-input").placeholder=cfg.gateway_ssid||"SSID";
    // AP 모드 경고 표시
    if(cfg.ap_mode){
      var warn=document.getElementById("ap-warning");
      if(warn){
        warn.style.display="block";
        var nameEl=document.getElementById("ap-ssid-name");
        if(nameEl)nameEl.textContent=cfg.ap_ssid||"ESP32-Mesh";
      }
    }
  }
}
async function saveConfig(){
  var ssid=document.getElementById("ssid-input").value.trim();
  var pass=document.getElementById("pass-input").value.trim();
  if(!ssid&&!pass){document.getElementById("config-result").textContent="Need SSID or password";return}
  var p="";
  if(ssid)p+="gateway_ssid="+encodeURIComponent(ssid)+"&";
  if(pass)p+="gateway_password="+encodeURIComponent(pass);
  var r=await fetchJSON("/api/config_save?"+p);
  if(r&&r.status==="saved"){
    document.getElementById("config-result").textContent="Saved!";
    document.getElementById("ssid-input").value="";
    document.getElementById("pass-input").value="";
    loadConfig();
  }
}
async function loadTime(){
  var r=await fetchJSON("/api/settime");
  if(r){
    document.getElementById("current-time").textContent=
      "현재 시간: "+r.current_time+(r.ntp_synced?" (NTP)":" (수동)");
    // datetime-local 입력 필드에 현재 시간 설정
    if(r.current_time){
      var dt=r.current_time.substring(0,16).replace(" ","T");
      document.getElementById("time-input").value=dt;
    }
  }
}
async function setTime(){
  var input=document.getElementById("time-input");
  var timeVal=input.value;
  if(!timeVal){document.getElementById("time-result").textContent="시간을 입력하세요";return}
  var r=await fetchJSON("/api/settime?time="+encodeURIComponent(timeVal));
  if(r&&r.status==="ok"){
    document.getElementById("time-result").textContent="설정됨: "+r.set_time;
    loadTime();
  }else{
    document.getElementById("time-result").textContent="설정 실패: "+JSON.stringify(r);
  }
}
async function syncBrowserTime(){
  var now=new Date();
  var iso=now.getFullYear()+"-"+
    ("0"+(now.getMonth()+1)).slice(-2)+"-"+
    ("0"+now.getDate()).slice(-2)+"T"+
    ("0"+now.getHours()).slice(-2)+":"+
    ("0"+now.getMinutes()).slice(-2)+":"+
    ("0"+now.getSeconds()).slice(-2);
  var r=await fetchJSON("/api/settime?time="+encodeURIComponent(iso));
  if(r&&r.status==="ok"){
    document.getElementById("time-result").textContent="브라우저 시간으로 설정: "+r.set_time;
    loadTime();
  }else{
    document.getElementById("time-result").textContent="설정 실패";
  }
}
loadConfig();
loadTime();
setInterval(loadTime,10000);
</script>
</body>
</html>"""


