import streamlit as st
import google.generativeai as genai
import re
from PIL import Image, ImageDraw, ImageFont, ImageOps
import io
import time
import os

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

def inject_ui_css(accent_color):
    st.markdown(f"""
        <style>
        .stApp {{ background-color: #000000; }}
        [data-testid="stSidebar"] {{ background-color: #111111; border-right: 1px solid #333333; }}
        h1, h2, h3, p, span, label {{ color: #EAEAEA !important; font-family: 'PingFang TC', sans-serif; }}
        .stButton>button {{ 
            background-color: {accent_color}; color: white; border-radius: 8px; border: none; 
            padding: 0.8rem 2rem; width: 100%; font-weight: bold; 
        }}
        </style>
    """, unsafe_allow_html=True)

# 3. 側邊欄
with st.sidebar:
    st.header("📐 畫布規格設定")
    post_type = st.radio("貼文類型", ["限時動態 (Stories)", "輪播貼文 (Carousel)"])
    
    st.markdown("---")
    st.header("✍️ 內容模式")
    mode = st.radio("生成模式", ["AI 智能生成焦點", "直接貼上草稿"])

    if mode == "AI 智能生成焦點":
        category = st.selectbox("主題類別", ["全球當日總經整理", "財商思維", "自我成長"])
        keywords = st.text_input("關鍵字 (可留空)", "")
    else:
        manual_raw = st.text_area("🔴 貼入原始內容：", height=150)
        st.caption("📱 **手機換頁技巧**：若想手動換頁，請在行首獨立輸入三個減號 `---`")

    word_count = st.number_input("預期總字數", min_value=50, max_value=900, value=250)
    tone = st.select_slider("語氣調性", options=["溫柔感性", "中性專業", "理性銳利"])

    st.markdown("---")
    st.header("🎨 視覺與排版微調")
    font_scale = st.slider("🔠 字體縮放比例", min_value=0.8, max_value=1.5, value=1.0, step=0.05)
    accent_color = st.color_picker("重點裝飾色", "#A9B388")
    
    inject_ui_css(accent_color) 

    uploaded_file = st.file_uploader("上傳底圖", type=["jpg", "jpeg", "png"])
    img_opacity = st.slider("底圖透明度", 0.0, 1.0, 0.75, step=0.05)

# 4. 生成引擎
st.header("Step 1. 文案處理")
if st.button("✨ 執行文案處理"):
    try:
        # 🟢 強化的 AI 自動分頁指令
        format_rule = """
        【格式死指令】：
        1. 標籤：***TITLE***, ***INSIGHT***, ***POINTS***。
        2. ***INSIGHT*** 段落字數絕對不可超過 50 字。
        3. ***POINTS*** 格式：『* **小標**：內容描述』。
        4. 除小標外，內文嚴禁標色。
        5. 【AI 自動分頁】：若重點超過 4 個，請務必在段落之間插入獨立一行的 `---` 來進行分頁。每一頁保持 3 到 4 個重點為佳。
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
        
        with st.spinner('AI 正在思考排版與分頁...'):
            response = model.generate_content(prompt)
            st.session_state['generated_draft'] = response.text
            st.success("文案處理完畢！已為您自動安排最佳分頁。")
    except Exception as e:
        st.error(f"文案生成失敗，請確認 API Key 是否設定正確。")

# 🟢 智慧多圖輪播引擎 (支援 `---` 與自動溢出保護)
def generate_carousel_images(base_img_bytes, t, i, p, ratio_type, accent_hex, opacity, font_scale):
    w = 1080
    h = 1920 if ratio_type == "限時動態 (Stories)" else 1350

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

    base_canvas = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    img.putalpha(int(255 * opacity))
    base_canvas.paste(img, (0, 0), img)

    gradient = Image.new('RGBA', (w, h))
    draw_grad = ImageDraw.Draw(gradient)
    for x in range(w):
        p_ratio = x / w
        if p_ratio <= 0.6:
            alpha_pct = 0.85 - ((0.85 - 0.6) * (p_ratio / 0.6))
        else:
            alpha_pct = 0.6 - ((0.6 - 0.2) * ((p_ratio - 0.6) / 0.4))
        draw_grad.line([(x, 0), (x, h)], fill=(0, 0, 0, int(255 * alpha_pct)))
    base_canvas = Image.alpha_composite(base_canvas, gradient)

    font_title = get_chinese_font(72 * font_scale)    
    font_insight = get_chinese_font(34 * font_scale)  
    font_points = get_chinese_font(36 * font_scale)   
    font_page = get_chinese_font(28 * font_scale)

    margin_x = 80
    max_text_width = w - (margin_x * 2) - 40 
    
    def get_text_size(text, font):
        try:
            if hasattr(font, 'getbbox'):
                bbox = font.getbbox(text)
                if bbox: return bbox[2] - bbox[0], bbox[3] - bbox[1]
        except: pass
        return len(text) * font.size, font.size

    def process_text(draw_obj, text, font, fill, max_w, start_x, start_y, line_height_mult=1.5, draw_mode=True):
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
                draw_obj.text((start_x, y), l, font=font, fill=fill)
            y += int(th * line_height_mult)
        return y

    pages = []
    current_canvas = base_canvas.copy()
    draw = ImageDraw.Draw(current_canvas)
    
    current_y = int(h * 0.231) 
    page_bottom_limit = h - int(150 * font_scale) 
    top_margin_subsequent = int(h * 0.15) 

    if t.strip():
        current_y = process_text(draw, t, font_title, "white", max_text_width, margin_x, current_y, 1.3)
        current_y += int(45 * font_scale)

    if i.strip():
        insight_x = margin_x + 30 
        insight_max_w = max_text_width - 30
        predicted_end_y = process_text(draw, i, font_insight, "#BBBBBB", insight_max_w, insight_x, current_y, 1.6, draw_mode=False)
        box_height = max(predicted_end_y - current_y, 30) 
        draw.rectangle([margin_x, current_y + 8, margin_x + 6, current_y + box_height - 15], fill=accent_hex)
        current_y = process_text(draw, i, font_insight, "#BBBBBB", insight_max_w, insight_x, current_y, 1.6)
        current_y += int(50 * font_scale)

    if p.strip():
        _, th_p = get_text_size("國", font_points)
        th_p = max(th_p, 30)
        line_height = int(th_p * 1.7)
        indent_w, _ = get_text_size("• ", font_points)

        for line in p.split('\n'):
            if not line.strip(): continue
            
            # 🟢 判斷是否需要換頁：支援 AI 的 --- 或是舊的 PAGE_BREAK
            if line.strip().startswith('---') or 'PAGE_BREAK' in line.upper():
                pages.append(current_canvas)
                current_canvas = base_canvas.copy()
                draw = ImageDraw.Draw(current_canvas)
                current_y = top_margin_subsequent 
                continue

            clean_line = line.strip()
            if clean_line.startswith('* '): clean_line = '• ' + clean_line[2:]
            elif not clean_line.startswith('•') and not clean_line.startswith('-'):
                clean_line = "• " + clean_line
            
            temp_x = margin_x
            lines_needed = 0
            parts = clean_line.split('**')
            for part in parts:
                for char in part:
                    cw, _ = get_text_size(char, font_points)
                    if temp_x + cw > margin_x + max_text_width:
                        temp_x = margin_x + indent_w
                        lines_needed += 1
                    temp_x += cw
            lines_needed += 1 
            
            estimated_point_height = (lines_needed * line_height) + int(20 * font_scale)
            
            # 高度防禦保護：如果這個重點畫不下了，系統自動切下一頁！
            if current_y + estimated_point_height > page_bottom_limit:
                pages.append(current_canvas)
                current_canvas = base_canvas.copy()
                draw = ImageDraw.Draw(current_canvas)
                current_y = top_margin_subsequent

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

    pages.append(current_canvas)

    if len(pages) > 1:
        for idx, page in enumerate(pages):
            d = ImageDraw.Draw(page)
            indicator = f"{idx + 1} / {len(pages)}"
            tw, _ = get_text_size(indicator, font_page)
            d.text(((w - tw) // 2, h - int(100 * font_scale)), indicator, font=font_page, fill="#777777")

    return pages

# 5. 渲染引擎
st.markdown("---")
st.header("Step 2. 合成與下載")
final_text = st.text_area("編輯區", value=st.session_state['generated_draft'], height=300)

if st.button("🖼️ 生成高品質圖卡"):
    if uploaded_file is None:
        st.warning("請先上傳圖片。")
    elif not final_text:
        st.warning("無內容。")
    else:
        with st.spinner('正在渲染多圖輪播畫布...'):
            try:
                def extract(text, tag):
                    pattern = rf"[\*]{{2,3}}{tag}[\*]{{2,3}}[:：\s]*(.*?)(?=\n\s*[\*]{{2,3}}\s*(?:TITLE|INSIGHT|POINTS)|$)"
                    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
                    return match.group(1).strip().lstrip(':').lstrip('：').strip() if match else ""

                t, i, p = extract(final_text, "TITLE"), extract(final_text, "INSIGHT"), extract(final_text, "POINTS")
                if not t:
                    t_match = re.search(r"^\*\*(.*?)\*\*", final_text)
                    if t_match: t = t_match.group(1)

                final_images = generate_carousel_images(uploaded_file.getvalue(), t, i, p, post_type, accent_color, img_opacity, font_scale)
                
                st.success(f"✅ 成功生成 {len(final_images)} 張圖卡！")
                st.info("📱 **手機用戶請直接對下方每張圖片「長按」並選擇「儲存圖片」。**")
                
                cols = st.columns(len(final_images))
                for idx, (col, img) in enumerate(zip(cols, final_images)):
                    with col:
                        st.image(img, use_container_width=True)
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        st.download_button(
                            label=f"📸 下載 圖 {idx+1}",
                            data=buf.getvalue(),
                            file_name=f"IG_Card_p{idx+1}_{int(time.time())}.png",
                            mime="image/png",
                            use_container_width=True,
                            key=f"dl_btn_{idx}"
                        )
                st.balloons()

            except Exception as e:
                st.error(f"渲染失敗：{e}")
