import logging
from datetime import datetime, timedelta
import re # For parsing quoted strings
import io 

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

# Assuming bot.py is in the parent directory of handlers
# For now, we import shared data and helper functions directly from bot.py
# This will be refactored later to reduce coupling.
from ..bot import polls_data, save_data, generate_poll_id, DEFAULT_POLL_DURATION_MINUTES, logger as bot_logger
from ..utils import generate_poll_chart, get_friendly_poll_status # Import from utils

# It's generally better for submodules to have their own logger,
# but for now, to keep changes minimal for this step, we can use the one from bot.py or define a new one.
# Let's define a new one for this module to follow best practices,
# and if needed, can be configured similarly to the main bot logger.
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the /start command is issued."""
    await update.message.reply_text("Welcome to the Voting Bot!")

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
    save_data() # Save data after creating a new poll

    logger.info(f"Poll {poll_id} created in chat {chat_id} by user {creator_id} with topic '{topic}' and options {options}. Duration: {duration_text}. Message ID: {sent_message.message_id}")
    await update.message.reply_text(f"Poll '{topic}' created with ID: {poll_id}. Users can vote using the buttons above.")


async def pollhistory_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the history of polls for the current chat."""
    chat_id = update.message.chat_id
    
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
        await update.message.reply_text("No polls found for this chat.")


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
            # generate_poll_chart is imported from ..bot
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
    save_data() # Save data after manually ending a poll

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
            await context.bot.edit_message_reply_markup(
                chat_id=poll["chat_id"],
                message_id=poll["message_id"],
                reply_markup=None
            )
            logger.info(f"Successfully edited and removed keyboard for ended poll {poll_id}.")
        except Exception as e:
            logger.error(f"Error updating original poll message for {poll_id}: {e}. It might be too old or message content unchanged.")
            await context.bot.send_message(
                chat_id=poll["chat_id"],
                text=f"Voting for poll '{poll['topic']}' has now concluded.",
                reply_to_message_id=poll["message_id"] # Reply to the original poll message
            )
