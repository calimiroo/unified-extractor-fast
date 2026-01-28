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
    # محاولة تثبيت التبعيات والمتصفح
    os.system("playwright install chromium")
    os.system("playwright install-deps")

install_playwright_browsers()

# ضبط السياسة لنظام ويندوز
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# --- قائمة الدول ---
countries = ["Afghanistan", "Albania", "Algeria", "Andorra", "Angola", "Antigua and Barbuda", "Argentina", "Armenia", "Australia", "Austria", "Azerbaijan", "Bahamas", "Bahrain", "Bangladesh", "Barbados", "Belarus", "Belgium", "Belize", "Benin", "Bhutan", "Bolivia", "Bosnia and Herzegovina", "Botswana", "Brazil", "Brunei", "Bulgaria", "Burkina Faso", "Burundi", "Cabo Verde", "Cambodia", "Cameroon", "Canada", "Central African Republic", "Chad", "Chile", "China", "Colombia", "Comoros", "Congo (Congo-Brazzaville)", "Costa Rica", "Côte d'Ivoire", "Croatia", "Cuba", "Cyprus", "Czechia (Czech Republic)", "Democratic Republic of the Congo", "Denmark", "Djibouti", "Dominica", "Dominican Republic", "Ecuador", "Egypt", "El Salvador", "Equatorial Guinea", "Eritrea", "Estonia", "Eswatini (fmr. \"Swaziland\")", "Ethiopia", "Fiji", "Finland", "France", "Gabon", "Gambia", "Georgia", "Germany", "Ghana", "Greece", "Grenada", "Guatemala", "Guinea", "Guinea-Bissau", "Guyana", "Haiti", "Holy See", "Honduras", "Hungary", "Iceland", "India", "Indonesia", "Iran", "Iraq", "Ireland", "Israel", "Italy", "Jamaica", "Japan", "Jordan", "Kazakhstan", "Kenya", "Kiribati", "Kuwait", "Kyrgyzstan", "Laos", "Latvia", "Lebanon", "Lesotho", "Liberia", "Libya", "Liechtenstein", "Lithuania", "Luxembourg", "Madagascar", "Malawi", "Malaysia", "Maldives", "Mali", "Malta", "Marshall Islands", "Mauritania", "Mauritius", "Mexico", "Micronesia", "Moldova", "Monaco", "Mongolia", "Montenegro", "Morocco", "Mozambique", "Myanmar (formerly Burma)", "Namibia", "Nauru", "Nepal", "Netherlands", "New Zealand", "Nicaragua", "Niger", "Nigeria", "North Korea", "North Macedonia", "Norway", "Oman", "Pakistan", "Palau", "Palestine State", "Panama", "Papua New Guinea", "Paraguay", "Peru", "Philippines", "Poland", "Portugal", "Qatar", "Romania", "Russia", "Rwanda", "Saint Kitts and Nevis", "Saint Lucia", "Saint Vincent and the Grenadines", "Samoa", "San Marino", "Sao Tome and Principe", "Saudi Arabia", "Senegal", "Serbia", "Seychelles", "Sierra Leone", "Singapore", "Slovakia", "Slovenia", "Solomon Islands", "Somalia", "South Africa", "South Korea", "South Sudan", "Spain", "Sri Lanka", "Sudan", "Suriname", "Sweden", "Switzerland", "Syrian Arab Republic", "Tajikistan", "Tanzania", "Thailand", "Timor-Leste", "Togo", "Tonga", "Trinidad and Tobago", "Tunisia", "Turkey", "Turkmenistan", "Tuvalu", "Uganda", "Ukraine", "United Arab Emirates", "United Kingdom", "United States of America", "Uruguay", "Uzbekistan", "Vanuatu", "Venezuela", "Vietnam", "Yemen", "Zambia", "Zimbabwe"]

logging.basicConfig(level=logging.INFO)
st.set_page_config(page_title="ICP Passport Lookup", layout="wide")
st.title("🔍 ICP Passport Unified Number Lookup")

# --- Session State ---
if 'authenticated' not in st.session_state: st.session_state.authenticated = False
if 'batch_results' not in st.session_state: st.session_state.batch_results = []
if 'passport_to_unified' not in st.session_state: st.session_state.passport_to_unified = {}
if 'unified_to_passport' not in st.session_state: st.session_state.unified_to_passport = {}

# --- Login ---
if not st.session_state.authenticated:
    with st.form("login_form"):
        pwd_input = st.text_input("Enter Password", type="password")
        if st.form_submit_button("Login") and pwd_input == "Bilkish":
            st.session_state.authenticated = True
            st.rerun()
    st.stop()

# --- Functions ---
def color_status(val):
    color = '#90EE90' if val == 'Found' else '#FFCCCB' if val == 'Not Found' else ''
    return f'background-color: {color}'

async def search_single_passport(passport_no, nationality, target_url, context):
    page = await context.new_page()
    try:
        await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
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
            async with page.expect_response("**/checkValidateLeavePermitRequest**", timeout=15000) as response_info:
                await page.locator("//label[contains(.,'Nationality')]/following::div[contains(@class,'ui-select-container')][1]").click()
                await page.keyboard.type(str(nationality), delay=70)
                await page.keyboard.press("Enter")
                
                resp = await response_info.value
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("unifiedNumber"): unified_number = str(data["unifiedNumber"]).strip()
        except: pass

        await page.close()
        return unified_number
    except:
        await page.close()
        return "ERROR"

async def search_batch_concurrent(df, url, concurrency_level, update_callback):
    async with async_playwright() as p:
        # إضافة args ضرورية لسيرفرات Linux
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        semaphore = asyncio.Semaphore(concurrency_level)
        
        results = [{"Passport Number": str(row['Passport Number']).strip(), 
                    "Nationality": str(row['Nationality']).strip().upper(),
                    "Unified Number": "", "Status": ""} for _, row in df.iterrows()]
        
        completed = 0
        found = 0
        
        async def worker(index):
            nonlocal completed, found
            async with semaphore:
                res = await search_single_passport(results[index]["Passport Number"], results[index]["Nationality"], url, context)
                results[index]["Unified Number"] = res
                results[index]["Status"] = "Found" if res not in ["Not Found", "ERROR"] else res
                completed += 1
                if results[index]["Status"] == "Found": found += 1
                await update_callback(completed, len(df), results, found)

        await asyncio.gather(*[worker(i) for i in range(len(df))])
        await browser.close()
        return results

# --- UI ---
tab1, tab2 = st.tabs(["Single Search", "Upload Excel File"])

with tab1:
    p_in = st.text_input("Passport Number")
    n_in = st.selectbox("Nationality", countries)
    if st.button("Search"):
        url = "https://smartservices.icp.gov.ae/echannels/web/client/guest/index.html#/leavePermit/588/step1?administrativeRegionId=1&withException=false"
        async def run_s():
            async with async_playwright() as p:
                b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
                c = await b.new_context()
                return await search_single_passport(p_in, n_in, url, c)
        res = asyncio.run(run_s())
        st.write(f"Result: {res}")

with tab2:
    uploaded_file = st.file_uploader("Upload Excel", type=["xlsx"])
    if uploaded_file:
        df_input = pd.read_excel(uploaded_file)
        st.subheader("Data Preview")
        st.dataframe(df_input, use_container_width=True) # عرض الجدول المرفوع فوراً
        
        concurrency = st.slider("Concurrency", 1, 5, 3)
        
        if st.button("🚀 Start Batch"):
            progress_bar = st.progress(0)
            status_area = st.empty()
            table_area = st.empty()
            start_time = time.time()

            async def update_ui(completed, total, results, found_count):
                progress_bar.progress(completed / total)
                elapsed = int(time.time() - start_time)
                status_area.info(f"Completed: {completed}/{total} | Found: {found_count} | Time: {elapsed}s")
                table_area.dataframe(pd.DataFrame(results).style.applymap(color_status, subset=['Status']), use_container_width=True)

            url = "https://smartservices.icp.gov.ae/echannels/web/client/guest/index.html#/leavePermit/588/step1?administrativeRegionId=1&withException=false"
            
            # حل مشكلة الـ Loop على السيرفر
            try:
                results = asyncio.run(search_batch_concurrent(df_input, url, concurrency, update_ui))
                st.session_state.batch_results = results
                st.success("Batch Completed!")
            except Exception as e:
                st.error(f"Error: {str(e)}")

    if st.session_state.batch_results:
        res_df = pd.DataFrame(st.session_state.batch_results)
        excel_buffer = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
        res_df.to_excel(excel_buffer.name, index=False)
        with open(excel_buffer.name, "rb") as f:
            st.download_button("📥 Download Results", f, "ICP_Results.xlsx")
