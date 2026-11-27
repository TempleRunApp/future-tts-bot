import os, asyncio, json, base64, hashlib, subprocess, threading, time, urllib.request, urllib.parse, uuid, tempfile, io
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
# ---- per-user API keys: encrypted at rest, bound to one user ----
def _sk():
    return hashlib.sha256((TOKEN + "|uk|v1").encode()).digest()
def _ks(b):
    k = _sk(); out = bytearray(); i = 0
    while len(out) < len(b):
        out += hashlib.sha256(k + i.to_bytes(4, "big")).digest(); i += 1
    return bytes(x ^ y for x, y in zip(b, out))
def enc(s):
    return base64.b64encode(_ks(s.encode())).decode()
def dec(s):
    try: return _ks(base64.b64decode(s)).decode()
    except Exception: return ""
def ukey(uid, eng):
    v = (state.get(str(uid)) or {}).get("keys", {}).get(eng)
    return dec(v) if v else ""
def set_ukey(uid, eng, key):
    s = st(uid); ks = s.setdefault("keys", {})
    if key: ks[eng] = enc(key)
    else: ks.pop(eng, None)
    save()
def mask(k):
    return (k[:4] + "\u2026" + k[-4:]) if len(k) > 12 else "\u2026" + k[-2:]
def check_key(eng, key):
    try:
        if eng == "g":
            r = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1", headers={"x-goog-api-key": key, "User-Agent": "futuretts/1.0"})
        elif eng == "q":
            r = urllib.request.Request("https://api.groq.com/openai/v1/models", headers={"Authorization": "Bearer " + key, "User-Agent": "futuretts/1.0"})
        else:
            r = urllib.request.Request("https://api.elevenlabs.io/v1/user", headers={"xi-api-key": key, "User-Agent": "futuretts/1.0"})
        return urllib.request.urlopen(r, timeout=20).status == 200
    except Exception:
        return False
await_key = {}
def keys_text(uid):
    q = ukey(uid, "q"); x = ukey(uid, "x"); g = ukey(uid, "g")
    return ("\U0001F511 \u0645\u0641\u0627\u062a\u064a\u062d\u064a\n\n"
      "\u0644\u0648 \u0639\u0646\u062f\u0643 \u0645\u0641\u062a\u0627\u062d API \u062e\u0627\u0635 \u0628\u0643\u060c \u062d\u0637\u0647 \u0647\u0646\u0627 \u0648\u0627\u0644\u0628\u0648\u062a \u0647\u064a\u0633\u062a\u062e\u062f\u0645\u0647 \u0644\u064a\u0643 \u0627\u0646\u062a \u0628\u0633\u060c \u0648\u0645\u0634 \u0628\u064a\u062a\u062d\u0633\u0628 \u0645\u0646 \u0631\u0635\u064a\u062f \u0627\u0644\u0628\u0648\u062a.\n\n"
      + "Groq: " + (("\u2705 \u0645\u062a\u0633\u062c\u0644 " + mask(q)) if q else "\u274c \u0645\u0634 \u0645\u062a\u0633\u062c\u0644") + "\n"
      + "ElevenLabs: " + (("\u2705 \u0645\u062a\u0633\u062c\u0644 " + mask(x)) if x else "\u274c \u0645\u0634 \u0645\u062a\u0633\u062c\u0644") + "\n"
      + "Gemini: " + (("\u2705 \u0645\u062a\u0633\u062c\u0644 " + mask(g)) if g else "\u274c \u0645\u0634 \u0645\u062a\u0633\u062c\u0644") + "\n\n"
      "\u0645\u0641\u0627\u062a\u064a\u062d \u0627\u0644\u0628\u0648\u062a \u0645\u062a\u0648\u0641\u0631\u0629 \u0628\u062f\u0648\u0646 \u0645\u0641\u062a\u0627\u062d \u062e\u0627\u0635\u060c \u0648\u0644\u0648 \u062d\u0637\u064a\u062a \u0645\u0641\u062a\u0627\u062d\u0643 \u0627\u0644\u062e\u0627\u0635 \u0628\u064a\u0628\u0642\u0649 \u0644\u064a\u0643 \u0627\u0646\u062a \u0648\u0628\u0644\u0627 \u062d\u062f \u062f\u0627\u062e\u0644 \u0627\u0644\u0631\u0635\u064a\u062f \u0627\u0644\u0645\u0634\u062a\u0631\u0643.\n"
      "\u0627\u0644\u0645\u0641\u062a\u0627\u062d \u0628\u064a\u062a\u062e\u0632\u0646 \u0645\u0634\u0641\u0631 \u0648\u0628\u0633 \u0644\u064a\u0643\u060c \u0648\u0628\u064a\u062a\u0645\u0633\u062d \u0645\u0646 \u0627\u0644\u0634\u0627\u062a \u0628\u0639\u062f \u0645\u0627 \u062a\u062d\u0637\u0647.")
def keys_kb(uid):
    rows = [[{"text": ("\u062a\u063a\u064a\u064a\u0631 \u0645\u0641\u062a\u0627\u062d Gemini" if ukey(uid, "g") else "\u0625\u0636\u0627\u0641\u0629 \u0645\u0641\u062a\u0627\u062d Gemini"), "callback_data": "kg"}],
            [{"text": ("\u062a\u063a\u064a\u064a\u0631 \u0645\u0641\u062a\u0627\u062d Groq" if ukey(uid, "q") else "\u0625\u0636\u0627\u0641\u0629 \u0645\u0641\u062a\u0627\u062d Groq"), "callback_data": "kq"}],
            [{"text": ("\u062a\u063a\u064a\u064a\u0631 \u0645\u0641\u062a\u0627\u062d ElevenLabs" if ukey(uid, "x") else "\u0625\u0636\u0627\u0641\u0629 \u0645\u0641\u062a\u0627\u062d ElevenLabs"), "callback_data": "kx"}]]
    if ukey(uid, "g"): rows.append([{"text": "\u0645\u0633\u062d \u0645\u0641\u062a\u0627\u062d Gemini", "callback_data": "dg"}])
    if ukey(uid, "q"): rows.append([{"text": "\u0645\u0633\u062d \u0645\u0641\u062a\u0627\u062d Groq", "callback_data": "dq"}])
    if ukey(uid, "x"): rows.append([{"text": "\u0645\u0633\u062d \u0645\u0641\u062a\u0627\u062d ElevenLabs", "callback_data": "dx"}])
    return {"inline_keyboard": rows}

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

def tg_voice(chat_id, ogg, caption, reply_to, ext="ogg", ct="audio/ogg"):
    b = uuid.uuid4().hex
    parts = []
    def f(n, v): parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}\r\n'.encode())
    f("chat_id", chat_id); f("caption", caption); f("reply_to_message_id", reply_to); f("allow_sending_without_reply","true")
    parts.append((f'--{b}\r\nContent-Disposition: form-data; name="voice"; filename="tts.{ext}"\r\nContent-Type: {ct}\r\n\r\n').encode()+ogg+b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    r = urllib.request.Request(API+"sendVoice", b"".join(parts), {"Content-Type":f"multipart/form-data; boundary={b}"})
    try: return json.load(urllib.request.urlopen(r, timeout=180))
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
    b = b""
    for _ in range(3):
        try: b = asyncio.run(go())
        except Exception: b = b""
        if b: break
        time.sleep(1)
    if not b: raise RuntimeError("empty")
    return b, "audio/mpeg"
LANGNAMES = {"ar":"العربية","en":"English","fr":"Français","de":"Deutsch","es":"Español","tr":"Türkçe","it":"Italiano","ru":"Русский","fa":"فارسی","ur":"اردو","hi":"हिन्दी","pt":"Português","id":"Indonesia","zh":"中文","ja":"日本語","ko":"한국어"}
_ki = [0]
def gemini_tts(text, voice, style, own=None):
    pool = [own] if own else GKEYS
    last = None
    for model in MODELS:
        for _ in range(len(pool)):
            key = own or pool[_ki[0] % len(pool)]
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
                _ki[0] += 1
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

def chunks(t, MAXCH=MAXCH):
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

C_WA = "https://wa.me/201025750695"
C_TG = "https://t.me/+201025750695"
G_WA = "https://chat.whatsapp.com/Lc80q70aLPTGel7wv8G0dh?s=cl&p=a&iam=2"
G_TG = "https://t.me/euvsugxaj"
def contact_kb():
    return {"inline_keyboard":[
        [{"text":"\U0001F4E2 تقنيات المستقبل تليجرام","url":G_TG}],
        [{"text":"\U0001F4AC تقنيات المستقبل واتساب","url":G_WA}],
        [{"text":"\U0001F468\u200D\U0001F4BB تواصل مع المطور","url":C_TG}],
    ]}
CONTACT_TEXT = "\U0001F4DE تواصل\n\nاختار من الأزرار:"
HELP = ("\U0001F399 أهلاً بك في بوت تقنيات المستقبل لتحويل النص إلى كلام\n\n"
 "ابعت أي نص بالعربي أو أي لغة، وهرجعه لك رسالة صوتية.\n\n"
 "\U0001F539 /voice اختيار اللغة والصوت (أكتر من 340 صوت عربي وعالمي)\n"
 "\U0001F539 /style اختيار طريقة الإلقاء\n"
 "\U0001F4DE /contact أو زر «تواصل» تحت: واتساب وتيليجرام ورقم الهاتف\n"
 "\U0001F511 /keys أو زر «مفاتيحي» تحت: تحط مفتاحك الخاص لـ Gemini أو Groq أو ElevenLabs (اختياري، بيتخزن مشفر وبس ليك)\n"
 "\U0001F539 /help المساعدة\n\n"
 "\U0001F4E2 انضم لمجتمع تقنيات المستقبل:\n"
 "تيليجرام: https://t.me/euvsugxaj\n"
 "واتساب: https://chat.whatsapp.com/Lc80q70aLPTGel7wv8G0dh?s=cl&p=a&iam=2")

def disp(vid):
    if vid.startswith("q:"):
        lg, vn = vid[2:].split("-", 1); return "Groq " + vn
    if vid.startswith("g:"): return "Gemini "+vid[2:]
    if vid.startswith("x:"): return "ElevenLabs " + ELEVEN_VOICES.get(vid[2:], "").split(" ")[0]
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
        return {"inline_keyboard":kb_rows(its)+[[{"text":"\U0001F511 مفاتيحي (API keys)","callback_data":"mk"},{"text":"\U0001F4DE تواصل","callback_data":"ct"}]]}
    its=[{"text":c,"callback_data":"L:"+c} for c in rest]
    return {"inline_keyboard":kb_rows(its,3)+[[{"text":"رجوع للغات الأساسية","callback_data":"lp:0"}]]}
def edge_label(k,v):
    p=k.split("-"); name=p[2].replace("Neural","") if len(p)>2 else k
    who="رجل" if v["Gender"]=="Male" else "امرأة"
    if p[0]=="ar": return f"{name} - {ARC.get(p[1],p[1])} - {who}"
    return f"{name} ({p[1]}) - {who}"
def voice_kb(lang, uid=None):
    its=[{"text":"⭐ أصوات Gemini الطبيعية","callback_data":"G:"+lang}]
    if (GROQ_KEYS or (uid and ukey(uid,"q"))) and lang in GROQ_VOICES: its.append({"text":"🎙 أصوات Groq" + (" (لهجة سعودية)" if lang=="ar" else ""),"callback_data":"Q:"+lang})
    if ELEVEN_KEYS or (uid and ukey(uid,"x")): its.append({"text":"🎧 أصوات ElevenLabs (إنجليزي أساسًا)","callback_data":"X:"+lang})
    its+=[{"text":edge_label(k,v),"callback_data":"v:e:"+k} for k,v in EDGE.items() if k.startswith(lang+"-")]
    return {"inline_keyboard":kb_rows(its[:90],1)+[[{"text":"رجوع لاختيار اللغة","callback_data":"lp:0"}]]}
def gem_kb(lang):
    its=[{"text":f"{n} - {VOICES[n]}","callback_data":"v:g:"+n} for n in VOICES]
    return {"inline_keyboard":kb_rows(its,2)+[[{"text":"رجوع لأصوات اللغة","callback_data":"L:"+lang}]]}
def groq_kb(lang):
    its=[{"text":lab,"callback_data":f"v:q:{lang}-{k}"} for k,lab in GROQ_VOICES[lang][1].items()]
    return {"inline_keyboard":kb_rows(its,2)+[[{"text":"رجوع لأصوات اللغة","callback_data":"L:"+lang}]]}
def cur_lang(uid):
    s = st(uid); v = s.get("voice", "")
    if v.startswith("q:") or v.startswith("e:"):
        return v[2:].split("-")[0]
    return s.get("lang") or "ar"
def after_kb():
    return {"inline_keyboard":[[{"text":"تغيير الصوت","callback_data":"chv"},{"text":"تغيير اللغة","callback_data":"lp:0"}],
                               [{"text":"\U0001F511 مفاتيحي (API keys)","callback_data":"mk"},{"text":"\U0001F4DE تواصل","callback_data":"ct"}]]}
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

MAXTOTAL = 15000
USER_Q = int(os.environ.get("GEMINI_USER_DAILY_CHARS", "3000"))      # Gemini chars per user per day (0 = unlimited)
GLOBAL_Q = int(os.environ.get("GEMINI_GLOBAL_DAILY_CHARS", "12000"))  # Gemini chars for all users per day (0 = unlimited)
GROQ_KEYS = [k.strip() for k in os.environ.get("GROQ_API_KEY", "").split(",") if k.strip()]
GROQ_USER_Q = int(os.environ.get("GROQ_USER_DAILY_CHARS", "600"))
GROQ_GLOBAL_Q = int(os.environ.get("GROQ_GLOBAL_DAILY_CHARS", "3000"))
GROQ_VOICES = {"ar": ("canopylabs/orpheus-arabic-saudi", {"abdullah":"عبدالله (رجل)","fahad":"فهد (رجل)","sultan":"سلطان (رجل)","lulwa":"لولوة (امرأة)","noura":"نورة (امرأة)","aisha":"عائشة (امرأة)"}),
               "en": ("canopylabs/orpheus-v1-english", {"autumn":"Autumn (F)","diana":"Diana (F)","hannah":"Hannah (F)","austin":"Austin (M)","daniel":"Daniel (M)","troy":"Troy (M)"})}
_gi = [0]
def groq_tts(text, lang, voice, own=None):
    model = GROQ_VOICES[lang][0]
    pool = [own] if own else GROQ_KEYS
    last = None
    for _ in range(len(pool)):
        key = own or pool[_gi[0] % len(pool)]
        body = {"model": model, "input": text, "voice": voice, "response_format": "wav"}
        r = urllib.request.Request("https://api.groq.com/openai/v1/audio/speech", json.dumps(body).encode(),
                                   {"Content-Type": "application/json", "Authorization": "Bearer " + key, "User-Agent": "futuretts/1.0"})
        try:
            return urllib.request.urlopen(r, timeout=90).read(), "audio/wav"
        except urllib.error.HTTPError as e:
            last = str(e.code)
            if e.code in (429, 403) and not own: _gi[0] += 1
        except Exception as e:
            last = str(e)
    raise RuntimeError(last)
ELEVEN_KEYS = [k.strip() for k in os.environ.get("ELEVEN_API_KEY", "").split(",") if k.strip()]
ELEVEN_USER_Q = int(os.environ.get("ELEVEN_USER_DAILY_CHARS", "200"))
ELEVEN_GLOBAL_Q = int(os.environ.get("ELEVEN_GLOBAL_DAILY_CHARS", "330"))
ELEVEN_VOICES = {"CwhRBWXzGAHq8TQ4Fs17":"Roger (رجل)","JBFqnCBsd6RMkjVDRZzb":"George (رجل)","nPczCjzI2devNBz1zQrb":"Brian (رجل)","onwK4e9ZLuTAKqWW03F9":"Daniel (رجل)","cjVigY5qzO86Huf0OWal":"Eric (رجل)","pqHfZKP75CvOlQylNhV4":"Bill (رجل)","EXAVITQu4vr4xnSDxMaL":"Sarah (امرأة)","XrExE9yKIg1WjnnlVkGX":"Matilda (امرأة)","pFZP5JQG7iQjIQuC4Bku":"Lily (امرأة)","Xb7hH8MSUJpSbSDYk0k2":"Alice (امرأة)","cgSgspJ2msm6clMCkdW9":"Jessica (امرأة)","hpp4J3VqNfWAUOO0d1Us":"Bella (امرأة)",
 "FGY2WhTYpPnrIDTdsKH5":"Laura (امرأة)","IKne3meq5aSn9XLyUdCD":"Charlie (رجل)","N2lVS1w4EtoT3dr4eOWO":"Callum (رجل)","SAz9YHcvj6GT2YYXdXww":"River (محايد)","SOYHLrjzK2X1ezoPC6cr":"Harry (رجل)","TX3LPaxmHKxFdv7VOQHJ":"Liam (رجل)","bIHbv24MWmeRgasZH58o":"Will (رجل)","iP95p4xoKVk53GoZ742B":"Chris (رجل)","pNInz6obpgDQGcFmaJgB":"Adam (رجل)"}
_ei = [0]
eusage = {"day": "", "u": {}, "g": 0}
def eleven_tts(text, vid, own=None):
    pool = [own] if own else ELEVEN_KEYS
    last = None
    for _ in range(len(pool)):
        key = own or pool[_ei[0] % len(pool)]
        body = {"text": text, "model_id": "eleven_multilingual_v2"}
        r = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{vid}?output_format=mp3_44100_64", json.dumps(body).encode(),
                                   {"Content-Type": "application/json", "xi-api-key": key, "User-Agent": "futuretts/1.0"})
        try:
            return urllib.request.urlopen(r, timeout=90).read(), "audio/mpeg"
        except urllib.error.HTTPError as e:
            last = str(e.code)
            if e.code in (401, 402, 403, 429) and not own: _ei[0] += 1
        except Exception as e:
            last = str(e)
    raise RuntimeError(last)
def eleven_ok(uid, n):
    d = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 7200))
    if eusage["day"] != d: eusage.update(day=d, u={}, g=0)
    if not ELEVEN_KEYS: return "off"
    if ELEVEN_USER_Q and eusage["u"].get(uid, 0) + n > ELEVEN_USER_Q: return "user"
    if ELEVEN_GLOBAL_Q and eusage["g"] + n > ELEVEN_GLOBAL_Q*len(ELEVEN_KEYS): return "global"
    return None
def eleven_add(uid, n): eusage["u"][uid] = eusage["u"].get(uid, 0) + n; eusage["g"] += n
def eleven_kb(lang):
    its=[{"text":lab,"callback_data":"v:x:"+k} for k,lab in ELEVEN_VOICES.items()]
    return {"inline_keyboard":kb_rows(its,2)+[[{"text":"رجوع لأصوات اللغة","callback_data":"L:"+lang}]]}
gusage = {"day": "", "u": {}, "g": 0}
def groq_ok(uid, n):
    d = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 7200))
    if gusage["day"] != d: gusage.update(day=d, u={}, g=0)
    if not GROQ_KEYS: return "off"
    if GROQ_USER_Q and gusage["u"].get(uid, 0) + n > GROQ_USER_Q: return "user"
    if GROQ_GLOBAL_Q and gusage["g"] + n > GROQ_GLOBAL_Q*len(GROQ_KEYS): return "global"
    return None
def groq_add(uid, n): gusage["u"][uid] = gusage["u"].get(uid, 0) + n; gusage["g"] += n
usage = {"day": "", "u": {}, "g": 0}
def _day():
    d = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 7200))
    if usage["day"] != d: usage.update(day=d, u={}, g=0)
def gem_ok(uid, n):
    _day()
    if USER_Q and usage["u"].get(uid, 0) + n > USER_Q: return "user"
    if GLOBAL_Q and usage["g"] + n > GLOBAL_Q*len(GKEYS): return "global"
    return None
def gem_add(uid, n):
    _day(); usage["u"][uid] = usage["u"].get(uid, 0) + n; usage["g"] += n
def edge_fallback(s):
    l = s.get("lang") or "ar"
    if l == "ar": return "e:ar-EG-SalmaNeural"
    for k in EDGE:
        if k.startswith(l + "-"): return "e:" + k
    return "e:ar-EG-SalmaNeural"
def quota_text(uid):
    _day(); left = max(0, USER_Q - usage["u"].get(uid, 0)) if USER_Q else None
    return ("رصيدك النهارده من أصوات Gemini: " + (f"{left} حرف متبقي من {USER_Q}." if left is not None else "غير محدود.") + "\nأصوات Edge مفتوحة بدون حد. الرصيد بيتجدد كل يوم.\nلو عندك مفتاح Groq أو ElevenLabs خاص بك، حطه من /keys ومش بيتحسب من رصيد البوت.")
def merge_ogg(parts):
    if len(parts) == 1: return parts[0]
    d = tempfile.mkdtemp(); names = []
    for k, b in enumerate(parts):
        p = os.path.join(d, f"{k}.ogg"); open(p, "wb").write(b); names.append(p)
    lst = os.path.join(d, "l.txt"); open(lst, "w").write("".join(f"file '{n}'\n" for n in names))
    out = os.path.join(d, "o.ogg")
    r = subprocess.run(["ffmpeg","-v","error","-f","concat","-safe","0","-i",lst,"-c","copy",out], capture_output=True)
    if r.returncode: raise RuntimeError("merge")
    return open(out, "rb").read()

def one_chunk(c, vid, style, allow_fb, own=None):
    gstyle = STYLES[style][1]
    if vid.startswith("e:"):
        try: return edge_tts_run(c, vid[2:], style)
        except Exception:
            if not allow_fb: raise
            return gemini_tts(c, "Kore", gstyle, own)
    for attempt in range(3):
        try: return gemini_tts(c, vid[2:], gstyle, own)
        except Exception:
            time.sleep(8 if attempt < 2 else 0)
    if not allow_fb: raise RuntimeError("gemini")
    return edge_tts_run(c, "ar-EG-SalmaNeural", style)

def speak(chat_id, uid, text, mid):
    s = st(uid)
    text = text.strip()
    cs = chunks(text[:MAXTOTAL], 190 if s["voice"].startswith("q:") else MAXCH)
    if len(text) > MAXTOTAL:
        tg("sendMessage", chat_id=chat_id, text=f"النص طويل، هحول أول {MAXTOTAL} حرف بس.", reply_to_message_id=mid)
    if len(cs) > 2:
        tg("sendMessage", chat_id=chat_id, text="النص طويل، التحويل هياخد دقيقة أو اتنين. استنى لحظات.", reply_to_message_id=mid)
    items = []
    vid = s["voice"]; total = sum(len(c) for c in cs); counted = False
    gcount = False; ecount = False
    if vid.startswith("q:"):
        uk = ukey(uid, "q")
        why = None if uk else groq_ok(uid, total)
        if why:
            vid = edge_fallback(s)
            tg("sendMessage", chat_id=chat_id, text=("خلص رصيدك اليومي من أصوات Groq، فهحول بصوت Edge المجاني. الرصيد بيتجدد بكرة." if why == "user" else "أصوات Groq وصلت للحد اليومي للبوت كله، فهحول بصوت Edge. جرب Groq تاني بكرة."), reply_to_message_id=mid)
            cs = chunks(text[:MAXTOTAL])
        else:
            try:
                lg, vn = vid[2:].split("-", 1)
                for c in cs:
                    tg("sendChatAction", chat_id=chat_id, action="record_voice")
                    items.append(groq_tts(c, lg, vn, uk)); time.sleep(0.5)
                gcount = not uk
            except Exception:
                items = []; vid = edge_fallback(s); cs = chunks(text[:MAXTOTAL])
                tg("sendMessage", chat_id=chat_id, text=("مفتاحك في Groq مش شغال، راجع المفتاح من /keys، وحولت بصوت Edge." if uk else "أصوات Groq مش متاحة دلوقتي، هحول بصوت Edge."), reply_to_message_id=mid)
    elif vid.startswith("x:"):
        ux = ukey(uid, "x")
        why = None if ux else eleven_ok(uid, total)
        if why:
            vid = edge_fallback(s)
            tg("sendMessage", chat_id=chat_id, text=("خلص رصيدك اليومي من أصوات ElevenLabs، فهحول بصوت Edge المجاني. الرصيد بيتجدد بكرة." if why == "user" else "أصوات ElevenLabs وصلت للحد اليومي للبوت كله، فهحول بصوت Edge. جرب تاني بكرة."), reply_to_message_id=mid)
        else:
            try:
                for c in cs:
                    tg("sendChatAction", chat_id=chat_id, action="record_voice")
                    items.append(eleven_tts(c, vid[2:], ux))
                ecount = not ux
            except Exception:
                items = []; vid = edge_fallback(s)
                tg("sendMessage", chat_id=chat_id, text=("مفتاحك في ElevenLabs مش شغال، راجع المفتاح من /keys، وحولت بصوت Edge." if ux else "أصوات ElevenLabs مش متاحة دلوقتي، هحول بصوت Edge."), reply_to_message_id=mid)
    elif vid.startswith("g:"):
        ug = ukey(uid, "g")
        why = None if ug else gem_ok(uid, total)
        if why:
            vid = edge_fallback(s)
            tg("sendMessage", chat_id=chat_id, text=("خلص رصيدك اليومي من أصوات Gemini، فهحول بصوت Edge المجاني. الرصيد بيتجدد بكرة." if why == "user" else "أصوات Gemini وصلت للحد اليومي للبوت كله، فهحول بصوت Edge. جرب Gemini تاني بكرة."), reply_to_message_id=mid)
        else: counted = not ug
    try:
        if not items:
            for n, c in enumerate(cs):
                tg("sendChatAction", chat_id=chat_id, action="record_voice")
                items.append(one_chunk(c, vid, s["style"], n == 0, ukey(uid, "g") if vid.startswith("g:") else None))
        if counted: gem_add(uid, total)
        if gcount: groq_add(uid, total)
        if ecount: eleven_add(uid, total)
        kinds = {("mp3" if "mpeg" in m else "pcm" if (r[:4] != b"RIFF") else "wav") for r, m in items}
        if kinds == {"mp3"}:
            data = b"".join(r for r, m in items); ext = "mp3"; ct = "audio/mpeg"
        elif kinds == {"pcm"} and len({m for r, m in items}) == 1:
            data = to_ogg(b"".join(r for r, m in items), items[0][1]); ext = "ogg"; ct = "audio/ogg"
        else:
            data = merge_ogg([to_ogg(r, m) for r, m in items]); ext = "ogg"; ct = "audio/ogg"
    except Exception:
        tg("sendMessage", chat_id=chat_id, text="حصلت مشكلة وقت التحويل، جرب تاني بعد شوية.", reply_to_message_id=mid); return
    tg_voice(chat_id, data, f"{BRAND} | {disp(vid)}", mid, ext, ct)

pend = {}
plock = threading.Lock()
def queue_text(chat_id, uid, text, mid):
    # join consecutive messages (Telegram splits long texts at 4096 chars) into one audio
    with plock:
        e = pend.get(uid)
        if e is None:
            e = pend[uid] = {"parts": [], "mid": mid, "chat": chat_id}
        e["parts"].append(text); e["n"] = e.get("n", 0) + 1; n = e["n"]
    def fire():
        time.sleep(3)
        with plock:
            e = pend.get(uid)
            if not e or e["n"] != n: return
            pend.pop(uid, None)
        speak(e["chat"], uid, "\n".join(e["parts"]), e["mid"])
    threading.Thread(target=fire, daemon=True).start()

def on_message(m):
    chat_id = m["chat"]["id"]; uid = m["from"]["id"]; mid = m["message_id"]
    if m["chat"].get("type") != "private": return
    text = m.get("text")
    doc = m.get("document")
    if not text and doc and (doc.get("mime_type","").startswith("text/") or doc.get("file_name","").lower().endswith(".txt")) and doc.get("file_size",0) < 200000:
        text = "\x00DOC"
    if not text:
        tg("sendMessage", chat_id=chat_id, text="ابعت نص أو ملف txt عشان أحوله لصوت."); return
    if CHANNELS:
        ok = is_member(uid)
        if ok is False or ok is None and False: gate_msg(chat_id); return
        if ok is None:
            tg("sendMessage", chat_id=chat_id, text="البوت تحت الصيانة لحظات، جرب بعد شوية."); return
    cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
    if cmd in ("/start","/help"):
        tg("sendMessage", chat_id=chat_id, text=HELP)
        tg("sendMessage", chat_id=chat_id, text=LANG_PROMPT, reply_markup=lang_kb())
    elif cmd == "/quota": tg("sendMessage", chat_id=chat_id, text=quota_text(uid))
    elif cmd in ("/contact","/support"): tg("sendMessage", chat_id=chat_id, text=CONTACT_TEXT, reply_markup=contact_kb())
    elif cmd in ("/keys","/key","/mykeys"): tg("sendMessage", chat_id=chat_id, text=keys_text(uid), reply_markup=keys_kb(uid))
    elif cmd in ("/cancel","/الغاء"): await_key.pop(uid, None); tg("sendMessage", chat_id=chat_id, text="تمام، لغيت.")
    elif cmd in ("/voice","/language"): tg("sendMessage", chat_id=chat_id, text=LANG_PROMPT, reply_markup=lang_kb())
    elif cmd == "/style": tg("sendMessage", chat_id=chat_id, text="اختار طريقة الإلقاء:", reply_markup=style_kb())
    elif cmd: tg("sendMessage", chat_id=chat_id, text=HELP)
    else:
        eng = await_key.pop(uid, None)
        if eng:
            k = text.strip()
            tg("deleteMessage", chat_id=chat_id, message_id=mid)
            if len(k) < 15 or " " in k or "\n" in k:
                await_key[uid] = eng
                tg("sendMessage", chat_id=chat_id, text="ده مش شكل مفتاح. ابعت المفتاح كامل في رسالة لوحده، أو /cancel."); return
            if not check_key(eng, k):
                await_key[uid] = eng
                tg("sendMessage", chat_id=chat_id, text="المفتاح مش شغال (المزود رفضه). راجع المفتاح وجرب تاني، أو /cancel."); return
            set_ukey(uid, eng, k)
            tg("sendMessage", chat_id=chat_id, text=f"تم حفظ مفتاحك لـ {'Gemini' if eng=='g' else 'Groq' if eng=='q' else 'ElevenLabs'} ({mask(k)}) وهستخدمه ليك انت بس. المفتاح مشفر ومربوط بحسابك.")
            return
        if limited(uid): tg("sendMessage", chat_id=chat_id, text="استنى دقيقة وجرب تاني."); return
        if not st(uid).get("chosen"):
            tg("sendMessage", chat_id=chat_id, text="الأول اختار اللغة والصوت:", reply_markup=lang_kb()); return
        if text == "\x00DOC":
            r = tg("getFile", file_id=doc["file_id"])
            try:
                raw = urllib.request.urlopen(f"https://api.telegram.org/file/bot{TOKEN}/"+r["result"]["file_path"], timeout=30).read()
                text = raw.decode("utf-8", "ignore")
            except Exception:
                tg("sendMessage", chat_id=chat_id, text="ما قدرتش أقرا الملف."); return
            if not text.strip(): return
            speak(chat_id, uid, text, mid); return
        queue_text(chat_id, uid, text, mid)

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
    if d == "mk":
        tg("sendMessage", chat_id=chat_id, text=keys_text(uid), reply_markup=keys_kb(uid)); return
    if d == "ct":
        tg("sendMessage", chat_id=chat_id, text=CONTACT_TEXT, reply_markup=contact_kb()); return
    if d.startswith("lp:"):
        show(chat_id, LANG_PROMPT, lang_kb(int(d[3:] or 0)), q)
    elif d.startswith("L:"):
        l=d[2:]; s=st(uid); s["lang"]=l; save()
        show(chat_id, f"اختار الصوت للغة {LANGNAMES.get(l,l)}:", voice_kb(l, uid), q)
    elif d.startswith("G:"):
        show(chat_id, "أصوات Gemini الطبيعية (بتقرا أي لغة):", gem_kb(d[2:]), q)
    elif d == "kg":
        await_key[uid] = "g"
        tg("sendMessage", chat_id=chat_id, text="ابعت مفتاح Gemini بتاعك في رسالة لوحده هنا.\nهتجيبه مجانًا من aistudio.google.com/apikey.\nهشيل رسالتك من الشات بعد الحفظ. لو غيرت رأيك ابعت /cancel.")
    elif d in ("kq","kx"):
        eng = d[1]; await_key[uid] = eng
        tg("sendMessage", chat_id=chat_id, text=("ابعت مفتاح Groq بتاعك في رسالة لوحده هنا.\nهتجيبه مجانًا من console.groq.com/keys.\nهشيل رسالتك من الشات بعد الحفظ. لو غيرت رأيك ابعت /cancel." if eng == "q" else "ابعت مفتاح ElevenLabs بتاعك في رسالة لوحده هنا.\nهتجيبه مجانًا من elevenlabs.io (Profile ثم API keys).\nهشيل رسالتك من الشات بعد الحفظ. لو غيرت رأيك ابعت /cancel."))
    elif d in ("dg","dq","dx"):
        eng = d[1]; set_ukey(uid, eng, "")
        tg("sendMessage", chat_id=chat_id, text={"g": "تم مسح مفتاح Gemini بتاعك، رجع البوت لمفاتيحه العامة.", "q": "تم مسح مفتاح Groq بتاعك، رجع البوت لمفتاحه العام."}.get(eng, "تم مسح مفتاح ElevenLabs بتاعك، رجع البوت لمفتاحه العام."))
    elif d.startswith("Q:") and (GROQ_KEYS or ukey(uid,"q")) and d[2:] in GROQ_VOICES:
        show(chat_id, "أصوات Groq (رصيدها اليومي صغير، ولما يخلص بحول بصوت Edge):", groq_kb(d[2:]), q)
    elif d.startswith("X:") and (ELEVEN_KEYS or ukey(uid,"x")):
        show(chat_id, "أصوات ElevenLabs (رصيدها اليومي صغير جدًا، ولما يخلص بحول بصوت Edge):", eleven_kb(d[2:]), q)
    elif d == "chv":
        l = cur_lang(uid)
        show(chat_id, f"اختار الصوت للغة {LANGNAMES.get(l,l)}:", voice_kb(l, uid), q)
    elif d.startswith("v:") and ((d[2:4]=="q:" and d[4:].split("-",1)[0] in GROQ_VOICES and d[4:].split("-",1)[-1] in GROQ_VOICES[d[4:].split("-",1)[0]][1]) or (d[2:4]=="x:" and d[4:] in ELEVEN_VOICES) or (d[2:4]=="g:" and d[4:] in VOICES) or (d[2:4]=="e:" and d[4:] in EDGE)):
        s = st(uid); s["voice"] = d[2:]; s["chosen"] = True; save()
        show(chat_id, f"تم اختيار الصوت: {disp(d[2:])}\nدلوقتي ابعت النص اللي عايز تحوله لصوت. الاختيار ده هيفضل محفوظ للنصوص الجاية.", after_kb(), q)
    elif d.startswith("s:") and d[2:] in STYLES:
        st(uid)["style"] = d[2:]; save()
        tg("sendMessage", chat_id=chat_id, text=f"تم اختيار طريقة الإلقاء: {STYLES[d[2:]][0]}.")

class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok keys-v1")
    def do_POST(self):
        n = int(self.headers.get("Content-Length",0)); body = self.rfile.read(n)
        if self.path == "/synth":
            import hashlib
            try:
                j = json.loads(body)
                if hashlib.sha256(j.get("tok","").encode()).hexdigest() != "4acaef2d75949589e072e0ec2460580944f15dc4457ed25e5a7efc8b506dce13": raise ValueError("auth")
                if j.get("engine") == "q": raw, mime = groq_tts(j["text"], j.get("lang","ar"), j["voice"])
                elif j.get("engine") == "x": raw, mime = eleven_tts(j["text"], j["voice"])
                else: raw, mime = gemini_tts(j["text"], j["voice"], j.get("style",""))
                self.send_response(200); self.send_header("X-Mime", mime or ""); self.end_headers(); self.wfile.write(raw)
            except Exception as e:
                self.send_response(500); self.end_headers(); self.wfile.write(str(e)[:200].encode())
            return
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
    try:
        CMDS = [
            {"command":"start","description":"ابدأ من هنا: حوّل النص لصوت"},
            {"command":"voice","description":"اختيار اللغة والصوت"},
            {"command":"style","description":"اختيار طريقة الإلقاء"},
            {"command":"keys","description":"مفاتيحي: أضف مفتاحك الخاص (اختياري)"},
            {"command":"contact","description":"تواصل معنا"},
            {"command":"quota","description":"رصيدي المتبقي النهارده"},
            {"command":"help","description":"المساعدة وطريقة الاستخدام"},
        ]
        tg("setMyCommands", commands=CMDS)
        tg("setMyCommands", commands=CMDS, language_code="ar")
    except Exception: pass
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT","10000"))), H).serve_forever()
