import io
import logging
import matplotlib.pyplot as plt

logger = logging.getLogger(__name__)

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
