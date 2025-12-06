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
st.markdown("""
    <style>
    .stButton>button {width: 100%; border-radius: 20px; font-weight: bold;}
    .stTextInput>div>div>input {border-radius: 10px;}
    </style>
    """, unsafe_allow_html=True)

# --- 函式庫 ---

def get_keys():
    try:
        return {
            "gemini": st.secrets["GEMINI_API_KEY"],
            "youtube": st.secrets["YOUTUBE_API_KEY"],
            "gcp_json": dict(st.secrets["gcp_service_account"])
        }
    except Exception:
        return None

def extract_video_id(url):
    regex = r"(?:v=|\/shorts\/|\/)([0-9A-Za-z_-]{11}).*"
    match = re.search(regex, url)
    return match.group(1) if match else None

def search_trending_video(api_key):
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        # 搜尋關鍵字：Oddly Satisfying, Stress Relief
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
        selected_video = random.choice(items)
        video_id = selected_video["id"]["videoId"]
        return f"https://www.youtube.com/shorts/{video_id}"
    except Exception as e:
        st.error(f"搜尋功能異常: {e}")
        return None

def get_video_info(video_id, api_key):
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
    genai.configure(api_key=api_key)
    
    # --- 關鍵修改：雙模型備援機制 ---
    # 優先嘗試免費且快速的 1.5 Flash
    model_name = 'gemini-1.5-flash'
    
    # 設定 Prompt：明確要求 Veo Prompt 為英文，腳本為中文
    prompt = f"""
    參考影片: {video_data['title']}
    頻道: {video_data['channel']}
    描述片段: {video_data['desc'][:200]}
    
    任務：
    這是一支熱門的紓壓影片。請分析它，並創作一個「二創」的 9 秒 Shorts 企劃。
    
    請直接回傳 JSON 格式 (嚴格遵守，不要 Markdown):
    {{
        "analysis": "中文分析：為什麼這支影片很紓壓？",
        "veo_prompt": "Detailed English prompt for Google Veo/Sora. MUST be in English. Include keywords like photorealistic, 4k, cinematic lighting, slow motion, satisfying texture.",
        "title": "中文標題 (包含 Emoji)",
        "script": "9秒鐘的畫面分鏡與腳本 (中文)",
        "tags": "#Tag1 #Tag2 (給出 5 個中英混合標籤)",
        "comment": "中文置頂留言"
    }}
    """
    
    try:
        # 嘗試使用新模型
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
    except Exception:
        # 如果失敗 (例如版本太舊)，自動切換回舊版模型
        st.warning("⚠️ 系統偵測到舊版環境，已自動切換至相容模式 (gemini-pro)。")
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content(prompt)

    try:
        text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        st.error(f"生成內容解析失敗: {e}")
        return None

def save_to_sheet(data, creds_dict, ref_url):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        # 請確認您的 Google Sheet 名稱完全一致
        sheet = client.open("Shorts_Content_Planner").sheet1
        
        row = [
            str(datetime.now())[:16],
            data['title'],      # 標題
            data['veo_prompt'], # 英文 Prompt (給 Veo 用)
            data['script'],     # 中文腳本
            data['tags'],       # 標籤
            data['comment'],    # 留言
            "未發布",
            ref_url             # 網址
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"儲存失敗 (請檢查 Sheet 名稱是否正確): {e}")
        return False

# --- 主介面邏輯 ---

st.title("🧘 Shorts 自動化靈感庫")
keys = get_keys()

if not keys:
    st.warning("⚠️ 請先設定 Secrets")
else:
    st.markdown("### 第一步：選擇影片來源")
    col1, col2 = st.columns([1, 1])
    
    with col1:
        if st.button("🎲 隨機搜熱門影片"):
            with st.spinner("🔍 正在 YouTube 尋找靈感..."):
                found_url = search_trending_video(keys['youtube'])
                if found_url:
                    st.session_state['auto_url'] = found_url
                    st.success("找到影片了！請按下方生成")
    
    with st.form("main_form"):
        default_val = st.session_state.get('auto_url', "")
        url_input = st.text_input("👇 影片網址 (自動填入或手動貼上)", value=default_val)
        
        st.markdown("### 第二步：AI 生成")
        submit = st.form_submit_button("✨ 開始分析與生成腳本")
    
    if submit and url_input:
        vid = extract_video_id(url_input)
        if not vid:
            st.error("❌ 無效的網址")
        else:
            with st.spinner("📊 分析影片與生成腳本中..."):
                v_info = get_video_info(vid, keys['youtube'])
                
                if v_info:
                    st.info(f"正在參考：{v_info['title']}")
                    result = generate_script(v_info, keys['gemini'])
                
                    if result:
                        st.success("🎉 生成成功！")
                        st.divider()
                        
                        st.caption("💡 爆紅分析")
                        st.info(result.get('analysis'))

                        st.subheader("🇺🇸 Veo Prompt (英文)")
                        st.code(result['veo_prompt'], language="text")
                        
                        c1, c2 = st.columns(2)
                        with c1:
                            st.subheader("標題")
                            st.write(result['title'])
                            st.subheader("腳本")
                            st.write(result['script'])
                        with c2:
                            st.subheader("標籤")
                            st.write(result['tags'])
                            st.subheader("留言")
                            st.write(result['comment'])

                        st.session_state['result_to_save'] = result
                        st.session_state['url_to_save'] = url_input

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
                    st.balloons()
