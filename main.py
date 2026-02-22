import os
import time
import shutil
import json
import gspread
from google import genai
from google.genai import types
from dotenv import load_dotenv
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 1. Load environment variables
load_dotenv()

# 2. Configure the NEW Google GenAI Client
# The new SDK automatically finds your GEMINI_API_KEY in the .env file!
client = genai.Client() 

# 3. Configure Google Sheets
gc = gspread.service_account(filename='credentials.json')
# UPDATE THIS LINE:
sheet = gc.open('Data').sheet1 

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
    print(f"\n📄 New receipt detected: {os.path.basename(file_path)}")
    print("🧠 Sending to Gemini for analysis...")
    
    try:
        # Upload the PDF using the NEW SDK
        receipt_file = client.files.upload(file=file_path)
        
        # Ask Gemini to generate the JSON response using the NEW SDK
        response = client.models.generate_content(
            model='gemini-2.5-flash-lite', # Using the high-volume free tier model
            contents=[receipt_file, PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        
        # Parse the JSON response into Python dictionaries
        data = json.loads(response.text)
        meta = data.get("receipt_metadata", {})
        items = data.get("items", [])
        
        rows_to_add = []
        for item in items:
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
        
        # Move the PDF to the processed folder
        shutil.move(file_path, os.path.join(PROCESSED_FOLDER, os.path.basename(file_path)))
        
    except Exception as e:
        print(f"❌ Error processing {file_path}: {e}")
        shutil.move(file_path, os.path.join(ERROR_FOLDER, os.path.basename(file_path)))

# 6. The "Watchdog" that monitors the folder 24/7
class ReceiptHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith('.pdf'):
            time.sleep(2)
            process_receipt(event.src_path)

if __name__ == "__main__":
    print(f"Waiting for new PDF in '{IN_FOLDER}'")
    
    # --- NEW FEATURE: Startup Folder Check ---
    # Look for any PDFs that are already in the folder
    existing_pdfs = [f for f in os.listdir(IN_FOLDER) if f.lower().endswith('.pdf')]
    
    if not existing_pdfs:
        print(f"📭 The '{IN_FOLDER}' folder is currently empty. Waiting for you to drop a PDF here!")
    else:
        print(f"📂 Found {len(existing_pdfs)} existing PDF(s) on startup. Processing them now...")
        for pdf in existing_pdfs:
            process_receipt(os.path.join(IN_FOLDER, pdf))
            
        # --- NEW COMPLETION MESSAGES ---
        print("\n✅ All caught up! Finished processing the startup queue.")
        print(f"👀 Now watching the '{IN_FOLDER}' folder for new PDFs...")
        # -------------------------------
    # -----------------------------------------

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