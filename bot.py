import os
import sys
import uuid
import shutil
import telebot
from dotenv import load_dotenv
from app import EmailVerifier
import concurrent.futures

# Load environment variables
load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID")

if not TOKEN:
    print("Please set TELEGRAM_BOT_TOKEN in your .env file or as an environment variable.")
    print("Example .env file content: TELEGRAM_BOT_TOKEN=your_bot_token_here")
    sys.exit(1)

if ALLOWED_USER_ID:
    try:
        ALLOWED_USER_ID = int(ALLOWED_USER_ID)
    except ValueError:
        print("ALLOWED_USER_ID must be an integer.")
        sys.exit(1)

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if ALLOWED_USER_ID and message.from_user.id != ALLOWED_USER_ID:
        bot.reply_to(message, "You are not authorized to use this bot.")
        return
    bot.reply_to(message, "Welcome! Send me a .txt file containing email addresses (one per line) and I will verify them for you.")

@bot.message_handler(content_types=['document'])
def handle_docs(message):
    if ALLOWED_USER_ID and message.from_user.id != ALLOWED_USER_ID:
        bot.reply_to(message, "You are not authorized to use this bot.")
        return
        
    try:
        # Check if the document is a txt file
        file_name = message.document.file_name
        if not file_name.endswith('.txt'):
            bot.reply_to(message, "Please upload a valid .txt file.")
            return
            
        bot.reply_to(message, "File received. Downloading and processing...")
        
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Create a unique directory to avoid file name collisions and race conditions
        unique_id = uuid.uuid4().hex[:8]
        work_dir = f"task_{unique_id}"
        os.makedirs(work_dir, exist_ok=True)
        
        file_path = os.path.join(work_dir, "input.txt")
        
        with open(file_path, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        # Read emails
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            emails = [line.strip() for line in f if line.strip()]
            
        if not emails:
            bot.reply_to(message, "The file is empty or contains no valid lines.")
            shutil.rmtree(work_dir, ignore_errors=True)
            return

        bot.reply_to(message, f"Loaded {len(emails)} emails. Starting verification... This might take a while.")
        
        # Initialize verifier
        verifier = EmailVerifier(file_path)
        
        # Process emails using ThreadPoolExecutor (same as app.py)
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            executor.map(verifier.verify, emails)
            
        # Determine output files from the EmailVerifier
        exists_file = verifier.exists_file
        not_exists_file = verifier.not_exists_file
        
        # Rename files to be exactly "exists.txt" and "not_exists.txt" prior to sending
        final_exists = os.path.join(work_dir, "exists.txt")
        final_not_exists = os.path.join(work_dir, "not_exists.txt")
        
        if os.path.exists(exists_file):
            os.rename(exists_file, final_exists)
        
        if os.path.exists(not_exists_file):
            os.rename(not_exists_file, final_not_exists)
            
        # Send exists.txt
        if os.path.exists(final_exists):
            with open(final_exists, 'rb') as f:
                bot.send_document(message.chat.id, f, caption="Found emails")
        else:
            bot.send_message(message.chat.id, "No valid/existing emails found.")
            
        # Send not_exists.txt
        if os.path.exists(final_not_exists):
            with open(final_not_exists, 'rb') as f:
                bot.send_document(message.chat.id, f, caption="Not found, invalid, or blocked emails")
        else:
            bot.send_message(message.chat.id, "All evaluated emails exist.")
            
        bot.send_message(message.chat.id, "Verification complete!")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        bot.reply_to(message, f"An error occurred: {e}")
    finally:
        # Clean up files
        if 'work_dir' in locals() and os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)



if __name__ == "__main__":
    print("Starting Telegram Bot...")
    bot.polling(none_stop=True)
