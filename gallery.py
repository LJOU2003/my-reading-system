import os
import time
from datetime import datetime, date, timedelta
import requests
import calendar
import pandas as pd
import altair as alt
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo


# =========================
# 0) 基本設定
# =========================
load_dotenv(override=True)
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()
BOOK_DS_ID = os.getenv("NOTION_DATABASE_ID", "").strip()
LOG_DS_ID = os.getenv("NOTION_LOG_ID", "").strip()
TODO_DS_ID = os.getenv("NOTION_TODO_ID", "").strip()

# --- 新增：取得今日日期變數 ---
today_str = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")
TIMEOUT_SECONDS = 15 * 60

# =========================
# 0.1) 密碼保護檢查 (支援多組密碼)
# =========================
def check_password():
    def password_entered():
        # 強制從 Secrets 讀取，不設預設密碼
        raw_passwords = os.getenv("ACCESS_PASSWORD")
        password_list = [p.strip() for p in raw_passwords.split(",")] if raw_passwords else []
        
        if st.session_state["password"] in password_list:
            st.session_state["password_correct"] = True
            st.session_state["last_activity"] = time.time()
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct"):
        # 檢查是否超時
        if time.time() - st.session_state.get("last_activity", 0) > TIMEOUT_SECONDS:
            st.session_state["password_correct"] = False
            st.warning("⏰ 登入已過期，請重新輸入。")
            return False
        st.session_state["last_activity"] = time.time() # 重新整理活動時間
        return True

    st.markdown("<h2 style='text-align:center;'>🔐 系統存取保護</h2>", unsafe_allow_html=True)
    st.text_input("請輸入管理員密碼", type="password", on_change=password_entered, key="password")
    return False

if not check_password():
    st.stop()

st.set_page_config(page_title="閱讀管理系統", layout="wide", page_icon="📚")

DEMO_MODE = False
if not NOTION_TOKEN or not BOOK_DS_ID:
    DEMO_MODE = True

# =========================
# 1) 資料處理
# =========================
PROP_TITLE = "名稱"
PROP_STATUS = "閱讀狀態"
PROP_TAGS = "分類標籤"
PROP_COVER = "封面"
PROP_AUTHOR = "作者"
PROP_PUBLISHER = "出版社"
PROP_YEAR = "出版年"
PROP_ISBN = "ISBN"
PROP_PAGES = "頁數"
PROP_SUMMARY = "簡介"
PROP_CATEGORY = "分類"
PROP_GENRE = "類別"
PROP_START_DATE = "開始閱讀"
PROP_END_DATE = "讀完日期"
PROP_PDF = "PDF"

LOG_DATE = "日期"
LOG_PAGES = "頁數"
LOG_MINS = "分鐘數"
LOG_BOOK = "書籍關聯"

TODO_NAME = "名稱"
TODO_DONE = "是否完成"
TODO_DUE = "截止日"

def get_plain_text(props, key):
    try:
        p = props.get(key, {})
        if "title" in p: return "".join([t.get("plain_text", "") for t in p["title"]])
        if "rich_text" in p: return "".join([t.get("plain_text", "") for t in p["rich_text"]])
        if "url" in p: return p["url"] or ""
        if "number" in p: return str(p["number"]) if p["number"] is not None else ""
        return ""
    except: return ""

def get_number(props, key):
    try: return props.get(key, {}).get("number", 0)
    except: return 0

def get_checkbox(props, key):
    try: return props.get(key, {}).get("checkbox", False)
    except: return False

def get_select(props, key):
    try: return props.get(key, {}).get("select", {}).get("name")
    except: return None

def get_multi_select(props, key):
    try: return [x["name"] for x in props.get(key, {}).get("multi_select", [])]
    except: return []

def get_date(props, key):
    try: return props.get(key, {}).get("date", {}).get("start")
    except: return None

def get_url_prop(props, key):
    try: return props.get(key, {}).get("url")
    except: return None

def get_cover(page_obj):
    try:
        cover = page_obj.get("cover")
        if not cover: 
            props = page_obj.get("properties", {})
            p = props.get(PROP_COVER, {})
            if "url" in p and p["url"]: return p["url"]
            if "files" in p and p["files"]:
                f = p["files"][0]
                return f.get("file", {}).get("url") or f.get("external", {}).get("url")
            return ""
        if cover["type"] == "external": return cover["external"]["url"]
        if cover["type"] == "file": return cover["file"]["url"]
        return ""
    except: return ""

def parse_book(p):
    props = p.get("properties", {})
    return {
        "id": p["id"],
        "title": get_plain_text(props, PROP_TITLE) or "(無書名)",
        "author": get_plain_text(props, PROP_AUTHOR),
        "status": get_select(props, PROP_STATUS) or "未分類",
        "category": get_select(props, PROP_CATEGORY) or "未分類",
        "genre": get_select(props, PROP_GENRE) or "未分類",
        "tags": get_multi_select(props, PROP_TAGS),
        "cover": get_cover(p),
        "publisher": get_plain_text(props, PROP_PUBLISHER),
        "year": get_plain_text(props, PROP_YEAR),
        "isbn": get_plain_text(props, PROP_ISBN),
        "pages": get_plain_text(props, PROP_PAGES),
        "summary": get_plain_text(props, PROP_SUMMARY),
        "start_date": get_date(props, PROP_START_DATE),
        "end_date": get_date(props, PROP_END_DATE),
        "pdf": get_url_prop(props, PROP_PDF)
    }

@st.cache_data(show_spinner=False, ttl=60)
def fetch_books():
    if DEMO_MODE: return []
    url = f"https://api.notion.com/v1/databases/{BOOK_DS_ID}/query"
    headers = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    try:
        response = requests.post(url, headers=headers, json={"page_size": 100})
        if response.status_code == 200:
            return [parse_book(p) for p in response.json().get("results", [])]
        else: return {"error": f"連線錯誤: {response.text}"}
    except Exception as e: return {"error": str(e)}

@st.cache_data(show_spinner=False, ttl=10)
def fetch_logs():
    if DEMO_MODE or not LOG_DS_ID: return []
    url = f"https://api.notion.com/v1/databases/{LOG_DS_ID}/query"
    headers = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    try:
        response = requests.post(url, headers=headers, json={"page_size": 100})
        logs = []
        if response.status_code == 200:
            results = response.json().get("results", [])
            for r in results:
                props = r.get("properties", {})
                d = get_date(props, LOG_DATE)
                p = get_number(props, LOG_PAGES)
                m = get_number(props, LOG_MINS)
                if d:
                    logs.append({
                        "id": r["id"],
                        "date": d,
                        "pages": p if p else 0,
                        "mins": m if m else 0
                    })
        return logs
    except: return []

def fetch_todos():
    if DEMO_MODE or not TODO_DS_ID: return []
    url = f"https://api.notion.com/v1/databases/{TODO_DS_ID}/query"
    headers = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    try:
        response = requests.post(url, headers=headers, json={"page_size": 100, "sorts": [{"timestamp": "created_time", "direction": "descending"}]})
        todos = []
        if response.status_code == 200:
            results = response.json().get("results", [])
            for r in results:
                props = r.get("properties", {})
                todos.append({
                    "id": r["id"],
                    "name": get_plain_text(props, TODO_NAME),
                    "done": get_checkbox(props, TODO_DONE),
                    "due_date": get_date(props, TODO_DUE)
                })
        return todos
    except: return []

def add_todo_task(task_name, due_date=None):
    if DEMO_MODE or not TODO_DS_ID: return False, "未設定資料庫 ID"
    url = "https://api.notion.com/v1/pages"
    headers = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    
    props = {
        TODO_NAME: {"title": [{"text": {"content": task_name}}]},
        TODO_DONE: {"checkbox": False}
    }
    if due_date:
        props[TODO_DUE] = {"date": {"start": str(due_date)}}

    try:
        response = requests.post(url, headers=headers, json={"parent": {"database_id": TODO_DS_ID}, "properties": props})
        if response.status_code == 200:
            return True, ""
        else:
            return False, response.text
    except Exception as e: return False, str(e)

def mark_todo_done(page_id):
    if DEMO_MODE: return False
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    
    props = {
        TODO_DONE: {"checkbox": True}
    }
    try:
        response = requests.patch(url, headers=headers, json={"properties": props})
        return response.status_code == 200
    except: return False

def add_log_to_notion(date_val, book_id, pages, mins):
    if DEMO_MODE or not LOG_DS_ID: return False
    url = "https://api.notion.com/v1/pages"
    headers = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    
    props = {
        LOG_DATE: {"date": {"start": str(date_val)}},
        LOG_PAGES: {"number": int(pages)},
        LOG_MINS: {"number": int(mins)},
        LOG_BOOK: {"relation": [{"id": book_id}]},
        "名稱": {"title": [{"text": {"content": f"Log {str(date_val)}"}}]}
    }
    try:
        response = requests.post(url, headers=headers, json={"parent": {"database_id": LOG_DS_ID}, "properties": props})
        return response.status_code == 200
    except: return False

@st.cache_data(show_spinner=False, ttl=300)
def fetch_database_schema():
    if DEMO_MODE: return [], [], [], []
    url = f"https://api.notion.com/v1/databases/{BOOK_DS_ID}"
    headers = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28"}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200: return [], [], [], []
        props = response.json().get("properties", {})
        
        def extract_options(prop_name, type_key):
            prop = props.get(prop_name, {})
            if type_key in ["select", "multi_select"]:
                return [o["name"] for o in prop.get(type_key, {}).get("options", [])]
            if type_key == "status":
                return [o["name"] for o in prop.get("status", {}).get("options", [])]
            return []

        s_opts = extract_options(PROP_STATUS, "select")
        if not s_opts: s_opts = extract_options(PROP_STATUS, "status")
        c_opts = extract_options(PROP_CATEGORY, "select")
        g_opts = extract_options(PROP_GENRE, "select")
        t_opts = extract_options(PROP_TAGS, "multi_select")
        return s_opts, c_opts, g_opts, t_opts
    except:
        return [], [], [], []

def add_book_to_notion(data):
    if DEMO_MODE: return False
    url = "https://api.notion.com/v1/pages"
    headers = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    props = {
        PROP_TITLE: {"title": [{"text": {"content": data["title"]}}]},
        PROP_STATUS: {"select": {"name": data["status"]}},
        PROP_TAGS: {"multi_select": [{"name": t} for t in data["tags"]]}
    }
    if data["cover_url"]: props[PROP_COVER] = {"url": data["cover_url"]}
    if data["pdf_url"]: props[PROP_PDF] = {"url": data["pdf_url"]}
    if data["author"]: props[PROP_AUTHOR] = {"rich_text": [{"text": {"content": data["author"]}}]}
    if data["category"] != "未分類": props[PROP_CATEGORY] = {"select": {"name": data["category"]}}
    if data["genre"] != "未分類": props[PROP_GENRE] = {"select": {"name": data["genre"]}}
    if data["summary"]: props[PROP_SUMMARY] = {"rich_text": [{"text": {"content": data["summary"]}}]}
    if data["start_date"]: props[PROP_START_DATE] = {"date": {"start": str(data["start_date"])}}
    if data["end_date"]: props[PROP_END_DATE] = {"date": {"start": str(data["end_date"])}}
    props = {k: v for k, v in props.items() if v is not None}
    try:
        response = requests.post(url, headers=headers, json={"parent": {"database_id": BOOK_DS_ID}, "properties": props})
        if response.status_code == 200: return True
        else: st.error(f"新增失敗: {response.text}"); return False
    except Exception as e: st.error(f"連線失敗: {str(e)}"); return False

def refresh_data(): st.cache_data.clear(); st.rerun()

books_data = fetch_books()
error_message = None
books = []
if isinstance(books_data, dict) and "error" in books_data:
    error_message = books_data["error"]
else:
    books = books_data

schema_status, schema_cat, schema_gen, schema_tags = fetch_database_schema()
opt_status = schema_status
opt_cat = schema_cat
opt_gen = schema_gen
opt_tag = schema_tags
# =========================
# 2) CSS 樣式 (RWD 增強版)
# =========================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;900&display=swap');
:root{ --bg:#f3f5f9; --purple:#6f2dbd; --text:#1e293b; --card:#ffffff; --green:#15803d; --orange:#ea580c; }
html,body,.stApp{ font-family:'Noto Sans TC',sans-serif !important; color:var(--text); background-color:var(--bg); }

/* --- 桌面版預設樣式 --- */
.topbar{ 
    position:fixed; top:0; left:0; right:0; height:64px; 
    background:var(--card); 
    padding:0 60px; 
    display:flex; justify-content:space-between; align-items:center; 
    box-shadow:0 4px 6px -1px rgba(0,0,0,0.05); z-index:90; 
}
.app-title{ font-size:20px; font-weight:900; color:var(--purple); display:flex; align-items:center; gap:8px; margin-left: 20px; }
.breadcrumb { font-size: 16px; color: #64748b; display: block; }

.block-container{ padding-top:88px !important; max-width: 100% !important; }

header[data-testid="stHeader"] { background: transparent !important; height: 64px !important; z-index: 100 !important; pointer-events: none !important; }
button[data-testid="stSidebarCollapsedControl"], button[data-testid="stSidebarExpandedControl"] {
    position: fixed !important; top: 18px !important; left: 20px !important; z-index: 9999999 !important;
    color: var(--purple) !important; pointer-events: auto !important; background-color: transparent !important; border: none !important; display: block !important; width: auto !important; transform: none !important;
}
section[data-testid="stSidebar"] { top: 64px !important; height: calc(100vh - 64px) !important; }

.book-img-container { width: 100%; aspect-ratio: 2 / 3; border-radius: 12px 12px 0 0; overflow: hidden; position: relative; background-color: #e2e8f0; }
.book-img-container img { width: 100%; height: 100%; object-fit: cover; display: block; }
.book-btn div.stButton > button { width: 100% !important; background-color: white !important; border: 1px solid #e0e0e0 !important; border-top: none !important; border-radius: 0 0 12px 12px !important; color: var(--purple) !important; font-weight: 700 !important; font-size: 14px !important; height: 50px !important; padding: 0 !important; margin-top: -17px !important; box-shadow: 0 4px 6px rgba(0,0,0,0.05) !important; z-index: 1; }
.detail-card { background-color: #fcfcfc; border-radius: 12px; padding: 20px; border: 1px solid #f0f0f0; margin-top: 15px; margin-bottom: 20px; }
.detail-label { font-size: 13px; color: #64748b; margin-bottom: 4px; }
.detail-value { font-size: 15px; font-weight: 600; color: #1e293b; margin-bottom: 12px; }
.pdf-link { display: block; width: 100%; padding: 12px; background-color: #fef2f2; color: #b91c1c; text-align: center; border-radius: 8px; border: 1px solid #fecaca; text-decoration: none; font-weight: 700; transition: 0.2s; }
.cal-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 8px; margin-top: 10px; }
.cal-cell { min-height: 100px; height: auto; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px; display: flex; flex-direction: column; justify-content: flex-start; background: #fff; transition: 0.2s; overflow: visible; }
.cal-cell.today { border: 2px solid var(--purple); background: #fbf7ff; }
.reading-block { background-color: var(--green); color: white; border-radius: 6px; padding: 4px; font-size: 12px; font-weight: 700; text-align: center; margin-top: 2px; box-shadow: 0 1px 2px rgba(0,0,0,0.1); width: 100%; }
.todo-block { background-color: var(--orange); color: white; border-radius: 6px; padding: 4px; font-size: 11px; font-weight: 600; text-align: left; margin-top: 2px; box-shadow: 0 1px 2px rgba(0,0,0,0.1); width: 100%; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.stat-box { background: #1e293b; color: white; border-radius: 12px; padding: 20px; margin-bottom: 15px; text-align: center; }
.stat-val { font-size: 28px; font-weight: 900; }
.chart-container { background: #fff; padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); height: 100%; display: flex; flex-direction: column; }
.chart-title { font-size: 16px; font-weight: 700; color: #1e293b; margin-bottom: 15px; display: flex; align-items: center; gap: 8px; }
.timer-display { font-size: 90px; font-weight: 900; color: var(--purple); font-family: 'Courier New', monospace; margin: 30px 0; letter-spacing: -2px;}
.timer-label { font-size: 20px; color: #64748b; font-weight: 700; text-transform: uppercase; letter-spacing: 3px; }
.todo-item { background: white; border: 1px solid #e2e8f0; padding: 15px; border-radius: 12px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 4px rgba(0,0,0,0.02); }
.todo-done { text-decoration: line-through; color: #cbd5e1; }
.todo-due-tag { font-size: 12px; color: #ea580c; background: #fff7ed; padding: 2px 6px; border-radius: 4px; margin-right: 8px; font-weight: 600; }
button[kind="primary"] { background-color: var(--purple) !important; color: white !important; border: none !important; }

@media (max-width: 768px) {
    .topbar { padding: 0 16px !important; height: 56px !important; }
    .app-title { font-size: 16px !important; margin-left: 30px !important; }
    .breadcrumb { display: none !important; }
    button[data-testid="stSidebarCollapsedControl"], button[data-testid="stSidebarExpandedControl"] { top: 12px !important; left: 10px !important; }
    section[data-testid="stSidebar"] { top: 56px !important; height: calc(100vh - 56px) !important; }
    .block-container { padding-top: 70px !important; padding-left: 1rem !important; padding-right: 1rem !important; }
    .timer-display { font-size: 60px !important; margin: 15px 0 !important; }
    .cal-cell { min-height: 60px !important; padding: 4px !important; }
}
[data-testid="stHeader"] > * { pointer-events:auto; }
</style>
""", unsafe_allow_html=True)

# =========================
# 3) UI 元件
# =========================
def render_topbar(title):
    st.markdown(f"""
    <div class="topbar">
        <div style="display:flex; align-items:center; gap:20px;">
            <div class="app-title"><span>📚</span> 閱讀管理系統</div>
            <div class="breadcrumb">/ {title}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

def render_sidebar():
    with st.sidebar:
        st.caption("導覽選單")
        if st.button("📊 儀表板", use_container_width=True): st.session_state.page = "dashboard"; st.rerun()
        if st.button("📚 書庫列表", use_container_width=True): st.session_state.page = "library"; st.rerun()
        if st.button("🗓️ 閱讀行事曆", use_container_width=True): st.session_state.page = "calendar"; st.rerun()
        if st.button("🍅 專注計時", use_container_width=True): st.session_state.page = "timer"; st.rerun()
        if st.button("✅ 待辦清單", use_container_width=True): st.session_state.page = "todo"; st.rerun()
        st.divider()
        if error_message: st.error("連線異常")
        else: st.success("✅ Notion 已連線")

# =========================
# 4) 功能頁面
# =========================
@st.dialog("📖 新增書籍")
def entry_form():
    with st.form("add"):
        c1, c2 = st.columns(2)
        title = c1.text_input("書名 (必填)", placeholder="請輸入書名")
        author = c2.text_input("作者")
        c3, c4, c5 = st.columns(3)
        status = c3.selectbox("狀態", opt_status if opt_status else ["未定義"])
        category = c4.selectbox("分類", ["未分類"] + (opt_cat if opt_cat else []))
        genre = c5.selectbox("類別", ["未分類"] + (opt_gen if opt_gen else []))
        st.caption("閱讀計畫")
        d1, d2 = st.columns(2)
        start_date = d1.date_input("開始閱讀", value=None)
        end_date = d2.date_input("預計讀完", value=None)
        tags = st.multiselect("標籤", opt_tag if opt_tag else [])
        cover_url = st.text_input("封面連結 (URL)") 
        pdf_url = st.text_input("PDF 檔案連結 (URL)")
        summary = st.text_area("簡介")
        st.write("---")
        if st.form_submit_button("確認新增", type="primary", use_container_width=True):
            if not title: st.error("請輸入書名")
            else:
                data = {"title":title, "author":author, "status":status, "category":category, "genre":genre, "tags":tags, "cover_url":cover_url, "pdf_url":pdf_url, "summary":summary, "start_date":start_date, "end_date":end_date}
                if add_book_to_notion(data): st.success("新增成功"); time.sleep(1); refresh_data()

def render_todo():
    render_topbar("待辦清單")
    st.markdown("""<style>div[data-testid="stVerticalBlock"]:has(div#todo-input-target) {background-color: white; border-radius: 12px; padding: 20px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px rgba(0,0,0,0.05);}</style>""", unsafe_allow_html=True)
    with st.container():
        st.markdown('<div id="todo-input-target"></div>', unsafe_allow_html=True)
        st.markdown('### 📝 新增待辦事項')
        c1, c2, c3 = st.columns([3, 1.5, 1])
        with c1: new_task = st.text_input("任務名稱", label_visibility="collapsed", placeholder="輸入任務...", key="new_todo_input")
        with c2: new_due = st.date_input("截止日", value=None, label_visibility="collapsed", help="選擇截止日期")
        with c3:
            if st.button("＋ 新增", type="primary", use_container_width=True):
                if not TODO_DS_ID: st.error("請檢查 .env 設定")
                elif not new_task: st.warning("請輸入內容")
                else:
                    success, msg = add_todo_task(new_task, new_due)
                    if success: st.success("已新增"); time.sleep(0.5); st.rerun()
                    else: st.error(f"失敗: {msg}")
    st.write("") 
    todos = fetch_todos()
    pending = [t for t in todos if not t["done"]]
    completed = [t for t in todos if t["done"]]
    c1, c2 = st.columns([1, 1], gap="large")
    with c1:
        st.markdown(f"### 🚧 未完成 ({len(pending)})")
        if not pending: st.info("目前沒有待辦事項！")
        for task in pending:
            col_text, col_btn = st.columns([4, 1])
            with col_text:
                due_h = f"<span class='todo-due-tag'>📅 {task['due_date']}</span>" if task['due_date'] else ""
                st.markdown(f'<div class="todo-item" style="margin:0;"><div>{due_h}{task["name"]}</div></div>', unsafe_allow_html=True)
            with col_btn:
                if st.button("完成", key=f"done_{task['id']}", use_container_width=True): mark_todo_done(task['id']); st.rerun()
            st.write("") 
    with c2:
        st.markdown(f"### ✅ 已完成 ({len(completed)})")
        with st.expander("查看已完成項目", expanded=False):
            for task in completed: st.markdown(f'<div class="todo-item todo-done">{task["name"]}</div>', unsafe_allow_html=True)

def render_timer():
    render_topbar("專注計時")
    st.markdown("""<style>div[data-testid="stVerticalBlock"]:has(div#timer-target) {background-color: white; border-radius: 24px; padding: 30px; box-shadow: 0 10px 30px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; text-align: center;}</style>""", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        with st.container():
            st.markdown('<div id="timer-target"></div>', unsafe_allow_html=True)
            st.markdown('<div class="timer-label">FOCUS TIMER</div>', unsafe_allow_html=True)
            t_mode = st.radio("選擇模式", ["25 分鐘 (專注)", "5 分鐘 (短休)", "15 分鐘 (長休)", "自訂"], horizontal=True, label_visibility="collapsed")
            total_mins = 25
            if "5 分鐘" in t_mode: total_mins = 5
            elif "15 分鐘" in t_mode: total_mins = 15
            elif "自訂" in t_mode: total_mins = st.number_input("設定分鐘數", min_value=1, max_value=120, value=25)
            total_secs = total_mins * 60
            if st.button("▶ 開始計時", type="primary", use_container_width=True):
                progress_bar = st.progress(0)
                status_text = st.empty()
                timer_text = st.empty()
                for i in range(total_secs, -1, -1):
                    mins, secs = divmod(i, 60)
                    time_str = f"{mins:02d}:{secs:02d}"
                    timer_text.markdown(f'<div class="timer-display">{time_str}</div>', unsafe_allow_html=True)
                    progress = (total_secs - i) / total_secs
                    progress_bar.progress(progress)
                    status_text.caption("⏳ 專注中...請勿關閉視窗")
                    time.sleep(1)
                status_text.success("✅ 時間到！休息一下吧！")
                st.balloons()
            else: st.markdown(f'<div class="timer-display">{total_mins:02d}:00</div>', unsafe_allow_html=True)

def render_dashboard():
    render_topbar("儀表板")
    if error_message: st.error(f"⚠️ {error_message}"); return
    todos = fetch_todos()
    pending_count = len([t for t in todos if not t["done"]])
    reading = sum(1 for b in books if b["status"] == "閱讀中")
    
    st.markdown(f"""
    <div style="background:linear-gradient(135deg, #6f2dbd, #8b2fc9); border-radius:16px; padding:30px; color:white; margin-bottom:24px; display:flex; justify-content:space-between; align-items:center;">
        <div>
            <h1 style="margin:0; font-size:24px; color:white;">歡迎~LJOU！ 👋</h1>
            <p style="opacity:0.9; margin-top:5px;">📅 今日日期：{today_str} </p>
        </div>
        <div style="text-align:right;"><div style="font-size:32px; font-weight:800;">{reading}</div><div style="font-size:13px; opacity:0.8;">正在閱讀</div></div>
    </div>
    """, unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1: st.markdown(f'<div style="background:#fff; padding:20px; border-radius:12px; box-shadow:0 4px 6px rgba(0,0,0,0.05); text-align:center;"><div style="font-size:24px; font-weight:800;">{len(books)}</div><div style="color:#64748b; font-size:14px;">總藏書</div></div>', unsafe_allow_html=True)
    with c2: st.markdown(f'<div style="background:#fff; padding:20px; border-radius:12px; box-shadow:0 4px 6px rgba(0,0,0,0.05); text-align:center;"><div style="font-size:24px; font-weight:800; color:#ea580c;">{pending_count}</div><div style="color:#64748b; font-size:14px;">待辦任務</div></div>', unsafe_allow_html=True)
    with c3: st.markdown(f'<div style="background:#fff; padding:20px; border-radius:12px; box-shadow:0 4px 6px rgba(0,0,0,0.05); text-align:center;"><div style="font-size:24px; font-weight:800; color:#6f2dbd;">{reading}</div><div style="color:#64748b; font-size:14px;">閱讀中</div></div>', unsafe_allow_html=True)
    
    st.write("")
    logs = fetch_logs()
    if books:
        df_cat = pd.DataFrame([b["category"] for b in books], columns=["分類"])
        df_cat_count = df_cat["分類"].value_counts().reset_index()
        df_cat_count.columns = ["分類", "數量"]
    else:
        df_cat_count = pd.DataFrame(columns=["分類", "數量"])
    if logs:
        df_logs = pd.DataFrame(logs)
        df_logs["date_obj"] = pd.to_datetime(df_logs["date"]).dt.date
        today_val = date.today()
        # --- 關鍵修正處：將 some 改回 -1 ---
        date_list = [today_val - timedelta(days=i) for i in range(6, -1, -1)]
        df_recent_base = pd.DataFrame({"date_obj": date_list})
        df_daily_sum = df_logs.groupby("date_obj")["pages"].sum().reset_index()
        df_recent = pd.merge(df_recent_base, df_daily_sum, on="date_obj", how="left").fillna(0)
        df_recent["日期"] = df_recent["date_obj"].apply(lambda x: x.strftime('%m/%d'))
        df_recent["頁數"] = df_recent["pages"].astype(int)
        
        month_list = []
        for i in range(6):
            y = today_val.year; m = today_val.month - i
            while m <= 0: m += 12; y -= 1
            month_list.append(f"{y}-{m:02d}")
        month_list.reverse()
        df_monthly_base = pd.DataFrame({"月份": month_list})
        df_logs["月份"] = pd.to_datetime(df_logs["date_obj"]).dt.strftime('%Y-%m')
        df_monthly_sum = df_logs.groupby("月份")["pages"].sum().reset_index()
        df_monthly_sum.columns = ["月份", "總頁數"]
        df_monthly = pd.merge(df_monthly_base, df_monthly_sum, on="月份", how="left").fillna(0)
    else:
        df_recent = pd.DataFrame(columns=["日期", "頁數"])
        df_monthly = pd.DataFrame(columns=["月份", "總頁數"])

    row1_c1, row1_c2 = st.columns([1, 1], gap="medium")
    with row1_c1:
        st.markdown('<div class="chart-container"><div class="chart-title">📖 書籍分類佔比</div>', unsafe_allow_html=True)
        if not df_cat_count.empty:
            pie = alt.Chart(df_cat_count).mark_arc(innerRadius=60, outerRadius=100).encode(color=alt.Color("分類"), theta="數量", tooltip=["分類", "數量"])
            st.altair_chart(pie.properties(height=300), use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    with row1_c2:
        st.markdown('<div class="chart-container"><div class="chart-title">📅 近 7 天閱讀頁數</div>', unsafe_allow_html=True)
        if not df_recent.empty:
            bar = alt.Chart(df_recent).mark_bar(color='#6f2dbd', width=20).encode(x=alt.X('日期', sort=None), y='頁數', tooltip=['日期', '頁數'])
            st.altair_chart(bar.properties(height=300), use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<div class="chart-container"><div class="chart-title">📈 每月閱讀趨勢</div>', unsafe_allow_html=True)
    if not df_monthly.empty:
        area = alt.Chart(df_monthly).mark_area(line={'color':'#6f2dbd'}, color=alt.Gradient(gradient='linear', stops=[alt.GradientStop(color='#6f2dbd', offset=0), alt.GradientStop(color='white', offset=1)], x1=1, x2=1, y1=1, y2=0)).encode(x=alt.X('月份', sort=None), y='總頁數', tooltip=['月份', '總頁數'])
        st.altair_chart(area.properties(height=300), use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

def render_library():
    render_topbar("書庫列表")
    if error_message: st.error(f"⚠️ {error_message}"); return
    c1, c2 = st.columns([6, 1.2])
    with c1: st.markdown(f"### 📚 我的書櫃 ({len(books)})")
    with c2: 
        if st.button("＋ 新增書籍", type="primary", use_container_width=True): entry_form()
    with st.container():
        st.markdown('<div class="filter-container">', unsafe_allow_html=True)
        f1, f2, f3, f4, f5 = st.columns([2, 0.8, 0.8, 0.8, 0.8], gap="small")
        with f1: q = st.text_input("搜尋", placeholder="書名...", label_visibility="collapsed")
        with f2: f_status = st.selectbox("狀態", ["狀態: 全部"] + (opt_status if opt_status else []), label_visibility="collapsed")
        with f3: f_cat = st.selectbox("分類", ["分類: 全部"] + (opt_cat if opt_cat else []), label_visibility="collapsed")
        with f4: f_genre = st.selectbox("類別", ["類別: 全部"] + (opt_gen if opt_gen else []), label_visibility="collapsed")
        with f5: f_tag = st.selectbox("標籤", ["標籤: 全部"] + (opt_tag if opt_tag else []), label_visibility="collapsed")
        st.markdown('</div>', unsafe_allow_html=True)
    filtered = books
    if q: filtered = [b for b in filtered if q.lower() in b["title"].lower()]
    if f_status != "狀態: 全部": filtered = [b for b in filtered if b["status"] == f_status]
    if f_cat != "分類: 全部": filtered = [b for b in filtered if b["category"] == f_cat]
    if f_genre != "類別: 全部": filtered = [b for b in filtered if b["genre"] == f_genre]
    if f_tag != "標籤: 全部": filtered = [b for b in filtered if f_tag in b["tags"]]
    if not filtered: st.info("🔍 無書籍"); return
    cols = 5; rows = [filtered[i:i+cols] for i in range(0, len(filtered), cols)]
    for row in rows:
        cc = st.columns(cols)
        for idx, book in enumerate(row):
            with cc[idx]:
                if book.get("cover"): st.markdown(f'<div class="book-img-container"><img src="{book["cover"]}"></div>', unsafe_allow_html=True)
                else: st.markdown('<div class="book-img-container"><div style="text-align:center; padding-top:40px;">📖</div></div>', unsafe_allow_html=True)
                st.markdown('<div class="book-btn">', unsafe_allow_html=True)
                btn_label = book["category"] if book.get("category") else "未分類"
                if st.button(btn_label, key=f"btn_{book['id']}", use_container_width=True):
                    st.session_state.selected_book = book; st.session_state.page = "book_detail"; st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)

def render_book_detail():
    book = st.session_state.get("selected_book")
    if not book: st.session_state.page = "library"; st.rerun(); return
    render_topbar("書籍詳情")
    if st.button("← 返回書庫", type="secondary"): st.session_state.page = "library"; st.rerun()
    st.write("") 
    c1, c2 = st.columns([1, 2], gap="large")
    with c1:
        if book.get("cover"): st.markdown(f'<div class="detail-cover"><img src="{book["cover"]}" style="width:100%; border-radius:12px; box-shadow:0 4px 12px rgba(0,0,0,0.1);"></div>', unsafe_allow_html=True)
        else: st.markdown('<div style="width:100%; aspect-ratio:2/3; background:#e2e8f0; border-radius:12px;"></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div style="font-size:32px; font-weight:900; color:#1e293b; margin-bottom:8px;">{book["title"]}</div>', unsafe_allow_html=True)
        st.markdown(f'<div style="font-size:16px; font-weight:600; color:#1e293b; margin-bottom:20px;">{book["author"] or "未知作者"}</div>', unsafe_allow_html=True)
        st.markdown(f"""
        <div class="detail-card">
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
                <div><div class="detail-label">出版社</div><div class="detail-value">{book["publisher"] or "--"}</div></div>
                <div><div class="detail-label">出版年</div><div class="detail-value">{book["year"] or "--"}</div></div>
                <div><div class="detail-label">ISBN</div><div class="detail-value">{book["isbn"] or "--"}</div></div>
                <div><div class="detail-label">頁數</div><div class="detail-value">{book["pages"] or "--"}</div></div>
                <div><div class="detail-label">開始閱讀</div><div class="detail-value" style="color:#6f2dbd;">{book["start_date"] or "--"}</div></div>
                <div><div class="detail-label">讀完日期</div><div class="detail-value" style="color:#22c55e;">{book["end_date"] or "--"}</div></div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        pdf_link = book.get("pdf")
        if pdf_link: st.markdown(f'''<div class="pdf-btn-container"><a href="{pdf_link}" target="_blank" class="pdf-link">📄 點擊查看 PDF 文件</a></div>''', unsafe_allow_html=True)
        else: st.markdown(f'''<div class="pdf-btn-container"><a class="pdf-link disabled">📄 未提供 PDF 文件</a></div>''', unsafe_allow_html=True)
        if book["summary"]: st.info(book["summary"])
        else: st.info("暫無簡介")

def render_calendar():
    render_topbar("閱讀行事曆")
    if error_message: st.error(f"⚠️ {error_message}"); return
    logs = fetch_logs(); todos = fetch_todos(); log_map = {}
    for log in logs:
        d = log["date"]
        if d:
            if d not in log_map: log_map[d] = {"pages": 0, "mins": 0, "todos": []}
            log_map[d]["pages"] += log["pages"]; log_map[d]["mins"] += log["mins"]
    for task in todos:
        d = task["due_date"]
        if d and not task["done"]:
            if d not in log_map: log_map[d] = {"pages": 0, "mins": 0, "todos": []}
            log_map[d]["todos"].append(task["name"])
    c_cal, c_detail = st.columns([3, 1.2], gap="large")
    with c_cal:
        col_ctrl1, col_ctrl2, _ = st.columns([1, 1, 2])
        with col_ctrl1: curr_year = st.number_input("年份", value=datetime.now().year, min_value=2020, max_value=2030)
        with col_ctrl2: curr_month = st.selectbox("月份", range(1, 13), index=datetime.now().month-1)
        cal = calendar.monthcalendar(curr_year, curr_month); st.write("")
        cols = st.columns(7); days = ["日", "一", "二", "三", "四", "五", "六"]
        for idx, d in enumerate(days): cols[idx].markdown(f"<div style='text-align:center; color:#64748b; font-weight:bold;'>{d}</div>", unsafe_allow_html=True)
        t_s = datetime.now().strftime("%Y-%m-%d")
        for week in cal:
            cols = st.columns(7)
            for idx, day in enumerate(week):
                with cols[idx]:
                    if day != 0:
                        d_obj = date(curr_year, curr_month, day); d_str = d_obj.strftime("%Y-%m-%d")
                        is_today = "today" if d_str == t_s else ""; content_html = f"<div class='cal-date-num'>{day}</div>"
                        if d_str in log_map:
                            data = log_map[d_str]
                            if data["pages"] > 0: content_html += f"<div class='reading-block'>{data['pages']} <span>頁</span></div>"
                            for t in data["todos"][:2]: content_html += f"<div class='todo-block'>📝 {t}</div>"
                        st.markdown(f"<div class='cal-cell {is_today}'>{content_html}</div>", unsafe_allow_html=True)
    with c_detail:
        st.markdown("### 📅 選取日期"); sel_date = st.date_input("日期", value=datetime.now()); sel_date_str = sel_date.strftime("%Y-%m-%d")
        day_data = log_map.get(sel_date_str, {"pages": 0, "mins": 0, "todos": []})
        d1, d2 = st.columns(2)
        with d1: st.markdown(f"""<div class='stat-box'><div class='stat-val'>{day_data['pages']}</div><div class='stat-label'>頁</div></div>""", unsafe_allow_html=True)
        with d2: st.markdown(f"""<div class='stat-box'><div class='stat-val'>{day_data['mins']}</div><div class='stat-label'>分鐘</div></div>""", unsafe_allow_html=True)
        for t in day_data["todos"]: st.info(t)
        st.divider(); st.markdown("#### 📝 新增閱讀紀錄")
        with st.form("add_log"):
            book_opts = {b["title"]: b["id"] for b in books}
            sel_book_name = st.selectbox("選擇書籍", list(book_opts.keys())) if book_opts else st.selectbox("選擇書籍", ["無書籍"])
            l1, l2 = st.columns(2); in_pages = l1.number_input("閱讀頁數", min_value=0, step=1); in_mins = l2.number_input("閱讀分鐘", min_value=0, step=5)
            if st.form_submit_button("＋ 新增紀錄", type="primary", use_container_width=True):
                if book_opts and add_log_to_notion(sel_date, book_opts[sel_book_name], in_pages, in_mins): st.success("已儲存"); time.sleep(1); refresh_data()

# =========================
# 控制邏輯
# =========================
if "page" not in st.session_state: st.session_state.page = "dashboard"
render_sidebar()

if st.session_state.page == "dashboard": render_dashboard()
elif st.session_state.page == "library": render_library()
elif st.session_state.page == "book_detail": render_book_detail()
elif st.session_state.page == "calendar": render_calendar()
elif st.session_state.page == "timer": render_timer()
elif st.session_state.page == "todo": render_todo()