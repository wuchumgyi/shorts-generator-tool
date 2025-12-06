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
st.set_page_config(page_title="Shorts 國際版生成器", page_icon="🎨", layout="centered")
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
    genai.configure(api_key=api_key)
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                return m.name
    except Exception:
        return None
    return "models/gemini-pro"

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

# --- 4. AI 生成邏輯 (視覺流暢優化版) ---
def generate_script(video_data, api_key):
    genai.configure(api_key=api_key)
    
    model_name = get_first_available_model(api_key)
    if not model_name:
        st.error("❌ 無法找到可用模型。")
        return None
    
    st.info(f"🤖 使用模型：{model_name}")
    model = genai.GenerativeModel(model_name)
    
    # Prompt 修改：加入視覺平滑化指令
    prompt = f"""
    Video Title: {video_data['title']}
    Channel: {video_data['channel']}
    
    Task: Create a viral 9-second Short plan.
    
    CRITICAL VISUAL INSTRUCTIONS (Fixing "Abrupt" transitions):
    1. The 'veo_prompt' MUST describe a CONTINUOUS ACTION (One-shot).
    2. Do NOT describe "Before" and "After" as separate states. Describe the PROCESS of changing.
    3. Use keywords: "gradual transformation", "morphing", "flowing", "continuous movement", "slowly revealing".
    4. Focus on the BOUNDARY where the change happens (e.g., the line where rust meets clean metal moving across the screen).
    5. Avoid words like "suddenly", "instantly", "then", "final shot". The whole 9 seconds is ONE action.
    
    DATA REQUIREMENTS:
    1. 'veo_prompt', 'script_en', 'tags', 'comment' MUST be in ENGLISH.
    2. 'script_zh', 'title_zh' MUST be in TRADITIONAL CHINESE (繁體中文).
    3. 'tags' MUST include #AI.
    4. Do NOT use tool names in tags (e.g., NO #Veo, NO #Sora, NO #Gemini).
    
    Output JSON ONLY:
    {{
        "title_en": "Catchy English Title",
        "title_zh": "吸睛的繁體中文標題 (含Emoji)",
        "veo_prompt": "Detailed prompt for Google Veo/Sora (English only), photorealistic, 4k, slow motion, continuous shot, focusing on the satisfying process",
        "script_en": "9-second visual description (English)",
        "script_zh": "9秒畫面描述與分鏡 (繁體中文翻譯)",
        "tags": "#Tag1 #Tag2 #AI (English Only, NO model names)",
        "comment": "Engaging first comment (English Only)"
    }}
    """
    try:
        response = model.generate_content(prompt)
        result = json.loads(clean_json_string(response.text))
        
        # --- Python 標籤過濾器 ---
        raw_tags = result.get('tags', '')
        tag_list = re.findall(r"#\w+", raw_tags)
        blacklist = ['#veo', '#sora', '#gemini', '#googleveo', '#openai', '#chatgpt']
        
        clean_tags = []
        has_ai = False
        
        for tag in tag_list:
            lower_tag = tag.lower()
            if lower_tag in blacklist: continue
            if lower_tag == '#ai': has_ai = True
            clean_tags.append(tag)
            
        if not has_ai:
            clean_tags.append("#AI")
            
        result['tags'] = " ".join(clean_tags)
             
        return result

    except Exception as e:
        st.error(f"生成失敗: {e}")
        return None

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
st.title("🎨 Shorts 國際版生成器 (平滑版)")
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
    if st.button("✨ 生成流暢腳本並自動存檔", type="primary"):
        if not url_input:
            st.warning("請先輸入網址")
        else:
            vid = extract_video_id(url_input)
            if vid:
                with st.spinner("1/3 分析影片..."):
                    v_info = get_video_info(vid, keys['youtube'])
                
                if v_info:
                    with st.spinner("2/3 AI 正在撰寫 (優化視覺連貫性)..."):
                        result = generate_script(v_info, keys['gemini'])
                    
                    if result:
                        with st.spinner("3/3 存檔中..."):
                            saved = save_to_sheet_auto(result, keys['gcp_json'], url_input)
                        
                        if saved:
                            st.markdown(f"""
                            <div class="success-box">
                                <h3>✅ 成功！腳本已優化</h3>
                                <p><strong>Tags:</strong> {result['tags']}</p>
                            </div>
                            """, unsafe_allow_html=True)
                            
                            st.divider()
                            st.caption("Veo Prompt (Optimized for Smoothness)")
                            st.code(result['veo_prompt'], language="text")
                            
                            c1, c2 = st.columns(2)
                            with c1:
                                st.write("**English Title:**", result['title_en'])
                                st.write("**Script (EN):**", result['script_en'])
                            with c2:
                                st.write("**中文標題:**", result['title_zh'])
                                st.write("**腳本 (中):**", result['script_zh'])
