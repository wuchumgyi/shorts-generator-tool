import streamlit as st
import google.generativeai as genai
from googleapiclient.discovery import build
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
import re

# --- 頁面設定 ---
st.set_page_config(page_title="Shorts 獵手 (自選模型版)", page_icon="🛡️", layout="wide")
st.markdown("""
    <style>
    .stButton>button {width: 100%; border-radius: 8px; font-weight: bold;}
    .video-card {background-color: #f0f2f6; padding: 15px; border-radius: 10px; margin-bottom: 10px;}
    .success-box {padding: 10px; background-color: #d4edda; color: #155724; border-radius: 5px;}
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

keys = get_keys()

# --- 2. 關鍵修復：獲取真正可用的模型 ---
@st.cache_resource
def get_valid_models(api_key):
    """
    直接詢問 API Key 支援哪些模型，不瞎猜。
    這個動作會被快取，不會一直消耗額度。
    """
    if not api_key: return []
    genai.configure(api_key=api_key)
    valid_models = []
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                # 這裡抓到的名稱會像是 'models/gemini-1.5-flash-001'
                valid_models.append(m.name)
    except Exception as e:
        print(f"Error listing models: {e}")
        return []
    return valid_models

# --- 側邊欄：模型選擇器 (解決 404 的核心) ---
with st.sidebar:
    st.header("⚙️ AI 模型設定")
    if keys and keys["gemini"]:
        # 1. 自動抓取列表
        available_models = get_valid_models(keys["gemini"])
        
        if available_models:
            # 2. 讓您自己選 (預設選第一個，通常是最新的)
            selected_model_name = st.selectbox(
                "👇 請選擇一個模型 (必選)", 
                available_models,
                index=0
            )
            st.success(f"目前使用：{selected_model_name}")
            st.info("💡 如果生成失敗，請在此切換另一個模型試試。")
        else:
            st.error("❌ 無法抓取模型列表。")
            st.warning("請檢查 Google Cloud Console 是否已啟用 'Generative Language API'。")
            selected_model_name = None
    else:
        st.error("⚠️ 請先設定 Secrets")
        selected_model_name = None

# --- 3. 核心工具 ---
def clean_json_string(text):
    text = text.replace("```json", "").replace("```", "")
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        text = text[start:end+1]
    return text.strip()

# --- 4. YouTube 搜尋 ---
def search_videos(api_key, keyword, max_results=10):
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        search_response = youtube.search().list(
            q=keyword, type="video", part="id,snippet",
            maxResults=max_results, order="viewCount", videoDuration="short"
        ).execute()

        videos = []
        for item in search_response.get("items", []):
            vid = item['id']['videoId']
            videos.append({
                'id': vid,
                'url': f"https://www.youtube.com/shorts/{vid}",
                'title': item['snippet']['title'],
                'thumbnail': item['snippet']['thumbnails']['high']['url'],
                'channel': item['snippet']['channelTitle'],
                'desc': item['snippet']['description']
            })
        return videos
    except Exception as e:
        st.error(f"搜尋失敗: {e}")
        return []

# --- 5. AI 生成 (使用您選的模型) ---
def generate_derivative_content(title, desc, api_key, model_name):
    genai.configure(api_key=api_key)
    
    # 這裡直接使用您在側邊欄選到的那個「絕對存在」的模型
    model = genai.GenerativeModel(model_name)
    
    prompt = f"""
    Video Title: {title}
    Original Desc: {desc}
    
    Task: Create a plan for a "Derivative Work" (二創) of this video for YouTube Shorts.
    
    Output JSON ONLY with these fields:
    {{
        "new_title": "A catchy Chinese title (繁體中文)",
        "script": "Detailed visual script for Veo/Kling (Traditional Chinese)",
        "tags": "#Tag1 #Tag2 #AI (English/Chinese mix)",
        "keywords": "Key1, Key2 (For SEO)"
    }}
    """
    try:
        response = model.generate_content(prompt)
        return json.loads(clean_json_string(response.text))
    except Exception as e:
        return {"error": str(e)}

# --- 6. 存檔 ---
def save_to_sheet(data, creds_dict):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("Shorts_Content_Planner").sheet1
        
        row = [
            str(datetime.now())[:16],
            data['url'],
            data['title'],
            data['keywords'],
            data['tags'],
            data['note']
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"寫入失敗: {e}")
        return False

# --- 主介面 ---
st.title("🎯 Shorts 獵手 (自選模型版)")

if keys["gemini"]:
    # 搜尋區塊
    with st.container():
        c1, c2 = st.columns([3, 1])
        with c1:
            keyword = st.text_input("🔍 輸入關鍵字", value="Oddly Satisfying")
        with c2:
            st.write("")
            st.write("")
            if st.button("開始搜尋", type="primary"):
                with st.spinner("搜尋中..."):
                    results = search_videos(keys['youtube'], keyword)
                    if results:
                        st.session_state.search_results = results
                        st.session_state.selected_video = results[0]
                        # 重置
                        st.session_state.ai_title = results[0]['title']
                        st.session_state.ai_script = ""
                        st.session_state.ai_tags = ""
                        st.session_state.ai_keywords = ""
                    else:
                        st.warning("找不到影片")

    # 內容區塊
    if 'search_results' in st.session_state and st.session_state.search_results:
        st.divider()
        col_list, col_detail = st.columns([1, 2])

        with col_list:
            st.markdown("### 📺 影片列表")
            for vid in st.session_state.search_results:
                if st.button(f"📄 {vid['title'][:15]}...", key=vid['id']):
                    st.session_state.selected_video = vid
                    st.session_state.ai_title = vid['title']
                    st.session_state.ai_script = ""
                    st.session_state.ai_tags = ""
                    st.session_state.ai_keywords = ""
                    st.rerun()

        with col_detail:
            selected = st.session_state.get('selected_video')
            if selected:
                st.subheader("📝 編輯與存檔")
                st.video(selected['url'])
                st.caption(f"來源: {selected['channel']}")
                st.markdown("---")

                # AI 按鈕
                col_btn, _ = st.columns([1, 1])
                with col_btn:
                    if st.button("✨ AI 生成並自動存檔"):
                        if not selected_model_name:
                            st.error("❌ 請先在左側邊欄選擇一個 AI 模型！")
                        else:
                            with st.spinner(f"AI ({selected_model_name}) 正在運作中..."):
                                ai_data = generate_derivative_content(
                                    selected['title'], selected['desc'], 
                                    keys['gemini'], selected_model_name
                                )
                                
                                if "error" not in ai_data:
                                    # 1. 更新介面
                                    st.session_state.ai_title = ai_data.get('new_title', selected['title'])
                                    st.session_state.ai_script = ai_data.get('script', '')
                                    st.session_state.ai_tags = ai_data.get('tags', '')
                                    st.session_state.ai_keywords = ai_data.get('keywords', '')
                                    
                                    # 2. 自動存檔
                                    data_to_save = {
                                        'url': selected['url'],
                                        'title': ai_data.get('new_title', selected['title']),
                                        'keywords': ai_data.get('keywords', ''),
                                        'tags': ai_data.get('tags', ''),
                                        'note': ai_data.get('script', '')
                                    }
                                    if save_to_sheet(data_to_save, keys['gcp_json']):
                                        st.success("✅ 成功！腳本已生成並存入 Google Sheet！")
                                        st.rerun()
                                else:
                                    st.error(f"生成失敗: {ai_data['error']}")

                # 表單 (顯示結果用)
                new_title = st.text_input("影片標題", key="ai_title")
                c1, c2 = st.columns(2)
                with c1:
                    tags_input = st.text_area("標籤", key="ai_tags")
                with c2:
                    kw_input = st.text_area("關鍵字", key="ai_keywords")
                
                note_input = st.text_area("二創腳本", key="ai_script", height=200)
                
                # 手動更新存檔按鈕
                if st.button("💾 手動更新存檔"):
                     data_to_save = {
                        'url': selected['url'],
                        'title': new_title,
                        'keywords': kw_input,
                        'tags': tags_input,
                        'note': note_input
                    }
                     if save_to_sheet(data_to_save, keys['gcp_json']):
                        st.success("✅ 資料已更新！")
