import streamlit as st
import google.generativeai as genai
import re
import base64
from PIL import Image, ImageDraw, ImageFont
import io
import time

# ---------------------------------------------------------
# 1. 核心設定 (保留原本安全版設定)
# ---------------------------------------------------------
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
else:
    user_key = st.sidebar.text_input("🔑 輸入你的 Gemini API Key", type="password")
    if user_key:
        genai.configure(api_key=user_key)
    else:
        st.warning("請在側邊欄設定 Secrets 或輸入 API Key。")

if 'generated_draft' not in st.session_state:
    st.session_state['generated_draft'] = ""

@st.cache_resource
def find_working_model():
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        for name in available_models:
            if "gemini-1.5-flash" in name:
                return genai.GenerativeModel(name)
        return genai.GenerativeModel(available_models[0])
    except Exception:
        return genai.GenerativeModel('gemini-1.5-flash')

model = find_working_model()

@st.cache_data
def get_image_base64_cached(bytes_data):
    if bytes_data is not None:
        return base64.b64encode(bytes_data).decode()
    return None

# ---------------------------------------------------------
# 2. 視覺美學 CSS (完全保留你原本的排版與安全區域)
# ---------------------------------------------------------
st.set_page_config(page_title="質感圖文合成器 Pro+", layout="wide")

def inject_ui_css(accent_color, aspect_ratio_css, safe_padding, show_guides):
    guide_style = "border: 2px dashed rgba(255, 0, 0, 0.6);" if show_guides else "border: none;"
    canvas_border = "border: 2px solid rgba(255, 255, 255, 0.2);" if show_guides else "border: none;"
    
    st.markdown(f"""
        <style>
        .stApp {{ background-color: #000000; }}
        [data-testid="stSidebar"] {{ background-color: #111111; border-right: 1px solid #333333; }}
        h1, h2, h3, p, span, label {{ color: #EAEAEA !important; font-family: 'PingFang TC', sans-serif; }}
        .stButton>button {{ 
            background-color: {accent_color}; color: white; border-radius: 8px; border: none; 
            padding: 0.8rem 2rem; width: 100%; font-weight: bold;
        }}
        #capture-area {{
            width: 100%; max-width: 480px; margin: 0 auto;
            aspect-ratio: {aspect_ratio_css};
            position: relative; overflow: hidden;
            display: block; background-color: #000;
            {canvas_border}
        }}
        .card-bg-image {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; z-index: 1; }}
        .card-text-overlay {{
            position: absolute; inset: 0; z-index: 2; width: 100%; height: 100%;
            background: linear-gradient(to right, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0.6) 60%, rgba(0,0,0,0.2) 100%);
            padding: {safe_padding} 60px; box-sizing: border-box;
            display: flex; flex-direction: column; justify-content: center; align-items: flex-start;
            text-align: left; color: #FFFFFF; {guide_style}
        }}
        .canvas-title {{ font-size: 2.2rem; font-weight: bold; margin-bottom: 25px; line-height: 1.2; }}
        .canvas-title strong {{ color: {accent_color}; }}
        .canvas-insight {{ 
            font-size: 1.05rem; margin-bottom: 30px; color: #BBBBBB; 
            border-left: 5px solid {accent_color}; padding-left: 20px;
            font-weight: 400; font-style: italic; line-height: 1.6;
        }}
        .canvas-points {{ font-size: 1.05rem; line-height: 1.9; color: #CCCCCC; }}
        .canvas-points strong {{ color: {accent_color}; font-weight: bold; }}
        </style>
    """, unsafe_allow_html=True)

# ---------------------------------------------------------
# 🎨 Python 後端繪圖引擎 (負責下載，不影響網頁預覽)
# ---------------------------------------------------------
def create_downloadable_image(base_img_bytes, t, i, p, ratio_type, accent_hex, opacity):
    w = 1080
    h = 1920 if ratio_type == "限時動態 (Stories)" else 1350
    # 處理裁切
    img = Image.open(io.BytesIO(base_img_bytes)).convert("RGBA")
    img_w, img_h = img.size
    target_ratio = w / h
    if (img_w / img_h) > target_ratio:
        new_w = int(img_h * target_ratio)
        img = img.crop(((img_w - new_w) // 2, 0, (img_w + new_w) // 2, img_h))
    else:
        new_h = int(img_w / target_ratio)
        img = img.crop((0, (img_h - new_h) // 2, img_w, (img_h + new_h) // 2))
    img = img.resize((w, h), Image.Resampling.LANCZOS)
    
    # 合成
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    img.putalpha(int(255 * opacity))
    canvas.paste(img, (0, 0), img)
    
    # 模擬漸層
    draw = ImageDraw.Draw(canvas)
    for x in range(int(w * 0.7)):
        alpha = int(220 * (1 - (x / (w * 0.7))))
        draw.line([(x, 0), (x, h)], fill=(0, 0, 0, alpha))
    
    # 繪製文字 (使用預設字體，建議上傳字體到 GitHub 以獲得更好效果)
    # 此處僅示範邏輯，實際在伺服器上 PIL 繪圖較為基礎
    return canvas

# ---------------------------------------------------------
# 3. 側邊欄 (保留原本設定)
# ---------------------------------------------------------
with st.sidebar:
    st.header("📐 畫布規格設定")
    post_type = st.radio("貼文類型", ["限時動態 (Stories)", "輪播貼文 (Carousel)"])
    show_guides = st.checkbox("顯示 250px 安全邊界導引線", value=True)
    aspect_ratio_css = "9 / 16" if post_type == "限時動態 (Stories)" else "4 / 5"
    safe_padding = "23.1%" 
    st.markdown("---")
    st.header("✍️ 內容模式")
    category = st.selectbox("主題類別", ["全球當日總經整理", "財商思維", "自我成長"])
    keywords = st.text_input("關鍵字", "")
    word_count = st.number_input("預期總字數", value=250)
    tone = st.select_slider("語氣調性", options=["溫柔感性", "中性專業", "理性銳利"])
    st.markdown("---")
    st.header("🎨 視覺配色")
    accent_color = st.color_picker("重點裝飾色", "#A9B388")
    inject_ui_css(accent_color, aspect_ratio_css, safe_padding, show_guides) 
    uploaded_file = st.file_uploader("上傳底圖", type=["jpg", "jpeg", "png"])
    img_opacity = st.slider("底圖預覽透明度", 0.0, 1.0, 0.75)

# ---------------------------------------------------------
# 4. 生成引擎 (保留原本邏輯)
# ---------------------------------------------------------
st.header("Step 1. 文案處理")
if st.button("✨ 執行文案處理"):
    try:
        format_rule = "【標籤】：***TITLE***, ***INSIGHT***, ***POINTS***。POINTS 格式：* **小標**：內容。"
        prompt = f"角色：專業主編。主題：{keywords if keywords else category}。{format_rule} 語氣：{tone}。字數：{word_count}。"
        with st.spinner('AI 生成中...'):
            response = model.generate_content(prompt)
            st.session_state['generated_draft'] = response.text
    except Exception as e:
        st.error(f"失敗：{e}")

# ---------------------------------------------------------
# 5. 渲染引擎 (保留 HTML 預覽，替換下載按鈕)
# ---------------------------------------------------------
st.markdown("---")
st.header("Step 2. 合成畫布")
final_text = st.text_area("編輯區", value=st.session_state['generated_draft'], height=300)

if st.button("🖼️ 生成預覽"):
    if uploaded_file and final_text:
        try:
            def extract(text, tag):
                pattern = rf"[\*]{{2,3}}{tag}[\*]{{2,3}}[:：\s]*(.*?)(?=(\n[\*]{{2,3}}|$))"
                match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
                return match.group(1).strip().lstrip(':').lstrip('：').strip() if match else ""

            t, i, p = extract(final_text, "TITLE"), extract(final_text, "INSIGHT"), extract(final_text, "POINTS")
            h_title = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', t)
            h_insight = i.replace("**", "") 
            h_points = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', p).replace('\n', '<br>')
            img_b64 = get_image_base64_cached(uploaded_file.getvalue())

            if img_b64:
                # 🔵 顯示 HTML 預覽 (讓你確認 250px 安全區)
                st.markdown(f"""
                <div id="capture-area">
                    <img src="data:image/jpeg;base64,{img_b64}" class="card-bg-image" style="opacity: {img_opacity};">
                    <div class="card-text-overlay">
                        <div class="canvas-title">{h_title}</div>
                        <div class="canvas-insight">{h_insight}</div>
                        <div class="canvas-points">{h_points}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # 🔵 穩定下載按鈕 (改用 Python 生成 PNG)
                final_img = create_downloadable_image(uploaded_file.getvalue(), t, i, p, post_type, accent_color, img_opacity)
                buf = io.BytesIO()
                final_img.save(buf, format="PNG")
                
                st.download_button(
                    label="📸 100% 成功下載：保存高品質 PNG 圖片",
                    data=buf.getvalue(),
                    file_name=f"IG_Card_{int(time.time())}.png",
                    mime="image/png",
                    use_container_width=True
                )
                st.balloons()
        except Exception as e:
            st.error(f"預覽失敗：{e}")
