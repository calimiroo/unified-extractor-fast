import streamlit as st
import pandas as pd
import time
import tempfile
import os
import sys
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

# --- تثبيت المتصفح مرة واحدة فقط عند بدء التطبيق ---
@st.cache_resource
def install_playwright_browsers():
    os.system("playwright install chromium")

install_playwright_browsers()

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# --- API Key for 2Captcha ---
CAPTCHA_API_KEY = "5d4de2d9ba962a796040bd90b2cac6da"

# --- مكتبة 2Captcha ---
try:
    from twocaptcha import TwoCaptcha
    TWO_CAPTCHA_AVAILABLE = True
except ImportError:
    TWO_CAPTCHA_AVAILABLE = False
    logging.warning("twocaptcha not installed. CAPTCHA solving will be skipped.")

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
if 'start_time_ref' not in st.session_state:
    st.session_state.start_time_ref = None
if 'passport_to_unified' not in st.session_state:
    st.session_state.passport_to_unified = {}
if 'unified_to_passport' not in st.session_state:
    st.session_state.unified_to_passport = {}
if 'single_res' not in st.session_state:
    st.session_state.single_res = None
if 'single_deep_res' not in st.session_state:
    st.session_state.single_deep_res = None
if 'deep_processed' not in st.session_state:
    st.session_state.deep_processed = 0
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
                st.session_state.batch_results = []
                st.session_state.passport_to_unified = {}
                st.session_state.unified_to_passport = {}
                st.session_state.single_res = None
                st.session_state.single_deep_res = None
                st.session_state.deep_processed = 0
                st.rerun()
            else:
                st.error("Incorrect Password.")
    st.stop()

# --- Helper Functions ---
def format_time(seconds):
    """Format time to show hours, minutes, seconds without days."""
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
            logging.warning(f"Duplicate Unified Number '{unified_str}' for different passport")
            return "Not Found"
    st.session_state.passport_to_unified[passport_no] = unified_str
    st.session_state.unified_to_passport[unified_str] = passport_no
    return unified_str

def color_status(val):
    if val == 'Found':
        color = '#90EE90' # Light Green
    elif val == 'Not Found':
        color = '#FFCCCB' # Light Red
    else:
        color = '' 
    return f'background-color: {color}'

async def solve_captcha(page):
    """Solve reCAPTCHA or Cloudflare Turnstile using 2Captcha"""
    if not TWO_CAPTCHA_AVAILABLE:
        return False
    solver = TwoCaptcha(CAPTCHA_API_KEY)
    solved = False
    try:
        if await page.locator("div.g-recaptcha").is_visible(timeout=5000):
            sitekey = await page.locator("div.g-recaptcha").get_attribute("data-sitekey", timeout=5000)
            result = solver.recaptcha(sitekey=sitekey, url=page.url)
            code = result['code']
            await page.evaluate(f'''() => {{
                document.getElementById("g-recaptcha-response").value = "{code}";
            }}''')
            logging.info("✅ reCAPTCHA solved successfully")
            solved = True
    except Exception as e:
        logging.warning(f"⚠️ reCAPTCHA solve failed: {e}")
    try:
        if await page.locator('iframe[src*="turnstile"]').is_visible(timeout=5000):
            iframe = page.frame_locator('iframe[src*="turnstile"]')
            widget = iframe.locator('textarea[hidden]')
            if await widget.count() > 0:
                sitekey = await widget.first.get_attribute('data-sitekey', timeout=5000)
                result = solver.turnstile(sitekey=sitekey, url=page.url)
                code = result['code']
                await page.evaluate(f'''() => {{
                    const textarea = document.querySelector('textarea[data-post-hook]');
                    if (textarea) {{ textarea.value = "{code}"; }}
                }}''')
                logging.info("✅ Cloudflare Turnstile solved successfully")
                solved = True
    except Exception as e:
        logging.warning(f"⚠️ Cloudflare Turnstile solve failed: {e}")
    return solved

async def search_single_passport_playwright(passport_no, nationality, target_url, context):
    page = await context.new_page()
    try:
        await page.goto(target_url, wait_until="networkidle", timeout=60000)
        await solve_captcha(page)
        try:
            await page.click("button:has-text('I Got It')", timeout=2000)
        except:
            pass
        await page.evaluate("""() => {
            const el = document.querySelector("input[value='4']");
            if (el) { el.click(); el.dispatchEvent(new Event('change', { bubbles: true })); }
        }""")
        try:
            await page.locator("//label[contains(.,'Passport Type')]/following::div[1]").click(timeout=10000)
            await page.keyboard.type("ORDINARY PASSPORT")
            await page.keyboard.press("Enter")
        except:
            pass
        await page.locator("input#passportNo").fill(passport_no)
        try:
            await page.locator('div[name="currentNationality"] button[ng-if="showClear"]').click(force=True, timeout=5000)
        except:
            pass
        await page.keyboard.press("Tab")
        unified_number = "Not Found"
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
            async with page.expect_response("**/checkValidateLeavePermitRequest**", timeout=10000) as response_info:
                await page.locator("//label[contains(.,'Nationality')]/following::div[contains(@class,'ui-select-container')][1]").click(timeout=10000)
                await page.keyboard.type(nationality, delay=50)
                await page.keyboard.press("Enter")
                response = await response_info.value
                if response.status == 200:
                    json_data = await response.json()
                    raw_unified = json_data.get("unifiedNumber")
                    if raw_unified:
                        unified_number = str(raw_unified).strip()
        except Exception as e:
            logging.warning(f"Basic search error for {passport_no}: {e}")
        final_result = get_unique_result(passport_no, unified_number)
        await page.close()
        return final_result
    except Exception as e:
        logging.error(f"Critical error for {passport_no}: {e}")
        await page.close()
        return "ERROR"

async def search_batch_concurrent(df, url, concurrency_level=5, update_callback=None):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1366, 'height': 768},
                                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        semaphore = asyncio.Semaphore(concurrency_level)
        results = [
            {
                "Passport Number": str(row['Passport Number']).strip(),
                "Nationality": str(row['Nationality']).strip().upper(),
                "Unified Number": "",
                "Status": ""
            } for _, row in df.iterrows()
        ]
        completed_count = 0
        found_count = 0
        
        async def run_single_search(index, row):
            nonlocal completed_count, found_count
            async with semaphore:
                p_num = results[index]["Passport Number"]
                nat = results[index]["Nationality"]
                res = await search_single_passport_playwright(p_num, nat, url, context)
                status_val = "Found" if res not in ["Not Found", "ERROR"] else res if res == "ERROR" else "Not Found"
                
                results[index]["Unified Number"] = res
                results[index]["Status"] = status_val
                
                completed_count += 1
                if status_val == "Found":
                    found_count += 1
                
                if update_callback:
                    await update_callback(completed_count, len(df), results, found_count)
                
                return results[index]

        tasks = [run_single_search(i, row) for i, (_, row) in enumerate(df.iterrows())]
        await asyncio.gather(*tasks, return_exceptions=True)
        await browser.close()
        return results

async def run_single_search_from_ui(p_in, n_in, url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1366, 'height': 768},
                                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        res = await search_single_passport_playwright(p_in.strip(), n_in.strip().upper(), url, context)
        await browser.close()
        return res

async def run_batch_search_with_updates(df, url, concurrency_level, progress_bar, combined_status_area, live_table_area):
    reset_duplicate_trackers()
    start_time = time.time()
    
    async def update_ui(completed, total, results, found_count):
        progress_bar.progress(completed / total)
        elapsed = time.time() - start_time
        time_str = format_time(elapsed)
        
        # النص المطلوب بدون تكرار
        summary_text = f"**Completed:** {completed}/{total} | **Found:** {found_count} | **Time Elapsed:** {time_str}"
        
        # تنسيق الشريط بلون سماوي فاتح
        styled_html = f"""
        <div style="background-color: #E0F7FA; padding: 10px; border-radius: 5px; border-left: 5px solid #00BCD4; color: #006064; font-family: sans-serif;">
            {summary_text}
        </div>
        """
        
        combined_status_area.markdown(styled_html, unsafe_allow_html=True)
        st.session_state.final_summary_text = styled_html
        
        current_df = pd.DataFrame(results)
        styled_df = current_df.style.applymap(color_status, subset=['Status'])
        live_table_area.dataframe(styled_df, use_container_width=True, height=400)

    results = await search_batch_concurrent(df, url, concurrency_level, update_ui)
    return results, time.time() - start_time

# --- UI Tabs ---
tab1, tab2 = st.tabs(["Single Search", "Upload Excel File"])

with tab1:
    st.subheader("🔍 Single Person Search")
    c1, c2 = st.columns(2)
    p_in = c1.text_input("Passport Number", key="s_p")
    n_in = c2.selectbox("Nationality (Country Name)", countries, key="s_n")
    if st.button("🔍 Search Now"):
        if p_in and n_in:
            with st.spinner("Searching for Unified Number..."):
                url = "https://smartservices.icp.gov.ae/echannels/web/client/guest/index.html#/leavePermit/588/step1?administrativeRegionId=1&withException=false "
                res = asyncio.run(run_single_search_from_ui(p_in, n_in, url))
                st.session_state.single_res = res
                st.session_state.single_deep_res = None
            st.rerun()
        else:
            st.error("Please enter Passport Number and Nationality.")
    
    res = st.session_state.get('single_res', None)
    if res is not None:
        st.subheader("Result:")
        if res == "Not Found":
            st.markdown("<h3 style='color:red;'>Not Found</h3>", unsafe_allow_html=True)
        elif res == "ERROR":
            st.markdown("<h3 style='color:red;'>Error Occurred</h3>", unsafe_allow_html=True)
        else:
            st.markdown(f"<h3 style='color:green;'>Found: {res}</h3>", unsafe_allow_html=True)

with tab2:
    st.subheader("📊 Batch Processing Control")
    uploaded_file = st.file_uploader("Upload Excel (Columns: 'Passport Number', 'Nationality')", type=["xlsx"])
    
    if uploaded_file:
        df = pd.read_excel(uploaded_file)
        st.write(f"Total records in file: {len(df)}")
        st.dataframe(df, height=150)
        required_cols = ['Passport Number', 'Nationality']
        
        if not all(col in df.columns for col in required_cols):
            st.error(f"The file must contain the following columns: {required_cols}")
        else:
            concurrency_level = st.slider("Concurrency Level", min_value=1, max_value=10, value=st.session_state.concurrency_level)
            st.session_state.concurrency_level = concurrency_level
            
            col_ctrl1, col_ctrl2, col_ctrl3 = st.columns(3)
            
            progress_bar = st.progress(0)
            combined_status_area = st.empty()
            
            # عرض الحالة النهائية أو الحالية بالشكل الملون
            if st.session_state.final_summary_text:
                combined_status_area.markdown(st.session_state.final_summary_text, unsafe_allow_html=True)

            live_table_area = st.empty()
            
            if col_ctrl1.button("🚀 Start Batch Search"):
                st.session_state.run_state = 'running'
                st.session_state.final_summary_text = "" 
                
                initial_results = [
                    {
                        "Passport Number": str(row['Passport Number']).strip(),
                        "Nationality": str(row['Nationality']).strip().upper(),
                        "Unified Number": "",
                        "Status": ""
                    } for _, row in df.iterrows()
                ]
                initial_df = pd.DataFrame(initial_results)
                styled_initial_df = initial_df.style.applymap(color_status, subset=['Status'])
                live_table_area.dataframe(styled_initial_df, use_container_width=True, height=400)
                
                with st.spinner("Running batch search..."):
                    url = "https://smartservices.icp.gov.ae/echannels/web/client/guest/index.html#/leavePermit/588/step1?administrativeRegionId=1&withException=false "
                    results, total_time = asyncio.run(run_batch_search_with_updates(df, url, concurrency_level, progress_bar, combined_status_area, live_table_area))
                    st.session_state.batch_results = results
                
                st.rerun()

            if col_ctrl2.button("⏸️ Pause"):
                st.session_state.run_state = 'paused'
                st.rerun()

            if col_ctrl3.button("⏹️ Stop & Reset"):
                st.session_state.run_state = 'stopped'
                st.session_state.batch_results = []
                st.session_state.final_summary_text = ""
                st.session_state.start_time_ref = None
                st.session_state.deep_processed = 0
                st.rerun()

            if st.session_state.batch_results:
                st.subheader("Batch Results")
                filtered_results = [r for r in st.session_state.batch_results if r is not None]
                if filtered_results:
                    current_df = pd.DataFrame(filtered_results)
                    styled_df = current_df.style.applymap(color_status, subset=['Status'])
                    st.dataframe(styled_df, use_container_width=True, height=400)
                    
                    excel_buffer = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
                    with pd.ExcelWriter(excel_buffer.name, engine='openpyxl') as writer:
                        current_df.to_excel(writer, index=False, sheet_name='Results')
                    with open(excel_buffer.name, "rb") as f:
                        st.download_button(
                            label="📥 Download Results (Excel)",
                            data=f,
                            file_name="ICP_Batch_Results.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
