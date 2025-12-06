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
st.set_page_config(page_title="Shorts 靈感庫 (診斷修復版)", page_icon="🛠️", layout="centered")

# --- 1. 金鑰讀取與檢查 ---
def get_keys():
    try:
        return {
            "gemini": st.secrets["GEMINI_API_KEY"],
            "youtube": st.secrets["YOUTUBE_API_KEY"],
            "gcp_json": dict(st.secrets["gcp_service_account"])
        }
    except Exception as e:
        st.error(f"❌ Secrets 設定讀取失敗: {e}")
        return None

# --- 2. 核心功能函式 ---

def check_available_models(api_key):
    """診斷功能：列出您的 API Key 能用的所有模型"""
    genai.configure(api_key=api_key)
    try:
        models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                models.append(m.name)
        return models
    except Exception as e:
        return [f"Error: {str(e)}"]

def test_sheet_connection(creds_dict):
    """診斷功能：測試能不能寫入 Google Sheet"""
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("Shorts_Content_Planner").sheet1
        # 測試寫入一行
        sheet.append_row([str(datetime.now()), "連線測試成功", "Test", "Test", "Test", "Test", "OK", ""])
        return True, "✅ 連線成功！已寫入一筆測試資料。"
    except Exception as e:
        return False, f"❌ 連線失敗: {str(e)}"

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
        st.error(f"YouTube API 錯誤: {e}")
        return None

def generate_script(video_data, api_key, model_name):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    prompt = f"""
    Video: {video_data['title']} ({video_data['channel']})
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
        cleaned_text = clean_json_string(response.text)
        return json.loads(cleaned_text)
    except Exception as e:
        st.error(f"AI 生成異常 ({model_name}): {e}")
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

# --- 主程式介面 ---
st.title("🛠️ Shorts 系統診斷與生成")
keys = get_keys()

if not keys:
    st.warning("⚠️ 請先設定 Secrets")
else:
    # --- 診斷區塊 (除錯用) ---
    with st.expander("🕵️ 系統狀態檢查 (若有問題點此展開)", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            if st.button("1. 檢查可用 AI 模型"):
                available = check_available_models(keys['gemini'])
                st.write("您的 API Key 支援以下模型：")
                st.code(available)
                if "models/gemini-1.5-flash" in available:
                    st.success("✅ 包含 1.5-flash (最新版)")
                elif "models/gemini-pro" in available:
                    st.warning("⚠️ 僅包含 gemini-pro (舊版)")
                else:
                    st.error("❌ 找不到 Gemini 模型，請檢查 API Key 是否正確")

        with c2:
            if st.button("2. 測試 Google Sheet 連線"):
                ok, msg = test_sheet_connection(keys['gcp_json'])
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)
                    st.info("💡 請確認 Sheet 名稱是否為 'Shorts_Content_Planner' 且已開權限給機器人")

    st.divider()

    # --- 正常功能區塊 ---
    # 自動選擇模型 (優先使用 1.5-flash)
    available_models = check_available_models(keys['gemini'])
    if "models/gemini-1.5-flash" in available_models:
        target_model = "gemini-1.5-flash"
        st.info(f"🚀 系統運作中 (使用模型: {target_model})")
    else:
        target_model = "gemini-pro"
        st.warning(f"⚠️ 系統運作中 (降級使用模型: {target_model})")

    url_input = st.text_input("貼上 YouTube 網址")
    
    if st.button("✨ 生成並自動存檔", type="primary"):
        if not url_input:
            st.error("請輸入網址")
        else:
            vid = extract_video_id(url_input)
            if vid:
                with st.spinner("分析影片中..."):
                    v_info = get_video_info(vid, keys['youtube'])
                
                if v_info:
                    with st.spinner(f"AI 正在思考 (使用 {target_model})..."):
                        result = generate_script(v_info, keys['gemini'], target_model)
                    
                    if result:
                        st.success("生成成功！")
                        st.subheader(result['title'])
                        st.code(result['veo_prompt'], language="text")
                        
                        with st.spinner("正在寫入試算表..."):
                            saved = save_to_sheet_auto(result, keys['gcp_json'], url_input)
                        
                        if saved:
                            st.success("✅ 資料已成功存入 Google Sheet！")
                        else:
                            st.error("❌ 存檔失敗，請檢查上方的「測試 Google Sheet 連線」")
