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
st.set_page_config(page_title="Shorts 終極生成器 (盲測版)", page_icon="💎", layout="centered")
st.markdown("""
    <style>
    .stButton>button {width: 100%; border-radius: 20px; font-weight: bold;}
    .stTextInput>div>div>input {border-radius: 10px;}
    .success-box {padding: 1rem; background-color: #d4edda; color: #155724; border-radius: 10px; margin-bottom: 1rem;}
    .warning-box {padding: 1rem; background-color: #fff3cd; color: #856404; border-radius: 10px; margin-bottom: 1rem;}
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

# --- 2. 核心工具函式 ---
def extract_video_id(url):
    regex = r"(?:v=|\/shorts\/|\/)([0-9A-Za-z_-]{11}).*"
    match = re.search(regex, url)
    return match.group(1) if match else None

def clean_json_string(text):
    text = text.replace("```json", "").replace("```", "")
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        text = text[start:end+1]
    return text.strip()

# --- 3. 搜尋與資訊獲取 ---
def search_trending_video(api_key):
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        # 搜尋關鍵字優化：加上 4k, satisfying 以確保素材品質
        search_response = youtube.search().list(
            q="Satisfying 4k Shorts",
            type="video",
            part="id,snippet",
            maxResults=30,
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
        st.error(f"YouTube 錯誤: {e}")
        return None

# --- 4. AI 生成邏輯 (盲測 + 強制重試) ---
# 這個版本完全不去問 Google 有哪些模型，直接拿我們指定的清單去撞，省流量
def generate_script_blindly(video_data, api_key):
    genai.configure(api_key=api_key)
    
    # 這是我們要嘗試的模型清單，按優先順序排列
    # 1. 優先試 Gemini 2.0 Flash (最新最強)
    # 2. 如果不行，試 Gemini 1.5 Flash (最穩)
    # 3. 最後保底 Gemini 1.5 Pro
    models_to_try = ["gemini-2.0-flash-exp", "gemini-1.5-flash", "gemini-1.5-pro"]
    
    prompt = f"""
    Video Title: {video_data['title']}
    Channel: {video_data['channel']}
    
    Task: Create a high-quality, viral 9-second Short plan.
    
    CRITICAL VISUAL INSTRUCTIONS (To fix "Abrupt" transitions):
    1. The 'veo_prompt' MUST describe a CONTINUOUS ACTION (One-shot).
    2. Focus on the PROCESS. Use words like "gradual transformation", "flowing", "slowly revealing".
    3. DO NOT use "Before" and "After" logic. Describe the boundary moving.
    
    DATA REQUIREMENTS:
    1. 'veo_prompt': Optimized for Google Veo (Smooth motion, photorealistic, 4k).
    2. 'kling_prompt': Optimized for Kling AI (Keywords: "8k, raw style, best quality, cinema lighting").
    3. 'script_en', 'tags', 'comment' MUST be in ENGLISH.
    4. 'script_zh', 'title_zh' MUST be in TRADITIONAL CHINESE (繁體中文).
    5. 'tags' MUST include #AI. NO tool names (#Veo, #Kling, #Sora).
    
    Output JSON ONLY:
    {{
        "title_en": "English Title",
        "title_zh": "中文標題",
        "veo_prompt": "Prompt for Veo (English)",
        "kling_prompt": "Prompt for Kling (English)",
        "script_en": "9-sec script (English)",
        "script_zh": "9秒畫面描述 (繁體中文)",
        "tags": "#Tag1 #Tag2 #AI",
        "comment": "Comment"
    }}
    """
    
    # --- 雙層迴圈：遍歷模型 -> 處理重試 ---
    for model_name in models_to_try:
        # 針對當前模型，最多試 3 次 (處理 429 錯誤)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 直接建立模型，不浪費額度去檢查是否存在
                model = genai.GenerativeModel(model_name)
                
                # 只在第一次嘗試時顯示提示
                if attempt == 0:
                    st.toast(f"🤖 正在嘗試模型：{model_name} ...")
                
                response = model.generate_content(prompt)
                result = json.loads(clean_json_string(response.text))
                
                # 標籤清洗
                raw_tags = result.get('tags', '')
                tag_list = re.findall(r"#\w+", raw_tags)
                blacklist = ['#veo', '#sora', '#gemini', '#kling', '#klingai', '#googleveo', '#openai']
                clean_tags = [t for t in tag_list if t.lower() not in blacklist]
                if not any(t.lower() == '#ai' for t in clean_tags): clean_tags.append("#AI")
                result['tags'] = " ".join(clean_tags)
                
                return result, model_name # 成功！直接回傳

            except Exception as e:
                error_msg = str(e)
                
                # 狀況 A: 404 (找不到模型 / 帳號不支援)
                # 直接跳出內層迴圈，換下一個模型試試，不要在這裡浪費時間重試
                if "404" in error_msg or "not found" in error_msg.lower():
                    # st.warning(f"{model_name} 暫不可用，切換下一模型...")
                    break 

                # 狀況 B: 429 (速度太快) -> 等待並在原地重試
                if "429" in error_msg or "quota" in error_msg.lower():
                    wait_seconds = 25 # 等待 25 秒
                    st.markdown(f"""
                    <div class="warning-box">
                    <b>⏳ Google 叫我們休息一下 (429 Error)</b><br>
                    模型 {model_name} 請求過快。自動冷卻 {wait_seconds} 秒後重試...
                    </div>
                    """, unsafe_allow_html=True)
                    time.sleep(wait_seconds)
                    continue # 繼續下一次 attempt (原地重試)
                
                # 其他錯誤 (例如 500 伺服器錯誤)
                st.error(f"發生未知錯誤 ({model_name}): {e}")
                break
                
    st.error("❌ 所有模型都嘗試失敗。請確認 API Key 正確，或稍後再試。")
    return None, None

# --- 5. 存檔邏輯 ---
def save_to_sheet_auto(data, creds_dict, ref_url):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("Shorts_Content_Planner").sheet1
        
        row = [
            str(datetime.now())[:16],
            ref_url,
            data.get('title_en', ''),
            data.get('title_zh', ''),
            data.get('veo_prompt', ''),
            data.get('kling_prompt', ''),
            data.get('script_en', ''),
            data.get('script_zh', ''),
            str(data.get('tags', '')),
            data.get('comment', '')
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"寫入失敗: {e}")
        return False

# --- 主介面 ---
st.title("💎 Shorts 終極生成器")
keys = get_keys()

if not keys:
    st.warning("⚠️ 請先設定 Secrets")
else:
    # 步驟 1
    st.markdown("### 步驟 1: 選擇來源")
    col1, col2 = st.columns([1, 1.5])
    with col1:
        if st.button("🎲 隨機搜熱門影片"):
            with st.spinner("🔍 正在 YouTube 挖掘熱門短片..."):
                found_url = search_trending_video(keys['youtube'])
                if found_url:
                    st.session_state['auto_url'] = found_url
                    st.success("已找到！請在下方確認並生成")

    # 步驟 2
    default_val = st.session_state.get('auto_url', "")
    url_input = st.text_input("👇 影片網址 (手動貼上 或 按上方搜尋)", value=default_val)
    
    st.markdown("### 步驟 2: AI 生成與存檔")
    if st.button("✨ 生成高品質腳本並存檔", type="primary"):
        if not url_input:
            st.warning("請先輸入網址")
        else:
            vid = extract_video_id(url_input)
            if vid:
                with st.spinner("1/3 分析影片中..."):
                    v_info = get_video_info(vid, keys['youtube'])
                
                if v_info:
                    with st.spinner("2/3 AI 正在撰寫 (直接盲測模型，不浪費額度)..."):
                        result, used_model = generate_script_blindly(v_info, keys['gemini'])
                    
                    if result:
                        with st.spinner("3/3 存檔中..."):
                            saved = save_to_sheet_auto(result, keys['gcp_json'], url_input)
                        
                        if saved:
                            st.markdown(f"""
                            <div class="success-box">
                                <h3>✅ 成功！(使用模型: {used_model})</h3>
                                <p><strong>中文標題:</strong> {result['title_zh']}</p>
                            </div>
                            """, unsafe_allow_html=True)
                            
                            st.divider()
                            c1, c2 = st.columns(2)
                            with c1:
                                st.subheader("🇺🇸 Google Veo")
                                st.code(result['veo_prompt'], language="text")
                            with c2:
                                st.subheader("🇨🇳 Kling AI")
                                st.code(result['kling_prompt'], language="text")
                                
                            st.caption("Common Script: " + result['script_zh'])
