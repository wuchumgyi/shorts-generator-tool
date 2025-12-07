import streamlit as st
import google.generativeai as genai
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import json
import re
import random
import requests
import time # 新增時間模組

# --- 頁面設定 ---
st.set_page_config(page_title="Shorts 自動化中控台 (防呆版)", page_icon="🛡️", layout="centered")
st.markdown("""
    <style>
    .stButton>button {width: 100%; border-radius: 20px; font-weight: bold;}
    .stTextInput>div>div>input {border-radius: 10px;}
    .success-box {padding: 1rem; background-color: #d4edda; color: #155724; border-radius: 10px; margin-bottom: 1rem;}
    .error-box {padding: 1rem; background-color: #f8d7da; color: #721c24; border-radius: 10px; margin-bottom: 1rem;}
    </style>
    """, unsafe_allow_html=True)

# --- 1. 金鑰讀取 ---
def get_keys():
    try:
        return {
            "gemini": st.secrets["GEMINI_API_KEY"],
            "youtube": st.secrets["YOUTUBE_API_KEY"], 
            "gcp_json": dict(st.secrets["gcp_service_account"]),
            "oauth": st.secrets.get("youtube_oauth")
        }
    except Exception:
        return None

# --- 2. 核心工具 ---
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
        # 優先嘗試 1.5 Flash
        try:
            m = genai.GenerativeModel('gemini-1.5-flash')
            # 測試性呼叫 (不消耗額度，僅確認存在)
            return 'gemini-1.5-flash'
        except:
            pass
        
        # 如果失敗，列出所有可用模型
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                if 'flash' in m.name: return m.name
                if 'pro' in m.name: return m.name
    except Exception:
        pass
    return "gemini-pro" # 最後的保底

# --- 3. 搜尋與資訊 ---
def search_trending_video(api_key):
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        search_response = youtube.search().list(
            q="Oddly Satisfying Shorts", type="video", part="id,snippet",
            maxResults=30, order="viewCount", videoDuration="short"
        ).execute()
        items = search_response.get("items", [])
        if not items: return None
        return f"https://www.youtube.com/shorts/{random.choice(items)['id']['videoId']}"
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
            "channel": item['snippet']['channelTitle']
        }
    except Exception as e:
        st.error(f"YouTube 錯誤: {e}")
        return None

# --- 4. AI 生成 (含 429 錯誤處理) ---
def generate_script(video_data, api_key):
    genai.configure(api_key=api_key)
    model_name = get_first_available_model(api_key)
    
    st.info(f"🤖 使用模型：{model_name}")
    model = genai.GenerativeModel(model_name)
    
    prompt = f"""
    Video Title: {video_data['title']}
    Channel: {video_data['channel']}
    Task: Create a viral 9-second Short plan.
    
    CRITICAL VISUAL INSTRUCTIONS:
    1. Describe a CONTINUOUS ACTION (One-shot).
    2. Focus on PROCESS, "gradual transformation", "morphing".
    3. NO "Before/After" cuts.
    
    REQUIREMENTS:
    1. 'veo_prompt', 'kling_prompt', 'script_en', 'tags', 'comment' in ENGLISH.
    2. 'script_zh', 'title_zh' in TRADITIONAL CHINESE.
    3. 'tags' MUST include #AI. NO tool names (#Veo, #Kling).
    
    Output JSON ONLY:
    {{
        "title_en": "English Title",
        "title_zh": "中文標題",
        "veo_prompt": "Prompt for Veo",
        "kling_prompt": "Prompt for Kling (8k, photorealistic)",
        "script_en": "Script EN",
        "script_zh": "Script ZH",
        "tags": "#Tag1 #Tag2 #AI",
        "comment": "First comment"
    }}
    """
    try:
        response = model.generate_content(prompt)
        result = json.loads(clean_json_string(response.text))
        
        # 標籤過濾
        raw_tags = result.get('tags', '')
        tag_list = re.findall(r"#\w+", raw_tags)
        blacklist = ['#veo', '#sora', '#gemini', '#kling', '#klingai', '#googleveo']
        clean_tags = [t for t in tag_list if t.lower() not in blacklist]
        if not any(t.lower() == '#ai' for t in clean_tags): clean_tags.append("#AI")
        result['tags'] = " ".join(clean_tags)
        return result
        
    except Exception as e:
        err_msg = str(e)
        if "429" in err_msg or "quota" in err_msg.lower():
            st.markdown("""
            <div class="error-box">
            <b>⏳ 速度太快了！(Quota Exceeded)</b><br>
            您觸發了免費版 API 的頻率限制。請等待 1 分鐘後再試一次。
            </div>
            """, unsafe_allow_html=True)
        elif "404" in err_msg:
             st.error(f"❌ 找不到模型 ({model_name})。請確認 requirements.txt 已更新且 API 已啟用。")
        else:
            st.error(f"生成失敗: {e}")
        return None

# --- 5. 試算表存取 ---
def get_sheet_client(creds_dict):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client.open("Shorts_Content_Planner").sheet1

def save_to_sheet_auto(data, creds_dict, ref_url):
    try:
        sheet = get_sheet_client(creds_dict)
        row = [
            str(datetime.now())[:16], ref_url,
            data.get('title_en', ''), data.get('title_zh', ''),
            data.get('veo_prompt', ''), data.get('kling_prompt', ''),
            data.get('script_en', ''), data.get('script_zh', ''),
            str(data.get('tags', '')), data.get('comment', '')
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"寫入失敗: {e}")
        return False

def fetch_last_row_from_sheet(creds_dict):
    try:
        sheet = get_sheet_client(creds_dict)
        all_values = sheet.get_all_values()
        if len(all_values) < 2: return None
        last_row = all_values[-1]
        # 確保不會因為欄位不足而報錯
        def get_val(idx): return last_row[idx] if len(last_row) > idx else ""
        
        return {
            "title_zh": get_val(3),
            "script_zh": get_val(7),
            "tags": get_val(8),
            "comment": get_val(9)
        }
    except Exception as e:
        st.error(f"讀取試算表失敗: {e}")
        return None

# --- 6. 自動上傳功能 ---
def get_authenticated_service(oauth_config):
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": oauth_config["client_id"],
        "client_secret": oauth_config["client_secret"],
        "refresh_token": oauth_config["refresh_token"],
        "grant_type": "refresh_token"
    }
    r = requests.post(token_url, data=data)
    if r.status_code == 200:
        access_token = r.json()["access_token"]
        from google.oauth2.credentials import Credentials
        creds = Credentials(token=access_token)
        return build("youtube", "v3", credentials=creds)
    else:
        st.error(f"OAuth 授權失敗: {r.text}")
        return None

def upload_to_youtube(service, file_obj, title, description, tags_str, category_id="22"):
    try:
        tags = [t.replace("#", "") for t in tags_str.split() if t.strip()]
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id
            },
            "status": {
                "privacyStatus": "private", 
                "selfDeclaredMadeForKids": False
            }
        }
        
        media = MediaIoBaseUpload(file_obj, mimetype="video/mp4", chunksize=-1, resumable=True)
        request = service.videos().insert(part="snippet,status", body=body, media_body=media)
        response = request.execute()
        return response
    except Exception as e:
        st.error(f"上傳錯誤: {e}")
        return None

def post_comment(service, video_id, text):
    try:
        service.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {"snippet": {"textOriginal": text}}
                }
            }
        ).execute()
        return True
    except Exception as e:
        st.warning(f"留言失敗: {e}")
        return False

# --- 主介面 ---
st.title("🛡️ Shorts 自動化中控台")
keys = get_keys()

if not keys:
    st.warning("⚠️ 請先設定 Secrets")
else:
    tab1, tab2 = st.tabs(["🧬 1. 靈感生成", "⬆️ 2. 影片上傳"])

    # --- Tab 1: 生成 ---
    with tab1:
        col1, col2 = st.columns([1, 1.5])
        with col1:
            if st.button("🎲 隨機搜熱門影片"):
                url = search_trending_video(keys['youtube'])
                if url:
                    st.session_state['auto_url'] = url
                    st.success("已找到！")

        default_val = st.session_state.get('auto_url', "")
        url_input = st.text_input("影片網址", value=default_val)
        
        # 加一個小提醒
        st.caption("💡 提示：免費版 API 有頻率限制，請勿連續快速點擊生成。")
        
        if st.button("✨ 生成雙引擎腳本並存檔", type="primary"):
            if not url_input:
                st.warning("請輸入網址")
            else:
                vid = extract_video_id(url_input)
                if vid:
                    with st.spinner("分析與生成中..."):
                        v_info = get_video_info(vid, keys['youtube'])
                        if v_info:
                            result = generate_script(v_info, keys['gemini'])
                            if result:
                                save_to_sheet_auto(result, keys['gcp_json'], url_input)
                                st.session_state['generated_data'] = result 
                                st.success("✅ 已存檔！請切換到「影片上傳」分頁")
                                st.code(result['veo_prompt'], language="text")

    # --- Tab 2: 上傳 ---
    with tab2:
        st.markdown("### 📤 自動上傳中心")
        
        col_load1, col_load2 = st.columns([2, 1])
        with col_load1:
            st.markdown("""
            <div class="success-box" style="background-color: #f0f2f6; color: #31333F;">
            <b>資料來源：</b><br>
            從 Google 試算表載入最新一筆資料，避免網頁重整後資料遺失。
            </div>
            """, unsafe_allow_html=True)
        with col_load2:
            if st.button("📂 載入試算表資料"):
                with st.spinner("讀取中..."):
                    sheet_data = fetch_last_row_from_sheet(keys['gcp_json'])
                    if sheet_data:
                        st.session_state['generated_data'] = sheet_data
                        st.success("已載入！")
                    else:
                        st.warning("試算表是空的或讀取失敗")

        current_data = st.session_state.get('generated_data', {})

        up_title = st.text_input("影片標題 (中文)", value=current_data.get('title_zh', ''))
        
        default_desc = ""
        if current_data.get('script_zh'):
            default_desc = f"{current_data.get('script_zh')}\n\n{current_data.get('tags', '')}"
            
        up_desc = st.text_area("影片說明欄", value=default_desc, height=150)
        up_tags = st.text_input("影片標籤 (Tags)", value=current_data.get('tags', ''))
        up_comment = st.text_input("置頂留言", value=current_data.get('comment', ''))
        
        uploaded_file = st.file_uploader("選擇影片檔案 (MP4)", type=["mp4", "mov"])
        
        if uploaded_file and st.button("🚀 確認上傳"):
            if not keys.get('oauth'):
                st.error("❌ 尚未設定 OAuth Secrets")
            else:
                with st.spinner("連線 YouTube..."):
                    yt_service = get_authenticated_service(keys['oauth'])
                    if yt_service:
                        with st.spinner("上傳中..."):
                            vid_response = upload_to_youtube(yt_service, uploaded_file, up_title, up_desc, up_tags)
                        
                        if vid_response:
                            vid_id = vid_response['id']
                            st.success(f"✅ 上傳成功！ID: {vid_id}")
                            st.markdown(f"**[前往觀看 (不公開)](https://www.youtube.com/watch?v={vid_id})**")
                            
                            if up_comment:
                                post_comment(yt_service, vid_id, up_comment)
                                st.success("✅ 留言成功！")
