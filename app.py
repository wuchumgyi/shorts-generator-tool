import streamlit as st
import google.generativeai as genai
from googleapiclient.discovery import build
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
import re

# --- 頁面設定 ---
st.set_page_config(page_title="Shorts 獵手 (試算表對應版)", page_icon="📊", layout="wide")
st.markdown("""
    <style>
    .stButton>button {width: 100%; border-radius: 8px; font-weight: bold;}
    .video-card {background-color: #f0f2f6; padding: 15px; border-radius: 10px; margin-bottom: 10px;}
    .success-box {padding: 10px; background-color: #d4edda; color: #155724; border-radius: 5px;}
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

# --- 2. 獲取可用模型 ---
@st.cache_resource
def get_valid_models(api_key):
    if not api_key: return []
    genai.configure(api_key=api_key)
    valid_models = []
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                valid_models.append(m.name)
    except:
        pass
    return valid_models

# --- 側邊欄設定 ---
with st.sidebar:
    st.header("⚙️ AI 模型設定")
    if keys["gemini"]:
        model_options = get_valid_models(keys["gemini"])
        if model_options:
            selected_model_name = st.selectbox("👇 選擇 AI 模型", model_options, index=0)
            st.success(f"目前使用：{selected_model_name}")
        else:
            st.error("❌ 無法抓取模型列表，請檢查 API Key 權限。")
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

# --- 5. AI 生成 (針對您的試算表格式優化) ---
def generate_content_for_sheet(title, desc, api_key, model_name):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    # ⚠️ Prompt 重點：
    # 1. 產生 Veo 和 Kling 兩種 Prompt
    # 2. 標題、腳本都要有中英文對照
    # 3. 標籤和留言強制英文
    prompt = f"""
    Video: {title}
    Desc: {desc}
    Task: Plan a "Derivative Work" (二創) for YouTube Shorts.
    
    REQUIREMENTS:
    1. 'veo_prompt' & 'kling_prompt': English ONLY. High detail.
    2. 'title_en', 'script_en', 'tags', 'comment': English ONLY.
    3. 'title_zh', 'script_zh': Traditional Chinese (繁體中文).
    4. Tags MUST include #AI.
    
    Output JSON ONLY:
    {{
        "title_en": "Catchy English Title",
        "title_zh": "吸睛中文標題",
        "veo_prompt": "Prompt for Google Veo (English)",
        "kling_prompt": "Prompt for Kling AI (English)",
        "script_en": "Visual script description (English)",
        "script_zh": "畫面分鏡描述 (繁體中文)",
        "tags": "#Tag1 #Tag2 #AI (English Only)",
        "comment": "Engaging first comment (English Only)"
    }}
    """
    try:
        response = model.generate_content(prompt)
        return json.loads(clean_json_string(response.text))
    except Exception as e:
        return {"error": str(e)}

# --- 6. 存檔 (對應 10 個欄位) ---
def save_to_sheet(data, creds_dict):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("Shorts_Content_Planner").sheet1
        
        # 依照您提供的圖片 (image_057615.png) 順序排列：
        # A: 時間, B: 網址, C: 英文標題, D: 中文標題, E: Veo, F: Kling, G: 英文腳本, H: 中文腳本, I: 英文標籤, J: 英文留言
        row = [
            str(datetime.now())[:16],   # A: 時間
            data['url'],                # B: 來源網址
            data['title_en'],           # C: 英文標題
            data['title_zh'],           # D: 中文標題
            data['veo_prompt'],         # E: Veo Prompt
            data['kling_prompt'],       # F: Kling Prompt
            data['script_en'],          # G: 英文腳本
            data['script_zh'],          # H: 中文腳本
            data['tags'],               # I: 英文標籤
            data['comment']             # J: 英文留言
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"寫入失敗: {e}")
        return False

# --- 主介面 ---
st.title("🎯 Shorts 獵手 (試算表對應版)")

if not keys["gemini"]:
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
                        # 清空暫存
                        for key in ['ai_title_en', 'ai_title_zh', 'ai_script_en', 'ai_script_zh', 'ai_tags', 'ai_comment', 'ai_veo', 'ai_kling']:
                            if key in st.session_state: del st.session_state[key]
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
                    if st.button("✨ AI 生成全套資料 (自動存檔)"):
                        if not selected_model_name:
                            st.error("請先選擇 AI 模型")
                        else:
                            with st.spinner(f"AI ({selected_model_name}) 正在生成並寫入..."):
                                ai_data = generate_content_for_sheet(
                                    selected['title'], selected['desc'], 
                                    keys['gemini'], selected_model_name
                                )
                                
                                if "error" not in ai_data:
                                    # 1. 存入 Session State 以便顯示
                                    st.session_state.ai_title_en = ai_data.get('title_en', '')
                                    st.session_state.ai_title_zh = ai_data.get('title_zh', '')
                                    st.session_state.ai_veo = ai_data.get('veo_prompt', '')
                                    st.session_state.ai_kling = ai_data.get('kling_prompt', '')
                                    st.session_state.ai_script_en = ai_data.get('script_en', '')
                                    st.session_state.ai_script_zh = ai_data.get('script_zh', '')
                                    st.session_state.ai_tags = ai_data.get('tags', '')
                                    st.session_state.ai_comment = ai_data.get('comment', '')
                                    
                                    # 2. 自動存檔
                                    data_to_save = {
                                        'url': selected['url'],
                                        'title_en': ai_data.get('title_en', ''),
                                        'title_zh': ai_data.get('title_zh', ''),
                                        'veo_prompt': ai_data.get('veo_prompt', ''),
                                        'kling_prompt': ai_data.get('kling_prompt', ''),
                                        'script_en': ai_data.get('script_en', ''),
                                        'script_zh': ai_data.get('script_zh', ''),
                                        'tags': ai_data.get('tags', ''),
                                        'comment': ai_data.get('comment', '')
                                    }
                                    if save_to_sheet(data_to_save, keys['gcp_json']):
                                        st.success("✅ 成功！資料已寫入 Google Sheet！")
                                        st.rerun()
                                else:
                                    st.error(f"生成失敗: {ai_data['error']}")

                # 顯示結果 (使用 expander 收納，讓畫面乾淨)
                if 'ai_title_en' in st.session_state:
                    with st.expander("👀 查看生成內容 (可手動修改後再次存檔)", expanded=True):
                        c1, c2 = st.columns(2)
                        with c1:
                            t_en = st.text_input("英文標題", key="ai_title_en")
                            s_en = st.text_area("英文腳本", key="ai_script_en")
                            veo = st.text_area("Veo Prompt", key="ai_veo")
                        with c2:
                            t_zh = st.text_input("中文標題", key="ai_title_zh")
                            s_zh = st.text_area("中文腳本", key="ai_script_zh")
                            kling = st.text_area("Kling Prompt", key="ai_kling")
                        
                        tags = st.text_area("英文標籤", key="ai_tags")
                        comm = st.text_input("英文留言", key="ai_comment")

                        if st.button("💾 手動更新存檔"):
                            data = {
                                'url': selected['url'],
                                'title_en': t_en, 'title_zh': t_zh,
                                'veo_prompt': veo, 'kling_prompt': kling,
                                'script_en': s_en, 'script_zh': s_zh,
                                'tags': tags, 'comment': comm
                            }
                            if save_to_sheet(data, keys['gcp_json']):
                                st.success("✅ 更新成功！")
