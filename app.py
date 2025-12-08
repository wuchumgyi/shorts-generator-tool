import streamlit as st
import google.generativeai as genai
from googleapiclient.discovery import build
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
import re

# --- 頁面設定 ---
st.set_page_config(page_title="Shorts 獵手 (穩定版)", page_icon="🎯", layout="wide")
st.markdown("""
    <style>
    .stButton>button {width: 100%; border-radius: 8px; font-weight: bold;}
    .video-card {background-color: #f0f2f6; padding: 15px; border-radius: 10px; margin-bottom: 10px;}
    .success-box {padding: 1rem; background-color: #d4edda; color: #155724; border-radius: 5px; margin-bottom: 1rem;}
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

# --- 4. AI 生成功能 (改用 gemini-pro) ---
def generate_derivative_content(title, desc, api_key):
    """生成二創腳本與標籤"""
    genai.configure(api_key=api_key)
    
    # ⚠️ 修正點：改回最通用的 'gemini-pro'，解決 404 錯誤
    model = genai.GenerativeModel("gemini-pro")
    
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

# --- 5. 存檔邏輯 ---
def save_to_sheet(data, creds_dict):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("Shorts_Content_Planner").sheet1
        
        # 欄位順序：時間 | 網址 | 標題 | 關鍵字 | 標籤 | 腳本筆記
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
st.title("🎯 Shorts 獵手 (自動存檔版)")
keys = get_keys()

if not keys:
    st.warning("⚠️ 請先設定 Secrets")
else:
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
                        # 重置暫存
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

        # 左側：影片列表
        with col_list:
            st.markdown("### 📺 影片列表")
            for vid in st.session_state.search_results:
                if st.button(f"📄 {vid['title'][:15]}...", key=vid['id']):
                    st.session_state.selected_video = vid
                    # 切換時重置
                    st.session_state.ai_title = vid['title']
                    st.session_state.ai_script = ""
                    st.session_state.ai_tags = ""
                    st.session_state.ai_keywords = ""
                    st.rerun()

        # 右側：編輯詳情
        with col_detail:
            selected = st.session_state.get('selected_video')
            if selected:
                st.subheader("📝 編輯與存檔")
                
                # 顯示影片
                st.video(selected['url'])
                st.caption(f"來源: {selected['channel']} | [開啟連結]({selected['url']})")

                st.markdown("---")

                # --- AI 功能區 (按鈕觸發 + 自動存檔) ---
                col_ai_btn, _ = st.columns([1, 1])
                with col_ai_btn:
                    # 這邊按鈕按下後，會執行：生成 -> 填入 -> 存檔
                    if st.button("✨ AI 生成並自動存檔"):
                        with st.spinner("AI 正在思考並寫入試算表..."):
                            ai_data = generate_derivative_content(selected['title'], selected['desc'], keys['gemini'])
                            
                            if "error" not in ai_data:
                                # 1. 更新介面顯示
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
                                    st.rerun() # 刷新頁面顯示結果
                            else:
                                st.error(f"AI 生成失敗: {ai_data['error']}")

                # --- 編輯表單 (顯示結果用，也可手動再改) ---
                new_title = st.text_input("影片標題", key="ai_title")
                
                c_tag, c_kw = st.columns(2)
                with c_tag:
                    tags_input = st.text_area("標籤 (Tags)", key="ai_tags")
                with c_kw:
                    kw_input = st.text_area("關鍵字 (Keywords)", key="ai_keywords")
                
                # 腳本區域
                note_input = st.text_area("二創腳本 / 筆記", key="ai_script", height=200)
                
                # 雖然有自動存檔，保留這個按鈕讓使用者手動修改後再次儲存
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
