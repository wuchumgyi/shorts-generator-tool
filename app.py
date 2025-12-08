import streamlit as st
import google.generativeai as genai
import os

st.set_page_config(page_title="API 診斷工具", page_icon="🔧")

st.title("🔧 Gemini API 連線診斷")

# 1. 讀取 API Key
api_key = st.secrets.get("GEMINI_API_KEY")

if not api_key:
    st.error("❌ 未偵測到 GEMINI_API_KEY。請檢查 Secrets 設定。")
else:
    # 遮蔽 Key 顯示前幾碼確認
    masked_key = api_key[:5] + "..." + api_key[-3:]
    st.info(f"🔑 已讀取 API Key: {masked_key}")

    # 2. 測試列出模型 (這是最基礎的權限測試)
    if st.button("🚀 開始測試連線"):
        try:
            genai.configure(api_key=api_key)
            
            st.write("正在嘗試連線 Google 伺服器...")
            
            # 嘗試列出所有可用模型
            models = []
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    models.append(m.name)
            
            if models:
                st.success("✅ 連線成功！您的 API Key 是有效的。")
                st.write("您的帳號支援以下模型：")
                st.json(models)
            else:
                st.warning("⚠️ 連線成功但找不到可用模型 (列表為空)。")
                
        except Exception as e:
            st.error("❌ 連線失敗")
            st.error(f"錯誤訊息: {e}")
            
            # 針對 404 錯誤提供具體解法
            if "404" in str(e):
                st.markdown("### 🛑 診斷結果：權限未開啟")
                st.markdown("您的 API Key 是對的，但**專案權限沒開**。請執行以下步驟：")
                st.markdown("1. 前往 [Google Cloud Console](https://console.cloud.google.com/)")
                st.markdown("2. 上方確認選到了您的專案")
                st.markdown("3. 搜尋 **'Generative Language API'**")
                st.markdown("4. 點擊 **'啟用 (ENABLE)'**")
                st.markdown("5. 等待 1-2 分鐘後再次測試")
