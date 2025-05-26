import logging
import uuid
from datetime import datetime, timedelta
import re # For parsing quoted strings
import io
import matplotlib.pyplot as plt
import json
import os
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

DATA_FILE = "telegram_bot_polls_data.json"

# In-memory data structures
polls_data = {}  # This will be populated by load_polls_data()
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

# Placeholder for the Telegram Bot Token
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"

DEFAULT_POLL_DURATION_MINUTES = 5

COMMAND_DESCRIPTIONS = {
    "start": {
        "description": "Shows this help message.",
        "usage": "/start"
    },
    "startpoll": {
        "description": "Starts a new poll.",
        "usage": "/startpoll [duration_minutes] \"Topic\" \"Option 1\" \"Option 2\" ...",
        "details": "- `duration_minutes` (optional): Poll duration in minutes (e.g., 30). Default is 5. Use 0 for no time limit.\n"
                   "- `\"Topic\"`: The question for your poll (must be in double quotes).\n"
                   "- `\"Option X\"`: At least two answer choices (each in double quotes).",
        "example": "/startpoll 60 \"Favorite Color?\" \"Red\" \"Blue\" \"Green\""
    },
    "endpoll": {
        "description": "Manually ends an active poll that you created.",
        "usage": "/endpoll <poll_id>",
        "details": "- `<poll_id>`: The unique ID of the poll (you get this when you create a poll).",
    },
    "pollhistory": {
        "description": "Shows the history of all polls created in this chat.",
        "usage": "/pollhistory"
    },
    "pollstats": {
        "description": "Shows statistics for a specific poll.",
        "usage": "/pollstats <poll_id> [chart_type]",
        "details": "- `<poll_id>`: The unique ID of the poll.\n"
                   "- `chart_type` (optional): `bar` or `pie`. Default is `bar`.",
        "example": "/pollstats your_poll_id pie"
    },
    "menu": {
        "description": "Opens an interactive menu for easier bot operations.",
        "usage": "/menu"
    }
}

def get_formatted_help_message() -> str:
    """Generates a formatted help message from COMMAND_DESCRIPTIONS."""
    message_parts = ["👋 *Welcome to the Advanced Voting Bot!*", "\nHere's how you can use me:\n"]
    
    # Categorize commands for better readability (optional, but good for UX)
    categories = {
        "Polling Commands": ["startpoll", "endpoll"],
        "Information Commands": ["pollhistory", "pollstats"],
        "General": ["start", "menu"]
    }

    processed_commands = set()

    for category_name, cmd_keys in categories.items():
        message_parts.append(f"\n*{category_name}:*")
        for cmd_key in cmd_keys:
            if cmd_key in COMMAND_DESCRIPTIONS:
                cmd_info = COMMAND_DESCRIPTIONS[cmd_key]
                message_parts.append(f"- `{cmd_info['usage']}`: {cmd_info['description']}")
                if "details" in cmd_info:
                    message_parts.append(f"  {cmd_info['details'].replace('-', '  -', 1)}") # Indent details
                if "example" in cmd_info:
                    message_parts.append(f"  _Example:_ `{cmd_info['example']}`")
                processed_commands.add(cmd_key)
    
    # Add any commands not in categories (though all should be)
    for cmd_key, cmd_info in COMMAND_DESCRIPTIONS.items():
        if cmd_key not in processed_commands:
            message_parts.append(f"\n*Other Commands:*") # Should ideally not happen if categories are complete
            message_parts.append(f"- `{cmd_info['usage']}`: {cmd_info['description']}")
            if "details" in cmd_info:
                message_parts.append(f"  {cmd_info['details'].replace('-', '  -', 1)}")
            if "example" in cmd_info:
                message_parts.append(f"  _Example:_ `{cmd_info['example']}`")


    message_parts.append("\nRemember to replace placeholders like `<poll_id>` with actual values.")
    message_parts.append("If you need help, just type `/start` again!")
    return "\n".join(message_parts)

HELP_MESSAGE = get_formatted_help_message()

# --- Data Persistence Functions ---

def convert_datetimes_to_iso(poll_data_dict: dict) -> dict:
    """Converts datetime objects in poll data to ISO 8601 strings for JSON serialization."""
    data_copy = poll_data_dict.copy()
    if isinstance(data_copy.get("start_time"), datetime):
        data_copy["start_time"] = data_copy["start_time"].isoformat()
    if isinstance(data_copy.get("end_time"), datetime):
        data_copy["end_time"] = data_copy["end_time"].isoformat()
    return data_copy

def convert_iso_to_datetimes(poll_data_dict: dict) -> dict:
    """Converts ISO 8601 string representations in poll data back to datetime objects."""
    data_copy = poll_data_dict.copy()
    if isinstance(data_copy.get("start_time"), str):
        data_copy["start_time"] = datetime.fromisoformat(data_copy["start_time"])
    if isinstance(data_copy.get("end_time"), str):
        data_copy["end_time"] = datetime.fromisoformat(data_copy["end_time"])
    return data_copy

def load_polls_data() -> dict:
    """Loads poll data from DATA_FILE. Returns an empty dict if file not found or error."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                loaded_data = json.load(f)
                # Convert datetime strings back to datetime objects
                return {
                    poll_id: convert_iso_to_datetimes(data)
                    for poll_id, data in loaded_data.items()
                }
        except (json.JSONDecodeError, IOError, TypeError) as e:
            logger.warning(f"Error loading data from {DATA_FILE}: {e}. Starting with empty data.")
            return {}
    else:
        logger.info(f"{DATA_FILE} not found. Starting with empty poll data.")
        return {}

def save_polls_data():
    """Saves the current polls_data to DATA_FILE."""
    global polls_data
    data_to_save = {
        poll_id: convert_datetimes_to_iso(data)
        for poll_id, data in polls_data.copy().items() # Iterate over a copy
    }
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data_to_save, f, indent=4)
        logger.info(f"Polls data successfully saved to {DATA_FILE}.")
    except IOError as e:
        logger.error(f"Error saving data to {DATA_FILE}: {e}")

async def scheduled_save_data(context: ContextTypes.DEFAULT_TYPE):
    """Async wrapper for save_polls_data to be used with JobQueue."""
    logger.info("JobQueue: Performing scheduled save of polls_data.")
    save_polls_data()

# --- End Data Persistence Functions ---

def generate_poll_id() -> str:
    """Generates a unique poll ID."""
    return uuid.uuid4().hex


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a detailed help message when the /start command is issued."""
    await update.message.reply_text(HELP_MESSAGE, parse_mode='Markdown')

async def new_chat_members_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message if the bot is added to a new chat."""
    if update.message.new_chat_members:
        bot_id = context.bot.id
        for member in update.message.new_chat_members:
            if member.id == bot_id:
                chat_id = update.message.chat_id
                logger.info(f"Bot added to new chat {chat_id}. Sending welcome message.")
                await context.bot.send_message(chat_id, HELP_MESSAGE, parse_mode='Markdown')
                break # Bot found, no need to check other new members

async def startpoll_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /startpoll command to create a new poll."""
    chat_id = update.message.chat_id
    creator_id = update.message.from_user.id
    args_str = " ".join(context.args)

    # Regex to find all quoted strings
    quoted_parts = re.findall(r'"(.*?)"', args_str)
    
    if not quoted_parts or len(quoted_parts) < 3: # Topic + at least 2 options
        await update.message.reply_text(
            "Usage: /startpoll [duration_minutes] \"Topic\" \"Option 1\" \"Option 2\" ...\n"
            "Topic and options must be enclosed in double quotes. At least two options are required."
        )
        return

    topic = quoted_parts[0]
    options = quoted_parts[1:]

    if len(options) < 2:
        await update.message.reply_text("A poll must have at least two options.")
        return

    # Determine duration
    # Remove quoted parts from args_str to find potential duration
    non_quoted_args_str = args_str
    for part in quoted_parts:
        non_quoted_args_str = non_quoted_args_str.replace(f'"{part}"', "").strip()
    
    duration_minutes = DEFAULT_POLL_DURATION_MINUTES # Default duration
    end_time = None

    if non_quoted_args_str: # Potential duration argument exists
        try:
            duration_input = int(non_quoted_args_str.split()[0])
            if duration_input < 0:
                await update.message.reply_text("Duration cannot be negative.")
                return
            duration_minutes = duration_input
        except ValueError:
            await update.message.reply_text(
                f"Invalid duration. Using default: {DEFAULT_POLL_DURATION_MINUTES} minutes.\n"
                "Usage: /startpoll [duration_minutes] \"Topic\" \"Option 1\" \"Option 2\" ..."
            )
            # Proceed with default duration
        except IndexError: # No non-quoted argument found, use default
            pass


    start_time = datetime.now()
    if duration_minutes > 0:
        end_time = start_time + timedelta(minutes=duration_minutes)
    
    poll_id = generate_poll_id()
    polls_data[poll_id] = {
        "chat_id": chat_id,
        "creator_id": creator_id,
        "topic": topic,
        "options": options,
        "start_time": start_time,
        "end_time": end_time,
        "status": "active",
        "votes": {},
        "message_id": None # Will be updated when the poll message is sent
    }

    options_text = "\n".join([f"- {opt}" for opt in options])
    duration_text = f"{duration_minutes} minutes" if duration_minutes > 0 else "No time limit"
    
    # Create InlineKeyboardButtons for each option
    keyboard = []
    for i, option in enumerate(options):
        keyboard.append([InlineKeyboardButton(option, callback_data=f"vote_{poll_id}_{i}")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    poll_message_text = (
        f"📊 *Poll: {topic}*\n\n"
        f"Select an option to vote:\n\n"
        f"Duration: {duration_text}"
    )
    
    sent_message = await update.message.reply_text(poll_message_text, reply_markup=reply_markup, parse_mode='Markdown')
    polls_data[poll_id]["message_id"] = sent_message.message_id

    logger.info(f"Poll {poll_id} created in chat {chat_id} by user {creator_id} with topic '{topic}' and options {options}. Duration: {duration_text}. Message ID: {sent_message.message_id}")
    
    # Send the Poll ID in a separate, formatted message
    await update.message.reply_text(
        f"Poll Created. Poll ID: `{poll_id}`",
        parse_mode='Markdown'
    )


async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles inline button presses for voting."""
    query = update.callback_query
    user_id = query.from_user.id
    callback_data = query.data

    # Ensure the query is answered to remove the "loading" state on the client
    # await query.answer() # Answer immediately, then process. Or answer after processing with specific message.

    if callback_data.startswith("vote_"):
        parts = callback_data.split("_")
        if len(parts) != 3:
            await query.answer("Invalid vote data.", show_alert=True)
            return

        action, poll_id, option_index_str = parts
        
        if poll_id not in polls_data:
            await query.answer("Error: Poll not found. It might have been deleted.", show_alert=True)
            return

        poll = polls_data[poll_id]

        if poll["status"] != "active":
            await query.answer("This poll is no longer active.", show_alert=True)
            return

        # Check poll duration if applicable
        if poll["end_time"] and datetime.now() > poll["end_time"]:
            poll["status"] = "closed" # Close the poll
            await query.answer("This poll has expired and is now closed.", show_alert=True)
            # Optionally, edit the poll message to show it's closed
            # if poll.get("message_id") and poll.get("chat_id"):
            #     try:
            #         await context.bot.edit_message_text(
            #             chat_id=poll["chat_id"],
            #             message_id=poll["message_id"],
            #             text=f"📊 *Poll: {poll['topic']}* (Closed)\n\nVoting has ended.",
            #             parse_mode='Markdown'
            #         )
            #     except Exception as e:
            #         logger.error(f"Error editing message for closed poll {poll_id}: {e}")
            return

        if user_id in poll["votes"]:
            voted_option_index = poll["votes"][user_id]
            voted_option_text = poll["options"][voted_option_index]
            await query.answer(f"You have already voted for: '{voted_option_text}'.", show_alert=True)
            return

        try:
            option_index = int(option_index_str)
            if not (0 <= option_index < len(poll["options"])):
                await query.answer("Invalid option selected.", show_alert=True)
                return
        except ValueError:
            await query.answer("Error processing your vote.", show_alert=True)
            return

        # Record the vote
        poll["votes"][user_id] = option_index
        selected_option_text = poll["options"][option_index]
        
        await query.answer(f"Your vote for '{selected_option_text}' has been recorded!", show_alert=False)
        logger.info(f"User {user_id} voted for option {option_index} ('{selected_option_text}') in poll {poll_id}")
    else:
        await query.answer() # Default answer for other callbacks if any


def get_friendly_poll_status(status: str) -> str:
    """Converts internal poll status to a user-friendly string."""
    status_map = {
        "active": "Active",
        "closed": "Closed (Expired)", # Generic closed, might be updated by specific end reasons
        "ended_manually": "Ended by Creator",
        "ended_time_expired": "Ended (Time Limit Reached)",
        # "ended_all_voted": "Ended (All Voted)" # If implemented
    }
    return status_map.get(status, status.replace("_", " ").title())


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Returns the InlineKeyboardMarkup for the main menu."""
    keyboard = [
        [InlineKeyboardButton("🚀 Start New Poll", callback_data='menu_start_poll_guide')],
        [InlineKeyboardButton("📊 View Poll History", callback_data='menu_view_history_cmd')],
        [InlineKeyboardButton("🛑 End a Poll", callback_data='menu_end_poll_list')],
        [InlineKeyboardButton("📈 View Poll Statistics", callback_data='menu_stats_poll_list')] # Placeholder
    ]
    return InlineKeyboardMarkup(keyboard)

async def menu_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the main menu with inline keyboard buttons."""
    reply_markup = get_main_menu_keyboard()
    await update.message.reply_text("Voting Bot Menu:\nChoose an option:", reply_markup=reply_markup)

async def back_to_main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Edits the current message to show the main menu."""
    query = update.callback_query
    await query.answer()
    reply_markup = get_main_menu_keyboard()
    await query.edit_message_text("Voting Bot Menu:\nChoose an option:", reply_markup=reply_markup)


async def menu_start_poll_guide_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'Start New Poll' menu button."""
    query = update.callback_query
    await query.answer()
    
    startpoll_info = COMMAND_DESCRIPTIONS.get("startpoll", {})
    usage = startpoll_info.get("usage", "/startpoll [duration_minutes] \"Topic\" \"Option 1\" \"Option 2\" ...")
    details = startpoll_info.get("details", "- `duration_minutes` (optional): Poll duration in minutes. Default is 5. Use 0 for no time limit.\n- `\"Topic\"`: The question for your poll.\n- `\"Option X\"`: At least two answer choices, in quotes.")
    example = startpoll_info.get("example", "/startpoll 60 \"Favorite IDE?\" \"VS Code\" \"PyCharm\" \"Neovim\" \"Other\"")

    guide_message = (
        "To start a new poll, please use the command: \n"
        f"`{usage}`\n\n"
        f"{details.replace('-', '  -', 1)}\n\n" # Indent details
        f"_Example:_\n`{example}`\n\n"
        "See /start for more detailed command descriptions."
    )
    await query.message.reply_text(guide_message, parse_mode='Markdown')


async def menu_view_history_cmd_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'View Poll History' menu button by invoking pollhistory_command_handler."""
    query = update.callback_query
    await query.answer()
    # Pass the message object from the callback query to the existing handler
    # We need to create a "pseudo" Update object or adapt pollhistory_command_handler
    # For simplicity, let's adapt pollhistory_command_handler to accept a message_obj
    await pollhistory_command_handler(update, context, message_obj=query.message)


async def menu_stats_poll_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays a list of all polls in the chat to select for statistics."""
    query = update.callback_query
    chat_id = query.message.chat_id

    chat_polls = {pid: pdata for pid, pdata in polls_data.items() if pdata["chat_id"] == chat_id}

    keyboard = []
    if not chat_polls:
        message_text = "No polls found in this chat."
    else:
        message_text = "Select a poll to view its statistics:"
        # Sort polls by start time, newest first for example
        sorted_poll_ids = sorted(chat_polls.keys(), key=lambda pid: chat_polls[pid]["start_time"], reverse=True)
        for poll_id in sorted_poll_ids:
            poll_data = chat_polls[poll_id]
            topic_short = poll_data['topic'][:25] + "..." if len(poll_data['topic']) > 25 else poll_data['topic']
            status_friendly = get_friendly_poll_status(poll_data['status'])
            keyboard.append([
                InlineKeyboardButton(
                    f"{topic_short} (Status: {status_friendly})", 
                    callback_data=f"stats_select_chart_type_{poll_id}"
                )
            ])
    
    keyboard.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='back_to_main_menu')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.answer()
    await query.edit_message_text(text=message_text, reply_markup=reply_markup)


async def stats_select_chart_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Allows user to select the format for poll statistics (bar, pie, text)."""
    query = update.callback_query
    poll_id = query.data.split("stats_select_chart_type_")[-1]

    if poll_id not in polls_data:
        await query.answer("Error: Poll not found. It might have been deleted.", show_alert=True)
        await menu_stats_poll_list_callback(update, context) # Show poll list again
        return

    poll_topic = polls_data[poll_id]["topic"]
    keyboard = [
        [InlineKeyboardButton("📊 Bar Chart", callback_data=f"stats_execute_{poll_id}_bar")],
        [InlineKeyboardButton("🥧 Pie Chart", callback_data=f"stats_execute_{poll_id}_pie")],
        [InlineKeyboardButton("📝 Text Only", callback_data=f"stats_execute_{poll_id}_text")],
        [InlineKeyboardButton("⬅️ Back to Poll List", callback_data="menu_stats_poll_list")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.answer()
    await query.edit_message_text(f"Choose statistics format for poll '{poll_topic}':", reply_markup=reply_markup)


async def stats_execute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetches poll data, calculates stats, and sends them as text and/or chart."""
    query = update.callback_query
    parts = query.data.split("_") # stats_execute_{poll_id}_{chart_type}
    poll_id = parts[2]
    chart_type = parts[3] # 'bar', 'pie', or 'text'
    
    chat_id = query.message.chat_id

    await query.answer("Generating statistics...")

    if poll_id not in polls_data:
        await context.bot.send_message(chat_id, "Error: Poll not found. It might have been deleted.")
        await query.edit_message_text(
            "Statistics request processed. Poll not found.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Poll List", callback_data='menu_stats_poll_list')],
                [InlineKeyboardButton("🏠 Main Menu", callback_data='back_to_main_menu')]
            ])
        )
        return

    poll = polls_data[poll_id]

    if poll["chat_id"] != chat_id: # Should ideally not happen if list is filtered by chat_id
        await context.bot.send_message(chat_id, "Error: Poll does not belong to this chat.")
        await query.edit_message_text(
            "Statistics request processed. Error accessing poll.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Poll List", callback_data='menu_stats_poll_list')],
                [InlineKeyboardButton("🏠 Main Menu", callback_data='back_to_main_menu')]
            ])
        )
        return

    options = poll["options"]
    vote_counts = [0] * len(options)
    for voter_id, option_index in poll["votes"].items():
        if 0 <= option_index < len(options):
            vote_counts[option_index] += 1
    total_votes = sum(vote_counts)

    # Send Text Statistics
    stats_message = f"📊 *Statistics for Poll: {poll['topic']}*\n"
    stats_message += f"🆔 *ID:* `{poll_id}`\n"
    stats_message += f"🚦 *Status:* {get_friendly_poll_status(poll['status'])}\n\n"
    if total_votes == 0:
        stats_message += "No votes have been cast yet."
    else:
        for i, option_text in enumerate(options):
            percentage = (vote_counts[i] / total_votes) * 100 if total_votes > 0 else 0
            stats_message += f"🔹 *{option_text}:* {vote_counts[i]} vote(s) ({percentage:.2f}%)\n"
    stats_message += f"\n👥 *Total Votes Cast:* {total_votes}"
    await context.bot.send_message(chat_id, stats_message, parse_mode='Markdown')

    # Generate and Send Chart (if requested and possible)
    if chart_type in ["bar", "pie"]:
        if total_votes > 0:
            try:
                chart_buffer = generate_poll_chart(poll["topic"], options, vote_counts, chart_type)
                if chart_buffer:
                    await context.bot.send_photo(
                        chat_id=chat_id, 
                        photo=chart_buffer, 
                        caption=f"Chart for poll: '{poll['topic']}' ({chart_type} chart)"
                    )
                    logger.info(f"Sent {chart_type} chart for poll {poll_id} to chat {chat_id} via menu.")
                else: # Error during chart generation
                    await context.bot.send_message(chat_id, "Could not generate the chart due to an internal error.")
            except Exception as e:
                logger.error(f"Failed to generate or send chart for poll {poll_id} via menu: {e}")
                await context.bot.send_message(chat_id, "An error occurred while generating the poll chart.")
        else: # No votes for chart
            await context.bot.send_message(chat_id, f"Cannot generate a '{chart_type}' chart as there are no votes yet for poll '{poll['topic']}'.")

    # Update the menu message
    await query.edit_message_text(
        "Statistics request processed. See messages above.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Poll List", callback_data='menu_stats_poll_list')],
            [InlineKeyboardButton("🏠 Main Menu", callback_data='back_to_main_menu')]
        ])
    )


async def menu_end_poll_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays a list of active polls created by the user to end, or a 'no polls' message."""
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    active_user_polls = {
        pid: pdata for pid, pdata in polls_data.items() 
        if pdata["chat_id"] == chat_id and pdata["status"] == "active" # and pdata["creator_id"] == user_id
    }

    keyboard = []
    if not active_user_polls:
        message_text = "You have no active polls in this chat to end."
    else:
        message_text = "Select one of your active polls to end:"
        for poll_id, poll_data in active_user_polls.items():
            topic_short = poll_data['topic'][:30] + "..." if len(poll_data['topic']) > 30 else poll_data['topic']
            keyboard.append([InlineKeyboardButton(f"{topic_short} (ID: ...{poll_id[-6:]})", callback_data=f"end_poll_confirm_{poll_id}")])
    
    keyboard.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='back_to_main_menu')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.answer()
    await query.edit_message_text(text=message_text, reply_markup=reply_markup)


async def end_poll_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Asks for confirmation before ending a poll."""
    query = update.callback_query
    poll_id = query.data.split("end_poll_confirm_")[-1]

    if poll_id not in polls_data:
        await query.answer("Error: Poll not found. It might have been deleted.", show_alert=True)
        await back_to_main_menu_callback(update, context) # Or show poll list again
        return

    poll_topic = polls_data[poll_id]["topic"]
    keyboard = [
        [InlineKeyboardButton("✅ Yes, End Poll", callback_data=f"end_poll_execute_{poll_id}")],
        [InlineKeyboardButton("❌ No, Cancel", callback_data="menu_end_poll_list")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.answer()
    await query.edit_message_text(f"Are you sure you want to end the poll: '{poll_topic}'?", reply_markup=reply_markup)


async def end_poll_execute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ends the poll after confirmation and permission check."""
    query = update.callback_query
    user_id = query.from_user.id
    poll_id = query.data.split("end_poll_execute_")[-1]

    if poll_id not in polls_data:
        await query.answer("Error: Poll not found. It might have been deleted.", show_alert=True)
        await back_to_main_menu_callback(update, context)
        return

    poll = polls_data[poll_id]

    if poll["creator_id"] != user_id:
        await query.answer("Error: Only the poll creator can end this poll.", show_alert=True)
        # Show the list of polls again, as the user might be able to end other polls
        await menu_end_poll_list_callback(update, context)
        return

    if poll["status"] != "active":
        await query.answer(f"Error: Poll is no longer active. Current status: {get_friendly_poll_status(poll['status'])}.", show_alert=True)
        await menu_end_poll_list_callback(update, context)
        return

    # Perform poll ending logic (similar to endpoll_command_handler)
    poll["status"] = "ended_manually"
    poll["end_time"] = datetime.now()
    
    logger.info(f"Poll {poll_id} ('{poll['topic']}') was manually ended by creator {user_id} via menu.")
    
    # Notify chat (optional, as the original poll message is edited)
    # await context.bot.send_message(chat_id=poll["chat_id"], text=f"Poll '{poll['topic']}' has been manually ended by the creator.")

    # Try to edit the original poll message
    if poll.get("message_id") and poll.get("chat_id"):
        try:
            updated_text = f"📊 *Poll: {poll['topic']}* (Ended by creator)\n\nVoting has concluded."
            await context.bot.edit_message_text(
                chat_id=poll["chat_id"], message_id=poll["message_id"],
                text=updated_text, parse_mode='Markdown'
            )
            await context.bot.edit_message_reply_markup(
                chat_id=poll["chat_id"], message_id=poll["message_id"], reply_markup=None
            )
            logger.info(f"Successfully edited original message for ended poll {poll_id} via menu.")
        except Exception as e:
            logger.error(f"Error updating original poll message for {poll_id} (ended via menu): {e}")

    await query.answer(f"Poll '{poll['topic']}' has been ended.")
    await query.edit_message_text(
        f"Poll '{poll['topic']}' has been successfully ended.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='back_to_main_menu')]])
    )


async def pollhistory_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, message_obj=None) -> None:
    """Displays the history of polls for the current chat. Can be called from command or callback."""
    message_to_use = message_obj if message_obj else update.message
    if not message_to_use:
        logger.error("pollhistory_command_handler called without a valid message object.")
        return

    chat_id = message_to_use.chat_id
    
    chat_polls = {pid: pdata for pid, pdata in polls_data.items() if pdata["chat_id"] == chat_id}

    if not chat_polls:
        await update.message.reply_text("No polls found for this chat.")
        return

    history_messages = []
    current_message = "📜 *Poll History for this Chat:*\n\n"
    
    # Sort polls by start time, newest first for example
    sorted_poll_ids = sorted(chat_polls.keys(), key=lambda pid: chat_polls[pid]["start_time"], reverse=True)

    for poll_id in sorted_poll_ids:
        poll = chat_polls[poll_id]
        
        options_str = ", ".join(poll['options'])
        if len(options_str) > 100: # Truncate if too long
            options_str = options_str[:97] + "..."
        
        start_time_str = poll['start_time'].strftime("%Y-%m-%d %H:%M:%S")
        end_time_str = poll['end_time'].strftime("%Y-%m-%d %H:%M:%S") if poll['end_time'] else "N/A (or still active)"
        if poll['status'] == 'active' and poll['end_time'] is None:
            end_time_str = "No time limit"

        poll_info = (
            f"------------------------------------\n"
            f"📝 *Topic:* {poll['topic']}\n"
            f"🆔 *ID:* `{poll_id}`\n"
            f"🚦 *Status:* {get_friendly_poll_status(poll['status'])}\n"
            f"👤 *Creator ID:* {poll['creator_id']}\n"
            f"🗳️ *Options ({len(poll['options'])}):* {options_str}\n"
            f"⏰ *Started:* {start_time_str}\n"
            f"🏁 *Ended:* {end_time_str}\n"
            f"👥 *Votes Cast:* {len(poll['votes'])}\n"
        )
        
        # Telegram message length limit is 4096 characters.
        # We add some buffer for markdown and other text.
        if len(current_message) + len(poll_info) > 4000:
            history_messages.append(current_message)
            current_message = "" # Start a new message
        
        current_message += poll_info

    if current_message: # Add the last or only message
        history_messages.append(current_message)

    for msg_part in history_messages:
        await update.message.reply_text(msg_part, parse_mode='Markdown')

    if not history_messages: # Should not happen if chat_polls is not empty, but as a safeguard
        await message_to_use.reply_text("No polls found for this chat.") # Use message_to_use


def generate_poll_chart(poll_topic: str, options: list[str], vote_counts: list[int], chart_type: str) -> io.BytesIO | None:
    """Generates a bar or pie chart for poll statistics and returns it as a BytesIO buffer."""
    try:
        plt.figure(figsize=(10, 6)) # Adjust figure size as needed
        
        if chart_type == "bar":
            bars = plt.bar(options, vote_counts, color=['skyblue', 'lightgreen', 'lightcoral', 'gold', 'lightsalmon', 'cyan'])
            plt.ylabel('Votes')
            plt.title(f'Poll Statistics: {poll_topic}\n(Bar Chart)')
            plt.xticks(rotation=45, ha="right") # Rotate labels for better readability
            plt.tight_layout() # Adjust layout to prevent labels from being cut off

            # Add vote counts on top of bars
            for bar in bars:
                yval = bar.get_height()
                plt.text(bar.get_x() + bar.get_width()/2.0, yval + 0.05, int(yval), va='bottom', ha='center')

        elif chart_type == "pie":
            # Filter out options with zero votes for pie chart to avoid clutter
            filtered_options = [opt for i, opt in enumerate(options) if vote_counts[i] > 0]
            filtered_vote_counts = [vc for vc in vote_counts if vc > 0]

            if not filtered_vote_counts: # All options have 0 votes
                 plt.text(0.5, 0.5, 'No votes to display in pie chart.', horizontalalignment='center', verticalalignment='center')
            else:
                plt.pie(filtered_vote_counts, labels=filtered_options, autopct='%1.1f%%', startangle=140, 
                        colors=['skyblue', 'lightgreen', 'lightcoral', 'gold', 'lightsalmon', 'cyan'])
                plt.title(f'Poll Statistics: {poll_topic}\n(Pie Chart)')
                plt.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.
        else:
            logger.warning(f"Invalid chart type requested: {chart_type}")
            return None

        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close() # Close the plot to free memory
        return buf
    except Exception as e:
        logger.error(f"Error generating chart for poll '{poll_topic}': {e}")
        return None


async def pollstats_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays statistics for a specific poll, optionally with a chart."""
    chat_id = update.message.chat_id
    
    if not context.args:
        await update.message.reply_text("Usage: /pollstats <poll_id> [chart_type]\n(chart_type: 'bar' or 'pie', defaults to 'bar')")
        return

    poll_id = context.args[0]
    chart_type_input = context.args[1].lower() if len(context.args) > 1 else "bar"

    if chart_type_input not in ["bar", "pie"]:
        await update.message.reply_text(f"Invalid chart type '{chart_type_input}'. Defaulting to 'bar'. Valid types are 'bar' or 'pie'.")
        chart_type = "bar"
    else:
        chart_type = chart_type_input
        
    if poll_id not in polls_data:
        await update.message.reply_text("Error: Poll not found.")
        return

    poll = polls_data[poll_id]

    if poll["chat_id"] != chat_id:
        await update.message.reply_text("Error: This poll ID does not belong to this chat, or you do not have permission to view its stats.")
        return

    options = poll["options"]
    vote_counts = [0] * len(options)
    
    for voter_id, option_index in poll["votes"].items():
        if 0 <= option_index < len(options): # Ensure option_index is valid
            vote_counts[option_index] += 1
    
    total_votes = sum(vote_counts)

    stats_message = f"📊 *Statistics for Poll: {poll['topic']}*\n"
    stats_message += f"🆔 *ID:* `{poll_id}`\n"
    stats_message += f"🚦 *Status:* {get_friendly_poll_status(poll['status'])}\n\n"

    if total_votes == 0:
        stats_message += "No votes have been cast yet."
    else:
        for i, option_text in enumerate(options):
            percentage = (vote_counts[i] / total_votes) * 100 if total_votes > 0 else 0
            stats_message += f"🔹 *{option_text}:* {vote_counts[i]} vote(s) ({percentage:.2f}%)\n"
    
    stats_message += f"\n👥 *Total Votes Cast:* {total_votes}"

    await update.message.reply_text(stats_message, parse_mode='Markdown')

    if total_votes > 0:
        try:
            chart_buffer = generate_poll_chart(poll["topic"], options, vote_counts, chart_type)
            if chart_buffer:
                await context.bot.send_photo(
                    chat_id=chat_id, 
                    photo=chart_buffer, 
                    caption=f"Chart for poll: '{poll['topic']}' ({chart_type} chart)"
                )
                logger.info(f"Sent {chart_type} chart for poll {poll_id} to chat {chat_id}")
            elif chart_type_input in ["bar", "pie"]: # If a valid chart type was requested but buffer is None (error)
                 await update.message.reply_text("Could not generate the chart due to an internal error. Please check logs.")
        except Exception as e:
            logger.error(f"Failed to generate or send chart for poll {poll_id}: {e}")
            await update.message.reply_text("An error occurred while generating the poll chart. Displaying text stats only.")
    elif chart_type_input in ["bar", "pie"]: # If chart was requested but no votes
        await update.message.reply_text(f"Cannot generate a '{chart_type}' chart as there are no votes yet for poll '{poll['topic']}'.")


async def check_active_polls(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodically checks active polls and closes them if their end_time has passed."""
    bot = context.application.bot
    # Iterate over a copy of items in case the dictionary is modified during iteration elsewhere (though less likely for this specific job)
    for poll_id, poll in list(polls_data.items()): # Use list() for a copy of items
        if poll["status"] == "active" and poll["end_time"]:
            if datetime.now() >= poll["end_time"]:
                poll["status"] = "ended_time_expired"
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


async def endpoll_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /endpoll command to manually end an active poll."""
    user_id = update.message.from_user.id
    
    if not context.args:
        await update.message.reply_text("Usage: /endpoll <poll_id>")
        return

    poll_id = context.args[0]

    if poll_id not in polls_data:
        await update.message.reply_text("Error: Poll not found.")
        return

    poll = polls_data[poll_id]

    if poll["creator_id"] != user_id:
        await update.message.reply_text("Error: Only the poll creator can end this poll.")
        return

    if poll["status"] != "active":
        await update.message.reply_text(f"Error: Poll is not active. Current status: {poll['status']}.")
        return
    
    # End the poll
    poll["status"] = "ended_manually"
    poll["end_time"] = datetime.now() # Set/update end time

    logger.info(f"Poll {poll_id} was manually ended by creator {user_id}.")
    await context.bot.send_message(
        chat_id=poll["chat_id"], 
        text=f"Poll '{poll['topic']}' has been manually ended by the creator."
    )

    # Try to edit the original poll message to remove buttons or indicate it's closed
    if poll.get("message_id") and poll.get("chat_id"):
        try:
            updated_text = f"📊 *Poll: {poll['topic']}* (Ended by creator)\n\nVoting has concluded."
            await context.bot.edit_message_text(
                chat_id=poll["chat_id"],
                message_id=poll["message_id"],
                text=updated_text,
                parse_mode='Markdown'
            )
            # If text edit is successful, we can also try to remove keyboard. 
            # If edit_message_text already removes it, this is redundant.
            # For some bots/clients, editing text AND reply_markup in one go is better.
            # Let's try to remove reply_markup explicitly if text was edited.
            await context.bot.edit_message_reply_markup(
                chat_id=poll["chat_id"],
                message_id=poll["message_id"],
                reply_markup=None
            )
            logger.info(f"Successfully edited and removed keyboard for ended poll {poll_id}.")
        except Exception as e:
            logger.error(f"Error updating original poll message for {poll_id}: {e}. It might be too old or message content unchanged.")
            # Send a new message if editing failed and buttons are likely still active
            await context.bot.send_message(
                chat_id=poll["chat_id"],
                text=f"Voting for poll '{poll['topic']}' has now concluded.",
                reply_to_message_id=poll["message_id"] # Reply to the original poll message
            )


def main() -> None:
    """Start the bot."""
    # Load existing poll data
    global polls_data
    polls_data = load_polls_data()

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Setup JobQueue
    job_queue = application.job_queue
    job_queue.run_repeating(check_active_polls, interval=60, first=0) # Check every 60 seconds
    job_queue.run_repeating(scheduled_save_data, interval=300, first=300) # Save data every 5 minutes

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("startpoll", startpoll_command_handler))
    application.add_handler(CommandHandler("endpoll", endpoll_command_handler))
    application.add_handler(CommandHandler("pollhistory", pollhistory_command_handler))
    application.add_handler(CommandHandler("pollstats", pollstats_command_handler))
    application.add_handler(CommandHandler("menu", menu_command_handler))

    # Add handler for callback queries (button presses)
    # General vote button handler
    application.add_handler(CallbackQueryHandler(button_callback_handler, pattern='^vote_'))
    # Menu specific callback handlers
    application.add_handler(CallbackQueryHandler(menu_start_poll_guide_callback, pattern='^menu_start_poll_guide$'))
    application.add_handler(CallbackQueryHandler(menu_view_history_cmd_callback, pattern='^menu_view_history_cmd$'))
    application.add_handler(CallbackQueryHandler(menu_end_poll_list_callback, pattern='^menu_end_poll_list$'))
    application.add_handler(CallbackQueryHandler(end_poll_confirm_callback, pattern='^end_poll_confirm_'))
    application.add_handler(CallbackQueryHandler(end_poll_execute_callback, pattern='^end_poll_execute_'))
    application.add_handler(CallbackQueryHandler(back_to_main_menu_callback, pattern='^back_to_main_menu$'))
    # Add other menu button handlers here as they are implemented (e.g., menu_stats_poll_list)
    application.add_handler(CallbackQueryHandler(menu_stats_poll_list_callback, pattern='^menu_stats_poll_list$'))
    application.add_handler(CallbackQueryHandler(stats_select_chart_type_callback, pattern='^stats_select_chart_type_'))
    application.add_handler(CallbackQueryHandler(stats_execute_callback, pattern='^stats_execute_'))


    # Add handler for new chat members (bot being added to a group)
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_members_handler))

    # Start the Bot
    application.run_polling()


if __name__ == "__main__":
    main()
