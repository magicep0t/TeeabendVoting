import json # Added for data persistence
import logging
import uuid
from datetime import datetime, timedelta

from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
# Removed unused imports: Update, InlineKeyboardMarkup, InlineKeyboardButton, MessageHandler, filters
# Removed unused standard library imports: re, io
# Removed unused third-party import: matplotlib.pyplot

from . import config # Updated config import
DEFAULT_POLL_DURATION_MINUTES = config.DEFAULT_POLL_DURATION_MINUTES # Make it available for ..bot import
# TELEGRAM_BOT_TOKEN will be used as config.TELEGRAM_BOT_TOKEN directly in main()
from .handlers import command_handlers, callback_handlers # Import the new handlers

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# In-memory data structures
polls_data = {}
# poll_id: {
#     "chat_id": int,
#     "creator_id": int,
#     "topic": str,
#     "options": list[str],
#     "start_time": datetime,
#     "end_time": datetime | None,
#     "status": str,  # "active", "closed"
#     "votes": dict,  # {user_id: option_index}
#     "message_id": int | None # message_id of the poll message
# }
chat_members = {}  # Stores chat_id: set(user_id)

DATA_FILE = "polls_data.json"

def load_data():
    global polls_data
    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            # Deserialize datetime strings back to datetime objects
            for poll_id, poll_info in data.items():
                if "start_time" in poll_info and isinstance(poll_info["start_time"], str):
                    poll_info["start_time"] = datetime.fromisoformat(poll_info["start_time"])
                if "end_time" in poll_info and poll_info["end_time"] and isinstance(poll_info["end_time"], str):
                    poll_info["end_time"] = datetime.fromisoformat(poll_info["end_time"])
            polls_data = data
            logger.info(f"Successfully loaded data from {DATA_FILE}")
    except FileNotFoundError:
        logger.info(f"{DATA_FILE} not found. Starting with empty polls data.")
        polls_data = {} # Ensure polls_data is initialized
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from {DATA_FILE}. Starting with empty polls data.")
        polls_data = {} # Ensure polls_data is initialized
    except Exception as e:
        logger.error(f"Failed to load data from {DATA_FILE}: {e}. Starting with empty polls data.")
        polls_data = {} # Ensure polls_data is initialized

def save_data():
    try:
        # Create a deepcopy for serialization to avoid modifying original datetime objects
        polls_data_serializable = {}
        for poll_id, poll_info_orig in polls_data.items():
            poll_info = poll_info_orig.copy() # Work on a copy
            if "start_time" in poll_info and isinstance(poll_info["start_time"], datetime):
                poll_info["start_time"] = poll_info["start_time"].isoformat()
            if "end_time" in poll_info and poll_info["end_time"] and isinstance(poll_info["end_time"], datetime):
                poll_info["end_time"] = poll_info["end_time"].isoformat()
            polls_data_serializable[poll_id] = poll_info

        with open(DATA_FILE, "w") as f:
            json.dump(polls_data_serializable, f, indent=4)
        logger.info(f"Successfully saved data to {DATA_FILE}")
    except Exception as e:
        logger.error(f"Failed to save data to {DATA_FILE}: {e}")

def generate_poll_id() -> str:
    """Generates a unique poll ID."""
    return uuid.uuid4().hex


async def check_active_polls(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodically checks active polls and closes them if their end_time has passed."""
    bot = context.application.bot
    # Iterate over a copy of items in case the dictionary is modified during iteration elsewhere (though less likely for this specific job)
    for poll_id, poll in list(polls_data.items()): # Use list() for a copy of items
        if poll["status"] == "active" and poll["end_time"]:
            if datetime.now() >= poll["end_time"]:
                poll["status"] = "ended_time_expired"
                save_data() # Save data after poll status changes
                logger.info(f"Poll {poll_id} ('{poll['topic']}') has expired due to time limit.")
                
                try:
                    await bot.send_message(
                        chat_id=poll["chat_id"],
                        text=f"Poll '{poll['topic']}' has ended as the time limit was reached."
                    )
                except Exception as e:
                    logger.error(f"Error sending message for expired poll {poll_id} to chat {poll['chat_id']}: {e}")

                # Try to edit the original poll message
                if poll.get("message_id") and poll.get("chat_id"):
                    try:
                        updated_text = f"📊 *Poll: {poll['topic']}* (Time Expired)\n\nVoting has concluded."
                        await bot.edit_message_text(
                            chat_id=poll["chat_id"],
                            message_id=poll["message_id"],
                            text=updated_text,
                            parse_mode='Markdown'
                        )
                        await bot.edit_message_reply_markup(
                            chat_id=poll["chat_id"],
                            message_id=poll["message_id"],
                            reply_markup=None
                        )
                        logger.info(f"Successfully edited and removed keyboard for time-expired poll {poll_id}.")
                    except Exception as e:
                        logger.error(f"Error updating original poll message for time-expired poll {poll_id}: {e}. It might be too old or message content unchanged.")
                        # Optionally send another message if editing failed but primary notification about expiry already sent.
            # Future improvement: Placeholder for "all-voted" check
            # elif poll["status"] == "active" and chat_id in chat_members and len(poll["votes"]) == len(chat_members[chat_id]):
            #     poll["status"] = "ended_all_voted"
            #     logger.info(f"Poll {poll_id} ('{poll['topic']}') has ended because all members voted.")
            #     # Similar notification and message edit logic would follow


def main() -> None:
    """Start the bot."""
    load_data() # Load data at startup
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build() # Use config.TELEGRAM_BOT_TOKEN

    # Setup JobQueue
    job_queue = application.job_queue
    job_queue.run_repeating(check_active_polls, interval=60, first=0) # Check every 60 seconds

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", command_handlers.start))
    application.add_handler(CommandHandler("startpoll", command_handlers.startpoll_command_handler))
    application.add_handler(CommandHandler("endpoll", command_handlers.endpoll_command_handler))
    application.add_handler(CommandHandler("pollhistory", command_handlers.pollhistory_command_handler))
    application.add_handler(CommandHandler("pollstats", command_handlers.pollstats_command_handler))

    # Add handler for callback queries (button presses)
    application.add_handler(CallbackQueryHandler(callback_handlers.button_callback_handler))

    # Start the Bot
    application.run_polling()


if __name__ == "__main__":
    main()
