import streamlit as st
import google.generativeai as genai
from googleapiclient.discovery import build
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import json
import re

# --- 頁面設定 ---
st.set_page_config(page_title="Shorts 流量獵手 (Pro計算版)", page_icon="💰", layout="wide")
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
        # 請確保 secrets.toml 裡的 key 名稱一致
        "gemini": st.secrets.get("GEMINI_API_KEY"),
        "youtube": st.secrets.get("YOUTUBE_API_KEY"),
        "gcp_json": dict(st.secrets["gcp_service_account"]) if "gcp_service_account" in st.secrets else None
    }

keys = get_keys()

# --- 2. 獲取可用模型 (會自動抓取 3.0 Pro) ---
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
    # 排序：讓 Pro 或 Latest 排在前面
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
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        videos = []
        
        direct_vid = extract_video_id(query)
        
        if direct_vid:
            # === 模式一：指定影片 ===
            response = youtube.videos().list(
                part="snippet,statistics", id=direct_vid
            ).execute()
            items = response.get("items", [])
        else:
            # === 模式二：病毒式搜尋 ===
            published_after = (datetime.utcnow() - timedelta(days=days_filter)).isoformat("T") + "Z"
            
            search_response = youtube.search().list(
                q=query, 
                type="video", 
                part="id,snippet",
                maxResults=max_results, 
                order="viewCount",      # 按觀看數排序
                videoDuration="short",  # 只抓 Shorts
                publishedAfter=published_after # 只抓近期
            ).execute()
            
            video_ids = [item['id']['videoId'] for item in search_response.get("items", [])]
            if not video_ids: return []
            
            response = youtube.videos().list(
                part="snippet,statistics",
                id=",".join(video_ids)
            ).execute()
            items = response.get("items", [])
            
            # 二次排序
            items.sort(key=lambda x: int(x['statistics'].get('viewCount', 0)), reverse=True)

        for item in items:
            vid = item['id']
            stats = item.get('statistics', {})
            view_count = int(stats.get('viewCount', 0))
            
            if view_count > 1000000:
                view_str = f"{view_count/1000000:.1f}M views"
            elif view_count > 1000:
                view_str = f"{view_count/1000:.1f}K views"
            else:
                view_str = f"{view_count} views"
            
            pub_date = item['snippet']['publishedAt'][:10]

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

# --- 5. AI 生成 (含 Token 計算功能) ---
def generate_creative_content(title, desc, api_key, model_name):
    genai.configure(api_key=api_key)
    generation_config = genai.types.GenerationConfig(
        temperature=0.85,
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
    1. **VEO PROMPT (Cinematic Focus):** Focus on lighting, camera movement, and technical specs (4k, 60fps).
    2. **KLING PROMPT (Physics Focus):** Focus on realistic motion, fluid dynamics, and textures.
    3. **SEO TAGS:** Provide 15-20 mixed tags (Broad + Specific + Trending).
    4. **SCRIPTS:** Visual-heavy description.
    
    OUTPUT JSON ONLY:
    {{
        "title_en": "Clickbait-style English Title",
        "title_zh": "繁體中文標題 (帶有情緒)",
        "veo_prompt": "English prompt for VEO",
        "kling_prompt": "English prompt for KLING",
        "script_en": "Visual description (English)",
        "script_zh": "繁體中文畫面描述",
        "tags": "#Tag1 #Tag2 ...",
        "comment": "Engaging first comment"
    }}
    """
    try:
        response = model.generate_content(prompt)
        
        # === 關鍵修改：抓取 Token 用量 ===
        usage = response.usage_metadata
        token_info = {
            "input": usage.prompt_token_count,
            "output": usage.candidates_token_count,
            "total": usage.total_token_count
        }
        
        result = json.loads(clean_json_string(response.text))
        result['token_usage'] = token_info # 將用量塞入回傳資料
        return result
        
    except Exception as e:
        return {"error": str(e)}

# --- 6. 存檔 ---
def save_to_sheet(data, creds_dict):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
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
st.title("💰 Shorts 流量獵手 (AI 導演 x 成本監控版)")
st.caption("專為 Veo/Kling 生成設計 · 支援 3.0 Pro 計費顯示")

if not keys["gemini"]:
    st.warning("⚠️ 請檢查 Secrets 設定 (GEMINI_API_KEY)")
else:
    # 搜尋區塊
    with st.container():
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            query_input = st.text_input("🔍 輸入關鍵字", value="oddly satisfying")
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
                        # 清空舊生成
                        for k in list(st.session_state.keys()):
                            if k.startswith('ai_'): del st.session_state[k]
                    else:
                        st.warning("⚠️ 找不到符合條件的影片。")

    # 內容區塊
    if 'search_results' in st.session_state and st.session_state.search_results:
        st.divider()
        col_list, col_detail = st.columns([1.5, 2])

        # 左側列表
        with col_list:
            st.markdown(f"### 🔥 熱門影片列表")
            for vid in st.session_state.search_results:
                with st.container():
                    is_viral = vid['raw_views'] > 500000
                    viral_badge = "🔥 " if is_viral else ""
                    
                    st.markdown(f"**{viral_badge}[{vid['title']}]({vid['url']})**")
                    st.markdown(f"""
                    <span class='stat-box'>👁️ {vid['views']}</span>
                    <span class='stat-box'>📅 {vid['date']}</span>
                    """, unsafe_allow_html=True)
                    
                    if st.button(f"👉 選擇此影片", key=vid['id']):
                        st.session_state.selected_video = vid
                        for k in list(st.session_state.keys()):
                            if k.startswith('ai_'): del st.session_state[k]
                        st.rerun()
                    st.divider()

        # 右側詳情
        with col_detail:
            selected = st.session_state.get('selected_video')
            if selected:
                st.info(f"✅ 當前分析：{selected['title']}")
                st.video(selected['url'])
                
                # 模型選擇
                if keys["gemini"]:
                    model_options = get_valid_models(keys["gemini"])
                    selected_model_name = st.selectbox("🤖 選擇 AI 模型 (請選 3.0 Pro 或 2.0 Flash)", model_options)
                
                if st.button("✨ 生成 Veo/Kling 專用腳本 (自動存檔)", type="primary"):
                    if not selected_model_name:
                        st.error("請檢查 AI 模型設定")
                    else:
                        with st.spinner(f"AI ({selected_model_name}) 正在運算中..."):
                            ai_data = generate_creative_content(
                                selected['title'], selected['desc'], 
                                keys['gemini'], selected_model_name
                            )
                            
                            if "error" not in ai_data:
                                # 儲存至 Session State
                                st.session_state.ai_data_full = ai_data # 存完整資料含 token
                                st.session_state.ai_title_en = ai_data.get('title_en', '')
                                st.session_state.ai_title_zh = ai_data.get('title_zh', '')
                                st.session_state.ai_veo = ai_data.get('veo_prompt', '')
                                st.session_state.ai_kling = ai_data.get('kling_prompt', '')
                                st.session_state.ai_script_zh = ai_data.get('script_zh', '')
                                st.session_state.ai_tags = ai_data.get('tags', '')
                                
                                # 自動存檔
                                if save_to_sheet(ai_data, keys['gcp_json']):
                                    st.toast("✅ 資料已存至 Google Sheets!", icon="💾")
                            else:
                                st.error(f"生成失敗: {ai_data['error']}")

                # 顯示生成結果與費用
                if 'ai_data_full' in st.session_state:
                    data = st.session_state.ai_data_full
                    
                    # === 💰 費用顯示區塊 ===
                    if 'token_usage' in data:
                        u = data['token_usage']
                        # 3.0 Pro 費率計算 (Input $2, Output $12 / 1M tokens)
                        cost_usd = (u['input']/1000000 * 2.0) + (u['output']/1000000 * 12.0)
                        cost_twd = cost_usd * 32.5 # 假設匯率
                        
                        st.markdown(f"""
                        <div class="cost-box">
                            <b>💰 本次生成成本 (以 Gemini 3.0 Pro 費率估算):</b><br>
                            輸入 Tokens: {u['input']} | 輸出 Tokens: {u['output']} | 總計: {u['total']}<br>
                            <b>預估費用: {cost_twd:.4f} TWD</b> (USD ${cost_usd:.5f})
                        </div>
                        """, unsafe_allow_html=True)
                    # =========================

                    st.subheader("🎨 生成內容")
                    t1, t2 = st.tabs(["🎥 Google Veo Prompt", "⚡ Kling AI Prompt"])
                    with t1: st.text_area("Veo", key="ai_veo", height=100)
                    with t2: st.text_area("Kling", key="ai_kling", height=100)

                    st.text_input("中文標題", key="ai_title_zh")
                    st.text_area("腳本描述", key="ai_script_zh", height=120)
                    st.text_area("SEO 標籤", key="ai_tags", height=60)
