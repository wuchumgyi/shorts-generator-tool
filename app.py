import streamlit as st
import google.generativeai as genai
from googleapiclient.discovery import build
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import json
import re

# --- 頁面設定 ---
st.set_page_config(page_title="Shorts 流量獵手 (AI 導演版)", page_icon="🎬", layout="wide")
st.markdown("""
    <style>
    .stButton>button {width: 100%; border-radius: 8px; font-weight: bold;}
    .video-card {background-color: #f0f2f6; padding: 15px; border-radius: 10px; margin-bottom: 10px; border-left: 5px solid #ff0000;}
    .stat-box {font-size: 0.8em; color: #555; background: #e0e0e0; padding: 2px 6px; border-radius: 4px; margin-right: 5px;}
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
    # 預設排序，讓 Pro 或 Flash 排前面方便選擇
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

# --- 4. YouTube 搜尋 (流量獵手邏輯) ---
def search_or_fetch_videos(api_key, query, days_filter=14, max_results=10):
    """
    days_filter: 限制搜尋最近 N 天內的影片
    邏輯：依發布時間過濾 -> 依觀看數排序 (由高到低)
    """
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        videos = []
        
        direct_vid = extract_video_id(query)
        
        if direct_vid:
            # === 模式一：指定影片 (Direct) ===
            response = youtube.videos().list(
                part="snippet,statistics", id=direct_vid
            ).execute()
            items = response.get("items", [])
        else:
            # === 模式二：病毒式搜尋 (Viral Search) ===
            # 計算 RFC 3339 格式的時間 (例如：2023-10-01T00:00:00Z)
            published_after = (datetime.utcnow() - timedelta(days=days_filter)).isoformat("T") + "Z"
            
            search_response = youtube.search().list(
                q=query, 
                type="video", 
                part="id,snippet",
                maxResults=max_results, 
                order="viewCount",      # 關鍵：按觀看數排序
                videoDuration="short",  # 關鍵：只抓 Shorts
                publishedAfter=published_after # 關鍵：只抓近期的
            ).execute()
            
            # 搜尋結果只有 id，需要再一次 request 拿統計數據 (觀看數)
            video_ids = [item['id']['videoId'] for item in search_response.get("items", [])]
            if not video_ids: return []
            
            response = youtube.videos().list(
                part="snippet,statistics",
                id=",".join(video_ids)
            ).execute()
            items = response.get("items", [])
            
            # 再次確保按觀看數排序 (API 有時會混亂)
            items.sort(key=lambda x: int(x['statistics'].get('viewCount', 0)), reverse=True)

        for item in items:
            vid = item['id']
            stats = item.get('statistics', {})
            view_count = int(stats.get('viewCount', 0))
            
            # 格式化觀看數 (例如 1.2M)
            if view_count > 1000000:
                view_str = f"{view_count/1000000:.1f}M views"
            elif view_count > 1000:
                view_str = f"{view_count/1000:.1f}K views"
            else:
                view_str = f"{view_count} views"
            
            pub_date = item['snippet']['publishedAt'][:10] # 取出 YYYY-MM-DD

            videos.append({
                'id': vid,
                'url': f"https://www.youtube.com/shorts/{vid}",
                'title': item['snippet']['title'],
                'thumbnail': item['snippet']['thumbnails']['high']['url'],
                'channel': item['snippet']['channelTitle'],
                'desc': item['snippet']['description'],
                'views': view_str,
                'date': pub_date,
                'raw_views': view_count
            })
                
        return videos
    except Exception as e:
        st.error(f"YouTube API 錯誤: {e}")
        return []

# --- 5. AI 生成 (導演級 Prompt) ---
def generate_creative_content(title, desc, api_key, model_name):
    genai.configure(api_key=api_key)
    # 設定參數以增加創造力
    generation_config = genai.types.GenerationConfig(
        temperature=0.85, # 提高創造性
        top_p=0.95,
        top_k=40
    )
    model = genai.GenerativeModel(model_name, generation_config=generation_config)
    
    prompt = f"""
    You are an expert AI Video Director specializing in creating viral Shorts using 'Google Veo' and 'Kling AI'.
    
    Input Video Info:
    - Original Title: {title}
    - Description: {desc}
    
    YOUR MISSION:
    Create a plan for a NEW, DERIVATIVE 9-12 second video. Do NOT just copy the original. Extract the "Satisfying Element" or "Core Humor" and reimagine it with higher quality visuals.
    
    REQUIREMENTS:
    
    1. **VEO PROMPT (Cinematic Focus):**
       - Veo excels at: 1080p+, Continuous shots, Cinematic Lighting, Drone flyovers, Slow-motion.
       - Structure: [Medium/Style], [Subject], [Action], [Lighting/Atmosphere], [Camera Movement], [Technical Specs].
       - Example: "Cinematic 4k shot, drone view, a golden retriever running through a field of lavender during golden hour, soft volumetric lighting, slow motion 60fps, highly detailed fur."
       
    2. **KLING PROMPT (Physics & Motion Focus):**
       - Kling excels at: Realistic human motion, fluid dynamics, complex interactions.
       - Structure: [Subject], [Detailed Action], [Environment], [Style].
       - Example: "A cyberpunk chef chopping neon vegetables, sparks flying, realistic physics, 8k resolution, cyberpunk city background, detailed textures."
       
    3. **SEO TAGS (Exposure Strategy):**
       - Mix 3 types of tags: 
         (A) Broad Niche (e.g., #Satisfying, #Funny)
         (B) Specific Content (e.g., #HydraulicPress, #CuteCat)
         (C) Trending/AI (e.g., #AIArt, #Veo, #ShortsTrend)
       - Provide 15-20 high-traffic tags.
       
    4. **SCRIPTS:**
       - Write a visual flow (not dialogue heavy). Focus on what we SEE.
    
    OUTPUT JSON ONLY:
    {{
        "title_en": "Clickbait-style English Title (Short & Punchy)",
        "title_zh": "繁體中文標題 (帶有情緒、懸念或驚嘆)",
        "veo_prompt": "English prompt optimized for VEO (Cinematic/Camera focus)",
        "kling_prompt": "English prompt optimized for KLING (Motion/Physics focus)",
        "script_en": "Visual description of the new video flow",
        "script_zh": "繁體中文畫面描述 (強調視覺衝擊)",
        "tags": "#Tag1 #Tag2 ... (Optimized list)",
        "comment": "A strategic first comment to pin (engaging question)"
    }}
    """
    try:
        response = model.generate_content(prompt)
        return json.loads(clean_json_string(response.text))
    except Exception as e:
        return {"error": str(e)}

# --- 6. 存檔 ---
def save_to_sheet(data, creds_dict):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        # 確保您的 Google Sheet 名稱正確
        sheet = client.open("Shorts_Content_Planner").sheet1
        
        row = [
            str(datetime.now())[:16],
            data['url'],
            data['title_en'],
            data['title_zh'],
            data['veo_prompt'],
            data['kling_prompt'],
            data['script_en'],
            data['script_zh'],
            data['tags'],
            data['comment']
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"寫入 Google Sheets 失敗: {e}")
        return False

# --- 主介面 ---
st.title("🎬 Shorts 流量獵手 (AI 導演版)")
st.caption("專為 Veo/Kling 生成設計 · 鎖定近期爆紅影片")

if not keys["gemini"]:
    st.warning("⚠️ 請檢查 Secrets 設定 (GEMINI_API_KEY)")
else:
    # 搜尋區塊
    with st.container():
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            query_input = st.text_input("🔍 輸入關鍵字 (例如: satisfying, funny cat, diy hacks)", value="oddly satisfying")
        with c2:
            days_opt = st.selectbox("📅 搜尋範圍", [7, 14, 30, 90], index=1, format_func=lambda x: f"最近 {x} 天")
        with c3:
            st.write("") 
            st.write("")
            if st.button("🚀 挖掘爆紅影片", type="primary"):
                with st.spinner("正在掃描 YouTube 流量數據..."):
                    results = search_or_fetch_videos(keys['youtube'], query_input, days_filter=days_opt)
                    if results:
                        st.session_state.search_results = results
                        st.session_state.selected_video = results[0]
                        # 清空舊的生成暫存
                        keys_to_clear = ['ai_title_en', 'ai_title_zh', 'ai_script_en', 'ai_script_zh', 'ai_tags', 'ai_comment', 'ai_veo', 'ai_kling']
                        for k in keys_to_clear:
                            if k in st.session_state: del st.session_state[k]
                    else:
                        st.warning("⚠️ 找不到符合條件的影片。試試看放寬日期限制？")

    # 內容區塊
    if 'search_results' in st.session_state and st.session_state.search_results:
        st.divider()
        col_list, col_detail = st.columns([1.5, 2])

        # 左側列表 (增強顯示觀看數與日期)
        with col_list:
            st.markdown(f"### 🔥 熱門影片列表")
            for vid in st.session_state.search_results:
                with st.container():
                    # 判斷是否為「超級爆款」 (例如 14天內超過 50萬觀看)
                    is_viral = vid['raw_views'] > 500000
                    viral_badge = "🔥 " if is_viral else ""
                    
                    st.markdown(f"**{viral_badge}[{vid['title']}]({vid['url']})**")
                    st.markdown(f"""
                    <span class='stat-box'>👁️ {vid['views']}</span>
                    <span class='stat-box'>📅 {vid['date']}</span>
                    <span class='stat-box'>👤 {vid['channel']}</span>
                    """, unsafe_allow_html=True)
                    
                    if st.button(f"👉 選擇此影片", key=vid['id']):
                        st.session_state.selected_video = vid
                        # 清空暫存
                        keys_to_clear = ['ai_title_en', 'ai_title_zh', 'ai_script_en', 'ai_script_zh', 'ai_tags', 'ai_comment', 'ai_veo', 'ai_kling']
                        for k in keys_to_clear:
                            if k in st.session_state: del st.session_state[k]
                        st.rerun()
                    st.divider()

        # 右側詳情
        with col_detail:
            selected = st.session_state.get('selected_video')
            if selected:
                st.info(f"✅ 當前分析：{selected['title']}")
                st.video(selected['url'])
                
                # 模型選擇區域
                if keys["gemini"]:
                    model_options = get_valid_models(keys["gemini"])
                    selected_model_name = st.selectbox("🤖 選擇 AI 模型 (建議選 Pro 或 Latest)", model_options)
                
                if st.button("✨ 生成 Veo/Kling 專用腳本 (自動存檔)", type="primary"):
                    if not selected_model_name:
                        st.error("請檢查 AI 模型設定")
                    else:
                        with st.spinner(f"AI ({selected_model_name}) 正在撰寫分鏡與 Prompt..."):
                            ai_data = generate_creative_content(
                                selected['title'], selected['desc'], 
                                keys['gemini'], selected_model_name
                            )
                            
                            if "error" not in ai_data:
                                # 更新 Session State
                                st.session_state.ai_title_en = ai_data.get('title_en', '')
                                st.session_state.ai_title_zh = ai_data.get('title_zh', '')
                                st.session_state.ai_veo = ai_data.get('veo_prompt', '')
                                st.session_state.ai_kling = ai_data.get('kling_prompt', '')
                                st.session_state.ai_script_en = ai_data.get('script_en', '')
                                st.session_state.ai_script_zh = ai_data.get('script_zh', '')
                                st.session_state.ai_tags = ai_data.get('tags', '')
                                st.session_state.ai_comment = ai_data.get('comment', '')
                                
                                # 自動存檔
                                data_to_save = {
                                    'url': selected['url'],
                                    'title_en': ai_data.get('title_en', ''),
                                    'title_zh': ai_data.get('title_zh', ''),
                                    'veo_prompt': ai_data.get('veo_prompt', ''),
                                    'kling_prompt': ai_data.get('kling_prompt', ''),
                                    'script_en': ai_data.get('script_en', ''),
                                    'script_zh': ai_data.get('script_zh', ''),
                                    'tags': ai_data.get('tags', ''),
                                    'comment': ai_data.get('comment', '')
                                }
                                if save_to_sheet(data_to_save, keys['gcp_json']):
                                    st.toast("✅ 資料已自動儲存至 Google Sheets!", icon="💾")
                                else:
                                    st.error("存檔失敗，請檢查 GCP 設定")
                            else:
                                st.error(f"生成失敗: {ai_data['error']}")

                # 顯示生成結果
                if 'ai_veo' in st.session_state:
                    st.subheader("🎨 影片生成 Prompts")
                    t1, t2 = st.tabs(["🎥 Google Veo", "⚡ Kling AI"])
                    
                    with t1:
                        st.text_area("Veo Prompt (複製到 Veo)", key="ai_veo", height=120)
                        st.caption("特點：電影感、運鏡流暢、高解析度")
                    
                    with t2:
                        st.text_area("Kling Prompt (複製到 Kling)", key="ai_kling", height=120)
                        st.caption("特點：動作擬真、物理效果好")

                    st.subheader("📝 影片資訊")
                    c_title, c_tags = st.columns(2)
                    with c_title:
                        st.text_input("中文標題", key="ai_title_zh")
                    with c_tags:
                        st.text_area("SEO 標籤", key="ai_tags", height=68)
                    
                    st.text_area("腳本描述", key="ai_script_zh", height=100)
                    
                    if st.button("💾 更新修改後的內容"):
                        # 這裡放更新邏輯 (同樣呼叫 save_to_sheet，但這只是範例，通常會 append 新的一行或 update)
                        st.toast("修改已記錄 (實際專案需實作 Update 邏輯)", icon="✅")
