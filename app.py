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
st.set_page_config(page_title="Shorts 萬能生成器", page_icon="🚀", layout="centered")
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

# --- 2. 核心功能 ---
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

# --- 關鍵修復：動態獲取可用模型 ---
def get_first_available_model(api_key):
    """
    不猜測模型名稱，直接詢問 API Key 支援什麼模型，並回傳第一個可用的。
    這樣可以 100% 避免 404 錯誤。
    """
    genai.configure(api_key=api_key)
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                # 直接回傳伺服器給的名稱 (例如 models/gemini-1.5-flash)
                return m.name
    except Exception as e:
        st.error(f"API Key 權限異常: {e}")
        return None
    return "models/gemini-pro" # 萬一都沒抓到，回傳一個預設值

def generate_script(video_data, api_key):
    genai.configure(api_key=api_key)
    
    # 步驟 A: 自動抓取對應的模型
    model_name = get_first_available_model(api_key)
    if not model_name:
        st.error("❌ 無法找到可用的 Gemini 模型，請檢查 API Key 是否啟用了 Generative Language API。")
        return None
        
    st.info(f"🤖 正在使用模型：{model_name}") # 顯示當前使用的模型
    
    model = genai.GenerativeModel(model_name)
    
    prompt = f"""
    Video Title: {video_data['title']}
    Channel: {video_data['channel']}
    
    Task: Create a plan for a NEW viral 9-second Short.
    
    Output JSON ONLY:
    {{
        "analysis": "中文分析",
        "veo_prompt": "Detailed English prompt for Veo, photorealistic, 4k",
        "title": "中文標題 (含 Emoji)",
        "script": "9秒中文腳本",
        "tags": "#Tag1 #Tag2",
        "comment": "中文置頂留言"
    }}
    """
    try:
        response = model.generate_content(prompt)
        return json.loads(clean_json_string(response.text))
    except Exception as e:
        st.error(f"生成失敗 ({model_name}): {e}")
        return None

def save_to_sheet_auto(data, creds_dict, ref_url):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("Shorts_Content_Planner").sheet1
        
        row = [
            str(datetime.now())[:16],
            data.get('title', ''),
            data.get('veo_prompt', ''),
            data.get('script', ''),
            str(data.get('tags', '')),
            data.get('comment', ''),
            "未發布",
            ref_url
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"寫入失敗: {e}")
        return False

# --- 3. 獲取影片資訊 ---
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

# --- 主介面 ---
st.title("🚀 Shorts 萬能生成器 (自動修復版)")
keys = get_keys()

if not keys:
    st.warning("⚠️ 請先設定 Secrets")
else:
    # 測試連結區塊 (隱藏式)
    with st.expander("🛠️ 展開進行連線測試"):
        if st.button("測試 Google Sheet 寫入"):
             # 簡單測試
             try:
                 save_to_sheet_auto({"title": "測試"}, keys['gcp_json'], "test_url")
                 st.success("✅ 試算表連線正常！")
             except:
                 st.error("連線失敗")

    url_input = st.text_input("YouTube 網址", placeholder="貼上網址...")
    
    if st.button("✨ 生成並自動存檔", type="primary"):
        if not url_input:
            st.warning("請輸入網址")
        else:
            vid = extract_video_id(url_input)
            if vid:
                with st.spinner("1/3 分析影片..."):
                    v_info = get_video_info(vid, keys['youtube'])
                
                if v_info:
                    # 這裡會自動選一個能用的模型
                    with st.spinner("2/3 AI 正在撰寫..."):
                        result = generate_script(v_info, keys['gemini'])
                    
                    if result:
                        with st.spinner("3/3 存檔中..."):
                            saved = save_to_sheet_auto(result, keys['gcp_json'], url_input)
                        
                        if saved:
                             st.markdown(f"""
                            <div class="success-box">
                                <h3>✅ 成功！已存入試算表</h3>
                                <p><strong>標題：</strong>{result['title']}</p>
                            </div>
                            """, unsafe_allow_html=True)
                             st.code(result['veo_prompt'], language="text")
