import os, asyncio, json, base64, subprocess, threading, time, urllib.request, urllib.parse, uuid, tempfile, io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from collections import defaultdict, deque

TOKEN = os.environ["BOT_TOKEN"]
GKEYS = [k.strip() for k in os.environ["GEMINI_API_KEY"].split(",") if k.strip()]
SECRET = os.environ.get("WEBHOOK_SECRET", "hook")
CHANNELS = [c.strip() for c in os.environ.get("REQUIRED_CHANNELS", "").split(",") if c.strip()]  # @name or -100id
CH_LINKS = [c.strip() for c in os.environ.get("CHANNEL_LINKS", "").split(",") if c.strip()]
BRAND = "تقنيات المستقبل"
MODELS = ["gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts"]
API = f"https://api.telegram.org/bot{TOKEN}/"
MAXCH = 900
PER_MIN = 6

VOICES = {
 "Zephyr":"مشرق","Puck":"حماسي","Charon":"إخباري","Kore":"حازم","Fenrir":"متحمس","Leda":"شبابي",
 "Orus":"حازم","Aoede":"خفيف","Callirrhoe":"مريح","Autonoe":"مشرق","Enceladus":"هامس","Iapetus":"واضح",
 "Umbriel":"هادئ","Algieba":"ناعم","Despina":"ناعم","Erinome":"واضح","Algenib":"خشن","Rasalgethi":"إخباري",
 "Laomedeia":"حماسي","Achernar":"رقيق","Alnilam":"حازم","Schedar":"متزن","Gacrux":"ناضج","Pulcherrima":"مباشر",
 "Achird":"ودود","Zubenelgenubi":"عفوي","Vindemiatrix":"لطيف","Sadachbia":"نشيط","Sadaltager":"عالم","Sulafat":"دافئ"}
STYLES = {"normal":("عادي",""),"slow":("بطيء","speaking slowly"),"fast":("سريع","speaking quickly"),
 "news":("نشرة أخبار","like a professional news anchor"),"warm":("دافئ","warm and friendly"),
 "calm":("هادئ","calm and relaxed"),"happy":("مبسوط","cheerful and excited")}

state = {}  # uid -> {"voice","style"}
SF = "state.json"
try: state = json.load(open(SF))
except Exception: pass
def save():
    try: json.dump(state, open(SF, "w"))
    except Exception: pass
def st(uid):
    return state.setdefault(str(uid), {"voice":"e:ar-EG-SalmaNeural","style":"normal"})

def tg(method, **p):
    data = json.dumps(p).encode()
    r = urllib.request.Request(API+method, data, {"Content-Type":"application/json"})
    try:
        return json.load(urllib.request.urlopen(r, timeout=30))
    except urllib.error.HTTPError as e:
        try: return json.load(e)
        except Exception: return {"ok":False}
    except Exception:
        return {"ok":False}

def tg_voice(chat_id, ogg, caption, reply_to):
    b = uuid.uuid4().hex
    parts = []
    def f(n, v): parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}\r\n'.encode())
    f("chat_id", chat_id); f("caption", caption); f("reply_to_message_id", reply_to); f("allow_sending_without_reply","true")
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="voice"; filename="tts.ogg"\r\nContent-Type: audio/ogg\r\n\r\n'.encode()+ogg+b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    r = urllib.request.Request(API+"sendVoice", b"".join(parts), {"Content-Type":f"multipart/form-data; boundary={b}"})
    try: return json.load(urllib.request.urlopen(r, timeout=60))
    except Exception as e: return {"ok":False,"err":str(e)}

import edge_tts
EDGE = {}
def load_edge():
    try:
        for v in asyncio.run(edge_tts.list_voices()):
            EDGE[v["ShortName"]] = v
    except Exception: pass
RATES = {"slow":"-25%","fast":"+30%"}
def edge_tts_run(text, voice, style):
    async def go():
        c = edge_tts.Communicate(text, voice, rate=RATES.get(style,"+0%"))
        b = b""
        async for ch in c.stream():
            if ch["type"] == "audio": b += ch["data"]
        return b
    b = asyncio.run(go())
    if not b: raise RuntimeError("empty")
    return b, "audio/mpeg"
LANGNAMES = {"ar":"العربية","en":"English","fr":"Français","de":"Deutsch","es":"Español","tr":"Türkçe","it":"Italiano","ru":"Русский","fa":"فارسی","ur":"اردو","hi":"हिन्दी","pt":"Português","id":"Indonesia","zh":"中文","ja":"日本語","ko":"한국어"}
_ki = [0]
def gemini_tts(text, voice, style):
    last = None
    for model in MODELS:
        for _ in range(len(GKEYS)):
            key = GKEYS[_ki[0] % len(GKEYS)]
            body = {"contents":[{"parts":[{"text": text}]}],
                    "generationConfig":{"responseModalities":["AUDIO"],
                      "speechConfig":{"voiceConfig":{"prebuiltVoiceConfig":{"voiceName":voice}}}}}
            if style:
                body["contents"][0]["parts"][0]["text"] = f"Say this {style}: {text}"
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            r = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type":"application/json","x-goog-api-key":key})
            try:
                j = json.load(urllib.request.urlopen(r, timeout=90))
                for p in j["candidates"][0]["content"]["parts"]:
                    if "inlineData" in p:
                        return base64.b64decode(p["inlineData"]["data"]), p["inlineData"].get("mimeType","")
                last = "no audio"
            except urllib.error.HTTPError as e:
                last = f"{e.code}"
                if e.code == 429: _ki[0] += 1
            except Exception as e:
                last = str(e)
    raise RuntimeError(last)

def to_ogg(raw, mime):
    if "mpeg" in mime: args = ["-f","mp3"]
    elif raw[:4] == b"RIFF": args = ["-f","wav"]
    else:
        rate = "24000"
        if "rate=" in mime: rate = mime.split("rate=")[1].split(";")[0]
        args = ["-f","s16le","-ar",rate,"-ac","1"]
    p = subprocess.run(["ffmpeg","-v","error","-i","pipe:0","-c:a","libopus","-b:a","48k","-f","ogg","pipe:1"][:2]+[] , input=raw, capture_output=True) if False else \
        subprocess.run(["ffmpeg","-v","error"]+args+["-i","pipe:0","-c:a","libopus","-b:a","48k","-ar","48000","-f","ogg","pipe:1"], input=raw, capture_output=True)
    if p.returncode: raise RuntimeError("ffmpeg")
    return p.stdout

def chunks(t):
    out, cur = [], ""
    for para in t.replace("\r","").split("\n"):
        while len(para) > MAXCH:
            cut = max(para.rfind(".",0,MAXCH), para.rfind("،",0,MAXCH), para.rfind(" ",0,MAXCH))
            cut = cut if cut > 100 else MAXCH
            out.append(para[:cut+1]); para = para[cut+1:]
        if len(cur)+len(para)+1 > MAXCH and cur: out.append(cur); cur = ""
        cur += (("\n" if cur else "")+para)
    if cur.strip(): out.append(cur)
    return [c for c in out if c.strip()]

def is_member(uid):
    for c in CHANNELS:
        r = tg("getChatMember", chat_id=c, user_id=uid)
        if not r.get("ok"): return None
        if r["result"]["status"] in ("left","kicked"): return False
    return True

def gate_msg(chat_id):
    rows = [[{"text":f"اشترك في قناة {i+1}" if len(CH_LINKS)>1 else "اشترك في القناة","url":l}] for i,l in enumerate(CH_LINKS)]
    rows.append([{"text":"✅ تم الاشتراك، تحقق","callback_data":"chk"}])
    tg("sendMessage", chat_id=chat_id, text=f"أهلاً بك في بوت تحويل النص إلى صوت من {BRAND}.\nعشان تستخدم البوت لازم تشترك في القناة الأول، وبعدها اضغط زر التحقق.", reply_markup={"inline_keyboard":rows})

HELP = (f"أهلاً بك في بوت {BRAND} لتحويل النص إلى صوت.\n"
 "ابعت أي نص بالعربي أو أي لغة وهرجعه لك رسالة صوتية.\n\n"
 "/voice لاختيار الصوت\n/style لاختيار طريقة الإلقاء\n/help للمساعدة")

def disp(vid):
    if vid.startswith("g:"): return "Gemini "+vid[2:]
    v = EDGE.get(vid[2:]); return (v["ShortName"] if v else vid[2:])
def voice_root():
    rows=[[{"text":"أصوات عربية (لهجات)","callback_data":"m:ar"}],
          [{"text":"أصوات Gemini من جوجل","callback_data":"m:g"}],
          [{"text":"لغات أخرى","callback_data":"m:l"}]]
    return {"inline_keyboard":rows}
def kb_rows(items, per=2):
    rows=[]
    for i in range(0,len(items),per): rows.append(items[i:i+per])
    return rows
def menu(kind):
    if kind=="g":
        its=[{"text":f"{n} - {VOICES[n]}","callback_data":"v:g:"+n} for n in VOICES]
    elif kind=="ar":
        its=[{"text":f"{v['ShortName'].split('-')[1]} {v['ShortName'].split('-')[2].replace('Neural','')} ({'رجل' if v['Gender']=='Male' else 'امرأة'})","callback_data":"v:e:"+k} for k,v in EDGE.items() if k.startswith("ar-")]
    elif kind=="l":
        langs=sorted({k.split("-")[0] for k in EDGE if not k.startswith("ar-")}, key=lambda x:(x not in LANGNAMES,x))
        its=[{"text":LANGNAMES.get(l,l),"callback_data":"m:l:"+l} for l in langs]
    elif kind.startswith("l:"):
        l=kind[2:]
        its=[{"text":f"{k.split('-',1)[1].replace('Neural','')} ({'M' if v['Gender']=='Male' else 'F'})","callback_data":"v:e:"+k} for k,v in EDGE.items() if k.startswith(l+"-")]
    else: its=[]
    return {"inline_keyboard":kb_rows(its[:96])+[[{"text":"رجوع","callback_data":"m:root"}]]}
def style_kb():
    return {"inline_keyboard":[[{"text":v[0],"callback_data":"s:"+k}] for k,v in STYLES.items()]}

hist = defaultdict(deque)
def limited(uid):
    now = time.time(); d = hist[uid]
    while d and now-d[0] > 60: d.popleft()
    if len(d) >= PER_MIN: return True
    d.append(now); return False

def speak(chat_id, uid, text, mid):
    s = st(uid)
    tg("sendChatAction", chat_id=chat_id, action="record_voice")
    for c in chunks(text)[:5]:
        try:
            vid = s["voice"]
            if vid.startswith("e:"):
                try: raw, mime = edge_tts_run(c, vid[2:], s["style"])
                except Exception: raw, mime = gemini_tts(c, "Kore", STYLES[s["style"]][1])
            else:
                try: raw, mime = gemini_tts(c, vid[2:] if vid[:2]=="g:" else vid, STYLES[s["style"]][1])
                except Exception: raw, mime = edge_tts_run(c, "ar-EG-SalmaNeural", s["style"])
            ogg = to_ogg(raw, mime)
        except Exception:
            tg("sendMessage", chat_id=chat_id, text="حصلت مشكلة وقت التحويل، جرب تاني بعد شوية.", reply_to_message_id=mid); return
        tg_voice(chat_id, ogg, f"{BRAND} | {disp(s['voice'])}", mid)

def on_message(m):
    chat_id = m["chat"]["id"]; uid = m["from"]["id"]; mid = m["message_id"]
    if m["chat"].get("type") != "private": return
    text = m.get("text")
    if not text:
        tg("sendMessage", chat_id=chat_id, text="ابعت نص عشان أحوله لصوت."); return
    if CHANNELS:
        ok = is_member(uid)
        if ok is False or ok is None and False: gate_msg(chat_id); return
        if ok is None:
            tg("sendMessage", chat_id=chat_id, text="البوت تحت الصيانة لحظات، جرب بعد شوية."); return
    cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
    if cmd in ("/start","/help"): tg("sendMessage", chat_id=chat_id, text=HELP)
    elif cmd == "/voice": tg("sendMessage", chat_id=chat_id, text="اختار الصوت:", reply_markup=voice_root())
    elif cmd == "/style": tg("sendMessage", chat_id=chat_id, text="اختار طريقة الإلقاء:", reply_markup=style_kb())
    elif cmd: tg("sendMessage", chat_id=chat_id, text=HELP)
    else:
        if limited(uid): tg("sendMessage", chat_id=chat_id, text="استنى دقيقة وجرب تاني."); return
        speak(chat_id, uid, text, mid)

def on_cb(q):
    uid = q["from"]["id"]; chat_id = q["message"]["chat"]["id"]; d = q.get("data","")
    if d == "chk":
        ok = is_member(uid)
        if ok: tg("answerCallbackQuery", callback_query_id=q["id"], text="تم التحقق"); tg("sendMessage", chat_id=chat_id, text=HELP)
        else: tg("answerCallbackQuery", callback_query_id=q["id"], text="لسه ما اشتركتش", show_alert=True)
        return
    if CHANNELS and not is_member(uid):
        tg("answerCallbackQuery", callback_query_id=q["id"], text="اشترك في القناة الأول", show_alert=True); return
    if d.startswith("m:"):
        k = d[2:]
        tg("answerCallbackQuery", callback_query_id=q["id"])
        if k=="root": tg("sendMessage", chat_id=chat_id, text="اختار الصوت:", reply_markup=voice_root())
        else: tg("sendMessage", chat_id=chat_id, text="اختار:", reply_markup=menu(k))
    elif d.startswith("v:") and ((d[2:4]=="g:" and d[4:] in VOICES) or (d[2:4]=="e:" and d[4:] in EDGE)):
        st(uid)["voice"] = d[2:]; save()
        tg("answerCallbackQuery", callback_query_id=q["id"], text="تم اختيار الصوت")
        tg("sendMessage", chat_id=chat_id, text=f"تم اختيار الصوت {disp(d[2:])}. ابعت النص.")
    elif d.startswith("s:") and d[2:] in STYLES:
        st(uid)["style"] = d[2:]; save()
        tg("answerCallbackQuery", callback_query_id=q["id"], text="تم")
        tg("sendMessage", chat_id=chat_id, text=f"تم اختيار طريقة الإلقاء: {STYLES[d[2:]][0]}.")

class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def do_POST(self):
        n = int(self.headers.get("Content-Length",0)); body = self.rfile.read(n)
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        if self.path != "/"+SECRET: return
        try: u = json.loads(body)
        except Exception: return
        def run():
            try:
                if "message" in u: on_message(u["message"])
                elif "callback_query" in u: on_cb(u["callback_query"])
            except Exception: pass
        threading.Thread(target=run, daemon=True).start()

if __name__ == "__main__":
    load_edge()
    pub = os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL")
    if pub: tg("setWebhook", url=pub.rstrip("/")+"/"+SECRET, allowed_updates=["message","callback_query"], drop_pending_updates=False)
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT","10000"))), H).serve_forever()
