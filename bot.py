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
    return state.setdefault(str(uid), {"voice":"g:Kore","style":"normal"})

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

HELP = ("\U0001F399 أهلاً بك في بوت تقنيات المستقبل لتحويل النص إلى كلام\n\n"
 "ابعت أي نص بالعربي أو أي لغة، وهرجعه لك رسالة صوتية.\n\n"
 "\U0001F539 /voice اختيار اللغة والصوت (أكتر من 340 صوت عربي وعالمي)\n"
 "\U0001F539 /style اختيار طريقة الإلقاء\n"
 "\U0001F539 /help المساعدة\n\n"
 "\U0001F4E2 انضم لمجتمع تقنيات المستقبل:\n"
 "تيليجرام: https://t.me/euvsugxaj\n"
 "واتساب: https://chat.whatsapp.com/Lc80q70aLPTGel7wv8G0dh?s=cl&p=a&iam=2")

def disp(vid):
    if vid.startswith("g:"): return "Gemini "+vid[2:]
    v = EDGE.get(vid[2:]); return (v["ShortName"] if v else vid[2:])
ARC = {"EG":"مصر","SA":"السعودية","AE":"الإمارات","KW":"الكويت","QA":"قطر","BH":"البحرين","OM":"عمان","JO":"الأردن","LB":"لبنان","SY":"سوريا","IQ":"العراق","YE":"اليمن","LY":"ليبيا","TN":"تونس","DZ":"الجزائر","MA":"المغرب","PS":"فلسطين","SD":"السودان"}
def kb_rows(items, per=2):
    return [items[i:i+per] for i in range(0,len(items),per)]
def lang_codes():
    codes = sorted({k.split("-")[0] for k in EDGE})
    main = [c for c in LANGNAMES if c in codes]
    rest = [c for c in codes if c not in LANGNAMES]
    return main, rest
def lang_kb(page=0):
    main, rest = lang_codes()
    if page == 0:
        its=[{"text":LANGNAMES[c],"callback_data":"L:"+c} for c in main]
        if rest: its.append({"text":"لغات أخرى","callback_data":"lp:1"})
        return {"inline_keyboard":kb_rows(its)}
    its=[{"text":c,"callback_data":"L:"+c} for c in rest]
    return {"inline_keyboard":kb_rows(its,3)+[[{"text":"رجوع للغات الأساسية","callback_data":"lp:0"}]]}
def edge_label(k,v):
    p=k.split("-"); name=p[2].replace("Neural","") if len(p)>2 else k
    who="رجل" if v["Gender"]=="Male" else "امرأة"
    if p[0]=="ar": return f"{name} - {ARC.get(p[1],p[1])} - {who}"
    return f"{name} ({p[1]}) - {who}"
def voice_kb(lang):
    its=[{"text":"⭐ أصوات Gemini الطبيعية","callback_data":"G:"+lang}]
    its+=[{"text":edge_label(k,v),"callback_data":"v:e:"+k} for k,v in EDGE.items() if k.startswith(lang+"-")]
    return {"inline_keyboard":kb_rows(its[:90],1)+[[{"text":"رجوع لاختيار اللغة","callback_data":"lp:0"}]]}
def gem_kb(lang):
    its=[{"text":f"{n} - {VOICES[n]}","callback_data":"v:g:"+n} for n in VOICES]
    return {"inline_keyboard":kb_rows(its,2)+[[{"text":"رجوع لأصوات اللغة","callback_data":"L:"+lang}]]}
def after_kb():
    return {"inline_keyboard":[[{"text":"تغيير الصوت","callback_data":"chv"},{"text":"تغيير اللغة","callback_data":"lp:0"}]]}
def show(q_or_chat, text, kb, q=None):
    if q:
        r = tg("editMessageText", chat_id=q["message"]["chat"]["id"], message_id=q["message"]["message_id"], text=text, reply_markup=kb)
        if r.get("ok"): return
    tg("sendMessage", chat_id=q_or_chat, text=text, reply_markup=kb)
LANG_PROMPT = "اختار اللغة اللي عايز تحول بيها النص لصوت:"
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
    if cmd in ("/start","/help"):
        tg("sendMessage", chat_id=chat_id, text=HELP)
        tg("sendMessage", chat_id=chat_id, text=LANG_PROMPT, reply_markup=lang_kb())
    elif cmd in ("/voice","/language"): tg("sendMessage", chat_id=chat_id, text=LANG_PROMPT, reply_markup=lang_kb())
    elif cmd == "/style": tg("sendMessage", chat_id=chat_id, text="اختار طريقة الإلقاء:", reply_markup=style_kb())
    elif cmd: tg("sendMessage", chat_id=chat_id, text=HELP)
    else:
        if limited(uid): tg("sendMessage", chat_id=chat_id, text="استنى دقيقة وجرب تاني."); return
        if not st(uid).get("chosen"):
            tg("sendMessage", chat_id=chat_id, text="الأول اختار اللغة والصوت:", reply_markup=lang_kb()); return
        speak(chat_id, uid, text, mid)

def on_cb(q):
    uid = q["from"]["id"]; chat_id = q["message"]["chat"]["id"]; d = q.get("data","")
    if d == "chk":
        ok = is_member(uid)
        if ok: tg("answerCallbackQuery", callback_query_id=q["id"], text="تم التحقق"); tg("sendMessage", chat_id=chat_id, text=HELP); tg("sendMessage", chat_id=chat_id, text=LANG_PROMPT, reply_markup=lang_kb())
        else: tg("answerCallbackQuery", callback_query_id=q["id"], text="لسه ما اشتركتش", show_alert=True)
        return
    if CHANNELS and not is_member(uid):
        tg("answerCallbackQuery", callback_query_id=q["id"], text="اشترك في القناة الأول", show_alert=True); return
    tg("answerCallbackQuery", callback_query_id=q["id"])
    if d.startswith("lp:"):
        show(chat_id, LANG_PROMPT, lang_kb(int(d[3:] or 0)), q)
    elif d.startswith("L:"):
        l=d[2:]; s=st(uid); s["lang"]=l; save()
        show(chat_id, f"اختار الصوت للغة {LANGNAMES.get(l,l)}:", voice_kb(l), q)
    elif d.startswith("G:"):
        show(chat_id, "أصوات Gemini الطبيعية (بتقرا أي لغة):", gem_kb(d[2:]), q)
    elif d == "chv":
        show(chat_id, "اختار اللغة:", lang_kb(), q)
    elif d.startswith("v:") and ((d[2:4]=="g:" and d[4:] in VOICES) or (d[2:4]=="e:" and d[4:] in EDGE)):
        s = st(uid); s["voice"] = d[2:]; s["chosen"] = True; save()
        show(chat_id, f"تم اختيار الصوت: {disp(d[2:])}\nدلوقتي ابعت النص اللي عايز تحوله لصوت. الاختيار ده هيفضل محفوظ للنصوص الجاية.", after_kb(), q)
    elif d.startswith("s:") and d[2:] in STYLES:
        st(uid)["style"] = d[2:]; save()
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
