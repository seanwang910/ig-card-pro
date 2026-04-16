import streamlit as st
import google.generativeai as genai
import re
from PIL import Image, ImageDraw, ImageFont
import io
import time

# 🔴 網站安全版設定
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
else:
    user_key = st.sidebar.text_input("🔑 輸入你的 Gemini API Key", type="password")
    if user_key:
        genai.configure(api_key=user_key)
    else:
        st.warning("請在側邊欄設定 Secrets 或輸入 API Key。")

# 🔴 初始化 Session State
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
# 🎨 核心：Python 影像處理引擎 (將你的 CSS 邏輯轉換為 PIL)
# ---------------------------------------------------------
def generate_image_pil(base_image_bytes, title, insight, points, ratio_type, accent_hex, opacity):
    # 1. 畫布規格 (1080p 寬度)
    w = 1080
    h = 1920 if ratio_type == "限時動態 (Stories)" else 1350
    
    # 2. 處理底圖 (滿版裁切邏輯)
    img = Image.open(io.BytesIO(base_image_bytes)).convert("RGBA")
    img_w, img_h = img.size
    target_ratio = w / h
    current_ratio = img_w / img_h
    
    if current_ratio > target_ratio:
        new_w = int(img_h * target_ratio)
        offset = (img_w - new_w) // 2
        img = img.crop((offset, 0, offset + new_w, img_h))
    else:
        new_h = int(img_w / target_ratio)
        offset = (img_h - new_h) // 2
        img = img.crop((0, offset, img_w, offset + new_h))
    
    img = img.resize((w, h), Image.Resampling.LANCZOS)
    
    # 3. 混合底圖與黑色背景 (透明度)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    img.putalpha(int(255 * opacity))
    canvas.paste(img, (0, 0), img)
    
    # 4. 繪製漸層遮罩 (模擬 CSS linear-gradient)
    draw = ImageDraw.Draw(canvas)
    for x in range(int(w * 0.8)): # 漸層範圍
        alpha = int(220 * (1 - (x / (w * 0.8))))
        if alpha > 0:
            draw.line([(x, 0), (x, h)], fill=(0, 0, 0, alpha))

    # 5. 文字排版與繪製 (安全區內縮 250px)
    # 注意：雲端伺服器通常只有基本字體，這部分建議下載高品質中文字體放到 GitHub
    try:
        title_font = ImageFont.truetype("arial.ttf", 70) # 暫代
        text_font = ImageFont.truetype("arial.ttf", 36)
    except:
        title_font = ImageFont.load_default()
        text_font = ImageFont.load_default()

    safe_y = 250 # 你的 250px 安全內縮
    margin_x = 80
    
    # 繪製標題
    draw.text((margin_x, safe_y), title, font=title_font, fill="white")
    
    # 繪製 Insight (附帶重點裝飾色邊條)
    draw.rectangle([margin_x, safe_y + 110, margin_x + 6, safe_y + 200], fill=accent_color)
    # 簡單換行處理 (Insight)
    draw.text((margin_x + 30, safe_y + 120), insight[:25], font=text_font, fill="#BBBBBB")
    if len(insight) > 25:
        draw.text((margin_x + 30, safe_y + 170), insight[25:50], font=text_font, fill="#BBBBBB")

    # 繪製 Points
    y_p = safe_y + 280
    for line in points.split('\n'):
        if line.strip():
            clean_line = line.replace('*', '').strip()
            draw.text((margin_x, y_p), f"• {clean_line}", font=text_font, fill="#CCCCCC")
            y_p += 70

    return canvas

# ---------------------------------------------------------
# UI 介面 (保持你原本的所有設定)
# ---------------------------------------------------------
st.set_page_config(page_title="質感圖文合成器 Pro+", layout="wide")

with st.sidebar:
    st.header("📐 畫布規格設定")
    post_type = st.radio("貼文類型", ["限時動態 (Stories)", "輪播貼文 (Carousel)"])
    st.markdown("---")
    category = st.selectbox("主題類別", ["全球當日總經整理", "財商思維", "自我成長"])
    keywords = st.text_input("關鍵字", "")
    accent_color = st.color_picker("重點裝飾色", "#A9B388")
    uploaded_file = st.file_uploader("上傳底圖", type=["jpg", "jpeg", "png"])
    img_opacity = st.slider("底圖透明度", 0.0, 1.0, 0.75)

# 1. 文案生成
if st.button("✨ 執行文案處理"):
    format_rule = "標籤：***TITLE***, ***INSIGHT***, ***POINTS***。POINTS 格式：『* **小標**：內容』。"
    prompt = f"角色：專業分析師。主題：{keywords if keywords else category}。{format_rule}。字數 250。"
    with st.spinner('AI 正在抓取具體數據...'):
        response = model.generate_content(prompt)
        st.session_state['generated_draft'] = response.text

final_text = st.text_area("編輯區", value=st.session_state['generated_draft'], height=250)

# 2. 合成與下載
if uploaded_file and final_text:
    if st.button("🖼️ 合成高品質圖片"):
        try:
            def extract(text, tag):
                pattern = rf"[\*]{{2,3}}{tag}[\*]{{2,3}}[:：\s]*(.*?)(?=(\n[\*]{{2,3}}|$))"
                match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
                return match.group(1).strip().replace('*', '') if match else ""

            t, i, p = extract(final_text, "TITLE"), extract(final_text, "INSIGHT"), extract(final_text, "POINTS")
            
            # 使用 PIL 合成圖片
            final_img = generate_image_pil(uploaded_file.getvalue(), t, i, p, post_type, accent_color, img_opacity)
            
            # 顯示預覽
            st.image(final_img, caption="預覽 (伺服器後端渲染)", width=450)
            
            # 🟢 使用標準下載按鈕
            buf = io.BytesIO()
            final_img.save(buf, format="PNG")
            byte_im = buf.getvalue()
            
            st.download_button(
                label="📸 點擊這裡：直接下載高品質 PNG",
                data=byte_im,
                file_name=f"IG_Post_{int(time.time())}.png",
                mime="image/png",
                use_container_width=True
            )
            st.balloons()
        except Exception as e:
            st.error(f"合成失敗：{e}")
