import pytest
import os
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import telegram_voting_bot.bot as bot

@pytest.fixture(autouse=True)
def reset_polls_data(tmp_path):
    """Resets polls_data and configures temporary file for each test."""
    test_file = str(tmp_path / "test_polls.json")
    bot.DATA_FILE = test_file
    bot.polls_data = {}
    yield
    bot.polls_data = {}
    if os.path.exists(test_file):
        try:
            os.remove(test_file)
        except OSError:
            pass

def test_quote_parsing():
    """Test parsing of standard double quotes, single quotes, and typographic smart quotes."""
    text1 = '/startpoll 15 "Favorite Fruit" "Apple" "Banana" "Cherry"'
    assert bot.parse_quoted_arguments(text1) == ["Favorite Fruit", "Apple", "Banana", "Cherry"]

    text2 = '/startpoll “German Tea” ‘Earl Grey’ “Assam”'
    assert bot.parse_quoted_arguments(text2) == ["German Tea", "Earl Grey", "Assam"]

    text3 = 'No quotes here'
    assert bot.parse_quoted_arguments(text3) == []

def test_persistence_serialization_deserialization(tmp_path):
    """Test JSON saving and loading with datetime objects and integer vote user_ids."""
    poll_id = "test_poll_123"
    start = datetime(2025, 1, 1, 10, 0, 0)
    end = datetime(2025, 1, 1, 11, 0, 0)
    test_file = str(tmp_path / "polls_storage.json")

    bot.polls_data = {
        poll_id: {
            "chat_id": 999,
            "creator_id": 111,
            "topic": "Lunch Plan",
            "options": ["Pizza", "Pasta"],
            "start_time": start,
            "end_time": end,
            "status": "active",
            "votes": {111: 0, 222: 1},
            "message_id": 555
        }
    }

    assert bot.save_polls_data(test_file) is True
    assert os.path.exists(test_file)

    loaded = bot.load_polls_data(test_file)
    assert poll_id in loaded
    poll = loaded[poll_id]
    assert poll["topic"] == "Lunch Plan"
    assert poll["start_time"] == start
    assert poll["end_time"] == end
    # Ensure keys in votes are converted back to int
    assert 111 in poll["votes"]
    assert 222 in poll["votes"]
    assert poll["votes"][111] == 0
    assert poll["votes"][222] == 1

def test_format_poll_message():
    """Test formatting the poll message with status and vote tallies."""
    poll = {
        "topic": "Deploy Today?",
        "options": ["Yes", "No", "Maybe"],
        "status": "active",
        "end_time": None,
        "votes": {100: 0, 101: 0, 102: 1}
    }
    msg = bot.format_poll_message(poll)
    assert "*Poll: Deploy Today?*" in msg
    assert "1. *Yes* — 2 vote(s)" in msg
    assert "2. *No* — 1 vote(s)" in msg
    assert "3. *Maybe* — 0 vote(s)" in msg
    assert "👥 *Total Votes:* 3" in msg

def test_chart_generation():
    """Test generating bar and pie charts into BytesIO."""
    options = ["Alpha", "Beta", "Gamma"]
    counts = [10, 5, 2]

    bar_buf = bot.generate_poll_chart("Test Bar", options, counts, "bar")
    assert bar_buf is not None
    assert len(bar_buf.getvalue()) > 0

    pie_buf = bot.generate_poll_chart("Test Pie", options, counts, "pie")
    assert pie_buf is not None
    assert len(pie_buf.getvalue()) > 0

    invalid_buf = bot.generate_poll_chart("Test Invalid", options, counts, "scatter")
    assert invalid_buf is None

@pytest.mark.asyncio
async def test_start_command():
    """Test /start command replies with help message."""
    update = MagicMock()
    update.message = AsyncMock()
    context = MagicMock()

    await bot.start(update, context)
    update.message.reply_text.assert_called_once()
    assert "Welcome to the Advanced Voting Bot" in update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_startpoll_command():
    """Test /startpoll creates a poll and registers it."""
    update = MagicMock()
    update.message = AsyncMock()
    update.message.chat_id = 42
    update.message.from_user.id = 100
    sent_msg = MagicMock()
    sent_msg.message_id = 888
    update.message.reply_text.return_value = sent_msg

    context = MagicMock()
    context.args = ["10", '"Topic"', '"Option A"', '"Option B"']

    await bot.startpoll_command_handler(update, context)

    assert len(bot.polls_data) == 1
    poll_id = list(bot.polls_data.keys())[0]
    poll = bot.polls_data[poll_id]
    assert poll["topic"] == "Topic"
    assert poll["options"] == ["Option A", "Option B"]
    assert poll["creator_id"] == 100
    assert poll["chat_id"] == 42
    assert poll["message_id"] == 888

@pytest.mark.asyncio
async def test_button_callback_voting_and_vote_change():
    """Test casting a vote and changing an existing vote."""
    poll_id = "poll_vote_test"
    bot.polls_data[poll_id] = {
        "chat_id": 42,
        "creator_id": 100,
        "topic": "Vote Topic",
        "options": ["First", "Second"],
        "start_time": datetime.now(),
        "end_time": None,
        "status": "active",
        "votes": {},
        "message_id": 777
    }

    update = MagicMock()
    query = MagicMock()
    query.from_user = MagicMock()
    query.from_user.id = 200
    query.data = f"vote_{poll_id}_0"
    query.answer = AsyncMock()
    update.callback_query = query
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.edit_message_text = AsyncMock()

    # Vote for First
    await bot.button_callback_handler(update, context)
    assert bot.polls_data[poll_id]["votes"][200] == 0
    query.answer.assert_called_with("Your vote for 'First' has been recorded!", show_alert=False)

    # Change vote to Second
    query.data = f"vote_{poll_id}_1"
    await bot.button_callback_handler(update, context)
    assert bot.polls_data[poll_id]["votes"][200] == 1
    query.answer.assert_called_with("Vote changed to 'Second'!", show_alert=False)

@pytest.mark.asyncio
async def test_endpoll_permission_and_execution():
    """Test that only creator can end the poll."""
    poll_id = "poll_end_test"
    bot.polls_data[poll_id] = {
        "chat_id": 42,
        "creator_id": 100,
        "topic": "End Topic",
        "options": ["Yes", "No"],
        "start_time": datetime.now(),
        "end_time": None,
        "status": "active",
        "votes": {},
        "message_id": 777
    }

    update = MagicMock()
    update.message = AsyncMock()
    update.message.from_user = MagicMock()
    update.message.from_user.id = 999  # Not creator
    context = MagicMock()
    context.args = [poll_id]
    context.bot = AsyncMock()

    await bot.endpoll_command_handler(update, context)
    assert bot.polls_data[poll_id]["status"] == "active"
    update.message.reply_text.assert_called_with("Error: Only the poll creator can end this poll.")

    # Creator ends poll
    update.message.from_user.id = 100
    await bot.endpoll_command_handler(update, context)
    assert bot.polls_data[poll_id]["status"] == "ended_manually"

@pytest.mark.asyncio
async def test_results_command():
    """Test /results command outputs summary and winner."""
    poll_id = "poll_res"
    bot.polls_data[poll_id] = {
        "chat_id": 50,
        "creator_id": 10,
        "topic": "Pizza vs Burger",
        "options": ["Pizza", "Burger"],
        "start_time": datetime.now(),
        "end_time": None,
        "status": "active",
        "votes": {1: 0, 2: 0, 3: 1},
        "message_id": 11
    }

    update = MagicMock()
    update.message = AsyncMock()
    update.message.chat_id = 50
    context = MagicMock()
    context.args = [poll_id]

    await bot.results_command_handler(update, context)
    update.message.reply_text.assert_called_once()
    reply = update.message.reply_text.call_args[0][0]
    assert "*Results for Poll: Pizza vs Burger*" in reply
    assert "🏆 *Leader:* Pizza (2 votes)" in reply

@pytest.mark.asyncio
async def test_pollhistory_from_callback_query():
    """Verify pollhistory doesn't crash when called from a callback query."""
    poll_id = "poll_hist"
    bot.polls_data[poll_id] = {
        "chat_id": 77,
        "creator_id": 10,
        "topic": "History Topic",
        "options": ["A", "B"],
        "start_time": datetime.now(),
        "end_time": None,
        "status": "active",
        "votes": {},
        "message_id": 12
    }

    # Simulate callback query message (update.message is None)
    update = MagicMock()
    update.message = None
    query_msg = AsyncMock()
    query_msg.chat_id = 77
    context = MagicMock()

    await bot.pollhistory_command_handler(update, context, message_obj=query_msg)
    query_msg.reply_text.assert_called_once()
    assert "📜 *Poll History for this Chat:*" in query_msg.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_check_active_polls_expiry():
    """Test automatic closing of expired polls."""
    expired_poll_id = "expired_poll"
    active_poll_id = "active_poll"
    now = datetime.now()

    bot.polls_data = {
        expired_poll_id: {
            "chat_id": 10,
            "creator_id": 1,
            "topic": "Expired Topic",
            "options": ["A", "B"],
            "start_time": now - timedelta(minutes=10),
            "end_time": now - timedelta(minutes=1),
            "status": "active",
            "votes": {},
            "message_id": 101
        },
        active_poll_id: {
            "chat_id": 10,
            "creator_id": 1,
            "topic": "Still Active",
            "options": ["A", "B"],
            "start_time": now,
            "end_time": now + timedelta(minutes=10),
            "status": "active",
            "votes": {},
            "message_id": 102
        }
    }

    context = MagicMock()
    context.application = MagicMock()
    context.application.bot = AsyncMock()

    await bot.check_active_polls(context)
    assert bot.polls_data[expired_poll_id]["status"] == "ended_time_expired"
    assert bot.polls_data[active_poll_id]["status"] == "active"
    context.application.bot.send_message.assert_called_once()
