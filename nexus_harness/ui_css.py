"""The cockpit's stylesheet: a standalone page, so it owns its own palette.

No external font, no CDN, no framework. A local page that has to wait 200 ms for Google Fonts is a
page that lies about being local.
"""

CSS = """
:root{
  --bg:#0b0e13; --panel:#12161e; --panel-2:#161b25; --line:#232b38;
  --ink:#e6edf6; --dim:#8b98ab; --accent:#4fd1c5; --accent-2:#7aa2f7;
  --green:#3fb950; --red:#f85149; --amber:#d29922; --violet:#a371f7;
  --mono:ui-monospace,SFMono-Regular,"Cascadia Mono",Consolas,monospace;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{display:flex;gap:14px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--line);
  background:linear-gradient(180deg,#101520,#0d1219);position:sticky;top:0;z-index:5;flex-wrap:wrap}
.brand{font-weight:700;letter-spacing:.3px}
.brand span{color:var(--accent)}
.controls{display:flex;gap:10px;align-items:flex-end;margin-left:auto;flex-wrap:wrap}
label.field{display:flex;flex-direction:column;gap:2px;font-size:11px;color:var(--dim);min-width:0}
label.field select{max-width:250px}
select,input,textarea{background:var(--panel-2);color:var(--ink);border:1px solid var(--line);
  border-radius:7px;padding:6px 8px;font:13px var(--mono);outline:none;
  text-overflow:ellipsis;white-space:nowrap}
label.field select{width:250px}
select:focus,input:focus,textarea:focus{border-color:var(--accent-2)}
main{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(320px,1fr);gap:14px;padding:14px 16px 40px}
@media (max-width:980px){main{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.panel h2{margin:0;padding:9px 12px;font-size:12px;letter-spacing:.6px;text-transform:uppercase;
  color:var(--dim);border-bottom:1px solid var(--line);display:flex;gap:8px;align-items:center}
.panel h2 .tag{margin-left:auto;font:11px var(--mono);color:var(--dim);text-transform:none;letter-spacing:0}
.goal{display:flex;gap:8px;padding:12px;border-bottom:1px solid var(--line)}
.goal textarea{flex:1;min-height:64px;resize:vertical}
button{background:var(--accent);color:#04231f;border:0;border-radius:8px;padding:9px 14px;
  font-weight:700;cursor:pointer}
button.ghost{background:transparent;color:var(--ink);border:1px solid var(--line);font-weight:500}
button:disabled{opacity:.45;cursor:not-allowed}
.feed{height:min(52vh,520px);overflow:auto;padding:10px 12px;font-family:var(--mono);font-size:12.5px}
.row{display:grid;grid-template-columns:64px 1fr;gap:8px;padding:4px 0;border-bottom:1px dashed #1b212c}
.row:last-child{border-bottom:0}
.k{font-size:10.5px;letter-spacing:.4px;text-transform:uppercase;padding-top:2px;color:var(--dim)}
.v{white-space:pre-wrap;word-break:break-word}
.k.director,.k.plan{color:var(--violet)} .k.worker,.k.tool{color:var(--accent-2)}
.k.gate{color:var(--green)} .k.gate.bad{color:var(--red)} .k.judge{color:var(--amber)}
.k.skills{color:var(--accent)} .k.session{color:#f0a35e} .k.error{color:var(--red)}
.bar{height:9px;background:#1b212c;border-radius:99px;overflow:hidden;margin:8px 12px 4px;position:relative}
.bar i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--accent),var(--accent-2));
  transition:width .4s}
.bar b{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--amber)}
.meta{display:flex;justify-content:space-between;padding:0 12px 10px;font:11px var(--mono);color:var(--dim)}
.cards{display:grid;gap:10px;padding:12px}
.card{background:var(--panel-2);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.card h3{margin:0 0 6px;font-size:11px;letter-spacing:.5px;text-transform:uppercase;color:var(--dim)}
.card .big{font:13px var(--mono);word-break:break-word}
.pill{display:inline-block;padding:1px 8px;border-radius:99px;font:11px var(--mono);border:1px solid var(--line)}
.pill.ok{color:var(--green);border-color:#1d3a25} .pill.bad{color:var(--red);border-color:#4a1f1f}
.pill.warn{color:var(--amber);border-color:#4a3a12} .pill.info{color:var(--accent-2)}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.chips span{font:11px var(--mono);color:var(--accent);background:#0f2b2a;border:1px solid #1d4a47;
  border-radius:99px;padding:1px 8px}
ul.plain{list-style:none;margin:0;padding:0;font:12px var(--mono);color:var(--dim)}
ul.plain li{padding:3px 0;border-bottom:1px dashed #1b212c}
footer{padding:0 16px 20px;color:#5d6a7d;font:11px var(--mono)}
"""
