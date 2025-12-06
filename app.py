import streamlit as st
import google.generativeai as genai
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
import re

# --- 頁面設定 ---
st.set_page_config(page_title="免費版 Shorts 生成器", page_icon="🧘", layout="centered")

# --- CSS 優化手機體驗 ---
st.markdown("""
    <style>
    .stButton>button {width: 100%; border-radius: 20px;}
    .stTextInput>div>div>input {border-radius: 10px;}
    </style>
    """, unsafe_allow_html=True)

# --- 函式庫定義 ---

def get_keys():
    """安全地獲取金鑰"""
    try:
        # 優先從 Streamlit Cloud 的 Secrets 讀取
        return {
            "gemini": st.secrets["GEMINI_API_KEY"],
            "youtube": st.secrets["YOUTUBE_API_KEY"],
            "gcp_json": dict(st.secrets["gcp_service_account"])
        }
    except Exception:
        return None

def extract_video_id(url):
    """從網址提取 YouTube ID"""
    regex = r"(?:v=|\/shorts\/|\/)([0-9A-Za-z_-]{11}).*"
    match = re.search(regex, url)
    return match.group(1) if match else None

def get_video_info(video_id, api_key):
    """使用 YouTube Data API 獲取資訊 (免費配額)"""
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        response = youtube.videos().list(part="snippet,statistics", id=video_id).execute()
        
        if not response['items']: return None
        
        item = response['items'][0]
        return {
            "title": item['snippet']['title'],
            "desc": item['snippet']['description'],
            "tags": item['snippet'].get('tags', []),
            "views": item['statistics'].get('viewCount', 0)
        }
    except Exception as e:
        st.error(f"YouTube 讀取失敗: {e}")
        return None

def generate_script(video_data, api_key):
    """使用 Gemini 生成 Veo 提示詞與腳本 (免費版)"""
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = f"""
    參考影片: {video_data['title']}
    描述: {video_data['desc'][:150]}
    
    任務：以此為靈感，創作一個「紓壓 (Stress Relief)」類型的 9 秒 Shorts 影片企劃。
    需包含 Google Veo (AI 影片生成) 的英文提示詞，以及對應的中文文案。
    
    請直接回傳 JSON 格式 (不要 Markdown):
    {{
        "veo_prompt": "英文 Prompt，必須包含 photorealistic, 4k, cinematic lighting, slow motion, detailed texture, 描述一個極致紓壓的物理現象(如流體、切割、擠壓)",
        "title": "中文吸睛標題 (含 Emoji)",
        "script": "9秒鐘的畫面描述 (中文)",
        "tags": "#Tag1 #Tag2 (中英混合)",
        "comment": "置頂留言內容"
    }}
    """
    
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        st.error(f"AI 生成失敗: {e}")
        return None

def save_to_sheet(data, creds_dict):
    """寫入 Google Sheet"""
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
            "未發布"
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"儲存失敗: {e}")
        return False

# --- 主介面 ---

st.title("🧘 免費版 Shorts 策劃助手")
st.caption("Gemini AI + YouTube API + Google Sheets")

keys = get_keys()

if not keys:
    st.warning("⚠️ 請先在 Streamlit Cloud 設定 Secrets (API Keys)")
    st.markdown("如果是在本機測試，請建立 `.streamlit/secrets.toml` 檔案。")
else:
    with st.form("main_form"):
        url = st.text_input("貼上 YouTube 參考連結", placeholder="https://youtube.com/shorts/...")
        submit = st.form_submit_button("✨ AI 魔法生成")
    
    if submit and url:
        vid = extract_video_id(url)
        if not vid:
            st.error("無效的網址")
        else:
            with st.spinner("🔍 分析影片數據..."):
                v_info = get_video_info(vid, keys['youtube'])
            
            if v_info:
                st.info(f"參考來源: {v_info['title']} ({v_info['views']} 次觀看)")
                
                with st.spinner("🧠 正在撰寫 Veo 腳本..."):
                    result = generate_script(v_info, keys['gemini'])
                
                if result:
                    st.success("生成完成！")
                    
                    # 顯示區塊
                    st.subheader("🎬 Veo Prompt (英文)")
                    st.code(result['veo_prompt'], language="text")
                    
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown(f"**標題:** {result['title']}")
                        st.markdown(f"**腳本:** {result['script']}")
                    with c2:
                        st.markdown(f"**標籤:** {result['tags']}")
                        st.markdown(f"**留言:** {result['comment']}")
                    
                    # 暫存結果到 Session State 以便按鈕讀取
                    st.session_state['last_result'] = result

    # 獨立的儲存按鈕 (避免誤觸)
    if 'last_result' in st.session_state:
        st.markdown("---")
        if st.button("💾 存入 Google Sheet"):
            with st.spinner("儲存中..."):
                if save_to_sheet(st.session_state['last_result'], keys['gcp_json']):
                    st.success("✅ 已儲存！")