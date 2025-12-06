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
st.set_page_config(page_title="Shorts 靈感生成器", page_icon="🧘", layout="centered")

# --- CSS 優化手機體驗 (按鈕與輸入框優化) ---
st.markdown("""
    <style>
    .stButton>button {width: 100%; border-radius: 20px; font-weight: bold;}
    .stTextInput>div>div>input {border-radius: 10px;}
    </style>
    """, unsafe_allow_html=True)

# --- 函式庫 ---

def get_keys():
    """從 Secrets 讀取金鑰"""
    try:
        return {
            "gemini": st.secrets["GEMINI_API_KEY"],
            "youtube": st.secrets["YOUTUBE_API_KEY"],
            "gcp_json": dict(st.secrets["gcp_service_account"])
        }
    except Exception:
        return None

def extract_video_id(url):
    """提取 YouTube ID"""
    regex = r"(?:v=|\/shorts\/|\/)([0-9A-Za-z_-]{11}).*"
    match = re.search(regex, url)
    return match.group(1) if match else None

def search_trending_video(api_key):
    """功能 A: 自動搜尋熱門紓壓影片"""
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        # 搜尋關鍵字：Oddly Satisfying, Stress Relief
        search_response = youtube.search().list(
            q="Oddly Satisfying Shorts",
            type="video",
            part="id,snippet",
            maxResults=20, # 抓前20名來隨機挑
            order="viewCount", 
            videoDuration="short"
        ).execute()

        items = search_response.get("items", [])
        if not items:
            return None
        
        # 隨機選一個，讓每次結果不同
        selected_video = random.choice(items)
        video_id = selected_video["id"]["videoId"]
        return f"https://www.youtube.com/shorts/{video_id}"
    except Exception as e:
        st.error(f"搜尋功能暫時無法使用: {e}")
        return None

def get_video_info(video_id, api_key):
    """獲取影片詳細數據"""
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
        st.error(f"YouTube 讀取失敗: {e}")
        return None

def generate_script(video_data, api_key):
    """Gemini 生成腳本"""
    genai.configure(api_key=api_key)
    # 使用 1.5 Flash 模型
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = f"""
    參考影片: {video_data['title']}
    頻道: {video_data['channel']}
    描述片段: {video_data['desc'][:200]}
    
    任務：
    這是一支熱門的紓壓影片。請分析它的亮點，並以此為靈感，創作一個「二創」的 9 秒 Shorts 企劃。
    
    請直接回傳 JSON 格式 (不要 Markdown):
    {{
        "analysis": "簡短分析：這支影片為什麼看起來很爽？(中文)",
        "veo_prompt": "英文 Prompt (給 Google Veo 用)，包含 photorealistic, 4k, cinematic lighting, slow motion, extreme close-up, 描述該物理現象",
        "title": "中文標題 (包含 Emoji, 吸引點擊)",
        "script": "9秒鐘的畫面分鏡與腳本 (中文)",
        "tags": "#Tag1 #Tag2 (給出 5 個相關標籤)",
        "comment": "一則會引起互動的置頂留言"
    }}
    """
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        st.error(f"AI 生成失敗: {e}")
        return None

def save_to_sheet(data, creds_dict, ref_url):
    """存入 Google Sheet"""
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("Shorts_Content_Planner").sheet1
        row = [
            str(datetime.now())[:16],
            data['title'],
            data['veo_prompt'],
            data['script'],
            data['tags'],
            data['comment'],
            "未發布",
            ref_url
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"儲存失敗: {e}")
        return False

# --- 主介面邏輯 ---

st.title("🧘 Shorts 自動化靈感庫")
keys = get_keys()

if not keys:
    st.warning("⚠️ 請先設定 Secrets")
else:
    # 1. 這是「自動搜尋按鈕」
    # 放在 Form 外面，點擊後會刷新頁面並把網址存入 session_state
    st.markdown("### 第一步：選擇影片來源")
    col1, col2 = st.columns([1, 1])
    
    with col1:
        if st.button("🎲 隨機搜熱門影片"):
            with st.spinner("🔍 正在 YouTube 尋找靈感..."):
                found_url = search_trending_video(keys['youtube'])
                if found_url:
                    st.session_state['auto_url'] = found_url
                    st.success("找到影片了！請按下方生成")
    
    # 2. 這是「主要的輸入區」
    # 如果剛剛有點自動搜尋，這裡就會自動填入網址；如果沒有，您可以自己貼
    with st.form("main_form"):
        # 讀取自動搜尋的結果，如果沒有則為空
        default_val = st.session_state.get('auto_url', "")
        
        # 這裡就是您要求的「手動輸入功能」，它和自動填入共用同一個框
        url_input = st.text_input("👇 影片網址 (自動填入或手動貼上)", value=default_val)
        
        st.markdown("### 第二步：AI 生成")
        submit = st.form_submit_button("✨ 開始分析與生成腳本")
    
    # 3. 執行生成邏輯
    if submit and url_input:
        vid = extract_video_id(url_input)
        if not vid:
            st.error("❌ 無效的網址，請確認連結正確")
        else:
            # A. 抓取影片資訊
            with st.spinner("📊 正在分析影片數據..."):
                v_info = get_video_info(vid, keys['youtube'])
            
            if v_info:
                st.info(f"正在參考：{v_info['title']} (觀看數：{v_info['views']})")
                
                # B. AI 生成腳本
                with st.spinner("🧠 Gemini 正在撰寫 Veo 提示詞..."):
                    result = generate_script(v_info, keys['gemini'])
                
                if result:
                    st.success("🎉 生成成功！")
                    st.divider()
                    
                    # C. 顯示結果
                    st.caption("💡 爆紅分析")
                    st.info(result.get('analysis'))

                    st.subheader("🇺🇸 Veo Prompt (英文)")
                    st.code(result['veo_prompt'], language="text")
                    st.caption("複製上方文字到 Google Veo 或 Sora")
                    
                    st.subheader("🇹🇼 中文腳本資料")
                    st.text_input("標題", value=result['title'])
                    st.text_area("腳本畫面", value=result['script'])
                    st.text_area("標籤", value=result['tags'])
                    st.text_area("留言", value=result['comment'])

                    # 暫存結果以便存檔
                    st.session_state['result_to_save'] = result
                    st.session_state['url_to_save'] = url_input

    # 4. 存檔按鈕 (獨立出來避免誤觸)
    if 'result_to_save' in st.session_state:
        st.markdown("---")
        if st.button("💾 將此結果存入 Google Sheet"):
            with st.spinner("寫入中..."):
                ok = save_to_sheet(
                    st.session_state['result_to_save'], 
                    keys['gcp_json'], 
                    st.session_state['url_to_save']
                )
                if ok:
                    st.success("✅ 資料已安全儲存！")
