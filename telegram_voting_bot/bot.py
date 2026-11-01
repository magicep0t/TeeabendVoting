import logging
import uuid
from datetime import datetime, timedelta
import re
import io
import json
import os
import matplotlib
# Use headless backend for Matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration via environment variables with defaults
DATA_FILE = os.environ.get("POLLS_DATA_FILE", "telegram_bot_polls_data.json")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
DEFAULT_POLL_DURATION_MINUTES = int(os.environ.get("DEFAULT_POLL_DURATION_MINUTES", "5"))

# In-memory data structures
polls_data: dict = {}
chat_members: dict = {}

COMMAND_DESCRIPTIONS = {
    "start": {
        "description": "Shows the welcome and help message with available commands.",
        "usage": "/start"
    },
    "startpoll": {
        "description": "Starts a new poll in the current chat.",
        "usage": "/startpoll [duration_minutes] \"Topic\" \"Option 1\" \"Option 2\" ...",
        "details": "- `duration_minutes` (optional): Poll duration in minutes (e.g., 30). Default is 5. Use 0 for no time limit.\n"
                   "- `\"Topic\"`: The question for your poll (must be in double quotes).\n"
                   "- `\"Option X\"`: At least two answer choices (each in double quotes).",
        "example": "/startpoll 60 \"Favorite Color?\" \"Red\" \"Blue\" \"Green\""
    },
    "endpoll": {
        "description": "Manually ends an active poll that you created.",
        "usage": "/endpoll <poll_id>",
        "details": "- `<poll_id>`: The unique ID of the poll (provided upon poll creation).",
    },
    "results": {
        "description": "Displays quick live or final results for a poll.",
        "usage": "/results <poll_id>",
        "details": "- `<poll_id>`: The unique ID of the poll.",
    },
    "pollhistory": {
        "description": "Shows the history of all polls created in this chat.",
        "usage": "/pollhistory"
    },
    "pollstats": {
        "description": "Shows detailed statistics and charts for a specific poll.",
        "usage": "/pollstats <poll_id> [chart_type]",
        "details": "- `<poll_id>`: The unique ID of the poll.\n"
                   "- `chart_type` (optional): `bar` or `pie`. Default is `bar`.",
        "example": "/pollstats your_poll_id pie"
    },
    "menu": {
        "description": "Opens an interactive menu for easy bot operations.",
        "usage": "/menu"
    }
}

def get_formatted_help_message() -> str:
    """Generates a formatted help message from COMMAND_DESCRIPTIONS."""
    message_parts = ["👋 *Welcome to the Advanced Voting Bot!*", "\nHere's how you can use me:\n"]

    categories = {
        "Polling Commands": ["startpoll", "endpoll", "results"],
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
                    message_parts.append(f"  {cmd_info['details'].replace('-', '  -', 1)}")
                if "example" in cmd_info:
                    message_parts.append(f"  _Example:_ `{cmd_info['example']}`")
                processed_commands.add(cmd_key)

    for cmd_key, cmd_info in COMMAND_DESCRIPTIONS.items():
        if cmd_key not in processed_commands:
            message_parts.append(f"\n*Other Commands:*")
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
    """Converts datetime objects and int keys in poll data for JSON serialization."""
    data_copy = poll_data_dict.copy()
    if isinstance(data_copy.get("start_time"), datetime):
        data_copy["start_time"] = data_copy["start_time"].isoformat()
    if isinstance(data_copy.get("end_time"), datetime):
        data_copy["end_time"] = data_copy["end_time"].isoformat()
    if "votes" in data_copy and isinstance(data_copy["votes"], dict):
        data_copy["votes"] = {str(k): v for k, v in data_copy["votes"].items()}
    return data_copy

def convert_iso_to_datetimes(poll_data_dict: dict) -> dict:
    """Converts ISO 8601 string representations and restores int vote keys."""
    data_copy = poll_data_dict.copy()
    if isinstance(data_copy.get("start_time"), str):
        data_copy["start_time"] = datetime.fromisoformat(data_copy["start_time"])
    if isinstance(data_copy.get("end_time"), str):
        data_copy["end_time"] = datetime.fromisoformat(data_copy["end_time"])
    if "votes" in data_copy and isinstance(data_copy["votes"], dict):
        # Convert string user_id keys back to integers
        converted_votes = {}
        for k, v in data_copy["votes"].items():
            try:
                converted_votes[int(k)] = int(v)
            except (ValueError, TypeError):
                converted_votes[k] = v
        data_copy["votes"] = converted_votes
    return data_copy

def load_polls_data(filepath: str | None = None) -> dict:
    """Loads poll data from filepath or DATA_FILE. Returns an empty dict if not found or on error."""
    target_file = filepath or DATA_FILE
    if os.path.exists(target_file):
        try:
            with open(target_file, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
                return {
                    poll_id: convert_iso_to_datetimes(data)
                    for poll_id, data in loaded_data.items()
                }
        except (json.JSONDecodeError, IOError, TypeError) as e:
            logger.warning(f"Error loading data from {target_file}: {e}. Starting with empty data.")
            return {}
    else:
        logger.info(f"{target_file} not found. Starting with empty poll data.")
        return {}

def save_polls_data(filepath: str | None = None) -> bool:
    """Atomically saves the current polls_data to target file."""
    global polls_data
    target_file = filepath or DATA_FILE
    data_to_save = {
        poll_id: convert_datetimes_to_iso(data)
        for poll_id, data in polls_data.copy().items()
    }
    tmp_file = f"{target_file}.tmp"
    try:
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, indent=4)
        os.replace(tmp_file, target_file)
        logger.info(f"Polls data successfully saved to {target_file}.")
        return True
    except IOError as e:
        logger.error(f"Error saving data to {target_file}: {e}")
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except OSError:
                pass
        return False

async def scheduled_save_data(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Async wrapper for save_polls_data to be used with JobQueue."""
    logger.info("JobQueue: Performing scheduled save of polls_data.")
    save_polls_data()

def generate_poll_id() -> str:
    """Generates a unique poll ID."""
    return uuid.uuid4().hex

def parse_quoted_arguments(args_str: str) -> list[str]:
    """Parses arguments enclosed in standard or smart quotes."""
    # Matches "...", “...”, ”...”, ‘...’, '...'
    pattern = r'["“](.*?)[”"]|[\'‘](.*?)[\'’]'
    matches = re.findall(pattern, args_str)
    results = []
    for m in matches:
        content = m[0] if m[0] else m[1]
        results.append(content)
    return results

def get_friendly_poll_status(status: str) -> str:
    """Converts internal poll status to a user-friendly string."""
    status_map = {
        "active": "Active",
        "closed": "Closed (Expired)",
        "ended_manually": "Ended by Creator",
        "ended_time_expired": "Ended (Time Limit Reached)",
    }
    return status_map.get(status, status.replace("_", " ").title())

def format_poll_message(poll: dict) -> str:
    """Generates the formatted message text for a poll."""
    topic = poll["topic"]
    options = poll["options"]
    votes = poll.get("votes", {})
    total_votes = len(votes)

    if poll.get("end_time") and poll["status"] == "active":
        duration_text = f"Ends at {poll['end_time'].strftime('%H:%M:%S')} (active)"
    elif poll["status"] == "active":
        duration_text = "No time limit"
    else:
        duration_text = get_friendly_poll_status(poll["status"])

    # Count votes per option
    vote_counts = [0] * len(options)
    for option_index in votes.values():
        if 0 <= option_index < len(options):
            vote_counts[option_index] += 1

    lines = [
        f"📊 *Poll: {topic}*",
        f"🚦 Status: {get_friendly_poll_status(poll['status'])}",
        f"⏱ Duration: {duration_text}\n",
        "Select an option below to vote (or change your vote):\n"
    ]

    for idx, opt in enumerate(options):
        count = vote_counts[idx]
        lines.append(f"{idx + 1}. *{opt}* — {count} vote(s)")

    lines.append(f"\n👥 *Total Votes:* {total_votes}")
    return "\n".join(lines)

def build_poll_keyboard(poll_id: str, options: list[str]) -> InlineKeyboardMarkup:
    """Builds the inline voting keyboard for a poll."""
    keyboard = []
    for i, option in enumerate(options):
        keyboard.append([InlineKeyboardButton(option, callback_data=f"vote_{poll_id}_{i}")])
    return InlineKeyboardMarkup(keyboard)

# --- Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a detailed help message when the /start command is issued."""
    if update.message:
        await update.message.reply_text(HELP_MESSAGE, parse_mode='Markdown')

async def new_chat_members_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message if the bot is added to a new chat."""
    if update.message and update.message.new_chat_members:
        bot_id = context.bot.id
        for member in update.message.new_chat_members:
            if member.id == bot_id:
                chat_id = update.message.chat_id
                logger.info(f"Bot added to new chat {chat_id}. Sending welcome message.")
                await context.bot.send_message(chat_id, HELP_MESSAGE, parse_mode='Markdown')
                break

async def startpoll_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /startpoll command to create a new poll."""
    if not update.message:
        return
    chat_id = update.message.chat_id
    creator_id = update.message.from_user.id
    args_str = " ".join(context.args) if context.args else ""

    quoted_parts = parse_quoted_arguments(args_str)

    if not quoted_parts or len(quoted_parts) < 3:
        await update.message.reply_text(
            "Usage: /startpoll [duration_minutes] \"Topic\" \"Option 1\" \"Option 2\" ...\n"
            "Topic and options must be enclosed in quotes. At least two options are required."
        )
        return

    topic = quoted_parts[0]
    options = quoted_parts[1:]

    if len(options) < 2:
        await update.message.reply_text("A poll must have at least two options.")
        return

    # Extract non-quoted duration prefix if provided
    non_quoted_args_str = args_str
    for part in quoted_parts:
        # Remove quoted string
        non_quoted_args_str = re.sub(rf'["“\']{re.escape(part)}["”\']', '', non_quoted_args_str).strip()

    duration_minutes = DEFAULT_POLL_DURATION_MINUTES
    if non_quoted_args_str:
        tokens = non_quoted_args_str.split()
        if tokens:
            try:
                duration_input = int(tokens[0])
                if duration_input < 0:
                    await update.message.reply_text("Duration cannot be negative.")
                    return
                duration_minutes = duration_input
            except ValueError:
                await update.message.reply_text(
                    f"Invalid duration. Using default: {DEFAULT_POLL_DURATION_MINUTES} minutes.\n"
                    "Usage: /startpoll [duration_minutes] \"Topic\" \"Option 1\" \"Option 2\" ..."
                )

    start_time = datetime.now()
    end_time = start_time + timedelta(minutes=duration_minutes) if duration_minutes > 0 else None

    poll_id = generate_poll_id()
    poll_entry = {
        "chat_id": chat_id,
        "creator_id": creator_id,
        "topic": topic,
        "options": options,
        "start_time": start_time,
        "end_time": end_time,
        "status": "active",
        "votes": {},
        "message_id": None
    }
    polls_data[poll_id] = poll_entry

    reply_markup = build_poll_keyboard(poll_id, options)
    poll_message_text = format_poll_message(poll_entry)

    sent_message = await update.message.reply_text(poll_message_text, reply_markup=reply_markup, parse_mode='Markdown')
    polls_data[poll_id]["message_id"] = sent_message.message_id
    save_polls_data()

    logger.info(f"Poll {poll_id} created in chat {chat_id} by user {creator_id}.")
    await update.message.reply_text(f"Poll Created. Poll ID: `{poll_id}`", parse_mode='Markdown')

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles inline button presses for voting and allows changing votes."""
    query = update.callback_query
    if not query or not query.from_user or not query.data:
        return

    user_id = query.from_user.id
    callback_data = query.data

    if callback_data.startswith("vote_"):
        # Format is vote_<poll_id>_<option_index>
        # Note: poll_id could potentially contain underscores or be a hex uuid
        prefix, rest = callback_data.split("vote_", 1)
        r_parts = rest.rsplit("_", 1)
        if len(r_parts) != 2:
            await query.answer("Invalid vote data.", show_alert=True)
            return

        poll_id, option_index_str = r_parts

        if poll_id not in polls_data:
            await query.answer("Error: Poll not found. It might have been deleted.", show_alert=True)
            return

        poll = polls_data[poll_id]

        if poll["status"] != "active":
            await query.answer("This poll is no longer active.", show_alert=True)
            return

        if poll["end_time"] and datetime.now() > poll["end_time"]:
            poll["status"] = "ended_time_expired"
            save_polls_data()
            await query.answer("This poll has expired and is now closed.", show_alert=True)
            return

        try:
            option_index = int(option_index_str)
            if not (0 <= option_index < len(poll["options"])):
                await query.answer("Invalid option selected.", show_alert=True)
                return
        except ValueError:
            await query.answer("Error processing your vote.", show_alert=True)
            return

        selected_option_text = poll["options"][option_index]
        existing_vote = poll["votes"].get(user_id)

        if existing_vote == option_index:
            await query.answer(f"You have already voted for: '{selected_option_text}'.", show_alert=True)
            return

        poll["votes"][user_id] = option_index
        save_polls_data()

        status_msg = f"Vote changed to '{selected_option_text}'!" if existing_vote is not None else f"Your vote for '{selected_option_text}' has been recorded!"
        await query.answer(status_msg, show_alert=False)
        logger.info(f"User {user_id} voted for option {option_index} in poll {poll_id}")

        # Live update poll message with current tally
        if poll.get("message_id") and poll.get("chat_id"):
            try:
                updated_text = format_poll_message(poll)
                reply_markup = build_poll_keyboard(poll_id, poll["options"])
                await context.bot.edit_message_text(
                    chat_id=poll["chat_id"],
                    message_id=poll["message_id"],
                    text=updated_text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.debug(f"Could not update poll message in real-time: {e}")
    else:
        await query.answer()

# --- Menu Callbacks ---

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Returns the InlineKeyboardMarkup for the main menu."""
    keyboard = [
        [InlineKeyboardButton("🚀 Start New Poll Guide", callback_data='menu_start_poll_guide')],
        [InlineKeyboardButton("📊 View Poll History", callback_data='menu_view_history_cmd')],
        [InlineKeyboardButton("🛑 End a Poll", callback_data='menu_end_poll_list')],
        [InlineKeyboardButton("📈 View Poll Statistics", callback_data='menu_stats_poll_list')]
    ]
    return InlineKeyboardMarkup(keyboard)

async def menu_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the main menu with inline keyboard buttons."""
    if update.message:
        reply_markup = get_main_menu_keyboard()
        await update.message.reply_text("Voting Bot Menu:\nChoose an option:", reply_markup=reply_markup)

async def back_to_main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Edits the current message to show the main menu."""
    query = update.callback_query
    if query:
        await query.answer()
        reply_markup = get_main_menu_keyboard()
        await query.edit_message_text("Voting Bot Menu:\nChoose an option:", reply_markup=reply_markup)

async def menu_start_poll_guide_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'Start New Poll' menu button."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    startpoll_info = COMMAND_DESCRIPTIONS.get("startpoll", {})
    usage = startpoll_info.get("usage", "/startpoll [duration_minutes] \"Topic\" \"Option 1\" \"Option 2\" ...")
    details = startpoll_info.get("details", "")
    example = startpoll_info.get("example", "")

    guide_message = (
        "To start a new poll, please use the command: \n"
        f"`{usage}`\n\n"
        f"{details.replace('-', '  -', 1)}\n\n"
        f"_Example:_\n`{example}`\n\n"
        "See /start for more detailed command descriptions."
    )
    if query.message:
        await query.message.reply_text(guide_message, parse_mode='Markdown')

async def menu_view_history_cmd_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'View Poll History' menu button by invoking pollhistory_command_handler."""
    query = update.callback_query
    if not query or not query.message:
        return
    await query.answer()
    await pollhistory_command_handler(update, context, message_obj=query.message)

async def menu_stats_poll_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays a list of all polls in the chat to select for statistics."""
    query = update.callback_query
    if not query or not query.message:
        return
    chat_id = query.message.chat_id

    chat_polls = {pid: pdata for pid, pdata in polls_data.items() if pdata["chat_id"] == chat_id}

    keyboard = []
    if not chat_polls:
        message_text = "No polls found in this chat."
    else:
        message_text = "Select a poll to view its statistics:"
        sorted_poll_ids = sorted(chat_polls.keys(), key=lambda pid: chat_polls[pid]["start_time"], reverse=True)
        for poll_id in sorted_poll_ids:
            poll_data = chat_polls[poll_id]
            topic_short = poll_data['topic'][:25] + "..." if len(poll_data['topic']) > 25 else poll_data['topic']
            status_friendly = get_friendly_poll_status(poll_data['status'])
            keyboard.append([
                InlineKeyboardButton(
                    f"{topic_short} ({status_friendly})",
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
    if not query:
        return
    poll_id = query.data.split("stats_select_chart_type_")[-1]

    if poll_id not in polls_data:
        await query.answer("Error: Poll not found. It might have been deleted.", show_alert=True)
        await menu_stats_poll_list_callback(update, context)
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
    if not query or not query.message:
        return
    # Callback format: stats_execute_<poll_id>_<chart_type>
    raw_data = query.data[len("stats_execute_"):]
    r_parts = raw_data.rsplit("_", 1)
    if len(r_parts) != 2:
        return
    poll_id, chart_type = r_parts

    chat_id = query.message.chat_id
    await query.answer("Generating statistics...")

    if poll_id not in polls_data:
        await context.bot.send_message(chat_id, "Error: Poll not found. It might have been deleted.")
        return

    poll = polls_data[poll_id]
    if poll["chat_id"] != chat_id:
        await context.bot.send_message(chat_id, "Error: Poll does not belong to this chat.")
        return

    options = poll["options"]
    vote_counts = [0] * len(options)
    for option_index in poll["votes"].values():
        if 0 <= option_index < len(options):
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

    await context.bot.send_message(chat_id, stats_message, parse_mode='Markdown')

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
                else:
                    await context.bot.send_message(chat_id, "Could not generate the chart due to an internal error.")
            except Exception as e:
                logger.error(f"Failed to generate or send chart for poll {poll_id}: {e}")
                await context.bot.send_message(chat_id, "An error occurred while generating the poll chart.")
        else:
            await context.bot.send_message(chat_id, f"Cannot generate a '{chart_type}' chart as there are no votes yet for poll '{poll['topic']}'.")

    await query.edit_message_text(
        "Statistics request processed. See messages above.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Poll List", callback_data='menu_stats_poll_list')],
            [InlineKeyboardButton("🏠 Main Menu", callback_data='back_to_main_menu')]
        ])
    )

async def menu_end_poll_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays a list of active polls created by the user in this chat to end."""
    query = update.callback_query
    if not query or not query.message or not query.from_user:
        return
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    active_user_polls = {
        pid: pdata for pid, pdata in polls_data.items() 
        if pdata["chat_id"] == chat_id and pdata["status"] == "active" and pdata["creator_id"] == user_id
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
    if not query:
        return
    poll_id = query.data.split("end_poll_confirm_")[-1]

    if poll_id not in polls_data:
        await query.answer("Error: Poll not found. It might have been deleted.", show_alert=True)
        await back_to_main_menu_callback(update, context)
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
    if not query or not query.from_user:
        return
    user_id = query.from_user.id
    poll_id = query.data.split("end_poll_execute_")[-1]

    if poll_id not in polls_data:
        await query.answer("Error: Poll not found. It might have been deleted.", show_alert=True)
        await back_to_main_menu_callback(update, context)
        return

    poll = polls_data[poll_id]

    if poll["creator_id"] != user_id:
        await query.answer("Error: Only the poll creator can end this poll.", show_alert=True)
        await menu_end_poll_list_callback(update, context)
        return

    if poll["status"] != "active":
        await query.answer(f"Error: Poll is no longer active. Current status: {get_friendly_poll_status(poll['status'])}.", show_alert=True)
        await menu_end_poll_list_callback(update, context)
        return

    poll["status"] = "ended_manually"
    poll["end_time"] = datetime.now()
    save_polls_data()

    logger.info(f"Poll {poll_id} ('{poll['topic']}') was manually ended by creator {user_id} via menu.")

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
        except Exception as e:
            logger.error(f"Error updating original poll message for {poll_id}: {e}")

    await query.answer(f"Poll '{poll['topic']}' has been ended.")
    await query.edit_message_text(
        f"Poll '{poll['topic']}' has been successfully ended.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='back_to_main_menu')]])
    )

async def pollhistory_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, message_obj=None) -> None:
    """Displays the history of polls for the current chat safely handling command or callback calls."""
    target_message = message_obj or (update.message if update else None)
    if not target_message:
        logger.error("pollhistory_command_handler called without a valid message object.")
        return

    chat_id = target_message.chat_id
    chat_polls = {pid: pdata for pid, pdata in polls_data.items() if pdata["chat_id"] == chat_id}

    if not chat_polls:
        await target_message.reply_text("No polls found for this chat.")
        return

    history_messages = []
    current_message = "📜 *Poll History for this Chat:*\n\n"
    sorted_poll_ids = sorted(chat_polls.keys(), key=lambda pid: chat_polls[pid]["start_time"], reverse=True)

    for poll_id in sorted_poll_ids:
        poll = chat_polls[poll_id]
        options_str = ", ".join(poll['options'])
        if len(options_str) > 100:
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

        if len(current_message) + len(poll_info) > 4000:
            history_messages.append(current_message)
            current_message = ""

        current_message += poll_info

    if current_message:
        history_messages.append(current_message)

    for msg_part in history_messages:
        await target_message.reply_text(msg_part, parse_mode='Markdown')

def generate_poll_chart(poll_topic: str, options: list[str], vote_counts: list[int], chart_type: str) -> io.BytesIO | None:
    """Generates a bar or pie chart for poll statistics and returns it as a BytesIO buffer."""
    try:
        fig, ax = plt.subplots(figsize=(10, 6))

        if chart_type == "bar":
            bars = ax.bar(options, vote_counts, color=['skyblue', 'lightgreen', 'lightcoral', 'gold', 'lightsalmon', 'cyan'])
            ax.set_ylabel('Votes')
            ax.set_title(f'Poll Statistics: {poll_topic}\n(Bar Chart)')
            ax.tick_params(axis='x', rotation=45)
            fig.tight_layout()

            for bar in bars:
                yval = bar.get_height()
                ax.text(bar.get_x() + bar.get_width() / 2.0, yval + 0.05, int(yval), va='bottom', ha='center')

        elif chart_type == "pie":
            filtered_options = [opt for i, opt in enumerate(options) if vote_counts[i] > 0]
            filtered_vote_counts = [vc for vc in vote_counts if vc > 0]

            if not filtered_vote_counts:
                ax.text(0.5, 0.5, 'No votes to display in pie chart.', horizontalalignment='center', verticalalignment='center')
            else:
                ax.pie(
                    filtered_vote_counts,
                    labels=filtered_options,
                    autopct='%1.1f%%',
                    startangle=140,
                    colors=['skyblue', 'lightgreen', 'lightcoral', 'gold', 'lightsalmon', 'cyan']
                )
                ax.set_title(f'Poll Statistics: {poll_topic}\n(Pie Chart)')
                ax.axis('equal')
        else:
            logger.warning(f"Invalid chart type requested: {chart_type}")
            plt.close(fig)
            return None

        buf = io.BytesIO()
        fig.savefig(buf, format='png')
        buf.seek(0)
        plt.close(fig)
        return buf
    except Exception as e:
        logger.error(f"Error generating chart for poll '{poll_topic}': {e}")
        return None

async def results_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays quick text results and leading option for a given poll."""
    if not update.message:
        return
    chat_id = update.message.chat_id

    if not context.args:
        await update.message.reply_text("Usage: /results <poll_id>")
        return

    poll_id = context.args[0]
    if poll_id not in polls_data:
        await update.message.reply_text("Error: Poll not found.")
        return

    poll = polls_data[poll_id]
    if poll["chat_id"] != chat_id:
        await update.message.reply_text("Error: This poll does not belong to this chat.")
        return

    options = poll["options"]
    vote_counts = [0] * len(options)
    for option_index in poll["votes"].values():
        if 0 <= option_index < len(options):
            vote_counts[option_index] += 1

    total_votes = sum(vote_counts)
    lines = [
        f"📊 *Results for Poll: {poll['topic']}*",
        f"🚦 *Status:* {get_friendly_poll_status(poll['status'])}",
        f"👥 *Total Votes:* {total_votes}\n"
    ]

    max_votes = -1
    leading_options = []
    for i, option in enumerate(options):
        count = vote_counts[i]
        pct = (count / total_votes * 100) if total_votes > 0 else 0
        lines.append(f"• *{option}*: {count} ({pct:.1f}%)")
        if count > max_votes and count > 0:
            max_votes = count
            leading_options = [option]
        elif count == max_votes and count > 0:
            leading_options.append(option)

    if leading_options:
        if len(leading_options) == 1:
            lines.append(f"\n🏆 *Leader:* {leading_options[0]} ({max_votes} votes)")
        else:
            lines.append(f"\n🤝 *Tie:* {', '.join(leading_options)} ({max_votes} votes each)")
    else:
        lines.append("\nNo votes cast yet.")

    await update.message.reply_text("\n".join(lines), parse_mode='Markdown')

async def pollstats_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays statistics for a specific poll, optionally with a chart."""
    if not update.message:
        return
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
    for option_index in poll["votes"].values():
        if 0 <= option_index < len(options):
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
            else:
                await update.message.reply_text("Could not generate the chart due to an internal error.")
        except Exception as e:
            logger.error(f"Failed to generate or send chart for poll {poll_id}: {e}")
            await update.message.reply_text("An error occurred while generating the poll chart. Displaying text stats only.")
    elif chart_type_input in ["bar", "pie"]:
        await update.message.reply_text(f"Cannot generate a '{chart_type}' chart as there are no votes yet for poll '{poll['topic']}'.")

async def check_active_polls(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodically checks active polls and closes them if their end_time has passed."""
    bot = context.application.bot
    updated_any = False
    for poll_id, poll in list(polls_data.items()):
        if poll["status"] == "active" and poll["end_time"]:
            if datetime.now() >= poll["end_time"]:
                poll["status"] = "ended_time_expired"
                updated_any = True
                logger.info(f"Poll {poll_id} ('{poll['topic']}') has expired due to time limit.")

                try:
                    await bot.send_message(
                        chat_id=poll["chat_id"],
                        text=f"Poll '{poll['topic']}' has ended as the time limit was reached."
                    )
                except Exception as e:
                    logger.error(f"Error sending message for expired poll {poll_id}: {e}")

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
                    except Exception as e:
                        logger.error(f"Error updating message for expired poll {poll_id}: {e}")

    if updated_any:
        save_polls_data()

async def endpoll_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /endpoll command to manually end an active poll."""
    if not update.message:
        return
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

    poll["status"] = "ended_manually"
    poll["end_time"] = datetime.now()
    save_polls_data()

    logger.info(f"Poll {poll_id} was manually ended by creator {user_id}.")
    await context.bot.send_message(
        chat_id=poll["chat_id"], 
        text=f"Poll '{poll['topic']}' has been manually ended by the creator."
    )

    if poll.get("message_id") and poll.get("chat_id"):
        try:
            updated_text = f"📊 *Poll: {poll['topic']}* (Ended by creator)\n\nVoting has concluded."
            await context.bot.edit_message_text(
                chat_id=poll["chat_id"],
                message_id=poll["message_id"],
                text=updated_text,
                parse_mode='Markdown'
            )
            await context.bot.edit_message_reply_markup(
                chat_id=poll["chat_id"],
                message_id=poll["message_id"],
                reply_markup=None
            )
        except Exception as e:
            logger.error(f"Error updating original poll message for {poll_id}: {e}")

def create_application(token: str | None = None) -> Application:
    """Builds and configures the Application instance."""
    bot_token = token or TELEGRAM_BOT_TOKEN
    if not bot_token or bot_token == "YOUR_TELEGRAM_BOT_TOKEN":
        raise ValueError(
            "TELEGRAM_BOT_TOKEN is not configured! "
            "Please set the TELEGRAM_BOT_TOKEN environment variable."
        )

    application = Application.builder().token(bot_token).build()

    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(check_active_polls, interval=60, first=0)
        job_queue.run_repeating(scheduled_save_data, interval=300, first=300)

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("startpoll", startpoll_command_handler))
    application.add_handler(CommandHandler("endpoll", endpoll_command_handler))
    application.add_handler(CommandHandler("results", results_command_handler))
    application.add_handler(CommandHandler("pollhistory", pollhistory_command_handler))
    application.add_handler(CommandHandler("pollstats", pollstats_command_handler))
    application.add_handler(CommandHandler("menu", menu_command_handler))

    # Callbacks
    application.add_handler(CallbackQueryHandler(button_callback_handler, pattern=r'^vote_'))
    application.add_handler(CallbackQueryHandler(menu_start_poll_guide_callback, pattern=r'^menu_start_poll_guide$'))
    application.add_handler(CallbackQueryHandler(menu_view_history_cmd_callback, pattern=r'^menu_view_history_cmd$'))
    application.add_handler(CallbackQueryHandler(menu_end_poll_list_callback, pattern=r'^menu_end_poll_list$'))
    application.add_handler(CallbackQueryHandler(end_poll_confirm_callback, pattern=r'^end_poll_confirm_'))
    application.add_handler(CallbackQueryHandler(end_poll_execute_callback, pattern=r'^end_poll_execute_'))
    application.add_handler(CallbackQueryHandler(back_to_main_menu_callback, pattern=r'^back_to_main_menu$'))
    application.add_handler(CallbackQueryHandler(menu_stats_poll_list_callback, pattern=r'^menu_stats_poll_list$'))
    application.add_handler(CallbackQueryHandler(stats_select_chart_type_callback, pattern=r'^stats_select_chart_type_'))
    application.add_handler(CallbackQueryHandler(stats_execute_callback, pattern=r'^stats_execute_'))

    # Member joins
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_members_handler))

    return application

def main() -> None:
    """Start the bot."""
    global polls_data
    polls_data = load_polls_data()

    try:
        application = create_application()
    except ValueError as e:
        logger.critical(e)
        print(f"\n[ERROR] {e}\nSet the TELEGRAM_BOT_TOKEN environment variable and restart.")
        return

    logger.info("Starting Telegram Voting Bot polling...")
    try:
        application.run_polling()
    finally:
        save_polls_data()
        logger.info("Bot stopped. Data saved.")

if __name__ == "__main__":
    main()
