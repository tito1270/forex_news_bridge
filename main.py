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

# Load Google Service Account info from environment variable
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
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/114.0.0.0 Safari/537.36"
    }
    logging.info(f"Fetching news from {url}")
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text  # HTML string
    except requests.RequestException as e:
        logging.error(f"Failed to fetch Forex Factory calendar page: {e}")
        raise

def parse_and_analyze(html_data):
    soup = BeautifulSoup(html_data, "html.parser")
    currency_stats = defaultdict(list)

    # The calendar events are in rows with class "calendar__row"
    rows = soup.find_all("tr", class_="calendar__row")
    for row in rows:
        # Currency is in a <td> with class 'calendar__currency'
        currency_td = row.find("td", class_="calendar__currency")
        if not currency_td:
            continue
        currency = currency_td.text.strip()

        # Impact is in a span with class like 'impact' inside a td class='impact'
        impact_td = row.find("td", class_="impact")
        if not impact_td:
            continue
        impact_span = impact_td.find("span", class_="impact")
        if not impact_span:
            continue
        impact = impact_span.get("title", "").strip()  # e.g. "High Impact"

        # We only want High or Medium impact events
        if not impact.lower().startswith(("high", "medium")):
            continue

        # Actual and Forecast values
        actual_td = row.find("td", class_="actual")
        forecast_td = row.find("td", class_="forecast")
        if actual_td is None or forecast_td is None:
            continue

        actual = actual_td.text.strip()
        forecast = forecast_td.text.strip()

        # If no actual or forecast, skip
        if actual == "" or forecast == "":
            continue

        try:
            # Convert values like "1.2M", "3.4K", "5.6%" into floats
            def convert_val(val):
                if val is None:
                    return None
                val = val.replace("%", "").replace(",", "").upper()
                if "M" in val:
                    return float(val.replace("M", "")) * 1_000_000
                if "K" in val:
                    return float(val.replace("K", "")) * 1_000
                return float(val)

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
        except Exception as e:
            logging.warning(f"Value conversion error for currency {currency}: {e}")
            continue

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

        # Log to Google Sheets if possible
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


