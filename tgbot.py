import json
import requests
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv
import os

# ------------------- Config (.env) -------------------
load_dotenv()  # .env dosyasını yükler

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_TOKEN = os.getenv("API_TOKEN")

HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "Authentication": API_TOKEN,
}

# API URL’leri
DEPOSIT_URL = "https://backofficewebadmin.betconstruct.com/api/en/Client/GetClientTransactionsV1"
WITHDRAW_URL = "https://backofficewebadmin.betconstruct.com/api/en/Client/GetClientWithdrawalRequestsWithTotals"
CLIENT_INFO_URL = "https://backofficewebadmin.betconstruct.com/api/en/Client/GetClients"


# ===================================================================
#  LOGIN İLE CLIENT BİLGİSİ ALMA
# ===================================================================
def fetch_client_by_login(login):
    body = {
        "Id": "",
        "FirstName": "",
        "LastName": "",
        "MiddleName": "",
        "Login": login,
        "PersonalId": "",
        "Email": "",
        "Phone": "",
        "MobilePhone": "",
        "ZipCode": None,
        "City": "",
        "RegionId": None,
        "CurrencyId": None,
        "IsTest": None,
        "IsStartWithSearch": False,
        "IsOrderedDesc": True,
        "MaxRows": 20,
        "OrderedItem": 1,
        "MinCreatedLocalDisable": True,
        "MaxCreatedLocalDisable": True
    }

    try:
        r = requests.post(CLIENT_INFO_URL, headers=HEADERS, json=body)
        r.raise_for_status()
        data = r.json()

        users = data.get("Data", {}).get("Objects", [])
        if not users:
            return None

        return users[0]  # tüm kullanıcı bilgilerini döndürür

    except Exception as e:
        print(f"Hata: {e}")
        return None


# ===================================================================
#  TARİH İŞLEMLERİ
# ===================================================================
def parse_date(date_str):
    return datetime.strptime(date_str, "%d-%m-%y")


def split_date_range(start, end, chunk_days=90):
    result = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=chunk_days), end)
        result.append((cur, nxt))
        cur = nxt + timedelta(days=1)
    return result


# ===================================================================
#  DEPOSIT ÇEKME
# ===================================================================
def fetch_deposits(client_id, start, end):
    body = {
        "ClientId": client_id,
        "CurrencyId": "TRY",
        "StartTimeLocal": start.strftime("%d-%m-%y"),
        "EndTimeLocal": end.strftime("%d-%m-%y"),
        "DocumentTypeIds": [3],
        "MaxRows": 100,
        "SkeepRows": 0,
        "ByPassTotals": False
    }

    try:
        r = requests.post(DEPOSIT_URL, headers=HEADERS, json=body)
        r.raise_for_status()
        data = r.json()

        if data.get("HasError"):
            return [], f"API Hatası: {data.get('Message')}"

        items = data.get("Data", {}).get("Objects", [])
        return [x.get("Amount", 0) for x in items], None

    except Exception as e:
        return [], f"Hata: {e}"


# ===================================================================
#  WITHDRAW ÇEKME
# ===================================================================
def fetch_withdrawals(client_id, start, end):
    body = {
        "ClientId": client_id,
        "CurrencyId": None,
        "FromDateLocal": f"{start.strftime('%d-%m-%y')} - 00:00:00",
        "ToDateLocal": f"{end.strftime('%d-%m-%y')} - 00:00:00",
        "StateList": [3]
    }

    try:
        r = requests.post(WITHDRAW_URL, headers=HEADERS, json=body)
        r.raise_for_status()
        data = r.json()

        items = data.get("Data", {}).get("ClientRequests", [])
        return [x.get("Amount", 0) for x in items], None

    except Exception as e:
        return [], f"Hata: {e}"


# ===================================================================
#  TELEGRAM MESAJ HANDLER
# ===================================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    parts = text.split()

    # Format kontrol
    if len(parts) < 3:
        await update.message.reply_text(
            "❗ Format hatalı!\nÖrnek: `kullanıcıadı 18-07-25 18-11-25`"
        )
        return

    login = parts[0]
    try:
        start_date = parse_date(parts[1])
        end_date = parse_date(parts[2])
    except ValueError:
        await update.message.reply_text("❗ HATALI SORGU")
        return
    # Kullanıcı bilgilerini al
    user = fetch_client_by_login(login)
    if not user:
        await update.message.reply_text("❗ Kullanıcı bulunamadı!")
        return

    client_id = user.get("Id")
    user_name = f"{user.get('FirstName', '')} {user.get('LastName', '')}".strip()
    if not user_name:
        user_name = user.get("Login", "Bilinmiyor")

    # Yatırımlar
    chunks = split_date_range(start_date, end_date)
    all_deposits = []
    for s, e in chunks:
        dep, err = fetch_deposits(client_id, s, e)
        if err:
            await update.message.reply_text(err)
            return
        all_deposits.extend(dep)

    # Çekimler
    withdrawals, w_err = fetch_withdrawals(client_id, start_date, end_date)

    # Mesaj hazırla
    msg = f"👤 *Oyuncu:* {user_name}\n🆔 *ID:* {client_id}\n\n"

    msg += "💰 *Yatırımlar:*\n"
    msg += "\n".join([f"• {x} TRY" for x in all_deposits]) if all_deposits else "• Yok"
    msg += f"\n\n🔹 *Toplam:* {sum(all_deposits)} TRY\n\n"

    msg += "💸 *Çekimler:*\n"
    msg += "\n".join([f"• {x} TRY" for x in withdrawals]) if withdrawals else "• Yok"
    msg += f"\n\n🔹 *Toplam:* {sum(withdrawals)} TRY\n\n"

    net = sum(all_deposits) - sum(withdrawals)
    msg += f"📊 *Net:* {net} TRY"

    await update.message.reply_text(msg, parse_mode="Markdown")


# ===================================================================
#  BOT BAŞLAT
# ===================================================================
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

print("Bot çalışıyor...")
app.run_polling()
