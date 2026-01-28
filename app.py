import streamlit as st
import pandas as pd
import time
import tempfile
import os
import sys
import asyncio
import logging

# --- إعدادات البيئة للسيرفر ---
@st.cache_resource
def install_playwright_browsers():
    # تثبيت المتصفح مع التبعيات اللازمة لنظام Linux/Streamlit Cloud
    os.system("playwright install chromium")
    os.system("playwright install-deps")

install_playwright_browsers()

# ضبط السياسة لنظام ويندوز فقط، وتجنبها على لينكس (السيرفر)
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# --- قائمة الدول الكاملة (كما هي في كودك) ---
countries = [
    "Afghanistan", "Albania", "Algeria", "Andorra", "Angola", "Antigua and Barbuda", "Argentina", "Armenia", "Australia", "Austria",
    "Azerbaijan", "Bahamas", "Bahrain", "Bangladesh", "Barbados", "Belarus", "Belgium", "Belize", "Benin", "Bhutan", "Bolivia",
    "Bosnia and Herzegovina", "Botswana", "Brazil", "Brunei", "Bulgaria", "Burkina Faso", "Burundi", "Cabo Verde", "Cambodia",
    "Cameroon", "Canada", "Central African Republic", "Chad", "Chile", "China", "Colombia", "Comoros", "Congo (Congo-Brazzaville)",
    "Costa Rica", "Côte d'Ivoire", "Croatia", "Cuba", "Cyprus", "Czechia (Czech Republic)", "Democratic Republic of the Congo",
    "Denmark", "Djibouti", "Dominica", "Dominican Republic", "Ecuador", "Egypt", "El Salvador", "Equatorial Guinea", "Eritrea",
    "Estonia", "Eswatini (fmr. \"Swaziland\")", "Ethiopia", "Fiji", "Finland", "France", "Gabon", "Gambia", "Georgia", "Germany",
    "Ghana", "Greece", "Grenada", "Guatemala", "Guinea", "Guinea-Bissau", "Guyana", "Haiti", "Holy See", "Honduras", "Hungary",
    "Iceland", "India", "Indonesia", "Iran", "Iraq", "Ireland", "Israel", "Italy", "Jamaica", "Japan", "Jordan", "Kazakhstan",
    "Kenya", "Kiribati", "Kuwait", "Kyrgyzstan", "Laos", "Latvia", "Lebanon", "Lesotho", "Liberia", "Libya", "Liechtenstein",
    "Lithuania", "Luxembourg", "Madagascar", "Malawi", "Malaysia", "Maldives", "Mali", "Malta", "Marshall Islands", "Mauritania",
    "Mauritius", "Mexico", "Micronesia", "Moldova", "Monaco", "Mongolia", "Montenegro", "Morocco", "Mozambique", "Myanmar (formerly Burma)",
    "Namibia", "Nauru", "Nepal", "Netherlands", "New Zealand", "Nicaragua", "Niger", "Nigeria", "North Korea", "North Macedonia",
    "Norway", "Oman", "Pakistan", "Palau", "Palestine State", "Panama", "Papua New Gecko", "Paraguay", "Peru", "Philippines",
    "Poland", "Portugal", "Qatar", "Romania", "Russia", "Rwanda", "Saint Kitts and Nevis", "Saint Lucia", "Saint Vincent and the Grenadines",
    "Samoa", "San Marino", "Sao Tome and Principe", "Saudi Arabia", "Senegal", "Serbia", "Seychelles", "Sierra Leone", "Singapore",
    "Slovakia", "Slovenia", "Solomon Islands", "Somalia", "South Africa", "South Korea", "South Sudan", "Spain", "Sri Lanka",
    "Sudan", "Suriname", "Sweden", "Switzerland", "Syrian Arab Republic", "Tajikistan", "Tanzania", "Thailand", "Timor-Leste",
    "Togo", "Tonga", "Trinidad and Tobago", "Tunisia", "Turkey", "Turkmenistan", "Tuvalu", "Uganda", "Ukraine", "United Arab Emirates",
    "United Kingdom", "United States of America", "Uruguay", "Uzbekistan", "Vanuatu", "Venezuela", "Vietnam", "Yemen", "Zambia", "Zimbabwe"
]

logging.basicConfig(level=logging.INFO)
st.set_page_config(page_title="ICP Passport Lookup", layout="wide")
st.title("🔍 ICP Passport Unified Number Lookup")

# --- إدارة حالة الجلسة ---
if 'authenticated' not in st.session_state: st.session_state.authenticated = False
if 'batch_results' not in st.session_state: st.session_state.batch_results = []
if 'final_summary_text' not in st.session_state: st.session_state.final_summary_text = ""
if 'passport_to_unified' not in st.session_state: st.session_state.passport_to_unified = {}
if 'unified_to_passport' not in st.session_state: st.session_state.unified_to_passport = {}
if 'single_res' not in st.session_state: st.session_state.single_res = None
if 'concurrency_level' not in st.session_state: st.session_state.concurrency_level = 3

# --- تسجيل الدخول ---
if not st.session_state.authenticated:
    with st.form("login_form"):
        st.subheader("🔐 Protected Access")
        pwd_input = st.text_input("Enter Password", type="password")
        if st.form_submit_button("Login"):
            if pwd_input == "Bilkish":
                st.session_state.authenticated = True
                st.rerun()
            else: st.error("Incorrect Password.")
    st.stop()

# --- دوال مساعدة ---
def format_time(seconds):
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"

def get_unique_result(passport_no, unified_str):
    if not unified_str or unified_str == "Not Found": return unified_str
    if unified_str in st.session_state.unified_to_passport:
        if st.session_state.unified_to_passport[unified_str] != passport_no: return "Not Found"
    st.session_state.passport_to_unified[passport_no] = unified_str
    st.session_state.unified_to_passport[unified_str] = passport_no
    return unified_str

def color_status(val):
    color = '#90EE90' if val == 'Found' else '#FFCCCB' if val == 'Not Found' else ''
    return f'background-color: {color}'

# --- وظائف البحث الرئيسية ---
async def search_single_passport_playwright(passport_no, nationality, target_url, context):
    page = await context.new_page()
    try:
        await page.goto(target_url, wait_until="networkidle", timeout=60000)
        try: await page.click("button:has-text('I Got It')", timeout=3000)
        except: pass
        
        await page.evaluate('document.querySelector("input[value=\'4\']").click()')
        
        try:
            await page.locator("//label[contains(.,'Passport Type')]/following::div[1]").click(timeout=5000)
            await page.keyboard.type("ORDINARY PASSPORT")
            await page.keyboard.press("Enter")
        except: pass

        await page.locator("input#passportNo").fill(str(passport_no))
        await page.keyboard.press("Tab")
        
        unified_number = "Not Found"
        try:
            async with page.expect_response("**/checkValidateLeavePermitRequest**", timeout=12000) as response_info:
                await page.locator("//label[contains(.,'Nationality')]/following::div[contains(@class,'ui-select-container')][1]").click()
                await page.keyboard.type(str(nationality), delay=60)
                await page.keyboard.press("Enter")
                
                resp = await response_info.value
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("unifiedNumber"): unified_number = str(data["unifiedNumber"]).strip()
        except: pass

        res = get_unique_result(passport_no, unified_number)
        await page.close()
        return res
    except:
        await page.close()
        return "ERROR"

async def search_batch_concurrent(df, url, concurrency_level, update_callback):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(user_agent="Mozilla/5.0")
        semaphore = asyncio.Semaphore(concurrency_level)
        
        results = [{"Passport Number": str(row['Passport Number']).strip(), 
                    "Nationality": str(row['Nationality']).strip().upper(),
                    "Unified Number": "", "Status": ""} for _, row in df.iterrows()]
        
        completed = 0
        found = 0
        
        async def worker(index):
            nonlocal completed, found
            async with semaphore:
                res = await search_single_passport_playwright(results[index]["Passport Number"], results[index]["Nationality"], url, context)
                results[index]["Unified Number"] = res
                results[index]["Status"] = "Found" if res not in ["Not Found", "ERROR"] else res
                completed += 1
                if results[index]["Status"] == "Found": found += 1
                await update_callback(completed, len(df), results, found)

        await asyncio.gather(*[worker(i) for i in range(len(df))])
        await browser.close()
        return results

# --- واجهة المستخدم ---
tab1, tab2 = st.tabs(["Single Search", "Upload Excel File"])

with tab1:
    st.subheader("🔍 Single Person Search")
    c1, c2 = st.columns(2)
    p_in = c1.text_input("Passport Number", key="s_p")
    n_in = c2.selectbox("Nationality", countries, key="s_n")
    if st.button("🔍 Search Now"):
        with st.spinner("Searching..."):
            url = "https://smartservices.icp.gov.ae/echannels/web/client/guest/index.html#/leavePermit/588/step1?administrativeRegionId=1&withException=false"
            
            async def run_single():
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    context = await browser.new_context()
                    return await search_single_passport_playwright(p_in, n_in, url, context)
            
            st.session_state.single_res = asyncio.run(run_single())
    
    if st.session_state.single_res:
        st.write(f"Result: {st.session_state.single_res}")

with tab2:
    uploaded_file = st.file_uploader("Upload Excel", type=["xlsx"])
    if uploaded_file:
        df = pd.read_excel(uploaded_file)
        concurrency = st.slider("Concurrency Level", 1, 5, st.session_state.concurrency_level)
        
        if st.button("🚀 Start Batch Search"):
            progress_bar = st.progress(0)
            status_area = st.empty()
            table_area = st.empty()
            start_time = time.time()

            async def update_ui(completed, total, results, found_count):
                progress_bar.progress(completed / total)
                elapsed = format_time(time.time() - start_time)
                summary = f"**Completed:** {completed}/{total} | **Found:** {found_count} | **Time:** {elapsed}"
                status_area.markdown(f"<div style='background:#E0F7FA;padding:10px;border-radius:5px;border-left:5px solid #00BCD4;'>{summary}</div>", unsafe_allow_html=True)
                table_area.dataframe(pd.DataFrame(results).style.applymap(color_status, subset=['Status']), use_container_width=True)

            url = "https://smartservices.icp.gov.ae/echannels/web/client/guest/index.html#/leavePermit/588/step1?administrativeRegionId=1&withException=false"
            
            # معالجة الـ Loop بشكل آمن للسيرفر
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            results = loop.run_until_complete(search_batch_concurrent(df, url, concurrency, update_ui))
            st.session_state.batch_results = results

    if st.session_state.batch_results:
        st.success("🏁 Done!")
        # زر التحميل كما هو في كودك
        res_df = pd.DataFrame(st.session_state.batch_results)
        excel_buffer = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
        res_df.to_excel(excel_buffer.name, index=False)
        with open(excel_buffer.name, "rb") as f:
            st.download_button("📥 Download Results", f, "ICP_Results.xlsx")
