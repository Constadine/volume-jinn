import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import tools

# Load environment variables from a .env file if present
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables for Telegram and Hevy API
TOKEN = os.getenv('TELEGRAM_TOKEN')
HEVY_API_KEY = os.getenv('HEVY_API_KEY')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /start handler: introduces the bot.
    """
    msg = (
        "👋 Hi! I can fetch your last workout from Hevy and generate a new plan with a 5% volume increase.\n"
        "Use the /plan command to get started."
    )
    await update.message.reply_text(msg)

async def plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /plan handler: fetch last workout, compute plans, and reply.
    """
    if not HEVY_API_KEY:
        await update.message.reply_text("❌ Server error: HEVY_API_KEY not set."
        )
        return

    try:
        # Fetch and structure workout data
        last_workout = tools.fetch_last_workout(HEVY_API_KEY)
        exercises = tools.structure_workout_data(last_workout)

        if not exercises:
            await update.message.reply_text("No exercises found in your last workout.")
            return

        # For each exercise, compute optimized plan
        for ex in exercises:
            name = ex['exercise']
            sets = ex['sets']
            prev_vol = ex['volume']
            opts = tools.get_optimized_options({'exercise': name, 'sets': sets}, 0.05)
            new_vol = opts.get('target_volume', 0)
            pct_change = ((new_vol / prev_vol - 1) * 100) if prev_vol else 0

            # Build and send the message
            lines = [
                f"Exercise: {name}",
                f"Previous Volume: {int(prev_vol)}",
                f"New Volume: {int(new_vol)} ({pct_change:+.0f}%)",
                "Plan for today:"
            ]
            for idx, (reps, weight) in enumerate(opts.get('final_sets', []), start=1):
                lines.append(f"Set {idx}: {reps}x{weight}")

            await update.message.reply_text("\n".join(lines))
    except Exception as e:
        logger.error("Error generating plan:", exc_info=e)
        await update.message.reply_text("⚠️ Failed to generate plan. Please try again later.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Log exceptions and notify the user.
    """
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text("⚠️ An unexpected error occurred. Please try again later.")


def main() -> None:
    """
    Start the Telegram bot.
    """
    if not TOKEN:
        logger.error("TELEGRAM_TOKEN environment variable not set.")
        return

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("plan", plan))
    app.add_error_handler(error_handler)

    logger.info("Bot started. Listening for commands...")
    app.run_polling()

if __name__ == '__main__':
    main()
