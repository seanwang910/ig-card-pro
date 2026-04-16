import streamlit as st
import google.generativeai as genai
import re
from PIL import Image, ImageDraw, ImageFont
import io
import time
import os

# 1. 核心設定 (保留安全版設定)
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
else:
    user_key = st.sidebar.text_input("🔑 輸入你的 Gemini API Key", type="password")
    if user_key:
        genai.configure(api_key=user_key)
    else:
        st.warning("請在部署環境 Secrets 中設定 GOOGLE_API_KEY。")

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

# ---------------------------------------------------------
# 🎨 核心修復：後端繪圖引擎 (解決破損與字體問題)
# ---------------------------------------------------------
def create_stable_image(base_img_bytes, t, i, p, ratio_type, accent_hex, opacity):
    # 規格設定
    w = 1080
    h = 1920 if ratio_type == "限時動態 (Stories)" else 1350
    
    # 1. 處理底圖 (滿版裁切)
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
    
    # 2. 建立畫布與遮罩
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    img.putalpha(int(255 * opacity))
    canvas.paste(img, (0, 0), img)
    
    # 3. 繪製精細漸層 (解決黑色區域破損問題)
    draw = ImageDraw.Draw(canvas)
    for x in range(int(w * 0.9)):
        alpha = int(240 * (1 - (x / (w * 0.9))**0.8)) # 使用冪函數讓漸層更柔和
        draw.line([(x, 0), (x, h)], fill=(0, 0, 0, alpha))
    
    # 4. 字體載入邏輯 (修復文字消失問題)
    # Streamlit Cloud 通常路徑為 /usr/share/fonts/...
    font_paths = [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:\\Windows\\Fonts\\msjh.ttc" # Windows 備用
    ]
    def get_font(size):
        for path in font_paths:
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
        return ImageFont.load_default()

    font_title = get_font(75)
    font_insight = get_font(38)
    font_points = get_font(36)
    
    # 5. 繪製文字 (座標對齊 CSS)
    margin_x = 80
    safe_y = 250 # 250px 安全區域
    
    # TITLE
    draw.text((margin_x, safe_y), t, font=font_title, fill="white")
    
    # INSIGHT 裝飾線與文字
    draw.rectangle([margin_x, safe_y + 120, margin_x + 8, safe_y + 240], fill=accent_hex)
    
    # Insight 自動換行處理
    wrapped_i = ""
    for char_idx, char in enumerate(i):
        wrapped_i += char
        if (char_idx + 1) % 22 == 0: wrapped_i += "\n"
    draw.multiline_text((margin_x + 40, safe_y + 125), wrapped_i, font=font_insight, fill="#BBBBBB", spacing=12)
    
    # POINTS 條列
    y_p = safe_y + 350
    point_lines = p.split('\n')
    for line in point_lines:
        if not line.strip(): continue
        clean_line = line.replace('*', '').strip()
        # Point 自動換行
        wrapped_p = ""
        for char_idx, char in enumerate(clean_line):
            wrapped_p += char
            if (char_idx + 1) % 24 == 0: wrapped_p += "\n    "
        
        draw.text((margin_x, y_p), f"• {wrapped_p}", font=font_points, fill="#CCCCCC", spacing=10)
        y_p += (wrapped_p.count('\n') + 1) * 65 + 10

    return canvas

# ---------------------------------------------------------
# UI 邏輯 (完全保留原本設定)
# ---------------------------------------------------------
st.set_page_config(page_title="質感圖文合成器 Pro+", layout="wide")

with st.sidebar:
    st.header("📐 規格設定")
    post_type = st.radio("貼文類型", ["限時動態 (Stories)", "輪播貼文 (Carousel)"])
    show_guides = st.checkbox("顯示 250px 安全區域", value=True)
    aspect_ratio_css = "9 / 16" if post_type == "限時動態 (Stories)" else "4 / 5"
    st.markdown("---")
    category = st.selectbox("主題類別", ["全球當日總經整理", "財商思維", "自我成長"])
    keywords = st.text_input("關鍵字", "")
    accent_color = st.color_picker("重點裝飾色", "#A9B388")
    uploaded_file = st.file_uploader("上傳底圖", type=["jpg", "jpeg", "png"])
    img_opacity = st.slider("底圖透明度", 0.0, 1.0, 0.75)

# 1. 文案生成
if st.button("✨ 執行文案處理"):
    format_rule = "標籤：***TITLE***, ***INSIGHT***, ***POINTS***。POINTS 格式：『* **小標**：內容』。"
    prompt = f"角色：專業分析師。主題：{keywords if keywords else category}。{format_rule}。明確數據與台股資訊。"
    with st.spinner('AI 正在重構內容...'):
        response = model.generate_content(prompt)
        st.session_state['generated_draft'] = response.text

final_text = st.text_area("編輯區", value=st.session_state['generated_draft'], height=300)

# 2. 合成預覽與下載
if uploaded_file and final_text:
    try:
        def extract(text, tag):
            pattern = rf"[\*]{{2,3}}{tag}[\*]{{2,3}}[:：\s]*(.*?)(?=(\n[\*]{{2,3}}|$))"
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            return match.group(1).strip().lstrip(':').lstrip('：').strip() if match else ""

        t, i, p = extract(final_text, "TITLE"), extract(final_text, "INSIGHT"), extract(final_text, "POINTS")

        # 網頁預覽 CSS
        b64_img = base64.b64encode(uploaded_file.getvalue()).decode()
        st.markdown(f"""
        <style>
        #preview-area {{
            width: 100%; max-width: 450px; margin: 0 auto; aspect-ratio: {aspect_ratio_css};
            position: relative; overflow: hidden; background: #000;
        }}
        .bg {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: {img_opacity}; }}
        .overlay {{
            position: absolute; inset: 0; z-index: 2;
            background: linear-gradient(to right, rgba(0,0,0,0.9) 0%, rgba(0,0,0,0.4) 100%);
            padding: 250px 60px; color: white; text-align: left;
            {"border: 2px dashed red;" if show_guides else ""}
        }}
        </style>
        <div id="preview-area">
            <img src="data:image/jpeg;base64,{b64_img}" class="bg">
            <div class="overlay">
                <h1 style="font-size: 2.2rem; margin-bottom: 20px;">{t}</h1>
                <p style="border-left: 5px solid {accent_color}; padding-left: 20px; color: #BBB;">{i}</p>
                <div style="font-size: 1rem; color: #CCC; line-height: 1.6;">{p.replace('\n', '<br>')}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # 🔵 核心：後端生成並提供穩定下載按鈕
        final_img = create_stable_image(uploaded_file.getvalue(), t, i, p, post_type, accent_color, img_opacity)
        buf = io.BytesIO()
        final_img.save(buf, format="PNG")
        
        st.download_button(
            label="📸 100% 下載成功：保存高品質 PNG 圖片",
            data=buf.getvalue(),
            file_name=f"IG_Post_{int(time.time())}.png",
            mime="image/png",
            use_container_width=True
        )
        st.balloons()
    except Exception as e:
        st.error(f"渲染出錯：{e}")
