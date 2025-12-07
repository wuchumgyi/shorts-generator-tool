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
st.set_page_config(page_title="Shorts 雙引擎生成器", page_icon="⚔️", layout="centered")
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

def get_first_available_model(api_key):
    """嘗試獲取可用模型，優先使用 Flash，失敗則降級"""
    genai.configure(api_key=api_key)
    try:
        # 測試性建立模型物件，確認是否支援
        model = genai.GenerativeModel('gemini-1.5-flash')
        return 'gemini-1.5-flash'
    except:
        # 如果 Flash 不行，就回傳 Pro
        return "gemini-pro"

# --- 3. 搜尋與資訊獲取 ---
def search_trending_video(api_key):
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        search_response = youtube.search().list(
            q="Oddly Satisfying Shorts",
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

# --- 4. AI 生成邏輯 (含 Retry 機制) ---
def generate_script_with_retry(video_data, api_key):
    genai.configure(api_key=api_key)
    
    # 自動選擇模型
    model_name = get_first_available_model(api_key)
    st.info(f"🤖 使用模型：{model_name}")
    model = genai.GenerativeModel(model_name)
    
    prompt = f"""
    Video Title: {video_data['title']}
    Channel: {video_data['channel']}
    
    Task: Create a viral 9-second Short plan.
    
    CRITICAL VISUAL INSTRUCTIONS (For Smoothness):
    1. Describe a CONTINUOUS ACTION (One-shot).
    2. Focus on the PROCESS of changing/moving.
    3. Use keywords: "gradual transformation", "morphing", "flowing".
    4. NO "Before" and "After" separation.
    
    DATA REQUIREMENTS:
    1. 'veo_prompt': Optimized for Google Veo (Smooth motion focus).
    2. 'kling_prompt': Optimized for Kling AI (High fidelity focus, keywords: "8k resolution, photorealistic, raw style, cinema lighting").
    3. 'script_en', 'tags', 'comment' MUST be in ENGLISH.
    4. 'script_zh', 'title_zh' MUST be in TRADITIONAL CHINESE (繁體中文).
    5. 'tags' MUST include #AI. Do NOT use tool names (#Veo, #Kling, #Sora).
    
    Output JSON ONLY:
    {{
        "title_en": "Catchy English Title",
        "title_zh": "吸睛的繁體中文標題 (含Emoji)",
        "veo_prompt": "Prompt for Google Veo (English)",
        "kling_prompt": "Prompt for Kling AI (English)",
        "script_en": "9-second visual description (English)",
        "script_zh": "9秒畫面描述與分鏡 (繁體中文翻譯)",
        "tags": "#Tag1 #Tag2 #AI (English Only, NO model names)",
        "comment": "Engaging first comment (English Only)"
    }}
    """
    
    # --- Retry 迴圈 (最多試 3 次) ---
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            result = json.loads(clean_json_string(response.text))
            
            # 標籤過濾
            raw_tags = result.get('tags', '')
            tag_list = re.findall(r"#\w+", raw_tags)
            blacklist = ['#veo', '#sora', '#gemini', '#kling', '#klingai', '#googleveo', '#openai']
            
            clean_tags = []
            has_ai = False
            for tag in tag_list:
                lower_tag = tag.lower()
                if lower_tag in blacklist: continue
                if lower_tag == '#ai': has_ai = True
                clean_tags.append(tag)
            
            if not has_ai: clean_tags.append("#AI")
            result['tags'] = " ".join(clean_tags)
                 
            return result # 成功就回傳

        except Exception as e:
            error_msg = str(e)
            # 檢查是否為 Quota (429) 錯誤
            if "429" in error_msg or "quota" in error_msg.lower():
                wait_time = 60 # 等待 60 秒
                st.markdown(f"""
                <div class="warning-box">
                <b>⏳ 觸發免費版頻率限制 (429 Error)</b><br>
                正在自動等待 {wait_time} 秒後重試 (第 {attempt + 1}/{max_retries} 次)...
                </div>
                """, unsafe_allow_html=True)
                time.sleep(wait_time) # 程式暫停
            elif "404" in error_msg:
                st.warning("⚠️ 找不到指定模型，嘗試切換至 gemini-pro...")
                model = genai.GenerativeModel('gemini-pro')
            else:
                st.error(f"生成失敗: {e}")
                return None
    
    st.error("❌ 重試次數過多，請稍後再試。")
    return None

# --- 5. 存檔邏輯 (Veo + Kling 欄位) ---
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
            data.get('kling_prompt', ''),  # Kling 欄位
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
st.title("⚔️ Shorts 雙引擎生成器 (Veo + Kling)")
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
    if st.button("✨ 生成雙引擎腳本並存檔", type="primary"):
        if not url_input:
            st.warning("請先輸入網址")
        else:
            vid = extract_video_id(url_input)
            if vid:
                with st.spinner("1/3 分析影片..."):
                    v_info = get_video_info(vid, keys['youtube'])
                
                if v_info:
                    with st.spinner("2/3 AI 正在撰寫 (若卡住是在自動排隊中)..."):
                        # 使用新的 retry 函式
                        result = generate_script_with_retry(v_info, keys['gemini'])
                    
                    if result:
                        with st.spinner("3/3 存檔中..."):
                            # ⚠️ 這裡就是剛剛出錯的地方，現在已修復
                            saved = save_to_sheet_auto(result, keys['gcp_json'], url_input)
                        
                        if saved:
                            st.markdown(f"""
                            <div class="success-box">
                                <h3>✅ 雙引擎腳本已存檔！</h3>
                                <p><strong>中文標題:</strong> {result['title_zh']}</p>
                            </div>
                            """, unsafe_allow_html=True)
                            
                            st.divider()
                            c1, c2 = st.columns(2)
                            with c1:
                                st.subheader("🇺🇸 Google Veo")
                                st.code(result['veo_prompt'], language="text")
                            with c2:
                                st.subheader("🇨🇳 Kling AI (可靈)")
                                st.code(result['kling_prompt'], language="text")
                                
                            st.caption("Common Script (EN): " + result['script_en'])
