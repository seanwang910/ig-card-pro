import streamlit as st
import google.generativeai as genai
import re
from PIL import Image, ImageDraw, ImageFont
import io
import time

# 🔴 網站安全版金鑰設定
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
# 🎨 Python 影像處理引擎 (取代不穩定的 JS)
# ---------------------------------------------------------
def create_card_pil(base_image, title, insight, points, ratio_name, accent_hex, opacity):
    # 1. 設定畫布尺寸 (以 1080px 為基準寬度)
    w = 1080
    h = 1920 if ratio_name == "限時動態 (Stories)" else 1350
    
    # 2. 處理底圖 (滿版裁切)
    img = Image.open(base_image).convert("RGBA")
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
    
    # 3. 調整透明度與黑色基底
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, int(255 * (1 - opacity))))
    img.putalpha(int(255 * opacity))
    canvas.paste(img, (0, 0), img)
    
    # 4. 繪製漸層 (從左到右)
    draw = ImageDraw.Draw(canvas)
    for x in range(w // 2):
        alpha = int(220 * (1 - (x / (w // 2))))
        draw.line([(x, 0), (x, h)], fill=(0, 0, 0, alpha))

    # 5. 準備字體 (雲端環境字體處理)
    try:
        # 嘗試載入系統中文字體 (Streamlit Cloud 常用路徑)
        font_path = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" 
        title_font = ImageFont.truetype(font_path, 70)
        text_font = ImageFont.truetype(font_path, 35)
    except:
        title_font = ImageFont.load_default()
        text_font = ImageFont.load_default()

    # 🎨 繪製文字 (簡化排版)
    safe_y = 250
    draw.text((80, safe_y), title, font=title_font, fill="white")
    
    # 繪製 Insight 的邊條
    draw.rectangle([80, safe_y + 120, 85, safe_y + 220], fill=accent_hex)
    draw.text((110, safe_y + 130), insight, font=text_font, fill="#BBBBBB")
    
    # 繪製 Points
    y_offset = safe_y + 280
    for line in points.split('\n'):
        if line.strip():
            draw.text((80, y_offset), line.strip(), font=text_font, fill="#CCCCCC")
            y_offset += 60

    return canvas

# ---------------------------------------------------------
# 側邊欄與介面
# ---------------------------------------------------------
st.set_page_config(page_title="質感圖文合成器 Pro+", layout="wide")
st.title("✨ 質感圖文合成器 Pro+ (網站穩定版)")

with st.sidebar:
    st.header("📐 規格設定")
    post_type = st.radio("貼文類型", ["限時動態 (Stories)", "輪播貼文 (Carousel)"])
    st.markdown("---")
    category = st.selectbox("主題類別", ["全球當日總經整理", "財商思維", "自我成長"])
    keywords = st.text_input("關鍵字", "")
    accent_color = st.color_picker("重點裝飾色", "#A9B388")
    uploaded_file = st.file_uploader("上傳底圖", type=["jpg", "jpeg", "png"])
    img_opacity = st.slider("底圖透明度", 0.0, 1.0, 0.75)

# Step 1: 文案生成
if st.button("✨ 1. 產生文案"):
    prompt = f"角色：專業分析師。主題：{keywords if keywords else category}。請給出 TITLE, INSIGHT (50字內), POINTS (含數據)。格式需標註標籤。"
    with st.spinner('AI 生成中...'):
        response = model.generate_content(prompt)
        st.session_state['generated_draft'] = response.text

final_text = st.text_area("文案內容 (可手動修改)", value=st.session_state['generated_draft'], height=200)

# Step 2: 合成與下載
if uploaded_file and final_text:
    if st.button("🖼️ 2. 合成畫布"):
        def extract(text, tag):
            pattern = rf"{tag}(.*?)(?=\n\n|\n\*\*\*|$)"
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            return match.group(1).strip().replace('*', '') if match else ""

        t = extract(final_text, "TITLE")
        i = extract(final_text, "INSIGHT")
        p = extract(final_text, "POINTS")

        # 調用 Python 合成引擎
        result_img = create_card_pil(uploaded_file, t, i, p, post_type, accent_color, img_opacity)
        
        # 預覽
        st.image(result_img, caption="預覽圖 (下載後為高品質滿版)", use_container_width=False, width=400)
        
        # 🔴 下載按鈕 (這是在雲端 100% 成功的作法)
        buf = io.BytesIO()
        result_img.save(buf, format="PNG")
        byte_im = buf.getvalue()
        
        st.download_button(
            label="📸 點擊這裡：直接下載高品質 PNG 圖片",
            data=byte_im,
            file_name=f"IG_Card_{int(time.time())}.png",
            mime="image/png",
            use_container_width=True
        )
