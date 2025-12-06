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
st.set_page_config(page_title="Shorts 靈感生成器 (穩定版)", page_icon="🧘", layout="centered")
st.markdown("""
    <style>
    .stButton>button {width: 100%; border-radius: 20px; font-weight: bold;}
    .stTextInput>div>div>input {border-radius: 10px;}
    .success-box {padding: 1rem; background-color: #d4edda; color: #155724; border-radius: 10px; margin-bottom: 1rem;}
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

# --- 2. 輔助函式 ---
def extract_video_id(url):
    regex = r"(?:v=|\/shorts\/|\/)([0-9A-Za-z_-]{11}).*"
    match = re.search(regex, url)
    return match.group(1) if match else None

def clean_json_string(text):
    """強力清洗 JSON 字串，避免 AI 廢話導致解析失敗"""
    # 移除 Markdown 標記
    text = text.replace("```json", "").replace("```", "")
    # 嘗試抓取第一個 { 到最後一個 } 之間的內容
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        text = text[start:end+1]
    return text.strip()

# --- 3. 核心功能 ---
def search_trending_video(api_key):
    """自動搜尋熱門影片"""
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        search_response = youtube.search().list(
            q="Oddly Satisfying Shorts",
            type="video",
            part="id,snippet",
            maxResults=20,
            order="viewCount", 
            videoDuration="short"
        ).execute()
        items = search_response.get("items", [])
        if not items: return None
        selected = random.choice(items)
        return f"https://www.youtube.com/shorts/{selected['id']['videoId']}"
    except Exception as e:
        st.error(f"搜尋失敗: {e}")
        return None

def get_video_info(video_id, api_key):
    """獲取影片資訊"""
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

def generate_script(video_data, api_key):
    """生成腳本 (使用 gemini-pro)"""
    genai.configure(api_key=api_key)
    
    # ⚠️ 強制使用 gemini-pro (最穩定，避免 404)
    model = genai.GenerativeModel('gemini-pro')
    
    prompt = f"""
    You are a professional video content strategist.
    Video Title: {video_data['title']}
    Channel: {video_data['channel']}
    
    Task: Create a plan for a NEW viral 9-second Short based on this inspiration.
    
    Please output ONLY a valid JSON object with the following fields:
    {{
        "analysis": "簡短中文分析：這支影片的紓壓點在哪？",
        "veo_prompt": "Detailed English prompt for Google Veo/Sora, photorealistic, 4k, cinematic lighting, slow motion",
        "title": "中文標題 (包含 Emoji)",
        "script": "9秒鐘的畫面分鏡與腳本 (中文)",
        "tags": "#Tag1 #Tag2 (5個中英混合標籤)",
        "comment": "中文置頂留言"
    }}
    Do not add any text outside the JSON.
    """
    
    try:
        response = model.generate_content(prompt)
        cleaned_text = clean_json_string(response.text)
        return json.loads(cleaned_text)
    except Exception as e:
        st.error(f"AI 生成異常: {e}")
        # 如果失敗，回傳一個空結構，避免程式當掉
        return None

def save_to_sheet_auto(data, creds_dict, ref_url):
    """自動存入 Google Sheet"""
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        # 開啟試算表
        try:
            sheet = client.open("Shorts_Content_Planner").sheet1
        except:
            st.error("找不到名為 'Shorts_Content_Planner' 的試算表，請確認名稱。")
            return False

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
        st.error(f"寫入試算表失敗: {e}")
        return False

# --- 主程式邏輯 ---
st.title("🧘 Shorts 靈感庫 (自動存檔版)")
keys = get_keys()

if not keys:
    st.warning("⚠️ 請先設定 Secrets")
else:
    # 1. 搜尋功能
    if st.button("🎲 隨機搜熱門影片"):
        with st.spinner("🔍 搜尋中..."):
            url = search_trending_video(keys['youtube'])
            if url:
                st.session_state['auto_url'] = url
                st.success("已找到熱門影片，請按下方生成！")

    # 2. 輸入與生成
    with st.form("main_form"):
        default_val = st.session_state.get('auto_url', "")
        url_input = st.text_input("YouTube 網址", value=default_val)
        submit = st.form_submit_button("✨ 生成並自動存檔")

    if submit and url_input:
        vid = extract_video_id(url_input)
        if not vid:
            st.error("網址無效")
        else:
            # A. 抓取資訊
            with st.spinner("1/3 分析影片數據..."):
                v_info = get_video_info(vid, keys['youtube'])
            
            if v_info:
                st.info(f"參考：{v_info['title']}")
                
                # B. AI 生成
                with st.spinner("2/3 AI 正在撰寫腳本 (Gemini Pro)..."):
                    result = generate_script(v_info, keys['gemini'])
                
                if result:
                    # C. 自動存檔
                    with st.spinner("3/3 正在寫入 Google Sheet..."):
                        saved = save_to_sheet_auto(result, keys['gcp_json'], url_input)
                    
                    if saved:
                        st.markdown(f"""
                        <div class="success-box">
                            <h3>✅ 生成成功且已存檔！</h3>
                            <p><strong>標題：</strong>{result['title']}</p>
                            <p><strong>Veo Prompt：</strong>{result['veo_prompt']}</p>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        # 顯示詳細資料供參考
                        with st.expander("查看完整腳本詳情"):
                            st.write("**腳本畫面：**", result['script'])
                            st.write("**標籤：**", result['tags'])
                            st.write("**留言：**", result['comment'])
                            st.write("**分析：**", result['analysis'])
                    else:
                        st.error("生成成功但存檔失敗，請檢查權限。")
