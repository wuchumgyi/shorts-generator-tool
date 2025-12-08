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
st.set_page_config(page_title="YouTube Shorts 獵手", page_icon="🎯", layout="wide")
st.markdown("""
    <style>
    .stButton>button {width: 100%; border-radius: 8px; font-weight: bold;}
    .reportview-container .main .block-container {padding-top: 2rem;}
    .video-container {border-radius: 15px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1);}
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

# --- 3. YouTube 搜尋功能 (核心) ---
def search_videos(api_key, keyword, max_results=5):
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        # 搜尋特定的關鍵字
        search_response = youtube.search().list(
            q=keyword,
            type="video",
            part="id,snippet",
            maxResults=max_results,
            order="viewCount", # 找觀看數最高的 (熱門)
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
                'channel': item['snippet']['channelTitle']
            })
        return videos
    except Exception as e:
        st.error(f"搜尋失敗: {e}")
        return []

def get_video_details(api_key, video_id):
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        response = youtube.videos().list(part="snippet,statistics", id=video_id).execute()
        if not response['items']: return None
        return response['items'][0]['snippet']
    except:
        return None

# --- 4. AI 輔助功能 (改為按需觸發) ---
def generate_tags_and_keywords(title, desc, api_key):
    """只生成標籤和關鍵字，負擔小，速度快"""
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    
    prompt = f"""
    Video: {title}
    Desc: {desc}
    Task: Generate 10 relevant viral hashtags and 5 SEO keywords for a YouTube Short.
    Output JSON: {{ "tags": "#Tag1 #Tag2...", "keywords": "Key1, Key2..." }}
    """
    try:
        response = model.generate_content(prompt)
        return json.loads(clean_json_string(response.text))
    except:
        return {"tags": "", "keywords": ""}

# --- 5. 存檔邏輯 ---
def save_to_sheet(data, creds_dict):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("Shorts_Content_Planner").sheet1
        
        # 欄位：時間 | 網址 | 標題 | 關鍵字 | 標籤 | 筆記/腳本
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
st.title("🎯 YouTube Shorts 獵手")
keys = get_keys()

if not keys:
    st.warning("⚠️ 請先設定 Secrets")
else:
    # --- 搜尋區塊 ---
    with st.container():
        c1, c2 = st.columns([3, 1])
        with c1:
            keyword = st.text_input("🔍 輸入關鍵字 (例如: 貓咪, 紓壓, 甚至特定產品)", value="Oddly Satisfying")
        with c2:
            st.write("") # Spacer
            st.write("") # Spacer
            search_btn = st.button("開始搜尋", type="primary")

    # 初始化 Session State
    if 'search_results' not in st.session_state:
        st.session_state.search_results = []
    if 'selected_video' not in st.session_state:
        st.session_state.selected_video = None

    # 執行搜尋
    if search_btn and keyword:
        with st.spinner(f"正在尋找關於「{keyword}」的熱門短影音..."):
            results = search_videos(keys['youtube'], keyword)
            if results:
                st.session_state.search_results = results
                st.session_state.selected_video = results[0] # 預設選第一個
            else:
                st.warning("找不到影片，請換個關鍵字試試。")

    # --- 顯示結果區塊 (左邊列表，右邊詳情) ---
    if st.session_state.search_results:
        st.divider()
        col_list, col_detail = st.columns([1, 2])

        # 左側：影片列表
        with col_list:
            st.subheader("📺 搜尋結果")
            for vid in st.session_state.search_results:
                # 每個影片做成一個按鈕，點了就換右邊的內容
                if st.button(f"▶ {vid['title'][:20]}...", key=vid['id']):
                    st.session_state.selected_video = vid

        # 右側：詳細資料與編輯
        with col_detail:
            selected = st.session_state.selected_video
            if selected:
                st.subheader("📝 編輯與存檔")
                
                # 1. 影片播放器
                st.video(selected['url'])
                st.caption(f"來源頻道: {selected['channel']} | [開啟連結]({selected['url']})")

                # 2. 編輯表單
                with st.form("edit_form"):
                    st.write("### 內容策劃")
                    
                    # 標題 (預設填入原標題，可修改)
                    new_title = st.text_input("影片標題", value=selected['title'])
                    
                    c_tag, c_kw = st.columns(2)
                    with c_tag:
                        # 這裡留空讓您自己填，或者按下面的 AI 按鈕來填
                        tags_input = st.text_area("標籤 (Tags)", placeholder="#Tag1 #Tag2...", key="tags_field")
                    with c_kw:
                        kw_input = st.text_area("關鍵字 (Keywords)", placeholder="Key1, Key2...", key="kw_field")
                    
                    note_input = st.text_area("筆記 / 二創腳本", placeholder="在這裡寫下您的想法或腳本...", height=150)
                    
                    # 存檔按鈕
                    save_submitted = st.form_submit_button("💾 存入 Google Sheet")
                    
                    if save_submitted:
                        data_to_save = {
                            'url': selected['url'],
                            'title': new_title,
                            'keywords': kw_input,
                            'tags': tags_input,
                            'note': note_input
                        }
                        if save_to_sheet(data_to_save, keys['gcp_json']):
                            st.success("✅ 資料已儲存！")

                # 3. AI 輔助按鈕 (放在表單外，避免誤觸提交)
                st.markdown("---")
                col_ai, _ = st.columns([1, 2])
                with col_ai:
                    if st.button("✨ AI 幫我想標籤"):
                        # 這裡才會消耗 Gemini 額度
                        try:
                            # 為了精準，我們再抓一次詳細描述
                            details = get_video_details(keys['youtube'], selected['id'])
                            desc = details['description'] if details else ""
                            
                            with st.spinner("AI 正在分析影片內容..."):
                                ai_data = generate_tags_and_keywords(selected['title'], desc, keys['gemini'])
                                
                                # 用 Toast 顯示結果，並讓使用者複製 (因為 Streamlit 限制，無法直接更新上方表單的值)
                                st.success("AI 生成完成！請複製下方內容：")
                                st.code(f"標籤：{ai_data.get('tags')}\n關鍵字：{ai_data.get('keywords')}", language="text")
                        except Exception as e:
                            st.error("AI 暫時忙碌，請稍後再試。")
