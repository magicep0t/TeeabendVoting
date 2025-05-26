import logging
from datetime import datetime # For checking poll expiry

from telegram import Update
from telegram.ext import ContextTypes

# Assuming bot.py is in the parent directory of handlers
from ..bot import polls_data, save_data # Removed bot_logger import as we'll use a local one

# It's generally better for modules to have their own loggers
logger = logging.getLogger(__name__)


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
            logger.warning(f"Invalid vote data received: {callback_data} from user {user_id}")
            return

        action, poll_id, option_index_str = parts
        
        if poll_id not in polls_data:
            await query.answer("Error: Poll not found. It might have been deleted.", show_alert=True)
            logger.warning(f"Poll {poll_id} not found for vote attempt by user {user_id}.")
            return

        poll = polls_data[poll_id]

        if poll["status"] != "active":
            await query.answer("This poll is no longer active.", show_alert=True)
            logger.info(f"Vote attempt on non-active poll {poll_id} by user {user_id}. Status: {poll['status']}")
            return

        # Check poll duration if applicable
        if poll["end_time"] and datetime.now() > poll["end_time"]:
            poll["status"] = "closed" # Close the poll
            save_data() # Save data as poll status is changed
            await query.answer("This poll has expired and is now closed.", show_alert=True)
            logger.info(f"Poll {poll_id} expired. Vote attempt by user {user_id} after expiry.")
            # Optionally, edit the poll message to show it's closed
            # This part is more complex and might be better handled in check_active_polls
            # to avoid multiple edits if many users vote on an expired poll simultaneously.
            return

        if user_id in poll["votes"]:
            voted_option_index = poll["votes"][user_id]
            voted_option_text = poll["options"][voted_option_index]
            await query.answer(f"You have already voted for: '{voted_option_text}'.", show_alert=True)
            logger.info(f"User {user_id} attempted to vote again in poll {poll_id}.")
            return

        try:
            option_index = int(option_index_str)
            if not (0 <= option_index < len(poll["options"])):
                await query.answer("Invalid option selected.", show_alert=True)
                logger.warning(f"Invalid option index {option_index_str} selected in poll {poll_id} by user {user_id}.")
                return
        except ValueError:
            await query.answer("Error processing your vote.", show_alert=True)
            logger.error(f"ValueError processing vote for poll {poll_id} by user {user_id}, option_index_str: {option_index_str}")
            return

        # Record the vote
        poll["votes"][user_id] = option_index
        selected_option_text = poll["options"][option_index]
        save_data() # Save data after a vote is recorded
        
        await query.answer(f"Your vote for '{selected_option_text}' has been recorded!", show_alert=False)
        logger.info(f"User {user_id} voted for option {option_index} ('{selected_option_text}') in poll {poll_id}")
    else:
        logger.warning(f"Unknown callback_data received: {callback_data} from user {user_id}")
        await query.answer() # Default answer for other callbacks if any
