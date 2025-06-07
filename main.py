from flask import Flask, jsonify, Response, request, send_from_directory
import requests
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
import os
import traceback
import json
import csv
from io import StringIO
import logging

# Google Sheets API
from googleapiclient.discovery import build
from google.oauth2 import service_account

app = Flask(__name__)

GOOGLE_SHEET_ID = "1xnVihsf6H3brKf2NOz2Puo3CX-5Vj7cUJQm9144VIh0"

# Load and validate SERVICE_ACCOUNT_INFO safely
try:
    SERVICE_ACCOUNT_INFO = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "{}"))
    if not SERVICE_ACCOUNT_INFO:
        raise ValueError("Empty service account info")
except Exception as e:
    SERVICE_ACCOUNT_INFO = None
    logging.warning(f"Google Service Account JSON not properly loaded: {e}")

def log_to_google_sheet(data_dict):
    if not SERVICE_ACCOUNT_INFO:
        logging.warning("Google Sheets logging skipped due to missing credentials")
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
        
        logging.info("✅ Logged to Google Sheets")
    except Exception as e:
        logging.error(f"❌ Error logging to Google Sheets: {e}")

def fetch_news():
    url = "https://cdn-nfs.faireconomy.media/ff_calendar_thisweek.xml"
    logging.info(f"Fetching news from: {url}")
    response = requests.get(url)
    if response.status_code != 200:
        logging.error(f"Failed to fetch Forex Factory news, status code: {response.status_code}")
        raise Exception("Failed to fetch Forex Factory news")
    return response.content

def parse_and_analyze(xml_data):
    root = ET.fromstring(xml_data)
    currency_stats = defaultdict(list)

    for item in root.findall("event"):
        # Safely get elements and their text
        currency_elem = item.find("currency")
        impact_elem = item.find("impact")
        actual_elem = item.find("actual")
        forecast_elem = item.find("forecast")

        if not (currency_elem and impact_elem and actual_elem and forecast_elem):
            continue  # skip if any required field is missing

        currency = currency_elem.text
        impact = impact_elem.text
        actual = actual_elem.text
        forecast = forecast_elem.text

        if impact in ("High", "Medium") and actual and forecast:
            try:
                # Replace K and M with numbers safely
                def convert_val(val):
                    val = val.replace("K", "000").replace("M", "000000").replace("%", "")
                    return float(val)

                actual_val = convert_val(actual)
                forecast_val = convert_val(forecast)

                if actual_val > forecast_val:
                    currency_stats[currency].append("Bullish")
                elif actual_val < forecast_val:
                    currency_stats[currency].append("Bearish")
                else:
                    currency_stats[currency].append("Neutral")
            except Exception as e:
                logging.warning(f"Error parsing values for currency {currency}: {e}")
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
        xml_data = fetch_news()
        result = parse_and_analyze(xml_data)

        # Log to Google Sheets
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
        xml_data = fetch_news()
        result = parse_and_analyze(xml_data)

        # Prepare CSV in-memory
        output = StringIO()
        writer = csv.writer(output)
        header = ["Currency", "Sentiment"]
        writer.writerow(header)
        for c in ["USD", "EUR", "JPY", "GBP", "AUD", "NZD", "CHF", "CAD"]:
            writer.writerow([c, result.get(c, "Neutral")])

        csv_data = output.getvalue()
        output.close()

        return Response(csv_data, mimetype='text/csv', headers={"Content-disposition": "attachment; filename=ForexSentiment.csv"})

    except Exception:
        logging.error("Error in /ForexSentiment.csv endpoint", exc_info=True)
        return Response("Internal Server Error", status=500)

@app.route('/')
def home():
    return "API is working!"

if __name__ == '__main__':
    # Set logging level
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
