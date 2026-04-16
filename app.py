import streamlit as st
import google.generativeai as genai
import re
import base64
from PIL import Image, ImageDraw, ImageFont
import io
import time
import os
import urllib.request

# 🔴 網站安全版設定
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
else:
    user_key = st.sidebar.text_input("🔑 輸入你的 Gemini API Key", type="password")
    if user_key:
        genai.configure(api_key=user_key)
    else:
        st.warning("請在側邊欄輸入 API Key 或在部署環境設定 Secrets 才能使用功能。")

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

# 🟢 自動獲取中文字體
@st.cache_resource
def get_chinese_font(size):
    font_name = "NotoSansTC-Bold.ttf"
    if not os.path.exists(font_name):
        try:
            url = "https://github.com/google/fonts/raw/main/ofl/notosanstc/NotoSansTC-Bold.ttf"
            urllib.request.urlretrieve(url, font_name)
        except Exception:
            pass
    try:
        return ImageFont.truetype(font_name, size)
    except:
        return ImageFont.load_default()

# 2. 視覺美學 CSS
st.set_page_config(page_title="質感圖文合成器 Pro+", layout="wide")

def inject_ui_css(accent_color, aspect_ratio_css, safe_padding, show_guides):
    guide_style = "border: 2px dashed rgba(255, 0, 0, 0.6);" if show_guides else "border: none;"
    
    st.markdown(f"""
        <style>
        .stApp {{ background-color: #000000; }}
        [data-testid="stSidebar"] {{ background-color: #111111; border-right: 1px solid #333333; }}
        h1, h2, h3, p, span, label {{ color: #EAEAEA !important; font-family: 'PingFang TC', sans-serif; }}
        
        .stButton>button {{ background-color: {accent_color}; color: white; border-radius: 8px; border: none; padding: 0.8rem 2rem; width: 100%; font-weight: bold; }}
        
        #capture-area {{
            width: 100%; max-width: 480px; margin: 0 auto;
            aspect-ratio: {aspect_ratio_css};
            position: relative; overflow: hidden; display: block; background-color: #000;
        }}
        .card-bg-image {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; z-index: 1; }}
        .card-text-overlay {{
            position: absolute; inset: 0; z-index: 2; width: 100%; height: 100%;
            background: linear-gradient(to right, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0.6) 60%, rgba(0,0,0,0.2) 100%);
            padding: {safe_padding} 60px; box-sizing: border-box; display: flex; flex-direction: column;
            justify-content: center; align-items: flex-start; text-align: left; color: #FFFFFF; {guide_style}
        }}
        .canvas-title {{ font-size: 2.2rem; font-weight: bold; margin-bottom: 25px; line-height: 1.2; color: #FFFFFF; }}
        .canvas-title strong {{ color: {accent_color}; }}
        .canvas-insight {{ font-size: 1.05rem; margin-bottom: 30px; color: #BBBBBB; border-left: 5px solid {accent_color}; padding-left: 20px; line-height: 1.6; }}
        .canvas-points {{ font-size: 1.05rem; line-height: 1.9; color: #CCCCCC; }}
        .canvas-points strong {{ color: {accent_color}; font-weight: bold; font-size: 1.05rem; }}
        </style>
    """, unsafe_allow_html=True)

# 3. 側邊欄
with st.sidebar:
    st.header("📐 畫布規格設定")
    post_type = st.radio("貼文類型", ["限時動態 (Stories)", "輪播貼文 (Carousel)"])
    show_guides = st.checkbox("顯示 250px 安全邊界導引線", value=False)
    
    aspect_ratio_css = "9 / 16" if post_type == "限時動態 (Stories)" else "4 / 5"
    safe_padding = "23.1%" 

    st.markdown("---")
    st.header("✍️ 內容模式")
    mode = st.radio("生成模式", ["AI 智能生成焦點", "直接貼上草稿"])

    if mode == "AI 智能生成焦點":
        category = st.selectbox("主題類別", ["全球當日總經整理", "財商思維", "自我成長"])
        keywords = st.text_input("關鍵字 (可留空)", "")
    else:
        manual_raw = st.text_area("🔴 貼入原始內容：", height=150)

    word_count = st.number_input("預期總字數", min_value=50, max_value=900, value=250)
    tone = st.select_slider("語氣調性", options=["溫柔感性", "中性專業", "理性銳利"])

    st.markdown("---")
    st.header("🎨 視覺配色")
    accent_color = st.color_picker("重點裝飾色", "#A9B388")
    inject_ui_css(accent_color, aspect_ratio_css, safe_padding, show_guides) 

    uploaded_file = st.file_uploader("上傳底圖", type=["jpg", "jpeg", "png"])
    img_opacity = st.slider("底圖預覽透明度", 0.0, 1.0, 0.75, step=0.05)

# 4. 生成引擎
st.header("Step 1. 文案處理")
if st.button("✨ 執行文案處理"):
    try:
        format_rule = "【格式死指令】：1. 標籤：***TITLE***, ***INSIGHT***, ***POINTS***。2. ***INSIGHT*** 絕不超過 50 字。3. ***POINTS*** 格式：『* **小標**：內容』。4. 除小標外，內文嚴禁標色。"
        if mode == "AI 智能生成焦點":
            persona = "專業首席分析師。" if category == "全球當日總經整理" else "內容主編"
            topic = keywords if keywords else ("全球經濟大事、台股表現與漲跌數據" if category == "全球當日總經整理" else "今日趨勢")
            instruction = "必須提供明確數據（如 +1.2%, -180點）。禁止空談。" if category == "全球當日總經整理" else "資訊具體明確。"
            prompt = f"角色：{persona}。主題：{topic}。{instruction} {format_rule} 字數：{word_count}。"
        else:
            prompt = f"優化以下草稿。{format_rule} 字數：{word_count}。\n草稿：{manual_raw}"
        
        with st.spinner('AI 分析數據中...'):
            response = model.generate_content(prompt)
            st.session_state['generated_draft'] = response.text
            st.success("文案處理完畢！")
    except Exception as e:
        st.error(f"文案生成失敗：{e}")

# 🟢 無腦固定座標版：絕對不會報錯的壓圖函數
def generate_fixed_image(base_img_bytes, t, i, p, ratio_type, accent_hex, opacity):
    w = 1080
    h = 1920 if ratio_type == "限時動態 (Stories)" else 1350

    # 底圖滿版
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

    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    img.putalpha(int(255 * opacity))
    canvas.paste(img, (0, 0), img)

    # 固定漸層
    gradient = Image.new('RGBA', (w, h))
    draw_grad = ImageDraw.Draw(gradient)
    for x in range(w):
        p_ratio = x / w
        alpha_pct = 0.85 - (0.65 * p_ratio) if p_ratio <= 0.8 else 0.2
        draw_grad.line([(x, 0), (x, h)], fill=(0, 0, 0, int(255 * alpha_pct)))
    canvas = Image.alpha_composite(canvas, gradient)

    draw = ImageDraw.Draw(canvas)
    
    font_title = get_chinese_font(65)
    font_insight = get_chinese_font(34)
    font_points = get_chinese_font(34)

    margin_x = 80
    
    # 🔴 絕對固定座標邏輯 (不再計算高度)
    # 1. 標題 (固定在 Y=250)
    current_y = int(h * 0.231)
    title_chunks = [t[idx:idx+13] for idx in range(0, len(t), 13)] # 一行最多 13 字
    for chunk in title_chunks[:2]: # 最多 2 行
        draw.text((margin_x, current_y), chunk, font=font_title, fill="white")
        current_y += 85
    
    # 2. 敘事 (固定接在標題下方 40px)
    current_y += 40
    insight_chunks = [i[idx:idx+23] for idx in range(0, len(i), 23)]
    
    # 強制畫框框：高度用行數直接相乘，絕對是正數！
    box_height = len(insight_chunks[:3]) * 55
    draw.rectangle([margin_x, current_y, margin_x + 6, current_y + box_height], fill=accent_hex)
    
    text_y = current_y + 5
    for chunk in insight_chunks[:3]:
        draw.text((margin_x + 30, text_y), chunk, font=font_insight, fill="#BBBBBB")
        text_y += 55
    
    # 3. 條列重點 (固定接在敘事下方 60px)
    current_y += box_height + 60
    for line in p.split('\n'):
        if not line.strip(): continue
        clean_line = line.replace('*', '').strip()
        if not clean_line.startswith('•') and not clean_line.startswith('-'):
            clean_line = "• " + clean_line
            
        point_chunks = [clean_line[idx:idx+23] for idx in range(0, len(clean_line), 23)]
        for chunk in point_chunks:
            draw.text((margin_x, current_y), chunk, font=font_points, fill="#CCCCCC")
            current_y += 55
        current_y += 15 # 點與點之間的間距

    return canvas

# 5. 渲染引擎
st.markdown("---")
st.header("Step 2. 合成畫布")
final_text = st.text_area("編輯區", value=st.session_state['generated_draft'], height=300)

if st.button("🖼️ 生成滿版高品質畫布"):
    if uploaded_file is None:
        st.warning("請先上傳圖片。")
    elif not final_text:
        st.warning("無內容。")
    else:
        with st.spinner('正在渲染畫布與生成下載檔案...'):
            try:
                def extract(text, tag):
                    pattern = rf"[\*]{{2,3}}{tag}[\*]{{2,3}}[:：\s]*(.*?)(?=(\n[\*]{{2,3}}|$))"
                    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
                    return match.group(1).strip().lstrip(':').lstrip('：').strip() if match else ""

                t, i, p = extract(final_text, "TITLE"), extract(final_text, "INSIGHT"), extract(final_text, "POINTS")
                if not t:
                    t_match = re.search(r"^\*\*(.*?)\*\*", final_text)
                    if t_match: t = t_match.group(1)

                h_title = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', t)
                h_insight = i.replace("**", "") 
                h_points = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', p).replace('\n', '<br>')

                img_b64 = get_image_base64_cached(uploaded_file.getvalue())
                
                if img_b64:
                    # 🟢 原汁原味保留 HTML 預覽
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
                    
                    # 🟢 強制轉成圖片並下載
                    final_img = generate_fixed_image(uploaded_file.getvalue(), t, i, p, post_type, accent_color, img_opacity)
                    buf = io.BytesIO()
                    final_img.save(buf, format="PNG")
                    
                    st.download_button(
                        label="📸 點擊下載：高品質滿版圖卡 (PNG)",
                        data=buf.getvalue(),
                        file_name=f"IG_Card_{int(time.time())}.png",
                        mime="image/png",
                        use_container_width=True
                    )
                    st.balloons()

            except Exception as e:
                st.error(f"渲染失敗：{e}")
