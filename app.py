import streamlit as st
import google.generativeai as genai
from googleapiclient.discovery import build
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import json
import re

# --- 頁面設定 ---
st.set_page_config(page_title="Shorts 流量獵手 (Veo專家版)", page_icon="🎬", layout="wide")
st.markdown("""
    <style>
    .stButton>button {width: 100%; border-radius: 8px; font-weight: bold;}
    .video-card {background-color: #f0f2f6; padding: 15px; border-radius: 10px; margin-bottom: 10px; border-left: 5px solid #ff0000;}
    .stat-box {font-size: 0.8em; color: #555; background: #e0e0e0; padding: 2px 6px; border-radius: 4px; margin-right: 5px;}
    .cost-box {background-color: #d1e7dd; color: #0f5132; padding: 10px; border-radius: 5px; border: 1px solid #badbcc; margin-bottom: 10px;}
    </style>
    """, unsafe_allow_html=True)

# --- 1. 初始化與讀取 Key ---
def get_keys():
    return {
        "gemini": st.secrets.get("GEMINI_API_KEY"),
        "youtube": st.secrets.get("YOUTUBE_API_KEY"),
        "gcp_json": dict(st.secrets["gcp_service_account"]) if "gcp_service_account" in st.secrets else None
    }

keys = get_keys()

# --- 2. 獲取可用模型 ---
@st.cache_resource
def get_valid_models(api_key):
    if not api_key: return []
    genai.configure(api_key=api_key)
    valid_models = []
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                valid_models.append(m.name)
    except:
        pass
    return sorted(valid_models, reverse=True)

# --- 3. 核心工具 ---
def clean_json_string(text):
    text = text.replace("```json", "").replace("```", "")
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        text = text[start:end+1]
    return text.strip()

def extract_video_id(input_str):
    regex = r"(?:v=|\/shorts\/|\/youtu\.be\/|\/watch\?v=)([0-9A-Za-z_-]{11})"
    match = re.search(regex, input_str)
    return match.group(1) if match else None

# --- 4. YouTube 搜尋 ---
def search_or_fetch_videos(api_key, query, days_filter=14, max_results=10):
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        videos = []
        direct_vid = extract_video_id(query)
        
        if direct_vid:
            response = youtube.videos().list(part="snippet,statistics", id=direct_vid).execute()
            items = response.get("items", [])
        else:
            published_after = (datetime.utcnow() - timedelta(days=days_filter)).isoformat("T") + "Z"
            search_response = youtube.search().list(
                q=query, type="video", part="id,snippet",
                maxResults=max_results, order="viewCount", videoDuration="short",
                publishedAfter=published_after
            ).execute()
            video_ids = [item['id']['videoId'] for item in search_response.get("items", [])]
            if not video_ids: return []
            response = youtube.videos().list(part="snippet,statistics", id=",".join(video_ids)).execute()
            items = response.get("items", [])
            items.sort(key=lambda x: int(x['statistics'].get('viewCount', 0)), reverse=True)

        for item in items:
            vid = item['id']
            stats = item.get('statistics', {})
            view_count = int(stats.get('viewCount', 0))
            if view_count > 1000000: view_str = f"{view_count/1000000:.1f}M views"
            elif view_count > 1000: view_str = f"{view_count/1000:.1f}K views"
            else: view_str = f"{view_count} views"
            
            videos.append({
                'id': vid,
                'url': f"https://www.youtube.com/shorts/{vid}",
                'title': item['snippet']['title'],
                'thumbnail': item['snippet']['thumbnails']['high']['url'],
                'channel': item['snippet']['channelTitle'],
                'desc': item['snippet']['description'],
                'views': view_str,
                'date': item['snippet']['publishedAt'][:10],
                'raw_views': view_count
            })
        return videos
    except Exception as e:
        st.error(f"YouTube API 錯誤: {e}")
        return []

# --- 5. AI 生成 (Veo 專家級 Prompt 核心) ---
def generate_creative_content(title, desc, api_key, model_name):
    genai.configure(api_key=api_key)
    # 稍微調低 temperature 讓指令更精確，不要太發散
    generation_config = genai.types.GenerationConfig(temperature=0.75, top_p=0.95, top_k=40)
    model = genai.GenerativeModel(model_name, generation_config=generation_config)
    
    # === 專家級 Veo 指令結構 ===
    prompt = f"""
    You are a 'Google Veo Prompt Engineering Expert' and a 'Cinematographer'.
    
    Original Video Context:
    - Title: {title}
    - Desc: {desc}
    
    TASK: 
    Create a detailed prompt for Google Veo (VideoFX) to generate a high-quality, viral 8-10 second video.
    The goal is to create a visually satisfying, photorealistic, or artistically stunning derivative work.
    
    CRITICAL VEO PROMPT RULES (Apply these to 'veo_prompt'):
    1. **Structure:** [Camera Movement] + [Subject & Action] + [Lighting & Atmosphere] + [Technical Specs].
    2. **Lighting:** Use words like 'Volumetric lighting', 'Golden hour', 'Soft studio lighting', 'Cinematic chiaroscuro', 'Tyndall effect'.
    3. **Camera:** Use specific terms like 'Drone shot', 'Macro close-up', 'Low angle', 'Slow motion (60fps)', 'Dolly zoom', 'Rack focus'.
    4. **Texture:** Describe materials (e.g., 'fluffy fur', 'metallic sheen', 'translucent gel', 'rough concrete').
    5. **Continuity:** Describe a SINGLE continuous shot. Do not ask for cuts or edits.
    6. **Quality:** Always include: '4k resolution', 'highly detailed', 'photorealistic', 'shallow depth of field'.
    
    OUTPUT JSON ONLY:
    {{
        "title_en": "Punchy English Title (Short)",
        "title_zh": "繁體中文標題 (吸睛)",
        "veo_prompt": "THE EXPERT VEO PROMPT (English, detailed, cinematic keywords)",
        "script_en": "Brief visual description of the scene",
        "script_zh": "繁體中文畫面描述",
        "tags": "#Tags (15-20 mixed)",
        "comment": "Engaging comment"
    }}
    """
    try:
        response = model.generate_content(prompt)
        usage = response.usage_metadata
        token_info = {"input": usage.prompt_token_count, "output": usage.candidates_token_count, "total": usage.total_token_count}
        result = json.loads(clean_json_string(response.text))
        result['token_usage'] = token_info
        return result
    except Exception as e:
        return {"error": str(e)}

# --- 6. 存檔 (維持省錢版結構：Kling 留白) ---
def save_to_sheet(data, creds_dict):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("Shorts_Content_Planner").sheet1
        
        # A-J 欄位
        row = [
            str(datetime.now())[:16],
            data.get('url', ''),
            data.get('title_en', ''),
            data.get('title_zh', ''),
            data.get('veo_prompt', ''),
            "",  # Kling 欄位留白
            data.get('script_en', ''),
            data.get('script_zh', ''),
            data.get('tags', ''),
            data.get('comment', '')
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"寫入 Google Sheets 失敗: {e}")
        return False

# --- 主介面 ---
st.title("💰 Shorts 流量獵手 (Veo 專家版)")

if not keys["gemini"]:
    st.warning("⚠️ 請檢查 Secrets 設定")
else:
    # 搜尋區塊
    with st.container():
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1: query_input = st.text_input("🔍 輸入關鍵字", value="oddly satisfying")
        with c2: days_opt = st.selectbox("📅 搜尋範圍", [7, 14, 30], index=1, format_func=lambda x: f"最近 {x} 天")
        with c3:
            st.write(""); st.write("")
            if st.button("🚀 挖掘爆紅影片", type="primary"):
                with st.spinner("掃描中..."):
                    results = search_or_fetch_videos(keys['youtube'], query_input, days_filter=days_opt)
                    if results:
                        st.session_state.search_results = results
                        st.session_state.selected_video = results[0]
                        for k in list(st.session_state.keys()):
                            if k.startswith('ai_'): del st.session_state[k]
                    else: st.warning("找不到影片")

    # 內容區塊
    if 'search_results' in st.session_state and st.session_state.search_results:
        st.divider()
        col_list, col_detail = st.columns([1.5, 2])

        with col_list:
            st.markdown(f"### 🔥 熱門影片列表")
            for vid in st.session_state.search_results:
                is_viral = vid['raw_views'] > 500000
                viral_badge = "🔥 " if is_viral else ""
                st.markdown(f"**{viral_badge}[{vid['title']}]({vid['url']})**")
                st.markdown(f"<span class='stat-box'>👁️ {vid['views']}</span> <span class='stat-box'>📅 {vid['date']}</span>", unsafe_allow_html=True)
                if st.button(f"👉 選擇此影片", key=vid['id']):
                    st.session_state.selected_video = vid
                    for k in list(st.session_state.keys()):
                        if k.startswith('ai_'): del st.session_state[k]
                    st.rerun()
                st.divider()

        with col_detail:
            selected = st.session_state.get('selected_video')
            if selected:
                st.info(f"✅ 當前分析：{selected['title']}")
                st.video(selected['url'])
                
                model_options = get_valid_models(keys["gemini"])
                selected_model_name = st.selectbox("🤖 選擇 AI 模型 (建議選 3.0 Pro)", model_options)
                
                if st.button("✨ 生成 Veo 專家級腳本 (自動存檔)", type="primary"):
                    if not selected_model_name: st.error("請檢查 AI 模型")
                    else:
                        with st.spinner("AI 導演正在構思分鏡與光影..."):
                            ai_data = generate_creative_content(selected['title'], selected['desc'], keys['gemini'], selected_model_name)
                            
                            if "error" not in ai_data:
                                ai_data['url'] = selected['url'] 
                                st.session_state.ai_data_full = ai_data
                                if save_to_sheet(ai_data, keys['gcp_json']):
                                    st.toast("✅ 資料已成功寫入 Google Sheets!", icon="💾")
                            else:
                                st.error(f"生成失敗: {ai_data['error']}")

                if 'ai_data_full' in st.session_state:
                    data = st.session_state.ai_data_full
                    if 'token_usage' in data:
                        u = data['token_usage']
                        cost_twd = ((u['input']/1e6 * 2.0) + (u['output']/1e6 * 12.0)) * 32.5
                        st.markdown(f"""
                        <div class="cost-box">
                            <b>💰 本次成本:</b> 輸入 {u['input']} / 輸出 {u['output']}<br>
                            <b>預估費用: {cost_twd:.4f} TWD</b>
                        </div>
                        """, unsafe_allow_html=True)

                    st.subheader("🎨 生成內容 (Veo 專家指令)")
                    
                    # 優化顯示：直接讓使用者好複製
                    st.info("💡 請複製下方指令，貼到 VideoFX (Gemini Advanced)：")
                    st.code(data.get('veo_prompt',''), language="text")
                    
                    st.divider()
                    st.text_input("中文標題", value=data.get('title_zh',''))
                    st.text_area("中文腳本", value=data.get('script_zh',''), height=120)
                    st.text_area("SEO 標籤", value=data.get('tags',''), height=60)
