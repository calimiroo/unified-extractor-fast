import streamlit as st
import pandas as pd
import asyncio
import os
import sys
import tempfile
import logging
from playwright.async_api import async_playwright

# --- إعدادات السيرفر ---
@st.cache_resource
def install_browsers():
    os.system("playwright install chromium")
    os.system("playwright install-deps")

install_browsers()

# قائمة الدول (مختصرة هنا ولكن استخدم القائمة الكاملة في كودك)
countries = ["India", "Pakistan", "Egypt", "United Arab Emirates", "Jordan"] 

# --- الكود المحسن للبحث المستقر ---
async def fetch_unified_number(passport_no, nationality, url, browser_context):
    # استخدام context جديد لكل صفحة لضمان عدم تداخل الكوكيز
    page = await browser_context.new_page()
    try:
        # تقليل وقت الانتظار الكلي لتجنب تعليق السيرفر
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        
        # محاولة إغلاق الرسائل المنبثقة
        try: await page.click("button:has-text('I Got It')", timeout=2000)
        except: pass

        # اختيار نظام الجواز
        await page.evaluate('document.querySelector("input[value=\'4\']").click()')
        
        # ملء رقم الجواز
        await page.wait_for_selector("input#passportNo", timeout=10000)
        await page.fill("input#passportNo", str(passport_no))
        await page.keyboard.press("Tab")

        unified = "Not Found"
        try:
            # انتظار الاستجابة من السيرفر مباشرة
            async with page.expect_response("**/checkValidateLeavePermitRequest**", timeout=15000) as resp_info:
                await page.locator("//label[contains(.,'Nationality')]/following::div[1]").click()
                await page.keyboard.type(str(nationality), delay=100)
                await page.keyboard.press("Enter")
                
                resp = await resp_info.value
                if resp.status == 200:
                    data = await resp.json()
                    unified = str(data.get("unifiedNumber", "Not Found"))
        except:
            unified = "Check Captcha/Timeout"

        return unified
    except Exception as e:
        return f"Error"
    finally:
        # إغلاق الصفحة فوراً هو أهم خطوة لمنع توقف البحث
        await page.close()

async def run_batch(df, concurrency):
    async with async_playwright() as p:
        # تشغيل المتصفح بإعدادات حفظ الذاكرة
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(user_agent="Mozilla/5.0")
        
        semaphore = asyncio.Semaphore(concurrency)
        results = []
        
        async def safe_search(row, i):
            async with semaphore:
                res = await fetch_unified_number(row['Passport Number'], row['Nationality'], target_url, context)
                results.append({"Passport Number": row['Passport Number'], "Unified Number": res, "Status": "Done"})

        target_url = "https://smartservices.icp.gov.ae/echannels/web/client/guest/index.html#/leavePermit/588/step1?administrativeRegionId=1&withException=false"
        tasks = [safe_search(row, i) for i, row in df.iterrows()]
        await asyncio.gather(*tasks)
        await browser.close()
        return results

# --- واجهة المستخدم ---
st.title("🚀 ICP Ultra-Stable Extractor")

uploaded_file = st.file_uploader("Upload Excel", type=["xlsx"])
if uploaded_file:
    df_input = pd.read_excel(uploaded_file)
    st.dataframe(df_input.head())
    
    # نصيحة: للأعداد الكبيرة، اجعل Concurrency بين 2 و 4
    concurrency = st.slider("Concurrency (Keep it low for stability)", 1, 5, 2)
    
    if st.button("Start Processing"):
        with st.spinner("Processing..."):
            # تشغيل الـ Loop بطريقة متوافقة مع Streamlit
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            final_results = loop.run_until_complete(run_batch(df_input, concurrency))
            
            st.session_state.results = final_results
            st.success("Finished!")

if 'results' in st.session_state:
    res_df = pd.DataFrame(st.session_state.results)
    st.dataframe(res_df)
