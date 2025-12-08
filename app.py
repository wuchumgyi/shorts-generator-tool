import streamlit as st
import google.generativeai as genai
from googleapiclient.discovery import build
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
import re

# --- 頁面設定 ---
st.set_page_config(page_title="Shorts 獵手 (影音預覽版)", page_icon="📺", layout="wide")
st.markdown("""
    <style>
    .stButton>button {width: 100%; border-radius: 8px; font-weight: bold;}
    .video-card {background-color: #f0f2f6; padding: 15px; border-radius: 10px; margin-bottom: 10px;}
    .success-box {padding: 10px; background-color: #d4edda; color: #155724; border-radius: 5px;}
    /* 讓左側列表的影片標題好看一點 */
    .video-title {font-size: 16px; font-weight: bold; margin-bottom: 5px;}
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

# --- 5. AI 生成 (二創指令) ---
def generate_creative_content(title, desc, api_key, model_name):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    prompt = f"""
    Source Video Title: {title}
    Source Description: {desc}
    
    Task: Create a plan for a NEW, ORIGINAL 9-second YouTube Short inspired by this source (Derivative Work/二創).
    
    CRITICAL INSTRUCTIONS:
    1. **NO Timecodes:** The script MUST be a single, continuous paragraph describing the flow of the 9-second video.
    2. **Be Creative:** Extract the satisfying element but CHANGE the object or material.
    3. **Language:** - 'veo_prompt', 'kling_prompt', 'script_en', 'tags', 'comment': English ONLY.
       - 'title_zh', 'script_zh': Traditional Chinese (繁體中文).
    
    Output JSON ONLY:
    {{
        "title_en": "Catchy English Title",
        "title_zh": "吸睛中文標題",
        "veo_prompt": "Prompt for Veo (English, continuous shot)",
        "kling_prompt": "Prompt for Kling (English, 8k realism)",
        "script_en": "9-sec visual flow description (English, No timecodes)",
        "script_zh": "9秒連貫畫面描述 (繁體中文, 無分鏡秒數)",
        "tags": "#Tag1 #Tag2 #AI",
        "comment": "Comment (English)"
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
            data['title_en'],
            data['title_zh'],
            data['veo_prompt'],
            data['kling_prompt'],
            data['script_en'],
            data['script_zh'],
            data['tags'],
            data['comment']
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"寫入失敗: {e}")
        return False

# --- 主介面 ---
st.title("📺 Shorts 獵手 (影音預覽版)")

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
        col_list, col_detail = st.columns([1.2, 2]) # 調整比例，讓左邊寬一點放播放器

        # --- 左側：搜尋結果 (影音預覽) ---
        with col_list:
            st.markdown("### 📋 搜尋結果 (可直接播放)")
            for vid in st.session_state.search_results:
                with st.container():
                    # 1. 標題與連結
                    st.markdown(f"**[{vid['title']}]({vid['url']})**")
                    
                    # 2. 影片預覽 (直接嵌入)
                    st.video(vid['url'])
                    
                    # 3. 選取按鈕
                    if st.button(f"👉 選這部 ({vid['channel']})", key=vid['id']):
                        st.session_state.selected_video = vid
                        # 切換時清空 AI 暫存
                        for key in ['ai_title_en', 'ai_title_zh', 'ai_script_en', 'ai_script_zh', 'ai_tags', 'ai_comment', 'ai_veo', 'ai_kling']:
                            if key in st.session_state: del st.session_state[key]
                        st.rerun()
                    st.divider()

        # --- 右側：編輯詳情 ---
        with col_detail:
            selected = st.session_state.get('selected_video')
            if selected:
                # 為了方便對照，這裡也可以放一個小的播放器或連結
                st.info(f"✅ 當前選中：{selected['title']}")
                st.markdown(f"🔗 **原始連結：** [{selected['url']}]({selected['url']})")
                
                st.markdown("---")

                # AI 按鈕
                col_btn, _ = st.columns([1, 1])
                with col_btn:
                    if st.button("✨ AI 生成二創腳本 (自動存檔)", type="primary"):
                        if not selected_model_name:
                            st.error("請先選擇 AI 模型")
                        else:
                            with st.spinner(f"AI ({selected_model_name}) 正在構思..."):
                                ai_data = generate_creative_content(
                                    selected['title'], selected['desc'], 
                                    keys['gemini'], selected_model_name
                                )
                                
                                if "error" not in ai_data:
                                    # 存入 Session State
                                    st.session_state.ai_title_en = ai_data.get('title_en', '')
                                    st.session_state.ai_title_zh = ai_data.get('title_zh', '')
                                    st.session_state.ai_veo = ai_data.get('veo_prompt', '')
                                    st.session_state.ai_kling = ai_data.get('kling_prompt', '')
                                    st.session_state.ai_script_en = ai_data.get('script_en', '')
                                    st.session_state.ai_script_zh = ai_data.get('script_zh', '')
                                    st.session_state.ai_tags = ai_data.get('tags', '')
                                    st.session_state.ai_comment = ai_data.get('comment', '')
                                    
                                    # 自動存檔
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
                                        st.success("✅ 成功！原創腳本已生成並存檔！")
                                        st.rerun()
                                else:
                                    st.error(f"生成失敗: {ai_data['error']}")

                # 顯示結果
                if 'ai_title_en' in st.session_state:
                    with st.expander("👀 查看/修改 生成內容", expanded=True):
                        c1, c2 = st.columns(2)
                        with c1:
                            t_en = st.text_input("英文標題", key="ai_title_en")
                            s_en = st.text_area("英文腳本 (無分鏡)", key="ai_script_en", height=150)
                            veo = st.text_area("Veo Prompt", key="ai_veo")
                        with c2:
                            t_zh = st.text_input("中文標題", key="ai_title_zh")
                            s_zh = st.text_area("中文腳本 (流暢敘述)", key="ai_script_zh", height=150)
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
                                st.success("✅ 資料已更新！")
