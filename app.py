import streamlit as st
import google.generativeai as genai
from googleapiclient.discovery import build
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
import re
import random
import time

# --- 頁面設定 ---
st.set_page_config(page_title="Shorts 救星 (穩定版)", page_icon="🛡️", layout="centered")
st.markdown("""
    <style>
    .stButton>button {width: 100%; border-radius: 20px; font-weight: bold;}
    .stTextInput>div>div>input {border-radius: 10px;}
    .success-box {padding: 1rem; background-color: #d4edda; color: #155724; border-radius: 10px; margin-bottom: 1rem;}
    .error-box {padding: 1rem; background-color: #f8d7da; color: #721c24; border-radius: 10px; margin-bottom: 1rem;}
    .warning-box {padding: 1rem; background-color: #fff3cd; color: #856404; border-radius: 10px; margin-bottom: 1rem;}
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

# --- 3. 搜尋與資訊獲取 ---
def search_trending_video(api_key):
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        search_response = youtube.search().list(
            q="Oddly Satisfying Shorts", # 改回最簡單的關鍵字
            type="video",
            part="id,snippet",
            maxResults=20,
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

# --- 4. AI 生成邏輯 (極簡穩定版) ---
def generate_script_stable(video_data, api_key):
    genai.configure(api_key=api_key)
    
    # ⚠️ 強制指定 gemini-1.5-flash
    # 這是最不容易出錯的模型，我們不要再去嘗試偵測別的了
    model_name = "gemini-1.5-flash"
    
    prompt = f"""
    Video Title: {video_data['title']}
    Channel: {video_data['channel']}
    
    Task: Create a high-quality, viral 9-second Short plan.
    
    CRITICAL VISUAL INSTRUCTIONS:
    1. The 'veo_prompt' MUST describe a CONTINUOUS ACTION (One-shot).
    2. Focus on the PROCESS (morphing, flowing). No "Before/After".
    
    DATA REQUIREMENTS:
    1. 'veo_prompt': English prompt for Google Veo (Smooth motion).
    2. 'kling_prompt': English prompt for Kling AI (High quality).
    3. 'script_en', 'tags', 'comment' in ENGLISH.
    4. 'script_zh', 'title_zh' in TRADITIONAL CHINESE.
    5. 'tags' MUST include #AI. NO tool names.
    
    Output JSON ONLY:
    {{
        "title_en": "English Title",
        "title_zh": "中文標題",
        "veo_prompt": "Prompt for Veo (English)",
        "kling_prompt": "Prompt for Kling (English)",
        "script_en": "Script (English)",
        "script_zh": "Script (Chinese)",
        "tags": "#Tag1 #Tag2 #AI",
        "comment": "Comment"
    }}
    """
    
    # --- 簡單的重試邏輯 ---
    try:
        model = genai.GenerativeModel(model_name)
        
        # 發送請求
        response = model.generate_content(prompt)
        result = json.loads(clean_json_string(response.text))
        
        # 簡單的標籤處理
        raw_tags = result.get('tags', '')
        if "#AI" not in raw_tags and "#ai" not in raw_tags:
            result['tags'] = raw_tags + " #AI"
            
        return result

    except Exception as e:
        error_msg = str(e)
        
        # 針對 429 錯誤給出明確指示
        if "429" in error_msg or "quota" in error_msg.lower():
            st.markdown("""
            <div class="error-box">
            <b>🔴 API 還在冷卻中 (429 Error)</b><br>
            您的 API Key 目前被 Google 暫時限制速度了。<br>
            <b>請您現在停止操作，去喝杯咖啡，等待 2~3 分鐘後再試一次。</b><br>
            這不是程式壞掉，而是需要一點時間讓計數器歸零。
            </div>
            """, unsafe_allow_html=True)
        else:
            st.error(f"生成發生錯誤 ({model_name}): {e}")
        return None

# --- 5. 存檔邏輯 ---
def save_to_sheet_auto(data, creds_dict, ref_url):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("Shorts_Content_Planner").sheet1
        
        row = [
            str(datetime.now())[:16],
            ref_url,
            data.get('title_en', ''),
            data.get('title_zh', ''),
            data.get('veo_prompt', ''),
            data.get('kling_prompt', ''),
            data.get('script_en', ''),
            data.get('script_zh', ''),
            str(data.get('tags', '')),
            data.get('comment', '')
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"寫入失敗: {e}")
        return False

# --- 主介面 ---
st.title("🛡️ Shorts 救星 (穩定版)")
keys = get_keys()

if not keys:
    st.warning("⚠️ 請先設定 Secrets")
else:
    # 步驟 1
    st.markdown("### 步驟 1: 選擇來源")
    col1, col2 = st.columns([1, 1.5])
    with col1:
        if st.button("🎲 隨機搜熱門影片"):
            with st.spinner("🔍 搜尋中..."):
                found_url = search_trending_video(keys['youtube'])
                if found_url:
                    st.session_state['auto_url'] = found_url
                    st.success("已找到！")

    # 步驟 2
    default_val = st.session_state.get('auto_url', "")
    url_input = st.text_input("👇 影片網址 (手動貼上 或 按上方搜尋)", value=default_val)
    
    st.markdown("### 步驟 2: AI 生成與存檔")
    if st.button("✨ 生成腳本 (使用最穩定的 1.5 Flash)", type="primary"):
        if not url_input:
            st.warning("請先輸入網址")
        else:
            vid = extract_video_id(url_input)
            if vid:
                with st.spinner("1/2 分析影片..."):
                    v_info = get_video_info(vid, keys['youtube'])
                
                if v_info:
                    with st.spinner("2/2 AI 正在撰寫..."):
                        result = generate_script_stable(v_info, keys['gemini'])
                    
                    if result:
                        with st.spinner("正在存檔..."):
                            saved = save_to_sheet_auto(result, keys['gcp_json'], url_input)
                        
                        if saved:
                            st.markdown(f"""
                            <div class="success-box">
                                <h3>✅ 成功！</h3>
                                <p><strong>中文標題:</strong> {result['title_zh']}</p>
                            </div>
                            """, unsafe_allow_html=True)
                            
                            st.divider()
                            c1, c2 = st.columns(2)
                            with c1:
                                st.subheader("🇺🇸 Google Veo")
                                st.code(result['veo_prompt'], language="text")
                            with c2:
                                st.subheader("🇨🇳 Kling AI")
                                st.code(result['kling_prompt'], language="text")
                                
                            st.caption("Common Script: " + result['script_zh'])
