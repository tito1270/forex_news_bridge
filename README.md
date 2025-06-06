# Render + Google Sheets + MT4 Forex News Bridge

## How it works
- Fetches Forex Factory XML data
- Analyzes sentiment (Bullish/Bearish/Neutral) for 8 currencies
- Logs result to Google Sheets
- Serves /summary.txt endpoint that MT4 can read

## Deployment
1. Upload this folder to GitHub
2. Deploy on Render.com (Python + Web Service)
3. Set environment variables:
   - `GOOGLE_SHEET_ID` = Your Google Sheet ID
   - `GOOGLE_SERVICE_ACCOUNT_JSON` = Paste the JSON credentials as a string

## Endpoint
- `/summary.txt` – returns latest analysis in text format
