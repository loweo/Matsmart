import os
import time
import shutil
import json
import gspread
import google.generativeai as genai
from dotenv import load_dotenv
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 1. Load environment variables (Your Gemini API Key)
load_dotenv()

# 2. Configure Gemini API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
# Using Gemini 1.5 Pro as it is the best model for handling PDFs natively
model = genai.GenerativeModel('gemini-1.5-pro')

# 3. Configure Google Sheets
# Make sure your credentials.json is in the folder and shared with your sheet!
gc = gspread.service_account(filename='credentials.json')
# UPDATE THIS LINE with the actual name of your Google Sheet:
sheet = gc.open('YOUR_SHEET_NAME_HERE').sheet1 

# 4. Define our folder paths
IN_FOLDER = "receipts_in"
PROCESSED_FOLDER = "receipts_processed"
ERROR_FOLDER = "receipts_error"

# 5. The Master Prompt
PROMPT = """
You are an expert data entry and nutritional analysis assistant. I will provide you with a PDF receipt from a Swedish grocery store (Hemköp). 
Your Task:
1. Extract the overall receipt metadata: Date of purchase, Store location, and Total price.
2. Extract every individual line item purchased. For each item, capture the Product Name, Quantity (or weight), and Total Price for that item. Skip non-food items like plastic bags (bärkasse) or deposit fees (pant), or categorize them accordingly.
3. Enrichment: Based on the Swedish product name, assign a broad Category (e.g., Produce, Dairy, Meat, Pantry, Bakery, Snacks, Household). 
4. Nutritional Estimation: Estimate the average Calories_per_100g for the item. If it is a non-food item, return null.

Output Constraints:
You must respond strictly in valid JSON format using this exact schema:
{
  "receipt_metadata": {
    "store": "Hemköp [Location]",
    "date": "YYYY-MM-DD",
    "total_receipt_cost": 0.00
  },
  "items": [
    {
      "product_name": "String",
      "quantity_or_weight": "String",
      "item_total_price": 0.00,
      "category": "String",
      "calories_per_100g": 0
    }
  ]
}
"""

def process_receipt(file_path):
    print(f"\n📄 New receipt detected: {file_path}")
    print("🧠 Sending to Gemini for analysis...")
    
    try:
        # Upload the PDF to Gemini
        receipt_file = genai.upload_file(path=file_path)
        
        # Ask Gemini to generate the JSON response
        response = model.generate_content(
            [receipt_file, PROMPT],
            # This forces Gemini to ONLY output clean JSON so our script doesn't break
            generation_config={"response_mime_type": "application/json"}
        )
        
        # Parse the JSON response into Python dictionaries
        data = json.loads(response.text)
        meta = data.get("receipt_metadata", {})
        items = data.get("items", [])
        
        rows_to_add = []
        for item in items:
            # Match this order to the columns in your Google Sheet!
            # Example: [Date, Store, Product Name, Category, Calories, Quantity, Price, Total Cost]
            row = [
                meta.get("date", ""),
                meta.get("store", ""),
                item.get("product_name", ""),
                item.get("category", ""),
                item.get("calories_per_100g", ""),
                item.get("quantity_or_weight", ""),
                item.get("item_total_price", ""),
                meta.get("total_receipt_cost", "")
            ]
            rows_to_add.append(row)
        
        if rows_to_add:
            print(f"📊 Sending {len(rows_to_add)} items to Google Sheets...")
            sheet.append_rows(rows_to_add)
            print("✅ Success!")
        
        # Move the PDF to the processed folder so it doesn't run twice
        shutil.move(file_path, os.path.join(PROCESSED_FOLDER, os.path.basename(file_path)))
        
    except Exception as e:
        print(f"❌ Error processing {file_path}: {e}")
        # Move to error folder so we don't lose the file, but don't crash the program
        shutil.move(file_path, os.path.join(ERROR_FOLDER, os.path.basename(file_path)))

# 6. The "Watchdog" that monitors the folder 24/7
class ReceiptHandler(FileSystemEventHandler):
    def on_created(self, event):
        # Only trigger if it's a PDF file
        if not event.is_directory and event.src_path.lower().endswith('.pdf'):
            # Wait 2 seconds to make sure the file is completely saved to the folder
            time.sleep(2)
            process_receipt(event.src_path)

if __name__ == "__main__":
    print(f"👀 Watching the '{IN_FOLDER}' folder for new Hemköp PDFs...")
    print("Press Ctrl+C to stop the script.\n")
    
    event_handler = ReceiptHandler()
    observer = Observer()
    observer.schedule(event_handler, IN_FOLDER, recursive=False)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\nScript stopped.")
    
    observer.join()