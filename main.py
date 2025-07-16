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
        "💪🏼 Hi! I can fetch your last workout from Hevy and generate a new plan with a 5% volume increase.\n"
        "Use the /plan command to get started."
    )
    await update.message.reply_text(msg)

async def plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /plan handler: optionally filter last workout by title, build a +5 % plan,
    and show per-exercise + overall volumes (both requested and actually produced).

    Usage examples
    --------------
    /plan                 → latest workout of any title
    /plan Pull Day        → latest workout with title "Pull Day"
    """
    if not HEVY_API_KEY:
        await update.message.reply_text("❌ Server error: HEVY_API_KEY not set.")
        return

    workout_title = " ".join(context.args).strip() or None   # "" → None

    try:
        last_workout = tools.fetch_last_workout(
            HEVY_API_KEY,
            workout_title=workout_title
        )
        if not last_workout:
            await update.message.reply_text(
                "No workout found "
                f'{"with that title " if workout_title else ""}in your history.'
            )
            return

        exercises = tools.structure_workout_data(last_workout)
        if not exercises:
            await update.message.reply_text("No exercises found in that workout.")
            return

        # Running totals for the final summary (exact, not theoretical)
        total_prev_vol     = 0
        total_target_vol   = 0
        total_exact_new_vol = 0

        for ex in exercises:
            name       = ex['exercise']
            sets       = ex['sets']
            prev_vol   = ex['volume']

            # Build +5 % plan
            opts = tools.get_optimized_options(
                {'exercise': name, 'sets': sets},
                0.05                     # Ask for +5 % target
            )
            target_vol = opts.get('target_volume', 0)

            # ── NEW: calculate the *actual* volume from the generated sets ──
            exact_new_vol = sum(r * w for r, w in opts.get('final_sets', []))

            # Protect against divide-by-zero in rare edge cases
            pct_change_target = ((target_vol / prev_vol - 1) * 100) if prev_vol else 0
            pct_change_exact  = ((exact_new_vol / prev_vol - 1) * 100) if prev_vol else 0

            # Update totals
            total_prev_vol     += prev_vol
            total_target_vol   += target_vol
            total_exact_new_vol += exact_new_vol

            # Build message
            lines = [
                f"🏋️‍♂️ *{name}*",
                f"Prev Vol:     {int(prev_vol)}",
                f"Target Vol:   {int(target_vol)}  ({pct_change_target:+.0f} %)",
                f"Exact  Vol:   {int(exact_new_vol)}  ({pct_change_exact:+.0f} %)",
                "Plan:"
            ]
            for i, (reps, weight) in enumerate(opts.get('final_sets', []), 1):
                lines.append(f"  • Set {i}: {reps} × {weight}")

            await update.message.reply_text(
                "\n".join(lines),
                parse_mode="Markdown"
            )

        # ── Summary after all exercises ──────────────────────────────────────
        if total_prev_vol:
            pct_change_target_total = ((total_target_vol / total_prev_vol - 1) * 100)
            pct_change_exact_total  = ((total_exact_new_vol / total_prev_vol - 1) * 100)
        else:
            pct_change_target_total = pct_change_exact_total = 0

        summary = [
            "🧮 *Plan Summary*",
            f"Prev Total Vol:      {int(total_prev_vol)}",
            f"Target Total Vol:    {int(total_target_vol)}  ({pct_change_target_total:+.0f} %)",
            f"Exact  Total Vol:    {int(total_exact_new_vol)}  ({pct_change_exact_total:+.0f} %)"
        ]
        await update.message.reply_text("\n".join(summary), parse_mode="Markdown")

    except Exception as e:
        logger.error("Error generating plan:", exc_info=e)
        await update.message.reply_text(
            "⚠️ Failed to generate plan. Please try again later."
        )




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
