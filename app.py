import streamlit as st
import google.generativeai as genai
from googleapiclient.discovery import build
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
import re
import random

# --- 頁面設定 ---
st.set_page_config(page_title="Shorts 國際版生成器", page_icon="🌍", layout="centered")
st.markdown("""
    <style>
    .stButton>button {width: 100%; border-radius: 20px; font-weight: bold;}
    .stTextInput>div>div>input {border-radius: 10px;}
    .success-box {padding: 1rem; background-color: #d4edda; color: #155724; border-radius: 10px; margin-bottom: 1rem;}
    </style>
    """, unsafe_allow_html=True)

# --- 1. 金鑰讀取 ---
def get_keys():
    try:
        return {
            "gemini": st.secrets["GEMINI_API_KEY"],
            "youtube": st.secrets["YOUTUBE_API_KEY"],
            "gcp_json": dict(st.secrets["gcp_service_account"])
        }
    except Exception:
        return None

# --- 2. 核心工具函式 ---
def extract_video_id(url):
    regex = r"(?:v=|\/shorts\/|\/)([0-9A-Za-z_-]{11}).*"
    match = re.search(regex, url)
    return match.group(1) if match else None

def clean_json_string(text):
    text = text.replace("```json", "").replace("```", "")
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        text = text[start:end+1]
    return text.strip()

def get_first_available_model(api_key):
    """自動抓取可用的模型，避免 404 錯誤"""
    genai.configure(api_key=api_key)
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                return m.name
    except Exception:
        return None
    return "models/gemini-pro"

# --- 3. 搜尋與資訊獲取 ---
def search_trending_video(api_key):
    """自動搜尋熱門影片"""
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        # 搜尋關鍵字：Oddly Satisfying, Stress Relief
        search_response = youtube.search().list(
            q="Oddly Satisfying Shorts",
            type="video",
            part="id,snippet",
            maxResults=30, # 抓多一點來隨機
            order="viewCount", 
            videoDuration="short"
        ).execute()

        items = search_response.get("items", [])
        if not items: return None
        selected = random.choice(items)
        return f"https://www.youtube.com/shorts/{selected['id']['videoId']}"
    except Exception as e:
        st.error(f"搜尋失敗: {e}")
        return None

def get_video_info(video_id, api_key):
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        response = youtube.videos().list(part="snippet,statistics", id=video_id).execute()
        if not response['items']: return None
        item = response['items'][0]
        return {
            "title": item['snippet']['title'],
            "desc": item['snippet']['description'],
            "tags": item['snippet'].get('tags', []),
            "views": item['statistics'].get('viewCount', 0),
            "channel": item['snippet']['channelTitle']
        }
    except Exception as e:
        st.error(f"YouTube 錯誤: {e}")
        return None

# --- 4. AI 生成邏輯 (語言分流 + 強制標籤) ---
def generate_script(video_data, api_key):
    genai.configure(api_key=api_key)
    
    # 自動選擇模型
    model_name = get_first_available_model(api_key)
    if not model_name:
        st.error("❌ 無法找到可用模型，請檢查 API 權限。")
        return None
    
    st.info(f"🤖 使用模型：{model_name}")
    model = genai.GenerativeModel(model_name)
    
    # Prompt: 明確要求欄位分離 + 強制 #AI
    prompt = f"""
    Video Title: {video_data['title']}
    Channel: {video_data['channel']}
    
    Task: Create a viral 9-second Short plan based on this video.
    
    REQUIREMENTS:
    1. 'veo_prompt', 'script_en', 'tags', 'comment' MUST be in ENGLISH.
    2. 'script_zh', 'title_zh' MUST be in TRADITIONAL CHINESE (繁體中文).
    3. 'tags' MUST include #AI.
    
    Output JSON ONLY:
    {{
        "title_en": "Catchy English Title",
        "title_zh": "吸睛的繁體中文標題 (含Emoji)",
        "veo_prompt": "Detailed prompt for Google Veo/Sora (English only), photorealistic, 4k, slow motion",
        "script_en": "9-second visual description (English)",
        "script_zh": "9秒畫面描述與分鏡 (繁體中文翻譯)",
        "tags": "#Tag1 #Tag2 #AI (English Only)",
        "comment": "Engaging first comment (English Only)"
    }}
    """
    try:
        response = model.generate_content(prompt)
        result = json.loads(clean_json_string(response.text))
        
        # --- 雙重保險：程式強制檢查並加入 #AI ---
        current_tags = result.get('tags', '')
        if '#AI' not in current_tags and '#ai' not in current_tags:
             # 如果 AI 忘了加，我們手動幫它加在最後面
             result['tags'] = f"{current_tags} #AI".strip()
             
        return result

    except Exception as e:
        st.error(f"生成失敗: {e}")
        return None

# --- 5. 存檔邏輯 (寫入 Google Sheet) ---
def save_to_sheet_auto(data, creds_dict, ref_url):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("Shorts_Content_Planner").sheet1
        
        # 欄位順序必須對應試算表標題
        row = [
            str(datetime.now())[:16],   # 時間
            ref_url,                    # 來源網址
            data.get('title_en', ''),   # 英文標題
            data.get('title_zh', ''),   # 中文標題
            data.get('veo_prompt', ''), # Veo Prompt
            data.get('script_en', ''),  # 英文腳本
            data.get('script_zh', ''),  # 中文腳本
            str(data.get('tags', '')),  # 英文標籤 (含 #AI)
            data.get('comment', '')     # 英文留言
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"寫入失敗: {e}")
        return False

# --- 主介面 ---
st.title("🌍 Shorts 國際版生成器")
keys = get_keys()

if not keys:
    st.warning("⚠️ 請先設定 Secrets")
else:
    # 1. 自動搜尋按鈕 (獨立區塊)
    st.markdown("### 步驟 1: 選擇來源")
    col1, col2 = st.columns([1, 1.5])
    with col1:
        if st.button("🎲 隨機搜熱門影片"):
            with st.spinner("🔍 正在 YouTube 挖掘熱門短片..."):
                found_url = search_trending_video(keys['youtube'])
                if found_url:
                    st.session_state['auto_url'] = found_url
                    st.success("已找到！請在下方確認並生成")

    # 2. 網址輸入框 (可手動貼上，也可自動填入)
    default_val = st.session_state.get('auto_url', "")
    url_input = st.text_input("👇 影片網址 (手動貼上 或 按上方搜尋)", value=default_val)
    
    # 3. 生成按鈕
    st.markdown("### 步驟 2: AI 生成與存檔")
    if st.button("✨ 生成中英文腳本並自動存檔", type="primary"):
        if not url_input:
            st.warning("請先輸入網址或搜尋影片")
        else:
            vid = extract_video_id(url_input)
            if vid:
                with st.spinner("1/3 分析影片數據..."):
                    v_info = get_video_info(vid, keys['youtube'])
                
                if v_info:
                    with st.spinner("2/3 AI 正在撰寫雙語腳本..."):
                        result = generate_script(v_info, keys['gemini'])
                    
                    if result:
                        with st.spinner("3/3 寫入雲端試算表..."):
                            saved = save_to_sheet_auto(result, keys['gcp_json'], url_input)
                        
                        if saved:
                            st.markdown(f"""
                            <div class="success-box">
                                <h3>✅ 成功！資料已分離並存檔</h3>
                                <p><strong>中文標題：</strong>{result['title_zh']}</p>
                                <p><strong>標籤確認：</strong>{result['tags']}</p>
                            </div>
                            """, unsafe_allow_html=True)
                            
                            # 顯示詳細結果讓您確認
                            st.divider()
                            c1, c2 = st.columns(2)
                            with c1:
                                st.subheader("🇺🇸 English Content")
                                st.caption("Veo Prompt")
                                st.code(result['veo_prompt'], language="text")
                                st.caption("Script")
                                st.write(result['script_en'])
                                st.caption("Tags")
                                st.write(result['tags'])
                                
                            with c2:
                                st.subheader("🇹🇼 繁體中文")
                                st.caption("標題")
                                st.write(result['title_zh'])
                                st.caption("腳本翻譯")
                                st.write(result['script_zh'])
