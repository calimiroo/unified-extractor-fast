import streamlit as st
import pandas as pd
import asyncio
import os
import sys
from playwright.async_api import async_playwright

# دالة محسنة للبحث للتعامل مع الأعداد الكبيرة
async def search_single_passport_safe(passport_no, nationality, target_url, browser_context):
    # إنشاء صفحة جديدة لكل عملية لضمان عدم تداخل البيانات
    page = await browser_context.new_page()
    try:
        # زيادة وقت الانتظار قليلاً للتعامل مع بطء السيرفر
        await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
        
        # التأكد من إغلاق أي رسائل منبثقة
        try:
            await page.click("button:has-text('I Got It')", timeout=3000)
        except: pass

        # اختيار "رقم الجواز"
        await page.evaluate('document.querySelector("input[value=\'4\']").click()')
        
        # تعبئة البيانات
        await page.locator("input#passportNo").fill(str(passport_no))
        
        # اختيار الجنسية مع انتظار الاستجابة
        unified_number = "Not Found"
        try:
            async with page.expect_response("**/checkValidateLeavePermitRequest**", timeout=20000) as response_info:
                await page.locator("//label[contains(.,'Nationality')]/following::div[1]").click()
                await page.keyboard.type(str(nationality), delay=100)
                await page.keyboard.press("Enter")
                
                resp = await response_info.value
                if resp.status == 200:
                    data = await resp.json()
                    unified_number = str(data.get("unifiedNumber", "Not Found"))
        except:
            unified_number = "Timeout/Captcha" # غالباً سبب التوقف هو ظهور كابتشا

        return unified_number
    except Exception as e:
        return f"Error: {str(e)[:50]}"
    finally:
        # حاسم جداً: إغلاق الصفحة فوراً لتحرير الرام
        await page.close()

async def batch_process_v2(df, concurrency_limit, update_callback):
    async with async_playwright() as p:
        # تشغيل المتصفح مع إعدادات تقليل استهلاك الرام
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--single-process"])
        context = await browser.new_context()
        
        semaphore = asyncio.Semaphore(concurrency_limit)
        results = []
        
        async def worker(row_data, index):
            async with semaphore:
                res = await search_single_passport_safe(row_data['Passport Number'], row_data['Nationality'], url, context)
                results.append({"Passport": row_data['Passport Number'], "Unified": res})
                await update_callback(len(results), len(df))

        tasks = [worker(row, i) for i, row in df.iterrows()]
        await asyncio.gather(*tasks)
        await browser.close()
        return results
