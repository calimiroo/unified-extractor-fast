import streamlit as st
import pandas as pd
import time
import tempfile
import os
import sys
import asyncio
import logging

# --- تثبيت المتصفح مرة واحدة فقط عند بدء التطبيق ---
@st.cache_resource
def install_playwright_browsers():
    os.system("playwright install chromium")

install_playwright_browsers()

# ضبط سياسة الأحداث لتناسب نظام التشغيل (ويندوز أو لينكس/سيرفر)
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# --- قائمة الدول ---
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
    "Norway", "Oman", "Pakistan", "Palau", "Palestine State", "Panama", "Papua New Guinea", "Paraguay", "Peru", "Philippines",
    "Poland", "Portugal", "Qatar", "Romania", "Russia", "Rwanda", "Saint Kitts and Nevis", "Saint Lucia", "Saint Vincent and the Grenadines",
    "Samoa", "San Marino", "Sao Tome and Principe", "Saudi Arabia", "Senegal", "Serbia", "Seychelles", "Sierra Leone", "Singapore",
    "Slovakia", "Slovenia", "Solomon Islands", "Somalia", "South Africa", "South Korea", "South Sudan", "Spain", "Sri Lanka",
    "Sudan", "Suriname", "Sweden", "Switzerland", "Syrian Arab Republic", "Tajikistan", "Tanzania", "Thailand", "Timor-Leste",
    "Togo", "Tonga", "Trinidad and Tobago", "Tunisia", "Turkey", "Turkmenistan", "Tuvalu", "Uganda", "Ukraine", "United Arab Emirates",
    "United Kingdom", "United States of America", "Uruguay", "Uzbekistan", "Vanuatu", "Venezuela", "Vietnam", "Yemen", "Zambia", "Zimbabwe"
]

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)

# --- Setup Page Config ---
st.set_page_config(page_title="ICP Passport Lookup", layout="wide")
st.title("🔍 ICP Passport Unified Number Lookup")

# --- Session State Management ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'run_state' not in st.session_state:
    st.session_state.run_state = 'stopped'
if 'batch_results' not in st.session_state:
    st.session_state.batch_results = []
if 'final_summary_text' not in st.session_state:
    st.session_state.final_summary_text = ""
if 'passport_to_unified' not in st.session_state:
    st.session_state.passport_to_unified = {}
if 'unified_to_passport' not in st.session_state:
    st.session_state.unified_to_passport = {}
if 'concurrency_level' not in st.session_state:
    st.session_state.concurrency_level = 5

# --- Login Form ---
if not st.session_state.authenticated:
    with st.form("login_form"):
        st.subheader("🔐 Protected Access")
        pwd_input = st.text_input("Enter Password", type="password")
        if st.form_submit_button("Login"):
            if pwd_input == "Bilkish":
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Incorrect Password.")
    st.stop()

# --- Helper Functions ---
def format_time(seconds):
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def reset_duplicate_trackers():
    st.session_state.passport_to_unified = {}
    st.session_state.unified_to_passport = {}

def get_unique_result(passport_no, unified_str):
    if not unified_str or unified_str == "Not Found":
        return unified_str
    if unified_str in st.session_state.unified_to_passport:
        existing_passport = st.session_state.unified_to_passport[unified_str]
        if existing_passport != passport_no:
            return "Not Found"
    st.session_state.passport_to_unified[passport_no] = unified_str
    st.session_state.unified_to_passport[unified_str] = passport_no
    return unified_str

def color_status(val):
    if val == 'Found': color = '#90EE90'
    elif val == 'Not Found': color = '#FFCCCB'
    else: color = '' 
    return f'background-color: {color}'

async def search_single_passport_playwright(passport_no, nationality, target_url, context):
    page = await context.new_page()
    try:
        await page.goto(target_url, wait_until="networkidle", timeout=60000)
        try:
            await page.click("button:has-text('I Got It')", timeout=2000)
        except: pass

        await page.evaluate("""() => {
            const el = document.querySelector("input[value='4']");
            if (el) { el.click(); el.dispatchEvent(new Event('change', { bubbles: true })); }
        }""")
        
        try:
            await page.locator("//label[contains(.,'Passport Type')]/following::div[1]").click(timeout=5000)
            await page.keyboard.type("ORDINARY PASSPORT")
            await page.keyboard.press("Enter")
        except: pass

        await page.locator("input#passportNo").fill(passport_no)
        try:
            await page.locator('div[name="currentNationality"] button[ng-if="showClear"]').click(force=True, timeout=2000)
        except: pass
        
        await page.keyboard.press("Tab")
        unified_number = "Not Found"
        
        try:
            async with page.expect_response("**/checkValidateLeavePermitRequest**", timeout=10000) as response_info:
                await page.locator("//label[contains(.,'Nationality')]/following::div[contains(@class,'ui-select-container')][1]").click(timeout=5000)
                await page.keyboard.type(nationality, delay=50)
                await page.keyboard.press("Enter")
                
                response = await response_info.value
                if response.status == 200:
                    json_data = await response.json()
                    raw_unified = json_data.get("unifiedNumber")
                    if raw_unified:
                        unified_number = str(raw_unified).strip()
        except: pass

        final_result = get_unique_result(passport_no, unified_number)
        await page.close()
        return final_result
    except Exception as e:
        await page.close()
        return "ERROR"

async def search_batch_concurrent(df, url, concurrency_level, update_callback):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1366, 'height': 768})
        semaphore = asyncio.Semaphore(concurrency_level)
        
        results = [{"Passport Number": str(row['Passport Number']).strip(), 
                    "Nationality": str(row['Nationality']).strip().upper(),
                    "Unified Number": "", "Status": ""} for _, row in df.iterrows()]
        
        completed_count = 0
        found_count = 0
        
        async def run_single_search(index):
            nonlocal completed_count, found_count
            async with semaphore:
                p_num = results[index]["Passport Number"]
                nat = results[index]["Nationality"]
                res = await search_single_passport_playwright(p_num, nat, url, context)
                
                status_val = "Found" if res not in ["Not Found", "ERROR"] else res
                results[index]["Unified Number"] = res
                results[index]["Status"] = status_val
                
                completed_count += 1
                if status_val == "Found": found_count += 1
                await update_callback(completed_count, len(df), results, found_count)

        tasks = [run_single_search(i) for i in range(len(df))]
        await asyncio.gather(*tasks)
        await browser.close()
        return results

# --- UI Tabs ---
tab1, tab2 = st.tabs(["Single Search", "Upload Excel File"])

with tab1:
    st.subheader("🔍 Single Person Search")
    c1, c2 = st.columns(2)
    p_in = c1.text_input("Passport Number")
    n_in = c2.selectbox("Nationality", countries)
    if st.button("🔍 Search Now"):
        with st.spinner("Searching..."):
            url = "https://smartservices.icp.gov.ae/echannels/web/client/guest/index.html#/leavePermit/588/step1?administrativeRegionId=1&withException=false"
            async def single_run():
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    context = await browser.new_context()
                    res = await search_single_passport_playwright(p_in, n_in, url, context)
                    await browser.close()
                    return res
            res = asyncio.run(single_run())
            if res == "Found" or (res != "Not Found" and res != "ERROR"):
                st.success(f"Found: {res}")
            else: st.error(res)

with tab2:
    uploaded_file = st.file_uploader("Upload Excel", type=["xlsx"])
    if uploaded_file:
        df = pd.read_excel(uploaded_file)
        concurrency = st.slider("Concurrency", 1, 10, st.session_state.concurrency_level)
        
        if st.button("🚀 Start Batch"):
            progress_bar = st.progress(0)
            status_area = st.empty()
            table_area = st.empty()
            start_t = time.time()

            async def update_ui(completed, total, results, found):
                progress_bar.progress(completed / total)
                elapsed = format_time(time.time() - start_t)
                html = f"<div style='background:#E0F7FA;padding:10px;border-radius:5px;'>Completed: {completed}/{total} | Found: {found} | Time: {elapsed}</div>"
                status_area.markdown(html, unsafe_allow_html=True)
                table_area.dataframe(pd.DataFrame(results).style.applymap(color_status, subset=['Status']), use_container_width=True)

            url = "https://smartservices.icp.gov.ae/echannels/web/client/guest/index.html#/leavePermit/588/step1?administrativeRegionId=1&withException=false"
            final_res = asyncio.run(search_batch_concurrent(df, url, concurrency, update_ui))
            st.session_state.batch_results = final_res
            st.success("Batch Completed!")
