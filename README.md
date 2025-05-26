# Telegram Voting Bot

## Description
A Telegram bot that allows users to create and participate in polls within a chat. The bot supports timed polls, manual poll ending, vote tracking, and displaying poll history and statistics with charts.

## Features
- Create polls with custom topics and multiple options.
- Set an optional duration for polls.
- Vote on polls using inline keyboard buttons.
- Manually end active polls (only by the poll creator).
- View poll history for the current chat.
- Display poll statistics, including vote counts, percentages, and a visual chart (bar or pie).
- Data persistence using JSON (poll data is saved and reloaded on restart).
- Configuration via a separate `config.py` file.

## Setup and Usage

### Prerequisites
- Python 3.7 or higher.

### Steps
1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/telegram-voting-bot.git # Replace with the actual URL when known
    cd telegram-voting-bot
    ```

2.  **Create and activate a virtual environment (recommended):**
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scriptsctivate`
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r telegram_voting_bot/requirements.txt
    ```

4.  **Configuration:**
    The bot requires a Telegram Bot Token to run.
    -   Navigate to the `telegram_voting_bot` directory.
    -   Create a `config.py` file by copying the example (which will be created in the next step):
        ```bash
        cp config.py.example config.py
        ```
    -   Open `telegram_voting_bot/config.py` and set your `TELEGRAM_BOT_TOKEN`.
        ```python
        # telegram_voting_bot/config.py
        TELEGRAM_BOT_TOKEN = "YOUR_ACTUAL_TELEGRAM_BOT_TOKEN"
        DEFAULT_POLL_DURATION_MINUTES = 5 # You can change the default poll duration here
        ```

5.  **Run the bot:**
    Ensure you are in the root directory of the project (where the `telegram_voting_bot` directory is located).
    ```bash
    python -m telegram_voting_bot.bot
    ```
    Or, if you are inside the `telegram_voting_bot` directory:
    ```bash
    python bot.py
    ```

## Available Commands

*   **`/start`**
    *   Sends a welcome message.

*   **`/startpoll [duration_minutes] "Topic" "Option 1" "Option 2" ...`**
    *   Creates a new poll.
    *   `[duration_minutes]`: (Optional) The duration of the poll in minutes. If not provided, the poll uses the `DEFAULT_POLL_DURATION_MINUTES` from `config.py`. If `DEFAULT_POLL_DURATION_MINUTES` is 0 or not set, and no duration is provided in the command, the poll runs indefinitely.
    *   `"Topic"`: The topic/question for the poll, enclosed in double quotes.
    *   `"Option 1" "Option 2" ...`: The poll options, each enclosed in double quotes. At least two options are required.
    *   Example: `/startpoll 30 "Favorite Color?" "Red" "Blue" "Green"`
    *   Example without duration: `/startpoll "Best Movie?" "Movie A" "Movie B"`

*   **Voting (Implicit)**
    *   Users vote by clicking the inline keyboard buttons attached to the poll message.

*   **`/endpoll <poll_id>`**
    *   Manually ends an active poll.
    *   Only the user who created the poll can use this command for their poll.
    *   `<poll_id>`: The unique ID of the poll to end (provided when the poll is created).

*   **`/pollhistory`**
    *   Displays a history of all polls created in the current chat, showing their topic, ID, status, and other details.

*   **`/pollstats <poll_id> [chart_type]`**
    *   Shows detailed statistics for a specific poll.
    *   `<poll_id>`: The ID of the poll.
    *   `[chart_type]`: (Optional) The type of chart to display. Can be `bar` (default) or `pie`.
    *   Example: `/pollstats abc123xyz pie`

## Future TODOs/Improvements

-   [ ] **Persistent Database:** Replace JSON storage with a more robust database solution (e.g., SQLite, PostgreSQL) for better scalability and data management.
-   [ ] **Enhanced Security/Permissions:** Implement finer-grained control over who can create polls or use administrative commands.
-   [ ] **Internationalization (i18n):** Add support for multiple languages in bot responses.
-   [ ] **Dockerization:** Provide a Dockerfile for easier and consistent deployment.
-   [ ] **Unit & Integration Tests:** Develop a comprehensive test suite to ensure code quality and reliability.
-   [ ] **Advanced Poll Options:**
    -   Anonymous polls (votes are not publicly attributed).
    -   Multiple choice votes (users can select more than one option).
    -   Scheduled polls (set a poll to start at a future time).
-   [ ] **Edit Polls:** Allow poll creators to edit the topic or options of a poll after creation, possibly restricted to before any votes are cast.
-   [ ] **User Mentions in Polls:** Option to notify users if they are mentioned in poll options or topics.
-   [ ] **"Close Poll" Button:** Add a button to poll messages for creators to quickly close their polls, as an alternative to `/endpoll <id>`.
-   [ ] **List Active Polls:** A command to quickly see all currently active polls in a chat.