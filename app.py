import streamlit as st
import google.generativeai as genai
import re
import base64
from PIL import Image, ImageDraw, ImageFont, ImageOps
import io
import time
import os

# 🔴 網站安全版設定：從部署環境讀取
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
else:
    user_key = st.sidebar.text_input("🔑 輸入你的 Gemini API Key", type="password")
    if user_key:
        genai.configure(api_key=user_key)
    else:
        st.warning("請在側邊欄輸入 API Key 或在部署環境設定 Secrets 才能使用功能。")

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

# 🟢 修正手機上傳 EXIF 翻轉問題 (網頁預覽用)
@st.cache_data
def get_image_base64_cached(bytes_data):
    if bytes_data is not None:
        try:
            img = Image.open(io.BytesIO(bytes_data))
            img = ImageOps.exif_transpose(img) # 自動轉正
            if img.mode != 'RGB':
                img = img.convert('RGB')
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            return base64.b64encode(buf.getvalue()).decode()
        except Exception:
            return None
    return None

# 🟢 讀取本地中文字體
@st.cache_resource
def get_chinese_font(size):
    try:
        return ImageFont.truetype("font.ttf", int(size))
    except Exception as e:
        try:
            return ImageFont.truetype("msjh.ttc", int(size))
        except:
            return ImageFont.load_default()

# 2. 視覺美學 CSS
st.set_page_config(page_title="質感圖文合成器 Pro+", layout="wide")

def inject_ui_css(accent_color, aspect_ratio_css, safe_padding, show_guides, font_scale):
    guide_style = "border: 2px dashed rgba(255, 0, 0, 0.6);" if show_guides else "border: none;"
    
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
        }}

        .card-bg-image {{
            position: absolute; inset: 0;
            width: 100%; height: 100%;
            object-fit: cover; z-index: 1;
        }}

        .card-text-overlay {{
            position: absolute; inset: 0;
            z-index: 2;
            width: 100%; height: 100%;
            background: linear-gradient(to right, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0.6) 60%, rgba(0,0,0,0.2) 100%);
            padding: {safe_padding} 60px; 
            box-sizing: border-box;
            display: flex; flex-direction: column;
            justify-content: center; align-items: flex-start;
            text-align: left; color: #FFFFFF;
            {guide_style}
        }}

        .canvas-title {{ font-size: {2.2 * font_scale}rem; font-weight: bold; margin-bottom: 25px; line-height: 1.2; color: #FFFFFF; }}
        .canvas-title strong {{ color: {accent_color}; }}
        .canvas-insight {{ 
            font-size: {1.05 * font_scale}rem; margin-bottom: 30px; color: #BBBBBB; 
            border-left: 5px solid {accent_color}; padding-left: 20px;
            font-weight: 400; font-style: italic; line-height: 1.6;
        }}
        .canvas-points {{ font-size: {1.05 * font_scale}rem; line-height: 1.9; color: #CCCCCC; }}
        .canvas-points strong {{ color: {accent_color}; font-weight: bold; font-size: {1.05 * font_scale}rem; }}
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
    st.header("🎨 視覺與排版微調")
    
    font_scale = st.slider("🔠 字體縮放比例", min_value=0.8, max_value=1.5, value=1.0, step=0.05)
    accent_color = st.color_picker("重點裝飾色", "#A9B388")
    
    inject_ui_css(accent_color, aspect_ratio_css, safe_padding, show_guides, font_scale) 

    uploaded_file = st.file_uploader("上傳底圖", type=["jpg", "jpeg", "png"])
    img_opacity = st.slider("底圖預覽透明度", 0.0, 1.0, 0.75, step=0.05)

# 4. 生成引擎
st.header("Step 1. 文案處理")
if st.button("✨ 執行文案處理"):
    try:
        format_rule = """
        【格式死指令】：
        1. 標籤：***TITLE***, ***INSIGHT***, ***POINTS***。
        2. ***INSIGHT*** 段落字數絕對不可超過 50 字。
        3. ***POINTS*** 格式：『* **小標**：內容描述』。
        4. 除小標外，內文嚴禁標色。
        """
        if mode == "AI 智能生成焦點":
            if category == "全球當日總經整理":
                persona = "專業首席分析師。"
                topic = keywords if keywords else "全球經濟大事、台股表現與具體漲跌數據"
                instruction = "必須提供明確數據（如 +1.2%, -180點）。禁止空談。"
            else:
                persona = "內容主編"
                topic = keywords if keywords else "今日趨勢"
                instruction = "資訊具體明確。"
            prompt = f"角色：{persona}。主題：{topic}。{instruction} {format_rule} 字數：{word_count}。"
        else:
            prompt = f"優化以下草稿。{format_rule} 字數：{word_count}。\n草稿：{manual_raw}"
        
        with st.spinner('AI 分析數據中...'):
            response = model.generate_content(prompt)
            st.session_state['generated_draft'] = response.text
            st.success("文案處理完畢！")
    except Exception as e:
        st.error(f"文案生成失敗，請確認 API Key 是否設定正確。")

# 🟢 Python 壓圖機
def generate_fixed_image(base_img_bytes, t, i, p, ratio_type, accent_hex, opacity, font_scale):
    w = 1080
    h = 1920 if ratio_type == "限時動態 (Stories)" else 1350

    # 🟢 修正手機上傳 EXIF 翻轉問題 (下載用)
    img = Image.open(io.BytesIO(base_img_bytes))
    img = ImageOps.exif_transpose(img).convert("RGBA")
    
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

    gradient = Image.new('RGBA', (w, h))
    draw_grad = ImageDraw.Draw(gradient)
    for x in range(w):
        p_ratio = x / w
        if p_ratio <= 0.6:
            alpha_pct = 0.85 - ((0.85 - 0.6) * (p_ratio / 0.6))
        else:
            alpha_pct = 0.6 - ((0.6 - 0.2) * ((p_ratio - 0.6) / 0.4))
        draw_grad.line([(x, 0), (x, h)], fill=(0, 0, 0, int(255 * alpha_pct)))
    canvas = Image.alpha_composite(canvas, gradient)

    draw = ImageDraw.Draw(canvas)
    
    font_title = get_chinese_font(72 * font_scale)    
    font_insight = get_chinese_font(34 * font_scale)  
    font_points = get_chinese_font(36 * font_scale)   

    margin_x = 80
    max_text_width = w - (margin_x * 2) - 40 
    current_y = int(h * 0.231) 

    def get_text_size(text, font):
        try:
            if hasattr(font, 'getbbox'):
                bbox = font.getbbox(text)
                if bbox: return bbox[2] - bbox[0], bbox[3] - bbox[1]
        except: pass
        return len(text) * font.size, font.size

    def process_text(text, font, fill, max_w, start_x, start_y, line_height_mult=1.5, draw_mode=True):
        if not text or not text.strip(): return start_y
        lines = []
        for paragraph in text.split('\n'):
            line = ""
            for char in paragraph:
                test_line = line + char
                tw, _ = get_text_size(test_line, font)
                if tw <= max_w: line = test_line
                else:
                    if line: lines.append(line)
                    line = char
            if line: lines.append(line)
        
        y = start_y
        _, th = get_text_size("國", font)
        th = max(th, 30)
        
        for l in lines:
            if draw_mode:
                draw.text((start_x, y), l, font=font, fill=fill)
            y += int(th * line_height_mult)
        return y

    # 1. 畫標題
    if t.strip():
        current_y = process_text(t, font_title, "white", max_text_width, margin_x, current_y, 1.3)
        current_y += int(45 * font_scale)

    # 2. 畫 Insight
    if i.strip():
        insight_x = margin_x + 30 
        insight_max_w = max_text_width - 30
        
        predicted_end_y = process_text(i, font_insight, "#BBBBBB", insight_max_w, insight_x, current_y, 1.6, draw_mode=False)
        box_height = max(predicted_end_y - current_y, 30) 
        
        draw.rectangle([margin_x, current_y + 8, margin_x + 6, current_y + box_height - 15], fill=accent_hex)
        current_y = process_text(i, font_insight, "#BBBBBB", insight_max_w, insight_x, current_y, 1.6)
        current_y += int(50 * font_scale)

    # 3. 畫 Points (雙色小標)
    if p.strip():
        _, th_p = get_text_size("國", font_points)
        th_p = max(th_p, 30)
        line_height = int(th_p * 1.7)
        indent_w, _ = get_text_size("• ", font_points)

        for line in p.split('\n'):
            if not line.strip(): continue
            
            clean_line = line.strip()
            if clean_line.startswith('* '): clean_line = '• ' + clean_line[2:]
            elif not clean_line.startswith('•') and not clean_line.startswith('-'):
                clean_line = "• " + clean_line
            
            parts = clean_line.split('**')
            current_x = margin_x
            
            for index, part in enumerate(parts):
                color = accent_hex if index % 2 == 1 else "#EAEAEA"
                for char in part:
                    cw, _ = get_text_size(char, font_points)
                    if current_x + cw > margin_x + max_text_width:
                        current_x = margin_x + indent_w
                        current_y += line_height
                    
                    draw.text((current_x, current_y), char, font=font_points, fill=color)
                    current_x += cw
            
            current_y += line_height + int(20 * font_scale) 

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
        with st.spinner('正在渲染畫布與生成圖片...'):
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
                    
                    final_img = generate_fixed_image(uploaded_file.getvalue(), t, i, p, post_type, accent_color, img_opacity, font_scale)
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
