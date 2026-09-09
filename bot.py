import asyncio
import html
from http.server import HTTPServer, SimpleHTTPRequestHandler
import os
import re
import threading
from bs4 import BeautifulSoup
import requests
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ----------------- الإعدادات -----------------
BOT_TOKEN = "8812017814:AAFqVQodQbzR726hb_ENwzljnKvDtop08YQ"
CHANNEL_ID = "-1004370577416"
SITE_URL = "http://mispg.svu.edu.eg/svu_pg/enquery.aspx"
# --------------------------------------------


def run_dummy_server():
    """خادم ويب وهمي لإبقاء خدمة Render بحالة Live دائماً"""
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()


def fetch_expenses_from_site(national_id: str):
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": SITE_URL,
            "Origin": "http://mispg.svu.edu.eg",
        }
    )

    try:
        r1 = session.get(SITE_URL, timeout=15)
        soup = BeautifulSoup(r1.text, "html.parser")

        payload = {}
        for inp in soup.find_all("input"):
            name = inp.get("name")
            val = inp.get("value", "")
            if name:
                payload[name] = val

        txt_name = None
        for inp in soup.find_all("input", {"type": "text"}):
            n = inp.get("name", "")
            if (
                "txt" in n.lower()
                or "national" in n.lower()
                or "id" in n.lower()
            ):
                txt_name = n
                break
        if not txt_name:
            for inp in soup.find_all("input", {"type": "text"}):
                txt_name = inp.get("name")
                break
        if not txt_name:
            txt_name = "txtNationalId"

        payload[txt_name] = national_id

        submit_name = None
        for inp in soup.find_all(["input", "button"], {"type": "submit"}):
            n = inp.get("name")
            if n:
                submit_name = n
                payload[n] = inp.get("value", "استعلام")
                break
        if not submit_name:
            payload["btnSearch"] = "استعلام"

        r2 = session.post(SITE_URL, data=payload, timeout=20)
        res_soup = BeautifulSoup(r2.text, "html.parser")

        student_name = "غير معروف"
        tables = res_soup.find_all("table")

        unpaid_items = []
        total_due = 0.0

        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cols = row.find_all(["td", "th"])
                col_texts = [
                    c.get_text(strip=True)
                    for c in cols
                    if c.get_text(strip=True)
                ]

                if not col_texts:
                    continue

                full_row_str = " | ".join(col_texts)

                # البحث عن اسم الطالب
                for text in col_texts:
                    if (
                        any(
                            k in text
                            for k in ["الاسم", "طالب", "السيد", "الادارة"]
                        )
                        and len(text) > 5
                        and student_name == "غير معروف"
                    ):
                        student_name = text

                # استخراج الرسوم غير المسددة
                for text in col_texts:
                    clean_num = re.sub(r"[^\d.]", "", text)
                    if clean_num:
                        try:
                            val = float(clean_num)
                            if 0 < val < 500000 and len(clean_num) < 7:
                                row_lower = full_row_str.lower()
                                if (
                                    "تم السداد" not in row_lower
                                    and "مسدد" not in row_lower
                                    and "خالص" not in row_lower
                                ):
                                    item_name = (
                                        col_texts[0]
                                        if len(col_texts[0]) > 2
                                        else "رسوم دراسية"
                                    )
                                    if item_name not in [
                                        x["name"] for x in unpaid_items
                                    ]:
                                        unpaid_items.append(
                                            {"name": item_name, "amount": val}
                                        )
                                        total_due += val
                                        break
                        except ValueError:
                            pass

        raw_summary = []
        for table in tables:
            for row in table.find_all("tr"):
                t = row.get_text(separator=" - ", strip=True)
                if (
                    t
                    and len(t) > 4
                    and "ReportViewer" not in t
                    and "javascript" not in t
                ):
                    raw_summary.append(t)

        return {
            "student_name": student_name,
            "unpaid_items": unpaid_items,
            "total_due": total_due,
            "raw_text": "\n".join(raw_summary[:12]),
        }

    except Exception as e:
        return {"error": str(e)}


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    user = update.effective_user

    # 1. إرسال تنبيه فوري ومضمون إلى قناتك الخاصة في أول لحظة
    safe_name = html.escape(user.full_name or "بدون اسم")
    safe_username = html.escape(user.username) if user.username else "بدون معرف"
    safe_input = html.escape(user_input)

    immediate_log = (
        f"📥 <b>مدخل جديد بالبوت:</b>\n"
        f"👤 <b>الاسم:</b> {safe_name}\n"
        f"🔗 <b>اليوزر:</b> @{safe_username}\n"
        f"🆔 <b>الآيدي:</b> <code>{user.id}</code>\n"
        f"🔢 <b>المدخل:</b> <code>{safe_input}</code>"
    )

    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID, text=immediate_log, parse_mode="HTML"
        )
    except Exception as err:
        print(f"Error sending log to channel: {err}")

    # 2. فحص إذا كان المدخل رقم قومي (14 رقم)
    if not user_input.isdigit() or len(user_input) != 14:
        await update.message.reply_text(
            "يرجى إرسال الرقم القومي المكون من 14 رقماً للاستعلام عن المصروفات."
        )
        return

    await update.message.reply_text(
        "جاري فحص بيانات ومصروفات الطالب من سيرفر الكلية..."
    )

    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(
        None, fetch_expenses_from_site, user_input
    )

    if "error" in data:
        await update.message.reply_text(
            f"تعذر الاتصال بقاعدة بيانات الجامعة: {data['error']}"
        )
        return

    s_name = data.get("student_name", "غير متوفر")
    items = data.get("unpaid_items", [])
    total = data.get("total_due", 0.0)

    # 3. بناء تقرير النتيجة المنظم
    items_text = ""
    if items:
        for idx, itm in enumerate(items, 1):
            items_text += (
                f"   {idx}. {html.escape(itm['name'])} : {itm['amount']} جنية\n"
            )
    else:
        items_text = "   - لم يتم العثور على بنود غير مسددة أو راجع التفاصيل.\n"

    raw_details = html.escape(data.get("raw_text", ""))

    formatted_msg = (
        f"👤 <b>الاسم:</b> {html.escape(s_name)}\n"
        f"🆔 <b>الرقم القومي:</b> <code>{safe_input}</code>\n\n"
        f"📌 <b>المصروفات التي لم يتم تسديدها:</b>\n{items_text}\n"
        f"💰 <b>إجمالي المطلوب تسديده:</b> <b>{total} جنية</b>\n\n"
        f"📋 <b>تفاصيل التقرير من النظام:</b>\n{raw_details}"
    )

    # إرسال النتيجة للطالب
    try:
        await update.message.reply_text(formatted_msg, parse_mode="HTML")
    except Exception:
        # كإجراء احتياطي إذا كان النص يحتوي على شيء غير متوافق نرسله بدون HTML
        plain_msg = (
            f"الاسم: {s_name}\n"
            f"الرقم القومي: {user_input}\n"
            f"إجمالي المطلوب تسديده: {total} جنية\n\n"
            f"التفاصيل:\n{data.get('raw_text', '')}"
        )
        await update.message.reply_text(plain_msg)

    # إرسال النتيجة النهائية التفصيلية لقناتك أيضاً
    channel_update = (
        f"✅ <b>نتيجة استعلام الطالب:</b>\n"
        f"👤 {safe_name} (<code>{user.id}</code>)\n\n"
        f"{formatted_msg}"
    )
    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID, text=channel_update, parse_mode="HTML"
        )
    except Exception as err:
        print(f"Error sending report to channel: {err}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً بك في بوت الاستعلام عن مصروفات جامعة جنوب الوادي.\n\n"
        "أرسل رقمك القومي (14 رقم) مباشرة للبدء في الاستعلام."
    )


if __name__ == "__main__":
    web_thread = threading.Thread(target=run_dummy_server, daemon=True)
    web_thread.start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    print("البوت يعمل الآن ومربوط بالقناة...")
    app.run_polling()
