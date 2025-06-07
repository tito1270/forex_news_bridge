from flask import Flask, Response
import requests
from bs4 import BeautifulSoup
from collections import defaultdict
from datetime import datetime
import os
import logging
import json
from io import StringIO
import csv

# Google Sheets API
from googleapiclient.discovery import build
from google.oauth2 import service_account

app = Flask(__name__)

GOOGLE_SHEET_ID = "1xnVihsf6H3brKf2NOz2Puo3CX-5Vj7cUJQm9144VIh0"

try:
    SERVICE_ACCOUNT_INFO = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "{}"))
    if not SERVICE_ACCOUNT_INFO:
        raise ValueError("Empty Google Service Account info")
except Exception as e:
    SERVICE_ACCOUNT_INFO = None
    logging.warning(f"Google Service Account JSON not loaded: {e}")

def log_to_google_sheet(data_dict):
    if not SERVICE_ACCOUNT_INFO:
        logging.warning("Skipping Google Sheets logging due to missing credentials")
        return
    
    try:
        creds = service_account.Credentials.from_service_account_info(
            SERVICE_ACCOUNT_INFO,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        service = build('sheets', 'v4', credentials=creds)
        sheet = service.spreadsheets()

        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        values = [[now] + [data_dict.get(c, "Neutral") for c in ["USD", "EUR", "JPY", "GBP", "AUD", "NZD", "CHF", "CAD"]]]
        body = {"values": values}

        sheet.values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range="Sheet1!A1",
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()
        logging.info("✅ Logged data to Google Sheets")
    except Exception as e:
        logging.error(f"Error logging to Google Sheets: {e}")

def fetch_news():
    url = "https://www.forexfactory.com/calendar.php"
    logging.info(f"Fetching news from {url}")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; ForexSentimentBot/1.0)"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logging.error(f"Failed to fetch Forex Factory calendar page: {e}")
        raise

def parse_and_analyze(html_data):
    soup = BeautifulSoup(html_data, "html.parser")

    currency_stats = defaultdict(list)

    # The calendar table rows have class "calendar__row"
    rows = soup.select("tr.calendar__row")
    if not rows:
        logging.warning("No calendar rows found on the page.")
        return {}

    for row in rows:
        # Extract currency
        currency_td = row.find("td", class_="calendar__currency")
        if not currency_td:
            continue
        currency = currency_td.text.strip()

        # Extract impact
        impact_td = row.find("td", class_="impact")
        if not impact_td:
            continue
        # Impact is shown as icons with alt text, e.g., "High Impact"
        impact_icon = impact_td.find("span", class_="impact-icon")
        impact = impact_icon['title'] if impact_icon and impact_icon.has_attr('title') else ""

        if impact not in ("High Impact", "Medium Impact"):
            continue

        # Extract actual and forecast
        actual_td = row.find("td", class_="actual")
        forecast_td = row.find("td", class_="forecast")

        actual = actual_td.text.strip() if actual_td else ""
        forecast = forecast_td.text.strip() if forecast_td else ""

        if not actual or not forecast or actual == "-" or forecast == "-":
            continue

        # Convert actual and forecast strings to floats for comparison
        def convert_val(val):
            try:
                val = val.replace("%", "").replace(",", "").upper()
                if "M" in val:
                    return float(val.replace("M", "")) * 1_000_000
                if "K" in val:
                    return float(val.replace("K", "")) * 1_000
                return float(val)
            except:
                return None

        actual_val = convert_val(actual)
        forecast_val = convert_val(forecast)

        if actual_val is None or forecast_val is None:
            continue

        if actual_val > forecast_val:
            currency_stats[currency].append("Bullish")
        elif actual_val < forecast_val:
            currency_stats[currency].append("Bearish")
        else:
            currency_stats[currency].append("Neutral")

    final_result = {}
    for currency, signals in currency_stats.items():
        score = signals.count("Bullish") - signals.count("Bearish")
        if score > 0:
            final_result[currency] = "Bullish"
        elif score < 0:
            final_result[currency] = "Bearish"
        else:
            final_result[currency] = "Neutral"

    logging.info(f"Parsed result: {final_result}")
    return final_result

@app.route('/summary.txt')
def news_summary_txt():
    try:
        html_data = fetch_news()
        result = parse_and_analyze(html_data)

        log_to_google_sheet(result)

        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M GMT")
        lines = [f"Date: {now}", ""]
        for c in ["USD", "EUR", "JPY", "GBP", "AUD", "NZD", "CHF", "CAD"]:
            sentiment = result.get(c, "Neutral")
            lines.append(f"{c} - {sentiment}")

        output = "\n".join(lines)
        return Response(output, mimetype="text/plain")

    except Exception:
        logging.error("Error in /summary.txt endpoint", exc_info=True)
        return Response("Internal Server Error", status=500)

@app.route('/ForexSentiment.csv')
def forex_sentiment_csv():
    try:
        html_data = fetch_news()
        result = parse_and_analyze(html_data)

        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["Currency", "Sentiment"])

        for c in ["USD", "EUR", "JPY", "GBP", "AUD", "NZD", "CHF", "CAD"]:
            writer.writerow([c, result.get(c, "Neutral")])

        csv_data = output.getvalue()
        output.close()

        return Response(
            csv_data,
            mimetype='text/csv',
            headers={"Content-Disposition": "attachment; filename=ForexSentiment.csv"}
        )

    except Exception:
        logging.error("Error in /ForexSentiment.csv endpoint", exc_info=True)
        return Response("Internal Server Error", status=500)

@app.route('/')
def home():
    return "Forex Sentiment API is running!"

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

