import streamlit as st
import google.generativeai as genai
from googleapiclient.discovery import build
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
import re

# --- 頁面設定 ---
st.set_page_config(page_title="Shorts 獵手 (自選模型版)", page_icon="🛠️", layout="wide")
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

# --- 2. 核心工具 ---
def clean_json_string(text):
    text = text.replace("```json", "").replace("```", "")
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        text = text[start:end+1]
    return text.strip()

# --- 3. YouTube 搜尋功能 ---
def search_videos(api_key, keyword, max_results=10):
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        search_response = youtube.search().list(
            q=keyword,
            type="video",
            part="id,snippet",
            maxResults=max_results,
            order="viewCount",
            videoDuration="short"
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

# --- 4. AI 生成功能 (動態模型) ---
def generate_derivative_content(title, desc, api_key, model_name):
    """使用使用者選定的模型生成內容"""
    genai.configure(api_key=api_key)
    
    # 使用使用者在側邊欄選擇的模型
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

# --- 5. 診斷功能 ---
def list_available_models(api_key):
    genai.configure(api_key=api_key)
    try:
        models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                models.append(m.name)
        return models
    except Exception as e:
        return [f"Error: {str(e)}"]

# --- 6. 存檔邏輯 ---
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
keys = get_keys()

# --- 側邊欄設定 ---
with st.sidebar:
    st.header("⚙️ 設定")
    st.info("如果遇到 404 錯誤，請在此切換模型嘗試。")
    
    # 讓使用者自己選模型
    selected_model = st.selectbox(
        "選擇 AI 模型",
        ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp", "gemini-pro"],
        index=0 # 預設選第一個
    )
    st.caption(f"當前使用: {selected_model}")

if not keys:
    st.warning("⚠️ 請先設定 Secrets")
else:
    # 建立分頁
    tab_search, tab_diag = st.tabs(["🎯 影片獵手", "🔧 系統診斷"])

    # === 分頁 1: 搜尋與生成 ===
    with tab_search:
        # --- 搜尋區塊 ---
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
                            st.session_state.ai_title = results[0]['title']
                            st.session_state.ai_script = ""
                            st.session_state.ai_tags = ""
                            st.session_state.ai_keywords = ""
                        else:
                            st.warning("找不到影片")

        # --- 內容區塊 ---
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
                    st.caption(f"來源: {selected['channel']} | [開啟連結]({selected['url']})")
                    st.markdown("---")

                    col_ai_btn, _ = st.columns([1, 1])
                    with col_ai_btn:
                        if st.button("✨ AI 幫我寫二創腳本"):
                            with st.spinner(f"正在呼叫 {selected_model}..."):
                                # 傳入使用者選定的模型
                                ai_data = generate_derivative_content(
                                    selected['title'], 
                                    selected['desc'], 
                                    keys['gemini'],
                                    selected_model
                                )
                                
                                if "error" not in ai_data:
                                    st.session_state.ai_title = ai_data.get('new_title', selected['title'])
                                    st.session_state.ai_script = ai_data.get('script', '')
                                    st.session_state.ai_tags = ai_data.get('tags', '')
                                    st.session_state.ai_keywords = ai_data.get('keywords', '')
                                    st.success("AI 生成完畢！")
                                    st.rerun()
                                else:
                                    st.error(f"AI 生成失敗: {ai_data['error']}")
                                    st.info("💡 建議：請到左側邊欄切換其他模型試試看！")

                    new_title = st.text_input("影片標題", key="ai_title")
                    
                    c_tag, c_kw = st.columns(2)
                    with c_tag:
                        tags_input = st.text_area("標籤 (Tags)", key="ai_tags")
                    with c_kw:
                        kw_input = st.text_area("關鍵字 (Keywords)", key="ai_keywords")
                    
                    note_input = st.text_area("二創腳本 / 筆記", key="ai_script", height=200)
                    
                    st.markdown("---")
                    
                    if st.button("💾 存入 Google Sheet", type="primary"):
                        data_to_save = {
                            'url': selected['url'],
                            'title': new_title,
                            'keywords': kw_input,
                            'tags': tags_input,
                            'note': note_input
                        }
                        with st.spinner("存檔中..."):
                            if save_to_sheet(data_to_save, keys['gcp_json']):
                                st.success("✅ 資料已成功儲存！")

    # === 分頁 2: 系統診斷 (專門用來解決 404 問題) ===
    with tab_diag:
        st.header("🔧 系統診斷")
        st.write("如果你一直遇到 404 錯誤，請按下方按鈕，看看你的 API Key 到底支援哪些模型。")
        
        if st.button("🔍 列出我能用的所有模型"):
            with st.spinner("正在查詢 Google API..."):
                available = list_available_models(keys['gemini'])
                st.write("### 查詢結果：")
                st.code(available)
                
                if "Error" in str(available):
                    st.error("❌ 無法連線到 Gemini API。")
                    st.warning("請檢查：\n1. Google Cloud Console 是否已啟用 'Generative Language API'？\n2. API Key 是否正確？")
                else:
                    st.success("✅ 連線成功！請從上面列表中挑選一個名字 (例如 models/gemini-1.5-flash)，去掉 'models/' 後，在左側邊欄選擇對應的模型。")
