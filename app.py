import streamlit as st
import google.generativeai as genai
from googleapiclient.discovery import build
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
import re

# --- 頁面設定 ---
st.set_page_config(page_title="Shorts 獵手 (完美修復版)", page_icon="💎", layout="wide")
st.markdown("""
    <style>
    .stButton>button {width: 100%; border-radius: 8px; font-weight: bold;}
    .success-box {padding: 1rem; background-color: #d4edda; color: #155724; border-radius: 5px; margin-bottom: 1rem;}
    </style>
    """, unsafe_allow_html=True)

# --- 1. 初始化與讀取 Key ---
def get_keys():
    return {
        "gemini": st.secrets.get("GEMINI_API_KEY"),
        "youtube": st.secrets.get("YOUTUBE_API_KEY"),
        "gcp_json": dict(st.secrets["gcp_service_account"]) if "gcp_service_account" in st.secrets else None
    }

keys = get_keys()

# --- 2. 獲取可用模型 (這就是解決 404 的關鍵) ---
@st.cache_resource
def get_valid_models(api_key):
    """只抓取真正能用的模型，避免瞎猜"""
    if not api_key: return []
    genai.configure(api_key=api_key)
    valid_models = []
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                # 只保留名稱，例如 'models/gemini-1.5-flash'
                valid_models.append(m.name)
    except:
        pass
    return valid_models

# --- 側邊欄：模型選擇器 ---
with st.sidebar:
    st.header("⚙️ 設定")
    if keys["gemini"]:
        # 這裡會自動列出您帳號裡真正能用的模型
        model_options = get_valid_models(keys["gemini"])
        if model_options:
            selected_model = st.selectbox("🤖 選擇 AI 模型", model_options, index=0)
            st.success(f"已連線：{selected_model}")
        else:
            st.error("無法獲取模型列表，請檢查 API Key")
            selected_model = None
    else:
        st.error("請先設定 Secrets")
        selected_model = None

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

# --- 5. AI 生成 (使用選定的模型) ---
def generate_content_with_model(title, desc, api_key, model_name):
    genai.configure(api_key=api_key)
    # 直接使用選單選出來的名字，絕對不會錯
    model = genai.GenerativeModel(model_name)
    
    prompt = f"""
    Video: {title}
    Desc: {desc}
    Task: Plan a "Derivative Work" (二創) for YouTube Shorts.
    
    Output JSON ONLY:
    {{
        "new_title": "Catchy Chinese Title (繁體中文)",
        "script": "Visual script for Veo/Kling (Traditional Chinese)",
        "tags": "#Tag1 #Tag2 #AI",
        "keywords": "Key1, Key2"
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
st.title("🎯 Shorts 獵手 (完美修復版)")

if not keys["gemini"] or not keys["youtube"]:
    st.warning("⚠️ 請檢查 Secrets 設定")
else:
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
                    if st.button("✨ AI 寫二創腳本"):
                        if not selected_model:
                            st.error("請先在左側選擇 AI 模型")
                        else:
                            with st.spinner(f"AI ({selected_model}) 正在思考..."):
                                ai_data = generate_content_with_model(
                                    selected['title'], selected['desc'], 
                                    keys['gemini'], selected_model
                                )
                                
                                if "error" not in ai_data:
                                    st.session_state.ai_title = ai_data.get('new_title', selected['title'])
                                    st.session_state.ai_script = ai_data.get('script', '')
                                    st.session_state.ai_tags = ai_data.get('tags', '')
                                    st.session_state.ai_keywords = ai_data.get('keywords', '')
                                    st.success("✅ 生成完畢！")
                                    st.rerun()
                                else:
                                    st.error(f"生成失敗: {ai_data['error']}")

                # 表單
                new_title = st.text_input("影片標題", key="ai_title")
                c1, c2 = st.columns(2)
                with c1:
                    tags_input = st.text_area("標籤", key="ai_tags")
                with c2:
                    kw_input = st.text_area("關鍵字", key="ai_keywords")
                
                note_input = st.text_area("二創腳本", key="ai_script", height=200)
                
                st.markdown("---")
                if st.button("💾 存入 Google Sheet", type="primary"):
                    data = {
                        'url': selected['url'], 'title': new_title,
                        'keywords': kw_input, 'tags': tags_input, 'note': note_input
                    }
                    if save_to_sheet(data, keys['gcp_json']):
                        st.markdown('<div class="success-box">✅ 已存入雲端試算表</div>', unsafe_allow_html=True)
