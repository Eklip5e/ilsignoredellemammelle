import os
import json
import random
from dotenv import load_dotenv
from pyrogram import Client, filters
import aiohttp
import asyncio
import schedule
from datetime import datetime
import time
import queue

# Load environment variables
load_dotenv()

# Bot configuration
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
DANBOORU_LOGIN = os.getenv("DANBOORU_LOGIN")
DANBOORU_API_KEY = os.getenv("DANBOORU_API_KEY")

class BotState:
    def __init__(self):
        self.STATE_FILE = "bot_state.json"
        self.state = self.load_state()
        self.active_chats = set()
        self.task_queue = queue.Queue()
        self.chat_tags = {}  # New dictionary to store chat-specific tags
        self.chat_times = {}

    def load_state(self):
        if os.path.exists(self.STATE_FILE):
            with open(self.STATE_FILE, "r") as f:
                data = json.load(f)
                self.chat_tags = data.get("chat_tags", {})
                self.chat_times = data.get("chat_times", {})  # Load chat-specific times
                return data
        return {"weight": 6, "tags": [], "time": "12:00", "chat_tags": {}, "chat_times": {}}

    def save_state(self):
        self.state["chat_tags"] = self.chat_tags
        self.state["chat_times"] = self.chat_times  # Save chat-specific times
        with open(self.STATE_FILE, "w") as f:
            json.dump(self.state, f)

    def get_tags(self, chat_id):
        return self.chat_tags.get(str(chat_id), self.state["tags"])

    def set_tags(self, chat_id, tags):
        self.chat_tags[str(chat_id)] = tags
        self.save_state()

    def get_time(self, chat_id):
        return self.chat_times.get(str(chat_id), self.state["time"])

    def set_time(self, chat_id, time):
        self.chat_times[str(chat_id)] = time
        self.save_state()

bot_state = BotState()

# Initialize the Pyrogram client
app = Client("danbooru_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

async def fetch_danbooru_images(tags, limit):
    url = "https://danbooru.donmai.us/posts.json"
    images = []
    attempts = 0
    max_attempts = 5

    async with aiohttp.ClientSession() as session:
        while len(images) < limit and attempts < max_attempts:
            # Select only one tag per image
            selected_tag = random.choice(tags)
            params = {
                "tags": selected_tag,
                "limit": min(200, limit - len(images)),
                "random": "true",
                "login": DANBOORU_LOGIN,
                "api_key": DANBOORU_API_KEY
            }

            try:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if isinstance(data, list):
                            new_images = [post["file_url"] for post in data if "file_url" in post]
                            images.extend(new_images)
                            print(f"Found {len(new_images)} images with tag: {selected_tag}")
                        else:
                            print(f"Unexpected response format for tag: {selected_tag}")
                            print(f"Response: {data}")
                    else:
                        print(f"API request failed for tag: {selected_tag}")
                        print(f"Status code: {response.status}")
                        print(f"Response: {await response.text()}")
            except Exception as e:
                print(f"Error during API request: {str(e)}")

            attempts += 1

    print(f"Found a total of {len(images)} images after {attempts} API calls")
    return images[:limit]
    # ... (keep this function unchanged)

async def send_images_to_chat(chat_id):
    total_to_send = bot_state.state["weight"]
    sent_count = 0
    max_attempts = total_to_send * 3
    attempts = 0

    chat_tags = bot_state.get_tags(chat_id)

    while sent_count < total_to_send and attempts < max_attempts:
        remaining = total_to_send - sent_count
        images = await fetch_danbooru_images(chat_tags, remaining * 2)

        if not images:
            print("No images found. Trying again with different tag combinations.")
            attempts += 1
            continue

        for image_url in images:
            try:
                await app.send_photo(chat_id, image_url)
                sent_count += 1
                if sent_count >= total_to_send:
                    break
            except Exception as e:
                print(f"Failed to send image: {image_url}. Error: {str(e)}")

        attempts += 1

        if sent_count >= total_to_send:
            break

    if sent_count == 0:
        await app.send_message(chat_id, "Sorry, I couldn't find any images matching the current tags. Please try different tags.")
    elif sent_count < total_to_send:
        await app.send_message(chat_id, f"I could only find and send {sent_count} images out of the requested {total_to_send}.")

    print(f"Successfully sent {sent_count} out of {total_to_send} images after {attempts} attempts.")

async def send_images(chat_id=None):
    if chat_id is None:
        # This is a scheduled call, so we send to all active chats
        for chat_id in bot_state.active_chats:
            await send_images_to_chat(chat_id)
    else:
        # This is a manual call, so we just send to the specified chat
        await send_images_to_chat(chat_id)

@app.on_message(filters.command("start"))
async def start_command(client, message):
    bot_state.active_chats.add(message.chat.id)
    await message.reply_text("Salve! Sono il Signore delle Mammelle, usa il comando /help per sapere cosa posso fare!")
    await message.reply_text("È tempo di mammelle fresche!")

@app.on_message(filters.command("help"))
async def help_command(client, message):
    bot_state.active_chats.add(message.chat.id)
    help_text = """
Comandi disponibili:
/start - Avvia il bot
/weight <number> - Decidi la quantità di immagini da ricevere (default: 6)
/daily - Forza il bot a mandare le immagini
/tagset <tags> - Imposta la lista dei tag
/taglist - Mostra la lista dei tag
/timeset <HH:MM> - Imposta l'ora del giorno in cui ricevere le immagini
/time - Mostra a che ora le immagini verranno inviate
"""
    await message.reply_text(help_text)

@app.on_message(filters.command("weight"))
async def weight_command(client, message):
    bot_state.active_chats.add(message.chat.id)
    try:
        weight = int(message.text.split()[1])
        bot_state.state["weight"] = weight
        bot_state.save_state()
        await message.reply_text(f"Numero di immagini impostata a: {weight}")
    except (ValueError, IndexError):
        await message.reply_text("Qualcosa non va, perfavore reinvia il comando correttamente: /weight <number>")

@app.on_message(filters.command("daily"))
async def daily_command(client, message):
    bot_state.active_chats.add(message.chat.id)
    await message.reply_text("Fetching...")
    await send_images(message.chat.id)

@app.on_message(filters.command("tagset"))
async def tagset_command(client, message):
    bot_state.active_chats.add(message.chat.id)
    tags = [tag.strip() for tag in ' '.join(message.text.split()[1:]).split(',') if tag.strip()]
    if tags:
        bot_state.set_tags(message.chat.id, tags)
        await message.reply_text(f"Lista attuale di tags: {', '.join(tags)}")
    else:
        await message.reply_text("Reinvia il comando con almeno un tag: /tagset tag1, tag2, tag3")

@app.on_message(filters.command("taglist"))
async def taglist_command(client, message):
    bot_state.active_chats.add(message.chat.id)
    tags = bot_state.get_tags(message.chat.id)
    if tags:
        await message.reply_text(f"Lista attuale di tags: {', '.join(tags)}")
    else:
        await message.reply_text("Non ci sono tag impostati per questa chat.")

@app.on_message(filters.command("timeset"))
async def timeset_command(client, message):
    bot_state.active_chats.add(message.chat.id)
    try:
        time_str = message.text.split()[1]
        scheduled_time = datetime.strptime(time_str, "%H:%M").time()
        bot_state.set_time(message.chat.id, time_str)
        schedule.clear()
        setup_schedules()  # We'll create this function to set up all schedules
        await message.reply_text(f"Invio giornaliero programmato alle: {time_str}")
    except (ValueError, IndexError):
        await message.reply_text("Qualcosa non va, perfavore, reinvia il comando correttamente: /timeset HH:MM")

@app.on_message(filters.command("time"))
async def time_command(client, message):
    bot_state.active_chats.add(message.chat.id)
    time = bot_state.get_time(message.chat.id)
    await message.reply_text(f"L'ora programmata è: {time}")

def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(1)

def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(1)

def setup_schedules():
    schedule.clear()
    for chat_id in bot_state.active_chats:
        time_str = bot_state.get_time(chat_id)
        schedule.every().day.at(time_str).do(lambda c=chat_id: bot_state.task_queue.put((send_images, c)))

async def process_queue():
    while True:
        try:
            task, chat_id = bot_state.task_queue.get_nowait()
            await task(chat_id)
        except queue.Empty:
            await asyncio.sleep(1)

async def main():
    await app.start()

    # Set up schedules for all active chats
    setup_schedules()

    # Run the scheduler in a separate thread
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, run_schedule)

    # Start processing the queue
    asyncio.create_task(process_queue())

    # Keep the bot running
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    app.run(main())

if __name__ == "__main__":
    app.run(main())
