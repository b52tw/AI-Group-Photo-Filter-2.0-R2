# -*- coding: utf-8 -*-
"""
chunba Network AI Photo Classifier v2.0 R2
內部顯示：峻爸製作

此版本不使用本機 AI 模型；照片判讀透過 Gemini API。
日期分類只讀 EXIF / 檔案日期，屬中繼資料處理，不是本機 AI 判讀。
指定人物部分採人工確認：程式可載入參考照片並標出「有人臉/人物候選」照片，
但不自動判定真實人物身分。
"""

import os, sys, io, csv, json, math, time, base64, queue, shutil, threading
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import requests
from PIL import Image, ImageOps, ImageTk
import pillow_heif

pillow_heif.register_heif_opener()

APP_TITLE = "峻爸製作｜網路 AI 智慧照片分類器 v2.0 R2"
APP_SUBTITLE = "Gemini 網路 AI｜快速掃描縮圖牆｜暫停／取消｜精確進階｜分類輸出"
MODEL_DEFAULT = "gemini-3.5-flash-lite"
MODEL_FALLBACK = "gemini-3.1-flash-lite"
EXTS = {".jpg",".jpeg",".png",".bmp",".webp",".heic",".heif",".tif",".tiff"}

PEOPLE_BUCKETS = [
    ("people_00", lambda n: n == 0),
    ("people_01", lambda n: n == 1),
    ("people_02", lambda n: n == 2),
    ("people_03_05", lambda n: 3 <= n <= 5),
    ("people_06_10", lambda n: 6 <= n <= 10),
    ("people_11_plus", lambda n: n >= 11),
]
SCENE_DIR = {
    "室內":"scene_indoor", "人物活動":"scene_people_event", "戶外／自然":"scene_outdoor_nature",
    "街景／交通":"scene_street_traffic", "餐飲場景":"scene_food", "運動場景":"scene_sport",
    "建築／展場":"scene_building_exhibition", "舞台／講座":"scene_stage_lecture", "其他／待確認":"scene_other",
    "":"scene_unknown"
}

def safe_exif_date(exif):
    for key in (36867, 36868, 306):
        v = exif.get(key)
        if not v: continue
        s = str(v).strip()
        for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try: return datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M:%S")
            except Exception: pass
    return ""

def read_metadata_date(path):
    try:
        with Image.open(path) as im:
            d = safe_exif_date(im.getexif())
        if d: return d, "EXIF"
    except Exception:
        pass
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"), "檔案日期"
    except Exception:
        return "", ""

def image_for_api(path, max_dim=720, quality=72):
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((max_dim,max_dim), Image.Resampling.LANCZOS)
        buf = io.BytesIO(); im.save(buf, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")

def next_run_folder(root):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y%m%d")
    for i in range(1,10000):
        rid = f"{day}_{i:03d}"
        p = root / f"chunba_{rid}"
        if not p.exists():
            p.mkdir(parents=True, exist_ok=False)
            return rid, p
    raise RuntimeError("Unable to allocate unique run ID")

def clean_json_text(s):
    s = s.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"): s = s[4:].strip()
    a, b = s.find("{"), s.rfind("}")
    return s[a:b+1] if a >= 0 and b > a else s

def gemini_request(api_key, model, image_b64, fields, precision, timeout=60):
    # No identity recognition. "target_candidate" only means a clear person/face is visible for human comparison.
    field_text = []
    if "person" in fields: field_text.append("person_present: 是否有真人；person_confidence: 0到1的視覺確定度")
    if "count" in fields: field_text.append("people_count: 可清楚辨識的人數整數；不確定時給最保守可見人數")
    if "scene" in fields: field_text.append("scene: 從指定場景類別擇一")
    if "target" in fields: field_text.append("target_candidate: 是否有足夠清楚的人臉/人物可供使用者人工比對參考照片；不要判定是不是同一個人")

    detail = {
        "快速":"快速掃描，優先速度，保守判斷，不要過度猜測。",
        "標準":"標準掃描，仔細檢查整張照片一次。",
        "精確":"精確掃描，逐區域檢查人物、遠處小人物與場景，對不確定項目說明。"
    }[precision]
    prompt = f"""你是照片整理分類器。{detail}
只分析可直接從照片看見的內容，不推測真實姓名、身分、職業或敏感屬性。
請回傳純 JSON，不要 Markdown。場景只能用：室內、人物活動、戶外／自然、街景／交通、餐飲場景、運動場景、建築／展場、舞台／講座、其他／待確認。
需要欄位：{'; '.join(field_text)}
另外一定回傳：
content_tags: 3到10個繁體中文可見內容標籤；
reason: 40字內繁體中文，說明你依哪些可見線索分類；
uncertainty: 20字內說明最不確定之處，若無則空字串。
JSON 範例：{{"person_present":true,"person_confidence":0.93,"people_count":6,"scene":"舞台／講座","target_candidate":true,"content_tags":["人物","舞台","投影幕"],"reason":"可見多人面向舞台與投影幕","uncertainty":"後排有部分遮擋"}}"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents":[{"parts":[
            {"text":prompt},
            {"inline_data":{"mime_type":"image/jpeg","data":image_b64}}
        ]}],
        "generationConfig":{"temperature":0.05,"responseMimeType":"application/json"}
    }
    r = requests.post(url, headers={"x-goog-api-key":api_key,"Content-Type":"application/json"}, json=payload, timeout=timeout)
    if r.status_code == 429:
        raise RuntimeError("RATE_LIMIT")
    r.raise_for_status()
    data = r.json()
    txt = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(clean_json_text(txt))

def people_bucket(n):
    try: n = int(n)
    except Exception: n = 0
    for name, fn in PEOPLE_BUCKETS:
        if fn(n): return name
    return "people_unknown"

def write_csv(path, rows):
    fields = ["selected","manual_target","original_path","original_name","date","date_source","person_present",
              "person_confidence","people_count","scene","content_tags","target_candidate","reason","uncertainty",
              "precision","model","status","error","export_path"]
    with open(path,"w",newline="",encoding="utf-8-sig") as f:
        w = csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader()
        for r in rows:
            x=r.copy(); x["selected"]="Y" if r.get("selected") else ""; x["manual_target"]="Y" if r.get("manual_target") else ""
            w.writerow(x)

class PreviewWindow(tk.Toplevel):
    def __init__(self, app, idx):
        super().__init__(app); self.app=app; self.idx=idx
        self.title("大圖預覽｜峻爸製作"); self.geometry("1040x780"); self.minsize(820,620)
        bar=ttk.Frame(self,padding=8); bar.pack(fill="x")
        ttk.Button(bar,text="← 上一張",command=lambda:self.move(-1)).pack(side="left")
        ttk.Button(bar,text="下一張 →",command=lambda:self.move(1)).pack(side="left",padx=5)
        ttk.Button(bar,text="切換選取",command=self.toggle_select).pack(side="left",padx=12)
        ttk.Button(bar,text="人工標記指定人物",command=self.toggle_manual_target).pack(side="left")
        ttk.Button(bar,text="關閉",command=self.destroy).pack(side="right")
        self.img=ttk.Label(self,anchor="center"); self.img.pack(fill="both",expand=True,padx=8,pady=4)
        self.info=tk.Text(self,height=9,wrap="word",font=("Microsoft JhengHei UI",10)); self.info.pack(fill="x",padx=8,pady=(0,8))
        self.bind("<Left>",lambda e:self.move(-1)); self.bind("<Right>",lambda e:self.move(1)); self.bind("<space>",lambda e:self.toggle_select())
        self.render()
    def move(self,d):
        view=self.app.filtered
        if not view or self.idx not in view:return
        p=view.index(self.idx); self.idx=view[(p+d)%len(view)]; self.render()
    def toggle_select(self): self.app.toggle_select(self.idx); self.render()
    def toggle_manual_target(self):
        r=self.app.results[self.idx]; r["manual_target"]=not r.get("manual_target",False); self.app.render_page(); self.render()
    def render(self):
        r=self.app.results[self.idx]
        try:
            with Image.open(r["original_path"]) as im:
                im=ImageOps.exif_transpose(im).convert("RGB"); im.thumbnail((980,520),Image.Resampling.LANCZOS); self.photo=ImageTk.PhotoImage(im)
            self.img.configure(image=self.photo,text="")
        except Exception: self.img.configure(image="",text="無法顯示")
        text=(f"{'☑ 已選取' if r.get('selected') else '☐ 未選取'}｜{'★ 已人工標記指定人物' if r.get('manual_target') else '☆ 未人工標記指定人物'}\n"
              f"檔案：{r.get('original_name','')}\n日期：{r.get('date','') or '未分析'}（{r.get('date_source','')}）\n"
              f"人物：{r.get('person_present','')}｜人數：{r.get('people_count','')}｜場景：{r.get('scene','')}\n"
              f"指定人物候選：{r.get('target_candidate','')}（只代表有清楚人物可人工比對，不是身分判定）\n"
              f"AI內容標籤：{r.get('content_tags','')}\nAI篩選依據：{r.get('reason','')}\n不確定處：{r.get('uncertainty','')}\n"
              f"模式：{r.get('precision','')}｜模型：{r.get('model','')}｜狀態：{r.get('status','')}")
        self.info.delete("1.0","end"); self.info.insert("1.0",text)

class App(tk.Tk):
    PAGE=20
    def __init__(self):
        super().__init__(); self.title(APP_TITLE); self.geometry("1320x860"); self.minsize(1050,700)
        self.q=queue.Queue(); self.results=[]; self.filtered=[]; self.page=0; self.refs=[]; self.thumb_refs=[]
        self.pause_event=threading.Event(); self.pause_event.set(); self.cancel_event=threading.Event(); self.worker_running=False
        self.run_id=""; self.run_folder=None
        self.src=tk.StringVar(); self.dst=tk.StringVar(); self.api_key=tk.StringVar(); self.model=tk.StringVar(value=MODEL_DEFAULT)
        self.do_person=tk.BooleanVar(value=True); self.do_count=tk.BooleanVar(value=True); self.do_date=tk.BooleanVar(value=True)
        self.do_scene=tk.BooleanVar(value=True); self.do_target=tk.BooleanVar(value=False); self.precision=tk.StringVar(value="快速")
        self.filter_people=tk.StringVar(value="全部"); self.filter_scene=tk.StringVar(value="全部"); self.filter_target=tk.StringVar(value="全部")
        self.filter_date=tk.StringVar(); self.only_selected=tk.BooleanVar(value=False); self.progress=tk.DoubleVar(value=0)
        self.build_ui(); self.after(100,self.poll)

    def build_ui(self):
        main=ttk.Frame(self); main.pack(fill="both",expand=True)
        ttk.Label(main,text=APP_TITLE,font=("Microsoft JhengHei UI",19,"bold")).pack(pady=(7,0))
        ttk.Label(main,text=APP_SUBTITLE).pack()
        ttk.Label(main,text="製作：峻爸｜程式、EXE、Artifact 與輸出檔名一律使用英文 chunba",font=("Microsoft JhengHei UI",9,"bold")).pack(pady=(0,5))

        p=ttk.Frame(main); p.pack(fill="x",padx=12)
        for row,(t,var,cmd) in enumerate([("來源照片",self.src,self.pick_src),("輸出根目錄",self.dst,self.pick_dst)]):
            ttk.Label(p,text=t+"：",width=10).grid(row=row,column=0,pady=2); ttk.Entry(p,textvariable=var).grid(row=row,column=1,sticky="ew",padx=5); ttk.Button(p,text="選擇",command=cmd).grid(row=row,column=2)
        p.columnconfigure(1,weight=1)

        api=ttk.LabelFrame(main,text="網路 AI｜免費層 Gemini") ; api.pack(fill="x",padx=12,pady=(5,2))
        ttk.Label(api,text="API Key：").grid(row=0,column=0,padx=(6,2),pady=4)
        ttk.Entry(api,textvariable=self.api_key,show="*",width=44).grid(row=0,column=1,padx=3)
        ttk.Label(api,text="模型：").grid(row=0,column=2,padx=(8,2))
        ttk.Combobox(api,textvariable=self.model,state="readonly",width=22,values=[MODEL_DEFAULT,MODEL_FALLBACK]).grid(row=0,column=3)
        ttk.Button(api,text="測試 API",command=self.test_api).grid(row=0,column=4,padx=6)
        ttk.Label(api,text="只使用網路 AI；日期欄位僅讀照片 EXIF/檔案日期，不使用本機 AI。").grid(row=0,column=5,padx=8,sticky="w")

        opts=ttk.LabelFrame(main,text="每次快速掃描可自由單選／複選") ; opts.pack(fill="x",padx=12,pady=3)
        ttk.Checkbutton(opts,text="純人物辨識",variable=self.do_person).grid(row=0,column=0,padx=6,pady=4,sticky="w")
        ttk.Checkbutton(opts,text="人數分類",variable=self.do_count).grid(row=0,column=1,padx=6,sticky="w")
        ttk.Checkbutton(opts,text="日期分類",variable=self.do_date).grid(row=0,column=2,padx=6,sticky="w")
        ttk.Checkbutton(opts,text="場景分類",variable=self.do_scene).grid(row=0,column=3,padx=6,sticky="w")
        ttk.Checkbutton(opts,text="指定人物人工確認候選",variable=self.do_target).grid(row=0,column=4,padx=6,sticky="w")
        ttk.Button(opts,text="加入參考照片",command=self.add_refs).grid(row=0,column=5,padx=6)
        self.ref_label=ttk.Label(opts,text="參考照片：0 張"); self.ref_label.grid(row=0,column=6,padx=6,sticky="w")
        ttk.Label(opts,text="掃描精度：").grid(row=0,column=7,padx=(12,2))
        ttk.Combobox(opts,textvariable=self.precision,state="readonly",width=8,values=["快速","標準","精確"]).grid(row=0,column=8)

        actions=ttk.Frame(main,padding=(12,5)); actions.pack(fill="x")
        self.scan_btn=ttk.Button(actions,text="① 快速掃描預覽",command=self.start_scan); self.scan_btn.pack(side="left")
        self.pause_btn=ttk.Button(actions,text="暫停",command=self.pause_resume,state="disabled"); self.pause_btn.pack(side="left",padx=5)
        self.cancel_btn=ttk.Button(actions,text="完全取消並重來",command=self.cancel_reset,state="disabled"); self.cancel_btn.pack(side="left",padx=5)
        self.adv_btn=ttk.Button(actions,text="② 精確進階所選",command=self.start_advanced,state="disabled"); self.adv_btn.pack(side="left",padx=(15,5))
        self.exp_btn=ttk.Button(actions,text="③ 輸出所選分類檔案",command=self.start_export,state="disabled"); self.exp_btn.pack(side="left",padx=5)
        ttk.Button(actions,text="開啟本次資料夾",command=self.open_run).pack(side="left",padx=5)
        self.run_label=ttk.Label(actions,text="本次編號：尚未開始"); self.run_label.pack(side="right")

        f=ttk.LabelFrame(main,text="縮圖牆篩選／整頁選取") ; f.pack(fill="x",padx=12,pady=3)
        ttk.Label(f,text="人數").grid(row=0,column=0,padx=(6,2)); ttk.Combobox(f,textvariable=self.filter_people,state="readonly",width=9,values=["全部","0","1","2","3-5","6-10","11+"]).grid(row=0,column=1)
        ttk.Label(f,text="場景").grid(row=0,column=2,padx=(8,2)); ttk.Combobox(f,textvariable=self.filter_scene,state="readonly",width=14,values=["全部","室內","人物活動","戶外／自然","街景／交通","餐飲場景","運動場景","建築／展場","舞台／講座","其他／待確認"]).grid(row=0,column=3)
        ttk.Label(f,text="指定人物候選").grid(row=0,column=4,padx=(8,2)); ttk.Combobox(f,textvariable=self.filter_target,state="readonly",width=10,values=["全部","候選","非候選","已人工標記"]).grid(row=0,column=5)
        ttk.Label(f,text="日期含").grid(row=0,column=6,padx=(8,2)); ttk.Entry(f,textvariable=self.filter_date,width=11).grid(row=0,column=7)
        ttk.Checkbutton(f,text="只看已選",variable=self.only_selected,command=self.apply_filter).grid(row=0,column=8,padx=5)
        ttk.Button(f,text="套用",command=self.apply_filter).grid(row=0,column=9,padx=3)
        ttk.Button(f,text="全選此頁",command=self.select_page).grid(row=0,column=10,padx=3)
        ttk.Button(f,text="全選篩選結果",command=self.select_filtered).grid(row=0,column=11,padx=3)
        ttk.Button(f,text="清除選取",command=self.clear_selected).grid(row=0,column=12,padx=3)

        st=ttk.Frame(main); st.pack(fill="x",padx=12); ttk.Progressbar(st,variable=self.progress,maximum=100).pack(fill="x",pady=(2,1)); self.status=ttk.Label(st,text="請選來源資料夾並輸入 Gemini API Key。") ; self.status.pack(anchor="w")
        nav=ttk.Frame(main); nav.pack(fill="x",padx=12,pady=(3,0)); ttk.Button(nav,text="← 上一頁",command=lambda:self.change_page(-1)).pack(side="left"); ttk.Button(nav,text="下一頁 →",command=lambda:self.change_page(1)).pack(side="left",padx=5); self.page_label=ttk.Label(nav,text="第 0 / 0 頁"); self.page_label.pack(side="left",padx=8); ttk.Label(nav,text="卡片會直接顯示：人數／場景／AI標籤／判斷依據，不需先點開。點照片可看大圖。").pack(side="right")

        self.canvas=tk.Canvas(main,highlightthickness=0); self.canvas.pack(fill="both",expand=True,padx=12,pady=(3,8)); sb=ttk.Scrollbar(self.canvas,orient="vertical",command=self.canvas.yview); self.canvas.configure(yscrollcommand=sb.set); sb.pack(side="right",fill="y")
        self.cards=ttk.Frame(self.canvas); self.win=self.canvas.create_window((0,0),window=self.cards,anchor="nw"); self.cards.bind("<Configure>",lambda e:self.canvas.configure(scrollregion=self.canvas.bbox("all"))); self.canvas.bind("<Configure>",lambda e:self.canvas.itemconfigure(self.win,width=max(100,e.width-18)))

    def pick_src(self):
        p=filedialog.askdirectory();
        if p:
            self.src.set(p)
            if not self.dst.get(): self.dst.set(str(Path(p).parent/"chunba_output"))
    def pick_dst(self):
        p=filedialog.askdirectory();
        if p:self.dst.set(p)
    def add_refs(self):
        fs=filedialog.askopenfilenames(filetypes=[("Images","*.jpg *.jpeg *.png *.webp *.heic *.heif *.bmp *.tif *.tiff")])
        for x in fs:
            if x not in self.refs:self.refs.append(x)
        if self.refs:self.do_target.set(True)
        self.ref_label.config(text=f"參考照片：{len(self.refs)} 張（僅供人工比對）")
    def cfg(self):
        fields=[]
        if self.do_person.get():fields.append("person")
        if self.do_count.get():fields.append("count")
        if self.do_scene.get():fields.append("scene")
        if self.do_target.get():fields.append("target")
        return {"fields":fields,"date":self.do_date.get(),"precision":self.precision.get(),"model":self.model.get(),"key":self.api_key.get().strip()}
    def validate(self):
        if not Path(self.src.get()).is_dir():messagebox.showwarning("提示","請先選來源照片資料夾。");return False
        if not self.dst.get():messagebox.showwarning("提示","請先選輸出根目錄。");return False
        c=self.cfg()
        if not c["fields"] and not c["date"]:messagebox.showwarning("提示","至少勾選一項掃描功能。");return False
        if c["fields"] and not c["key"]:messagebox.showwarning("提示","網路 AI 分析需要 Gemini API Key。");return False
        return True
    def test_api(self):
        if not self.api_key.get().strip():messagebox.showwarning("提示","請先輸入 API Key。");return
        self.status.config(text="正在測試 Gemini API…")
        threading.Thread(target=self.test_api_worker,daemon=True).start()
    def test_api_worker(self):
        try:
            url=f"https://generativelanguage.googleapis.com/v1beta/models/{self.model.get()}:generateContent"
            r=requests.post(url,headers={"x-goog-api-key":self.api_key.get().strip(),"Content-Type":"application/json"},json={"contents":[{"parts":[{"text":"只回答 OK"}]}]},timeout=20); r.raise_for_status(); self.q.put(("api_ok",))
        except Exception as e:self.q.put(("api_err",str(e)))
    def pause_resume(self):
        if self.pause_event.is_set(): self.pause_event.clear(); self.pause_btn.config(text="繼續"); self.status.config(text="已暫停；目前結果保留。")
        else: self.pause_event.set(); self.pause_btn.config(text="暫停"); self.status.config(text="繼續處理…")
    def cancel_reset(self):
        self.cancel_event.set(); self.pause_event.set(); self.results=[]; self.filtered=[]; self.page=0; self.render_page(); self.status.config(text="已取消目前工作，可重新設定後再掃描。原始照片未變更。")
        self.scan_btn.config(state="normal"); self.pause_btn.config(state="disabled",text="暫停"); self.cancel_btn.config(state="disabled"); self.adv_btn.config(state="disabled"); self.exp_btn.config(state="disabled"); self.worker_running=False
    def start_scan(self):
        if not self.validate():return
        self.cancel_event.clear(); self.pause_event.set(); self.worker_running=True; self.results=[]; self.filtered=[]; self.page=0
        self.run_id,self.run_folder=next_run_folder(self.dst.get()); self.run_label.config(text=f"本次編號：chunba_{self.run_id}")
        self.scan_btn.config(state="disabled"); self.pause_btn.config(state="normal",text="暫停"); self.cancel_btn.config(state="normal"); self.adv_btn.config(state="disabled"); self.exp_btn.config(state="disabled"); self.progress.set(0)
        threading.Thread(target=self.scan_worker,args=(self.cfg(),False,[]),daemon=True).start()
    def start_advanced(self):
        ids=[i for i,r in enumerate(self.results) if r.get("selected")]
        if not ids:messagebox.showwarning("提示","請先勾選要進行精確進階的照片。");return
        if not self.validate():return
        self.cancel_event.clear(); self.pause_event.set(); self.worker_running=True; self.scan_btn.config(state="disabled"); self.pause_btn.config(state="normal",text="暫停"); self.cancel_btn.config(state="normal"); self.adv_btn.config(state="disabled"); self.exp_btn.config(state="disabled")
        c=self.cfg(); c["precision"]="精確"; threading.Thread(target=self.scan_worker,args=(c,True,ids),daemon=True).start()
    def scan_worker(self,cfg,advanced,ids):
        try:
            if advanced: work=[(i,Path(self.results[i]["original_path"])) for i in ids]
            else:
                files=[p for p in Path(self.src.get()).rglob("*") if p.is_file() and p.suffix.lower() in EXTS]; work=list(enumerate(files))
            out=[] if not advanced else None
            for pos,(idx,p) in enumerate(work,1):
                if self.cancel_event.is_set():return
                self.pause_event.wait()
                if self.cancel_event.is_set():return
                if advanced: r=self.results[idx].copy()
                else:r={"selected":False,"manual_target":False,"original_path":str(p),"original_name":p.name,"date":"","date_source":"","person_present":"","person_confidence":"","people_count":"","scene":"","content_tags":"","target_candidate":"","reason":"","uncertainty":"","precision":cfg["precision"],"model":cfg["model"],"status":"","error":"","export_path":""}
                if cfg["date"]:
                    r["date"],r["date_source"]=read_metadata_date(p)
                if cfg["fields"]:
                    max_dim={"快速":640,"標準":960,"精確":1440}[cfg["precision"]]; quality={"快速":68,"標準":78,"精確":86}[cfg["precision"]]
                    try:
                        b64=image_for_api(p,max_dim,quality)
                        for attempt in range(4):
                            try:
                                g=gemini_request(cfg["key"],cfg["model"],b64,cfg["fields"],cfg["precision"]);break
                            except RuntimeError as e:
                                if str(e)=="RATE_LIMIT" and attempt<3: time.sleep(8*(attempt+1)); continue
                                raise
                        if "person" in cfg["fields"]:
                            r["person_present"]="是" if bool(g.get("person_present")) else "否"; r["person_confidence"]=g.get("person_confidence","")
                        if "count" in cfg["fields"]: r["people_count"]=g.get("people_count","")
                        if "scene" in cfg["fields"]: r["scene"]=g.get("scene","")
                        if "target" in cfg["fields"]: r["target_candidate"]="候選" if bool(g.get("target_candidate")) else "非候選"
                        r["content_tags"]="、".join(str(x) for x in g.get("content_tags",[])[:10]); r["reason"]=str(g.get("reason","")); r["uncertainty"]=str(g.get("uncertainty","")); r["status"]="精確進階完成" if advanced else "快速掃描完成"
                    except Exception as e:r["status"]="失敗"; r["error"]=str(e)
                if advanced:
                    r["precision"]="精確"; self.results[idx]=r
                else: out.append(r)
                self.q.put(("progress",100*pos/max(1,len(work)),f"{'精確進階' if advanced else '快速掃描'} {pos}/{len(work)}"))
            if advanced:
                write_csv(self.run_folder/f"chunba_{self.run_id}_advanced.csv",self.results); self.q.put(("advanced_done",))
            else:
                self.results=out; write_csv(self.run_folder/f"chunba_{self.run_id}_preview.csv",self.results); self.q.put(("scan_done",))
        except Exception as e:self.q.put(("error",str(e)))
    def match_filter(self,r):
        if self.only_selected.get() and not r.get("selected"):return False
        pf=self.filter_people.get(); n=r.get("people_count")
        try:n=int(n)
        except Exception:n=None
        if pf!="全部":
            ok=(pf=="0" and n==0) or (pf=="1" and n==1) or (pf=="2" and n==2) or (pf=="3-5" and n is not None and 3<=n<=5) or (pf=="6-10" and n is not None and 6<=n<=10) or (pf=="11+" and n is not None and n>=11)
            if not ok:return False
        sf=self.filter_scene.get();
        if sf!="全部" and r.get("scene")!=sf:return False
        tf=self.filter_target.get();
        if tf=="候選" and r.get("target_candidate")!="候選":return False
        if tf=="非候選" and r.get("target_candidate")!="非候選":return False
        if tf=="已人工標記" and not r.get("manual_target"):return False
        df=self.filter_date.get().strip();
        if df and df not in r.get("date",""):return False
        return True
    def apply_filter(self):self.filtered=[i for i,r in enumerate(self.results) if self.match_filter(r)]; self.page=0; self.render_page()
    def toggle_select(self,idx):self.results[idx]["selected"]=not self.results[idx].get("selected",False); self.render_page()
    def set_select(self,idx,val):self.results[idx]["selected"]=bool(val); self.update_page_label()
    def select_page(self):
        a=self.page*self.PAGE
        for i in self.filtered[a:a+self.PAGE]:self.results[i]["selected"]=True
        self.render_page()
    def select_filtered(self):
        for i in self.filtered:self.results[i]["selected"]=True
        self.render_page()
    def clear_selected(self):
        for r in self.results:r["selected"]=False
        self.render_page()
    def change_page(self,d):
        pages=max(1,math.ceil(len(self.filtered)/self.PAGE)) if self.filtered else 1; self.page=max(0,min(pages-1,self.page+d)); self.render_page()
    def make_thumb(self,path):
        try:
            with Image.open(path) as im:
                im=ImageOps.exif_transpose(im).convert("RGB"); im.thumbnail((205,135),Image.Resampling.LANCZOS); bg=Image.new("RGB",(205,135),(28,28,28)); bg.paste(im,((205-im.width)//2,(135-im.height)//2)); return ImageTk.PhotoImage(bg)
        except Exception:return None
    def render_page(self):
        for w in self.cards.winfo_children():w.destroy()
        self.thumb_refs=[]; total=len(self.filtered); pages=max(1,math.ceil(total/self.PAGE)) if total else 0
        if pages and self.page>=pages:self.page=pages-1
        ids=self.filtered[self.page*self.PAGE:(self.page+1)*self.PAGE]; cols=5
        for pos,idx in enumerate(ids):
            r=self.results[idx]; card=ttk.Frame(self.cards,relief="ridge",padding=4); card.grid(row=pos//cols,column=pos%cols,padx=4,pady=4,sticky="n")
            ph=self.make_thumb(r["original_path"]); self.thumb_refs.append(ph); tk.Button(card,image=ph if ph else "",text="" if ph else "無預覽",width=205,height=135,command=lambda i=idx:PreviewWindow(self,i)).pack()
            v=tk.BooleanVar(value=r.get("selected",False)); ttk.Checkbutton(card,text="選取",variable=v,command=lambda i=idx,x=v:self.set_select(i,x.get())).pack(anchor="w")
            n=r.get("people_count",""); scene=r.get("scene",""); ttk.Label(card,text=f"人數：{n if n!='' else '—'}｜{scene or '—'}",width=29).pack(anchor="w")
            ttk.Label(card,text=f"指定人物：{'★人工確認' if r.get('manual_target') else (r.get('target_candidate') or '—')}",width=29).pack(anchor="w")
            ttk.Label(card,text=f"標籤：{r.get('content_tags','') or '—'}",width=29,wraplength=205).pack(anchor="w")
            ttk.Label(card,text=f"依據：{r.get('reason','') or '—'}",width=29,wraplength=205).pack(anchor="w")
        for c in range(cols):self.cards.columnconfigure(c,weight=1)
        self.update_page_label(); self.adv_btn.config(state="normal" if self.results and not self.worker_running else "disabled"); self.exp_btn.config(state="normal" if self.results and not self.worker_running else "disabled")
    def update_page_label(self):
        total=len(self.filtered); pages=max(1,math.ceil(total/self.PAGE)) if total else 0; sel=sum(1 for r in self.results if r.get("selected")); self.page_label.config(text=f"第 {self.page+1 if pages else 0} / {pages} 頁｜篩選 {total} 張｜已選 {sel} 張")
    def start_export(self):
        ids=[i for i,r in enumerate(self.results) if r.get("selected")]
        if not ids:messagebox.showwarning("提示","請先選取要輸出的照片。");return
        self.exp_btn.config(state="disabled"); threading.Thread(target=self.export_worker,args=(ids,),daemon=True).start()
    def export_worker(self,ids):
        try:
            base=self.run_folder/"classified"; base.mkdir(parents=True,exist_ok=True); manifest=[]
            for seq,idx in enumerate(ids,1):
                r=self.results[idx]; src=Path(r["original_path"]); parts=[]
                if self.do_date.get():parts.append("date_"+(r.get("date","")[:7] if len(r.get("date",""))>=7 else "unknown"))
                if self.do_scene.get():parts.append(SCENE_DIR.get(r.get("scene",""),"scene_other"))
                if self.do_count.get():parts.append(people_bucket(r.get("people_count",0)))
                if self.do_person.get():parts.append("person_yes" if r.get("person_present")=="是" else "person_no")
                if self.do_target.get():parts.append("target_manual_yes" if r.get("manual_target") else "target_not_marked")
                folder=base/Path(*parts) if parts else base/"selected"; folder.mkdir(parents=True,exist_ok=True)
                ext=src.suffix.lower() or ".jpg"; dest=folder/f"chunba_{self.run_id}_{seq:05d}{ext}"; k=2
                while dest.exists():dest=folder/f"chunba_{self.run_id}_{seq:05d}_{k}{ext}";k+=1
                shutil.copy2(src,dest); rr=r.copy();rr["export_path"]=str(dest);manifest.append(rr); self.q.put(("progress",100*seq/max(1,len(ids)),f"輸出 {seq}/{len(ids)}"))
            write_csv(self.run_folder/f"chunba_{self.run_id}_export_manifest.csv",manifest); self.q.put(("export_done",len(manifest)))
        except Exception as e:self.q.put(("error",str(e)))
    def open_run(self):
        if self.run_folder and Path(self.run_folder).exists():os.startfile(self.run_folder)
        else:messagebox.showinfo("提示","尚未建立本次資料夾。")
    def poll(self):
        try:
            while True:
                m=self.q.get_nowait();k=m[0]
                if k=="progress":self.progress.set(m[1]);self.status.config(text=m[2])
                elif k=="api_ok":self.status.config(text="Gemini API 測試成功。") ; messagebox.showinfo("成功","API Key 可使用。")
                elif k=="api_err":self.status.config(text="API 測試失敗。") ; messagebox.showerror("API 測試失敗",m[1])
                elif k=="scan_done":self.worker_running=False;self.scan_btn.config(state="normal");self.pause_btn.config(state="disabled",text="暫停");self.cancel_btn.config(state="disabled");self.apply_filter();self.progress.set(100);self.status.config(text=f"快速掃描完成 {len(self.results)} 張｜本次 chunba_{self.run_id}")
                elif k=="advanced_done":self.worker_running=False;self.scan_btn.config(state="normal");self.pause_btn.config(state="disabled",text="暫停");self.cancel_btn.config(state="disabled");self.apply_filter();self.progress.set(100);self.status.config(text=f"精確進階完成｜已儲存 chunba_{self.run_id}_advanced.csv")
                elif k=="export_done":self.exp_btn.config(state="normal");self.progress.set(100);self.status.config(text=f"輸出完成 {m[1]} 張｜本次 chunba_{self.run_id}");messagebox.showinfo("完成",f"已輸出 {m[1]} 張。")
                elif k=="error":self.worker_running=False;self.scan_btn.config(state="normal");self.pause_btn.config(state="disabled",text="暫停");self.cancel_btn.config(state="disabled");self.adv_btn.config(state="normal" if self.results else "disabled");self.exp_btn.config(state="normal" if self.results else "disabled");messagebox.showerror("錯誤",m[1])
        except queue.Empty:pass
        self.after(100,self.poll)

if __name__=="__main__":App().mainloop()
