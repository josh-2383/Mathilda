# -*- coding: utf-8 -*- # Added for potential unicode characters in OCR
import discord
from discord.ext import commands
import sqlite3
import openai
import os
import random
import sympy as sp
from flask import Flask
import threading
from discord import Embed, Color
import asyncio
from datetime import datetime
import time
import logging
import math # Added for float comparison tolerance

# --- OCR Imports ---
import pytesseract
from PIL import Image # Pillow library
import io           # To handle image bytes
import requests     # To download image if needed
import functools    # For running blocking code in executor

# --- Voice Imports ---
import speech_recognition as sr # Speech recognition library
import wave             # For handling WAV audio format (built-in)
# Ensure PyNaCl is installed: pip install PyNaCl
# --------------------

# ======================
# LOGGING SETUP
# ======================
log_level = getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper(), logging.INFO)
logging.basicConfig(level=log_level, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logging.getLogger('discord.http').setLevel(logging.WARNING)
logging.getLogger('PIL').setLevel(logging.WARNING)
logging.getLogger('werkzeug').setLevel(logging.WARNING)
logging.getLogger('speech_recognition').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ======================
# ENVIRONMENT VARIABLES & REQUIREMENTS
# ======================
# discord.py>=2.0.0
# openai>=1.0.0
# sympy
# Flask
# python-dotenv
# Pillow
# pytesseract
# requests
# PyNaCl          # <--- ADD for Voice
# SpeechRecognition # <--- ADD for Voice
# waitress / gunicorn (Recommended for Flask production)

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not DISCORD_TOKEN:
    logger.critical("❌ FATAL ERROR: Missing DISCORD_TOKEN environment variable")
    exit(1)
if not OPENAI_API_KEY:
    logger.warning("⚠️ WARNING: Missing OPENAI_API_KEY environment variable. !solve and !ocr true commands will not work.")
else:
    # Initialize OpenAI client if key exists
    try:
        openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
        logger.info("OpenAI client initialized.")
    except Exception as e:
        logger.error(f"❌ Failed to initialize OpenAI client: {e}", exc_info=True)
        openai_client = None # Ensure it's None if init fails
        OPENAI_API_KEY = None # Treat as if key is missing

# ======================
# DATABASE SETUP / INIT
# ======================
DB_NAME = 'mathilda.db'

def init_database():
    """Initialize database with all required tables and columns"""
    conn = None # Define conn outside try block
    try:
        logger.info(f"Connecting to database: {DB_NAME}")
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        logger.info("Attempting to initialize database tables...")

        # Use TEXT primary key for user_id for better Discord ID compatibility
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS leaderboard (
            user_id TEXT PRIMARY KEY,
            points INTEGER DEFAULT 0,
            highest_streak INTEGER DEFAULT 0,
            total_correct INTEGER DEFAULT 0,
            last_active TEXT
        )""")
        logger.debug("Checked/Created leaderboard table.")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS question_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            question TEXT,
            answer TEXT,
            was_correct BOOLEAN,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        logger.debug("Checked/Created question_history table.")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wrong TEXT UNIQUE, -- Ensure 'wrong' term is unique (case-insensitive handled by code)
            correct TEXT,
            added_by TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_corrections_wrong_lower ON corrections (LOWER(wrong))")
        logger.debug("Checked/Created corrections table and index.")

        # --- Schema Migration: Add missing columns robustly ---
        logger.debug("Checking for missing columns in leaderboard...")
        table_info = cursor.execute("PRAGMA table_info(leaderboard)").fetchall()
        columns = [col[1].lower() for col in table_info]

        if 'highest_streak' not in columns:
            cursor.execute("ALTER TABLE leaderboard ADD COLUMN highest_streak INTEGER DEFAULT 0")
            logger.info("Added missing column 'highest_streak' to leaderboard.")
        if 'total_correct' not in columns:
            cursor.execute("ALTER TABLE leaderboard ADD COLUMN total_correct INTEGER DEFAULT 0")
            logger.info("Added missing column 'total_correct' to leaderboard.")
        if 'last_active' not in columns:
            cursor.execute("ALTER TABLE leaderboard ADD COLUMN last_active TEXT")
            logger.info("Added missing column 'last_active' to leaderboard.")

        conn.commit()
        logger.info("✅ Database initialized successfully")
        conn.close()
        return True
    except sqlite3.Error as e:
        logger.error(f"❌ Database initialization/migration failed: {e}", exc_info=True)
        if conn:
            conn.rollback()
            conn.close()
        raise

# --- Initialize DB on startup ---
try:
    init_database()
except Exception as db_init_err:
    logger.critical(f"❌ Halting execution due to database initialization failure: {db_init_err}")
    exit(1)
# ---------------------------------

# ======================
# FLASK WEB SERVER (Required for Render Web Service Port Binding)
# ======================
app = Flask(__name__)

@app.route('/')
def home():
    return f"Mathilda Discord Bot is running! ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})"

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    host = "0.0.0.0"
    try:
        # Using Waitress for production - add 'waitress' to requirements.txt
        from waitress import serve
        logger.info(f"Starting Waitress server on {host}:{port}")
        serve(app, host=host, port=port, threads=6) # Use Waitress

        # Fallback to Flask Dev Server (Not for production!)
        # logger.info(f"Starting Flask development server on {host}:{port}")
        # app.run(host=host, port=port, debug=False, use_reloader=False)

    except ImportError:
         logger.warning("Waitress not found. Falling back to Flask development server (NOT recommended for production).")
         logger.warning("Install Waitress: pip install waitress")
         logger.info(f"Starting Flask development server on {host}:{port}")
         app.run(host=host, port=port, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"❌ Flask server failed to start or crashed: {e}", exc_info=True)

flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.name = "FlaskServerThread"
flask_thread.start()
logger.info("Flask server thread started to handle web service requests.")
# --------------------------------------------------------------------------

# ======================
# DISCORD BOT SETUP
# ======================
intents = discord.Intents.default()
intents.message_content = True # REQUIRED for reading message content
intents.members = True # REQUIRED for reliable member lookups - Enable in Developer Portal!
intents.voice_states = True # REQUIRED FOR VOICE STATE CHANGES

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=commands.DefaultHelpCommand(no_category='Commands'),
    activity=discord.Game(name="!help | Math Time!"),
    case_insensitive=True
)

# Bot state management (in-memory)
bot.math_answers = {} # Stores current math quest {user_id: {"question": str, "answer": str, "streak": int, "message_id": int}}
bot.question_streaks = {} # Stores current streak {user_id: int} - might sync with DB value on first quest
bot.conversation_states = {} # Stores dicts: {user_id: {"mode": "math_help"}} # Example
bot.voice_clients = {} # Store active voice clients {guild_id: discord.VoiceClient}
bot.listening_info = {} # Store info needed during listening {guild_id: {"text_channel": discord.TextChannel, "sink": ...}}

# Math help triggers (lowercase set for faster lookups)
bot.math_help_triggers = {
    "help with math", "math question", "solve this", "how to calculate",
    "math help", "solve for", "how do i solve", "calculate", "math problem"
}

# ======================
# MATH QUESTION DATABASE (Consider moving to DB or JSON)
# ======================
math_questions = {
    # Basic Arithmetic
    "What is 2 + 2?": "4",
    "What is 15 - 7?": "8",
    "What is 6 × 9?": "54",
    "What is 144 ÷ 12?": "12",
    "What is 3^4?": "81",
    "What is √144?": "12 or sqrt(144)",
    "What is 5! (factorial)?": "120",
    "What is 15% of 200?": "30 or 30.0",
    "What is 0.25 as a fraction?": "1/4",
    "What is 3/4 + 1/2?": "5/4 or 1.25 or 1 1/4",
    "What is 2^10?": "1024",
    "What is the next prime number after 7?": "11",
    "What is 1.5 × 2.5?": "3.75",
    "What is 1000 ÷ 8?": "125",
    "What is 17 × 3?": "51",

    # Algebra
    "Solve for x: 3x + 5 = 20": "5 or x=5",
    "Factor x² - 9": "(x+3)(x-3) or (x-3)(x+3)", # Sympy handles order
    "Simplify 2(x + 3) + 4x": "6*x + 6", # Use * explicitly
    "Solve for y: 2y - 7 = 15": "11 or y=11",
    "Expand (x + 2)(x - 3)": "x**2 - x - 6", # Use ** for sympy
    "What is the slope of the line y = 2x + 5?": "2",
    "Solve the system: x + y = 5, x - y = 1": "x=3, y=2 or (3, 2) or y=2, x=3",
    "Simplify (x³ * x⁵) / x²": "x**6",
    "Solve the quadratic: x² - 5x + 6 = 0": "x=2, x=3 or x=3, x=2 or 2, 3 or 3, 2",
    "What is the vertex of the parabola y = x² - 4x + 3?": "(2, -1)",

    # Geometry (using approx values, consider accepting ranges or pi symbol)
    "Area of a circle with radius 5 (use pi ≈ 3.14159)": "78.54", # Tolerant float compare needed
    "Circumference of a circle with diameter 10 (use pi ≈ 3.14159)": "31.42", # Tolerant float compare needed
    "Volume of a cube with side length 3": "27",
    "Length of the hypotenuse for a right triangle with legs 3 and 4": "5", # Rephrased pythagorean
    "Sum of interior angles of a hexagon (in degrees)": "720",
    "Area of a triangle with base 6 and height 4": "12",
    "Surface area of a sphere with radius 2 (use pi ≈ 3.14159)": "50.27", # Tolerant float compare needed
    "Volume of a cylinder with radius 3 and height 5 (use pi ≈ 3.14159)": "141.37", # Tolerant float compare needed
    "Length of the diagonal of a 5 by 12 rectangle": "13",
    "Measure of one exterior angle of a regular octagon (in degrees)": "45",

    # Calculus
    "Derivative of x³ with respect to x": "3*x**2",
    "Integral of 2x dx": "x**2", # Ignoring + C for simplicity
    "Derivative of sin(x) with respect to x": "cos(x)",
    "Limit as x approaches 0 of (sin x)/x": "1",
    "Integral of e^x dx": "exp(x) or e**x", # Ignoring + C

    # Word Problems
    "If 5 apples cost $2.50, what is the price per apple in dollars?": "0.50 or 0.5",
    "A train travels 300 km in 2 hours. What is its average speed in km/h?": "150", # Ignoring units for now
    "A rectangle has an area of 24 square units and a length of 6 units. What is its width?": "4",
    "What is the final price of a $50 item after a 20% discount?": "40 or $40",
    "If 3 pencils cost $1.20, how much do 5 pencils cost in dollars?": "2.00 or 2 or $2.00 or $2",

    # Fun/Easter Eggs
    "What is the answer to life, the universe, and everything?": "42",
    "Secret question - type skibidi sigma rizzler": "skibidi sigma rizzler"
}

# ======================
# HELPER FUNCTIONS
# ======================
def create_embed(title=None, description=None, color=Color.blue(),
                 fields=None, footer=None, thumbnail=None, image=None):
    """Creates a Discord Embed object with common options."""
    # Truncate title and description if too long first
    if title and len(title) > 256: title = title[:253] + "..."
    if description and len(description) > 4096: description = description[:4093] + "..."

    embed = Embed(title=title, description=description, color=color)
    if fields:
        for name, value, inline in fields:
            field_name = str(name) if name else "​" # Use zero-width space for empty name
            field_value = str(value) if value is not None else "N/A"
            if not field_value: field_value = "N/A" # Prevent empty field errors
            # Truncate long field values
            if len(field_name) > 256: field_name = field_name[:253] + "..."
            if len(field_value) > 1024: field_value = field_value[:1021] + "..."
            embed.add_field(name=field_name, value=field_value, inline=inline)
    if footer:
        footer_text = str(footer)
        if len(footer_text) > 2048: footer_text = footer_text[:2045] + "..."
        embed.set_footer(text=footer_text)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if image:
        embed.set_image(url=image)

    return embed

# --- Database Interaction Functions (using local connections) ---

def db_execute(sql, params=(), fetch_one=False, fetch_all=False, commit=False):
    """Executes a SQL query with local connection management."""
    conn = None
    cursor = None
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row # Return rows as dictionary-like objects
        cursor = conn.cursor()
        cursor.execute(sql, params)

        result = None
        if fetch_one:
            result = cursor.fetchone()
        elif fetch_all:
            result = cursor.fetchall()

        if commit:
            conn.commit()

        return result
    except sqlite3.Error as e:
        logger.error(f"Database error: {e.__class__.__name__} occurred while executing SQL.")
        logger.error(f"SQL: {sql}")
        logger.error(f"Params: {params}")
        logger.exception("Database error traceback:")
        if conn and commit:
            try:
                conn.rollback()
                logger.info("Transaction rolled back due to error.")
            except sqlite3.Error as rb_err:
                logger.error(f"Error during rollback: {rb_err}")
        raise # Re-raise by default
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def update_leaderboard(user_id: str, points_change: int = 0, correct_answer: bool = False, current_streak: int = 0):
    """Update leaderboard stats for a user. Handles INSERT or UPDATE."""
    now = datetime.now().isoformat(sep=' ', timespec='seconds')
    user_id_str = str(user_id)

    try:
        # Fetch current state first to calculate accurately
        current_data = db_execute("SELECT points, highest_streak, total_correct FROM leaderboard WHERE user_id = ?", (user_id_str,), fetch_one=True)

        current_points = current_data['points'] if current_data else 0
        current_highest_streak = current_data['highest_streak'] if current_data else 0
        current_total_correct = current_data['total_correct'] if current_data else 0

        new_total_correct = current_total_correct + (1 if correct_answer else 0)
        # Current_streak passed is the *new* streak after the answer
        new_highest_streak = max(current_highest_streak, current_streak)
        new_points = max(0, current_points + points_change) # Ensure points don't go below 0

        sql = """
            INSERT INTO leaderboard (user_id, points, highest_streak, total_correct, last_active)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                points = excluded.points,
                highest_streak = MAX(leaderboard.highest_streak, excluded.highest_streak), -- Take max on update too
                total_correct = excluded.total_correct,
                last_active = excluded.last_active
            """
        # Note: ON CONFLICT behavior for highest_streak is slightly different here,
        # using MAX() ensures we don't accidentally lower it if the insert value was lower.
        # However, calculating it before the query as done above is more robust.
        # We'll pass the pre-calculated `new_highest_streak` which incorporates the logic.
        params = (user_id_str, new_points, new_highest_streak, new_total_correct, now)

        db_execute(sql, params, commit=True)
        logger.debug(f"Leaderboard updated for {user_id_str}: pts_change={points_change}, correct={correct_answer}, new_streak={current_streak}, new_pts={new_points}, new_high_streak={new_highest_streak}")
    except Exception as e:
        # Error already logged by db_execute
        logger.error(f"Failed to update leaderboard for {user_id_str} due to DB error.")


def log_question(user_id: str, question: str, user_answer: str, correct: bool):
    """Record a question attempt in the history table."""
    user_id_str = str(user_id)
    sql = """INSERT INTO question_history (user_id, question, answer, was_correct) VALUES (?, ?, ?, ?)"""
    params = (user_id_str, question, user_answer, int(correct))
    try:
        db_execute(sql, params, commit=True)
        logger.debug(f"Question logged for {user_id_str}: correct={correct}")
    except Exception as e:
        logger.error(f"Failed to log question for {user_id_str} due to DB error.")

# -------------------------------------------------------------

def is_answer_correct(user_answer: str, correct_answer_str: str, tolerance=1e-6) -> bool:
    """
    Checks if the user's answer matches the correct answer(s) with more flexibility.
    Handles case, whitespace, multiple options (' or '), floats, and basic sympy equivalence.
    """
    if not user_answer: return False # Empty answer is never correct

    user_ans_norm = user_answer.lower().strip().replace(',', '') # Normalize user input more aggressively
    correct_ans_norm = correct_answer_str.lower().strip()

    # 1. Check for multiple correct answers separated by ' or '
    possible_answers = {ans.strip() for ans in correct_ans_norm.split(' or ')} # Use set for efficiency
    if user_ans_norm in possible_answers:
        logger.debug(f"Correct: Exact match found for '{user_ans_norm}' in {possible_answers}")
        return True

    # 2. Try numerical comparison
    user_num = None
    try:
        user_num = float(user_ans_norm)
        # Check against all possible answers if they are numeric
        for possible in possible_answers:
            try:
                correct_num_str = possible.replace(',', '')
                correct_num = float(correct_num_str)
                if math.isclose(user_num, correct_num, rel_tol=tolerance, abs_tol=tolerance):
                    logger.debug(f"Correct: Numerical match found: {user_num} ≈ {correct_num}")
                    return True
            except ValueError:
                continue # This possible answer wasn't a number
    except ValueError:
        pass # User answer wasn't a number, proceed to other checks

    # 3. Try Sympy comparison for algebraic equivalence (if answers seem algebraic)
    try:
        # Check if user answer looks algebraic
        user_looks_algebraic = any(c.isalpha() for c in user_ans_norm if c not in ['e']) or any(c in user_ans_norm for c in '()^*/+-=')

        # Collect algebraic-looking possible answers
        algebraic_possible_answers = set()
        for possible in possible_answers:
             if any(c.isalpha() for c in possible if c not in ['e']) or any(c in possible for c in '()^*/+-='):
                  algebraic_possible_answers.add(possible)

        if user_looks_algebraic and algebraic_possible_answers:
            logger.debug(f"Attempting Sympy check for '{user_ans_norm}' against {algebraic_possible_answers}")
            # Prepare user expression for sympy
            user_expr_sympy_str = user_ans_norm.replace('^', '**')

            for possible in algebraic_possible_answers:
                try:
                    possible_expr_sympy_str = possible.replace('^', '**')

                    # Use evaluate=False initially? Maybe not needed with parse_expr
                    # Handle simple equations like x=5 vs 5
                    is_user_eq = '=' in user_expr_sympy_str
                    is_possible_eq = '=' in possible_expr_sympy_str

                    sym_user = None
                    sym_correct = None

                    try:
                        # Parse using robust transformations
                        sym_user = sp.parse_expr(user_expr_sympy_str, transformations='all', evaluate=True) # Evaluate basic things like 1+1
                        sym_correct = sp.parse_expr(possible_expr_sympy_str, transformations='all', evaluate=True)
                    except (sp.SympifyError, SyntaxError, TypeError) as parse_err:
                        logger.debug(f"Sympy parse failed for pair ('{user_expr_sympy_str}', '{possible_expr_sympy_str}'): {parse_err}")
                        continue # Try next possible answer

                    # Check for equivalence using simplify(expand(diff)) == 0
                    try:
                        # Expand first to handle factored forms vs expanded forms
                        diff = sp.simplify(sp.expand(sym_user - sym_correct))

                        # Check if difference is symbolically zero or numerically close to zero
                        if diff == 0:
                           logger.debug(f"Correct: Sympy symbolic match: {sym_user} == {sym_correct}")
                           return True
                        elif diff.is_number and math.isclose(float(diff), 0, abs_tol=tolerance):
                           logger.debug(f"Correct: Sympy numerical match: {sym_user} ≈ {sym_correct} (diff={diff})")
                           return True

                    except (AttributeError, TypeError, NotImplementedError) as simplify_err:
                        # Handle cases where simplify/expand fails
                         logger.debug(f"Sympy simplify/compare failed for pair ({sym_user}, {sym_correct}): {simplify_err}")
                         # Fallback: Check direct equality of parsed forms (less robust)
                         if sym_user == sym_correct:
                            logger.debug(f"Correct: Sympy direct parsed equality: {sym_user} == {sym_correct}")
                            return True


                except Exception as inner_sym_err: # Catch any unexpected error during pair comparison
                    logger.warning(f"Unexpected error during Sympy comparison for pair ('{user_expr_sympy_str}', '{possible_expr_sympy_str}'): {inner_sym_err}", exc_info=False)
                    continue # Try next possible answer

    except Exception as e: # Catch any unexpected error in the outer sympy block
        logger.warning(f"Sympy comparison block encountered an unexpected error: {e}", exc_info=True)
        pass # Fallback to no match if sympy fails badly

    # 4. Final check - if we got here, none of the flexible methods matched.
    logger.debug(f"Incorrect: No match found for '{user_ans_norm}' against {possible_answers}")
    return False


# ======================
# CORE BOT EVENTS & COMMANDS
# ======================
@bot.event
async def on_ready():
    """Bot startup handler"""
    logger.info(f"🚀 {bot.user.name} (ID: {bot.user.id}) is online!")
    logger.info(f"Using discord.py version {discord.__version__}")
    logger.info(f"Command prefix: '{bot.command_prefix}'")
    logger.info(f"Case Insensitive: {bot.case_insensitive}")
    logger.info(f"Connected to {len(bot.guilds)} guilds.")
    logger.info(f"OpenAI available: {'Yes' if openai_client else 'No'}")
    await bot.change_presence(activity=discord.Game(name="!help | Math Time!"))

@bot.event
async def on_command_error(ctx: commands.Context, error):
    """Generic command error handler"""
    if isinstance(error, commands.CommandNotFound):
        # Optionally ignore or send a message
        # await ctx.send("❓ Unknown command. Type `!help` for a list of commands.")
        logger.debug(f"CommandNotFound ignored: {ctx.message.content}")
        return
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(embed=create_embed(
            title="⏳ Cooldown",
            description=f"Please wait {error.retry_after:.1f} seconds before using `{ctx.command.name}` again.",
            color=Color.orange()
        ), delete_after=8) # Delete message after a bit
        await ctx.message.add_reaction("⏳")
    elif isinstance(error, commands.MissingRequiredArgument):
         await ctx.send(embed=create_embed(
            title="🤔 Missing Argument",
            description=f"You missed the `{error.param.name}` argument.\nUsage: `{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}`",
            color=Color.yellow()
        ))
    elif isinstance(error, commands.BadArgument):
         await ctx.send(embed=create_embed(
            title="🤔 Invalid Argument",
            description=f"Could not understand one of the arguments provided.\nUsage: `{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}`",
            color=Color.yellow()
        ))
    elif isinstance(error, commands.UserInputError):
        await ctx.send(embed=create_embed(
            title="🤔 Input Error",
            description=f"There was a problem with your input: {error}\nUsage: `{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}`",
            color=Color.yellow()
        ))
    elif isinstance(error, commands.CheckFailure):
        await ctx.send(embed=create_embed(
            title="🚫 Permission Denied",
            description="You do not have the necessary permissions to use this command.",
            color=Color.red()
        ))
    else:
        # For other errors, log them and notify the user
        logger.error(f"Unhandled error in command '{ctx.command}': {error}", exc_info=True)
        await ctx.send(embed=create_embed(
            title="❌ Unexpected Error",
            description="An unexpected error occurred while running this command. The developers have been notified.",
            color=Color.dark_red()
        ))

@bot.command(name="ping", help="Checks the bot's latency.")
@commands.cooldown(1, 5, commands.BucketType.user)
async def ping(ctx: commands.Context):
    """Checks bot latency"""
    latency = bot.latency * 1000 # Latency in milliseconds
    embed = create_embed(
        title="🏓 Pong!",
        description=f"Gateway Latency: `{latency:.2f} ms`",
        color=Color.blue()
    )
    await ctx.send(embed=embed)


@bot.command(name="mathquest", help="Starts a math question streak challenge.")
@commands.cooldown(1, 10, commands.BucketType.user)
async def mathquest(ctx: commands.Context):
    """Start a math question streak challenge with cooldown."""
    user_id = str(ctx.author.id)

    # Prevent starting if already in a quest or conversation
    if user_id in bot.math_answers:
        await ctx.send(embed=create_embed(
            title="⚠️ Already in Quest",
            description="You already have an active math question! Please answer it first.",
            color=Color.orange()
        ))
        ctx.command.reset_cooldown(ctx)
        return
    if user_id in bot.conversation_states:
        await ctx.send(embed=create_embed(
            title="⚠️ Action Paused",
            description="Please finish your current math help session (type `cancel`) before starting a new quest.",
            color=Color.orange()
        ))
        ctx.command.reset_cooldown(ctx)
        return

    try:
        question, correct_answer = random.choice(list(math_questions.items()))

        # Fetch current streak from DB or use in-memory cache
        current_streak = bot.question_streaks.get(user_id, 0)
        # Optional: Sync with DB on first quest of session
        # if user_id not in bot.question_streaks:
        #     db_data = db_execute("SELECT points, highest_streak FROM leaderboard WHERE user_id = ?", (user_id,), fetch_one=True)
        #     if db_data: # Consider resetting streak based on last_active time? For now, just use 0 if not in memory.
        #          pass # current_streak is already 0 if not found

        logger.info(f"Math quest started for {user_id} ({ctx.author.display_name}). Q: {question[:50]}... A: {correct_answer}")

        # Create embed response *before* storing state to get message ID
        embed = create_embed(
            title=f"🧮 Math Challenge (Streak: {current_streak})",
            description=f"**Question:**\n>>> {question}", # Use blockquote
            color=Color.green(),
            footer="Type your answer in chat!",
            thumbnail=ctx.author.display_avatar.url
        )
        sent_message = await ctx.send(embed=embed)

        # Store current challenge info including message ID
        bot.math_answers[user_id] = {
            "answer": correct_answer,
            "question": question,
            "streak": current_streak, # Store streak at the time question was asked
            "message_id": sent_message.id, # Store the ID of the question message
            "channel_id": ctx.channel.id
        }

    except Exception as e:
        logger.error(f"Error in mathquest command: {e}", exc_info=True)
        error_embed = create_embed(
            title="❌ Error",
            description=f"An unexpected error occurred while starting the challenge: {e}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)


@bot.command(name="solve", help="Solves a math problem using AI (if configured).\nUsage: !solve <problem>")
@commands.cooldown(1, 10, commands.BucketType.user) # Increased cooldown slightly
async def solve(ctx: commands.Context, *, problem: str):
    """Solve any math problem with step-by-step explanation using OpenAI."""
    if not openai_client: # Check the initialized client
        await ctx.send(embed=create_embed(
            title="❌ AI Feature Disabled",
            description="The OpenAI API key is not configured or the client failed to initialize. This command is unavailable.",
            color=Color.orange()
        ))
        return

    if len(problem) > 1500:
        await ctx.send(embed=create_embed(
            title="❌ Input Too Long",
            description="Your problem description is too long. Please keep it under 1500 characters.",
            color=Color.red()
        ))
        return

    thinking_msg = None
    try:
        thinking_embed = create_embed(
            title="🧠 Thinking...",
            description=f"Solving `{problem[:100]}{'...' if len(problem)>100 else ''}`...",
            color=Color.light_grey()
        )
        thinking_msg = await ctx.send(embed=thinking_embed)

        # Run blocking network call in executor thread
        response = await asyncio.to_thread(
            openai_client.chat.completions.create, # Use the initialized client
            model="gpt-3.5-turbo", # Or "gpt-4o" / "gpt-4-turbo" if available
            messages=[{
                "role": "system",
                "content": """You are Mathilda, a friendly and precise math tutor bot.
Explain solutions clearly, showing step-by-step working.
For equations, show the solving process.
For word problems, explain the setup and reasoning.
Format answers clearly using markdown (like **bold**, `code for equations`). Use LaTeX for complex formulas if possible, like $$x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}$$.
Keep explanations concise but thorough. Assume the user is asking for help understanding the process."""
            }, {
                "role": "user",
                "content": f"Solve and explain this math problem: {problem}"
            }],
            temperature=0.4, # Slightly lower temp for more deterministic math answers
            max_tokens=1500 # Increased limit slightly
        )

        answer = response.choices[0].message.content.strip()

        # --- Delete "Thinking..." message ---
        if thinking_msg:
            try:
                await thinking_msg.delete()
            except discord.HTTPException:
                logger.warning("Could not delete 'Thinking...' message (already deleted or other issue).")
                pass # Ignore if deletion failed

        # --- Send Response (Handle potential length issues) ---
        max_len = 4000 # Embed description limit is 4096, leave buffer
        base_desc = f"**Problem:**\n```\n{problem}\n```\n**Solution:**\n"
        remaining_len = max_len - (len(base_desc) + 50) # Extra buffer

        if len(answer) <= remaining_len:
            # Send single embed if short enough
            embed = create_embed(
                title="💡 Math Solution",
                description=base_desc + answer,
                color=Color.green(),
                footer=f"Solved for {ctx.author.display_name}"
            )
            await ctx.send(embed=embed)
        else:
            # Split long messages more robustly
            parts = []
            current_part_content = ""
            first_part = True

            # Split by paragraphs first, then lines if a paragraph is too long
            segments = []
            for paragraph in answer.split('\n\n'):
                max_para_len = 4000 # Limit for paragraph splitting
                if len(paragraph) > max_para_len:
                    current_line_chunk = ""
                    for line in paragraph.split('\n'):
                        if len(current_line_chunk) + len(line) + 1 < max_para_len:
                            current_line_chunk += line + "\n"
                        else:
                            segments.append(current_line_chunk.strip())
                            current_line_chunk = line + "\n"
                    if current_line_chunk: segments.append(current_line_chunk.strip())
                else:
                    segments.append(paragraph)

            # Assemble parts from segments
            for segment in segments:
                segment_with_sep = segment + "\n\n"
                # Determine limit for this part
                part_limit = remaining_len if first_part else (4096 - 100) # Leave headroom in subsequent parts

                if len(current_part_content) + len(segment_with_sep) <= part_limit:
                    current_part_content += segment_with_sep
                else:
                    # Finish the current part
                    if current_part_content: # Avoid adding empty parts
                         parts.append(current_part_content.strip())
                    # Start a new part with the current segment (handle segment larger than limit)
                    if len(segment_with_sep) > part_limit:
                         # If a single segment is too long even for a fresh part, truncate it
                         parts.append(segment_with_sep[:part_limit - 10] + "\n... (truncated)")
                         current_part_content = "" # Don't carry over
                    else:
                         current_part_content = segment_with_sep
                    first_part = False # Subsequent parts use full limit calculation

            # Add the last part
            if current_part_content:
                parts.append(current_part_content.strip())

            # Send the parts
            for i, part_content in enumerate(parts):
                if i == 0:
                    embed = create_embed(
                        title="💡 Math Solution (Part 1)",
                        description=base_desc + part_content,
                        color=Color.green(),
                        footer=f"Solved for {ctx.author.display_name}"
                    )
                else:
                    embed = create_embed(
                        title=f"💡 Math Solution (Part {i+1})",
                        description=part_content,
                        color=Color.green(),
                        footer=f"Solved for {ctx.author.display_name}"
                    )
                await ctx.send(embed=embed)
                await asyncio.sleep(0.3) # Small delay between parts

    except openai.APIError as e:
        logger.error(f"OpenAI API error in !solve for {ctx.author.id}: {e}", exc_info=True)
        # FIX: Corrected SyntaxError here
        if thinking_msg:
            try:
                await thinking_msg.delete()
            except discord.HTTPException:
                logger.warning("Could not delete 'Thinking...' message (already deleted or other issue).")
                pass
        await ctx.send(embed=create_embed(title="❌ OpenAI Error", description=f"Could not get solution from AI: {e}", color=Color.red()))
    except Exception as e:
        logger.error(f"Error in solve command for {ctx.author.id}: {e}", exc_info=True)
        # FIX: Corrected SyntaxError here
        if thinking_msg:
            try:
                await thinking_msg.delete()
            except discord.HTTPException:
                logger.warning("Could not delete 'Thinking...' message (already deleted or other issue).")
                pass
        error_embed = create_embed(
            title="❌ Error",
            description=f"An unexpected error occurred while solving: {e}",
            color=Color.dark_red()
        )
        await ctx.send(embed=error_embed)

@bot.command(name="leaderboard", aliases=["lb"], help="Shows the math quest leaderboard.")
@commands.cooldown(1, 15, commands.BucketType.channel) # Channel cooldown
async def leaderboard(ctx: commands.Context, limit: int = 10):
    """Displays the top users based on points."""
    if limit < 1 or limit > 25:
        limit = 10 # Default to 10 if limit is unreasonable

    try:
        results = db_execute(
            "SELECT user_id, points, highest_streak, total_correct FROM leaderboard ORDER BY points DESC LIMIT ?",
            (limit,),
            fetch_all=True
        )

        if not results:
            await ctx.send(embed=create_embed(title="🏆 Leaderboard", description="The leaderboard is empty!", color=Color.gold()))
            return

        embed = create_embed(
            title=f"🏆 Math Quest Leaderboard (Top {len(results)})",
            color=Color.gold()
        )

        board_text = ""
        rank = 1
        for row in results:
            user_id = int(row['user_id']) # Convert back to int for fetching user
            user = bot.get_user(user_id) or await bot.fetch_user(user_id) # Fetch if not cached
            username = user.display_name if user else f"User ID {user_id}"
            points = row['points']
            streak = row['highest_streak']
            correct = row['total_correct']
            # Format entry: Rank. Username - Points (Streak: X, Correct: Y)
            board_text += f"`{rank}.` **{username}** - {points} points (Streak: {streak}, Correct: {correct})\n"
            rank += 1

        embed.description = board_text
        await ctx.send(embed=embed)

    except Exception as e:
        logger.error(f"Error fetching leaderboard: {e}", exc_info=True)
        await ctx.send(embed=create_embed(title="❌ Error", description="Could not retrieve the leaderboard.", color=Color.red()))

# ======================
# ON_MESSAGE HANDLER (CRITICAL FOR ANSWERS)
# ======================
@bot.event
async def on_message(message: discord.Message):
    # Ignore messages from the bot itself
    if message.author == bot.user:
        return
    # Ignore DMs if not intended (adjust as needed)
    if message.guild is None:
        # logger.debug("Ignoring DM")
        return

    # Process commands first (important change!)
    # This allows commands to work even if user is technically in a quest state
    # We'll handle answers specifically by checking reference later
    await bot.process_commands(message)

    # --- Check if this message is a reply to a specific quest ---
    user_id = str(message.author.id)
    if user_id in bot.math_answers and message.reference:
        quest_data = bot.math_answers[user_id]
        # Check if the message this replies to is the bot's question message
        # AND if it's in the same channel
        if (message.reference.message_id == quest_data["message_id"] and
            message.channel.id == quest_data["channel_id"]):

            # It's an answer to the active quest for this user
            question = quest_data["question"]
            correct_answer_str = quest_data["answer"]
            streak_when_asked = quest_data["streak"]

            # Clean up state immediately to prevent duplicate processing
            del bot.math_answers[user_id]
            # Get the potentially updated streak from memory (if user answered previous questions quickly)
            # Or fallback to the streak when the question was asked if memory is empty.
            last_known_streak = bot.question_streaks.get(user_id, streak_when_asked)

            user_answer = message.content
            logger.info(f"Checking answer from {user_id} ({message.author.display_name}) replying to msg {quest_data['message_id']}. A: '{user_answer}'")

            try:
                # Run potentially slow check in executor if sympy is involved
                # For now, assume is_answer_correct is fast enough for most cases
                correct = is_answer_correct(user_answer, correct_answer_str)

                if correct:
                    new_streak = last_known_streak + 1
                    bot.question_streaks[user_id] = new_streak # Update in-memory streak cache
                    points_gain = 10 + new_streak # Example scoring: base 10 + 1 per streak point
                    await message.add_reaction("✅")
                    response_embed = create_embed(
                        title=f"✅ Correct! (Streak: {new_streak})",
                        description=f"+{points_gain} points!",
                        color=Color.green(),
                        footer=f"Answered by {message.author.display_name}"
                    )
                    # Use reference=message to reply directly to the answer
                    await message.channel.send(embed=response_embed, reference=message, mention_author=False)
                    update_leaderboard(user_id, points_gain, correct_answer=True, current_streak=new_streak)
                    log_question(user_id, question, user_answer, True)
                else:
                    bot.question_streaks[user_id] = 0 # Reset streak
                    points_loss = -5 # Example penalty, adjust as desired
                    await message.add_reaction("❌")
                    response_embed = create_embed(
                        title="❌ Incorrect",
                        description=f"The correct answer was: `{correct_answer_str}`\nYour streak resets to 0. {points_loss} points.",
                        color=Color.red(),
                        footer=f"Attempt by {message.author.display_name}"
                    )
                    await message.channel.send(embed=response_embed, reference=message, mention_author=False)
                    update_leaderboard(user_id, points_loss, correct_answer=False, current_streak=0)
                    log_question(user_id, question, user_answer, False)

            except Exception as e:
                 logger.error(f"Error checking answer for {user_id} ({message.author.display_name}): {e}", exc_info=True)
                 await message.add_reaction("⚠️")
                 await message.channel.send(embed=create_embed(
                     title="⚠️ Error",
                     description="Could not process your answer due to an internal error.",
                     color=Color.orange()),
                     reference=message, mention_author=False
                 )
                 # Reset streak/state as a precaution, ensure DB reflects potential failure
                 bot.question_streaks.pop(user_id, None)
                 update_leaderboard(user_id, 0, correct_answer=False, current_streak=0)
                 log_question(user_id, question, user_answer, False) # Log attempt as incorrect on error

            return # Handled as an answer, stop further processing for this message

    # --- Placeholder: Check for math help triggers / conversation ---
    content_lower = message.content.lower().strip()
    if not content_lower.startswith(bot.command_prefix): # Only check non-commands here
        if user_id in bot.conversation_states:
             # Handle conversation steps (e.g., math help, cancel)
             if bot.conversation_states[user_id]["mode"] == "math_help":
                 if content_lower == "cancel":
                     del bot.conversation_states[user_id]
                     await message.reply("Math help session cancelled.", mention_author=False)
                     logger.debug(f"Math help session cancelled for {user_id}")
                     return
                 # --- TODO: Add logic to handle the actual math help query ---
                 # Maybe call a function similar to !solve but within the conversation context
                 await message.reply(f"Okay, let me think about: `{message.content[:100]}{'...' if len(message.content)>100 else ''}`\n(Math help interaction not fully implemented yet!)", mention_author=False)
                 # del bot.conversation_states[user_id] # End conversation after one exchange? Or add steps?
                 return

        # Check if message triggers a new math help session
        elif any(trigger in content_lower for trigger in bot.math_help_triggers):
             if user_id in bot.math_answers: # Don't interrupt math quest
                 await message.reply("Please answer your current `/mathquest` question first!", mention_author=False, delete_after=10)
                 return

             bot.conversation_states[user_id] = {"mode": "math_help", "step": "waiting_for_problem"}
             await message.reply(f"Okay {message.author.mention}, I can try to help with math! What's the problem? (Type `cancel` to exit this mode)", mention_author=False)
             logger.debug(f"Started math help session for {user_id}")
             return


# ======================
# PLACEHOLDER COMMANDS (OCR, Voice, Corrections)
# ======================

@bot.command(name="ocr", help="Extracts text from an image (requires Tesseract). [WIP]")
@commands.cooldown(1, 15, commands.BucketType.user)
async def ocr(ctx: commands.Context, solve_after: bool = False):
    """Extracts text from an image attachment using OCR."""
    # Check for attachments
    if not ctx.message.attachments:
        await ctx.send(embed=create_embed(title="📎 No Image Found", description="Please attach an image to your message when using the `!ocr` command.", color=Color.yellow()))
        return

    attachment = ctx.message.attachments[0]
    # Basic check for image file types
    if not any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.bmp', '.tiff']):
         await ctx.send(embed=create_embed(title="⚠️ Invalid File Type", description="Please attach a valid image file (PNG, JPG, BMP, TIFF).", color=Color.yellow()))
         return

    thinking_msg = await ctx.send(embed=create_embed(title="🔍 Reading Image...", color=Color.light_grey()))

    try:
        image_bytes = await attachment.read()
        img = Image.open(io.BytesIO(image_bytes))

        # Run Tesseract in executor thread (blocking I/O)
        extracted_text = await asyncio.to_thread(
             functools.partial(pytesseract.image_to_string, img, timeout=20) # Add timeout
        )
        extracted_text = extracted_text.strip()

        await thinking_msg.delete() # Delete thinking message

        if not extracted_text:
            await ctx.send(embed=create_embed(title="🚫 No Text Detected", description="Could not find any text in the provided image.", color=Color.orange()))
            return

        # Send extracted text (split if necessary)
        ocr_result_desc = f"**Extracted Text:**\n```\n{extracted_text}\n```"
        if len(ocr_result_desc) > 4000: # Basic check, embed creation handles finer limits
             ocr_result_desc = ocr_result_desc[:4000] + "... (truncated)"

        await ctx.send(embed=create_embed(title="📄 OCR Result", description=ocr_result_desc, color=Color.blue()))

        # --- Optional: Pass to !solve ---
        if solve_after:
            if not openai_client:
                await ctx.send(embed=create_embed(title="⚠️ AI Disabled", description="Cannot solve the extracted text as the OpenAI feature is not available.", color=Color.orange()))
                return
            logger.info(f"Passing OCR text from {ctx.author.id} to !solve logic.")
            # Re-invoke the solve command's logic programmatically
            # Create a dummy context or directly call the solve function's core logic
            # For simplicity here, let's just use invoke (might mess up cooldowns slightly)
            solve_command = bot.get_command("solve")
            if solve_command:
                # We need to create a new context or pass the text carefully
                # await ctx.invoke(solve_command, problem=extracted_text) # Simplest but might have side effects
                # Safer: Call a helper function containing solve's core logic
                 await solve_command(ctx, problem=extracted_text) # Reuse existing context, passing problem arg
            else:
                 await ctx.send("Error: Could not find the solve command to process OCR text.")


    except pytesseract.TesseractNotFoundError:
         logger.error("Tesseract OCR engine not found or not in PATH.")
         await thinking_msg.edit(embed=create_embed(title="❌ OCR Error", description="Tesseract OCR engine not found on the server. This feature is unavailable.", color=Color.red()))
    except pytesseract.TesseractError as e:
         logger.error(f"Tesseract processing error: {e}", exc_info=True)
         await thinking_msg.edit(embed=create_embed(title="❌ OCR Error", description=f"An error occurred during text extraction: {e}", color=Color.red()))
    except Exception as e:
        logger.error(f"Error in OCR command: {e}", exc_info=True)
        try: await thinking_msg.delete()
        except discord.HTTPException: pass
        await ctx.send(embed=create_embed(title="❌ Error", description="An unexpected error occurred during OCR.", color=Color.dark_red()))


@bot.command(name="join", help="Makes the bot join your current voice channel. [WIP]")
@commands.cooldown(1, 10, commands.BucketType.user)
async def join(ctx: commands.Context):
    """Joins the user's voice channel."""
    if not ctx.author.voice:
        await ctx.send(embed=create_embed(title="🔊 Not in Voice", description="You need to be in a voice channel to use this command.", color=Color.orange()))
        return

    channel = ctx.author.voice.channel
    guild_id = ctx.guild.id

    if guild_id in bot.voice_clients and bot.voice_clients[guild_id].is_connected():
        # Already connected, maybe move?
        vc = bot.voice_clients[guild_id]
        if vc.channel == channel:
             await ctx.send(embed=create_embed(title="🔊 Already Here", description=f"I'm already in {channel.name}.", color=Color.blue()))
        else:
             await vc.move_to(channel)
             await ctx.send(embed=create_embed(title="🔊 Moved", description=f"Moved to {channel.name}.", color=Color.blue()))
    else:
        try:
            vc = await channel.connect(timeout=15.0, reconnect=True)
            bot.voice_clients[guild_id] = vc
            await ctx.send(embed=create_embed(title="🔊 Joined", description=f"Joined {channel.name}!", color=Color.green()))
            logger.info(f"Bot joined voice channel {channel.id} in guild {guild_id}")
        except asyncio.TimeoutError:
             logger.error(f"Timeout connecting to voice channel {channel.id}")
             await ctx.send(embed=create_embed(title="❌ Timeout", description="Could not connect to the voice channel in time.", color=Color.red()))
        except Exception as e:
            logger.error(f"Error joining voice channel {channel.id}: {e}", exc_info=True)
            await ctx.send(embed=create_embed(title="❌ Error", description=f"Failed to join voice channel: {e}", color=Color.red()))

@bot.command(name="leave", aliases=["disconnect"], help="Disconnects the bot from the voice channel. [WIP]")
@commands.cooldown(1, 5, commands.BucketType.user)
async def leave(ctx: commands.Context):
    """Disconnects from the current voice channel."""
    guild_id = ctx.guild.id

    if guild_id in bot.voice_clients and bot.voice_clients[guild_id].is_connected():
        vc = bot.voice_clients[guild_id]
        channel_name = vc.channel.name
        await vc.disconnect(force=False) # Graceful disconnect
        del bot.voice_clients[guild_id]
         # Clean up listening info if any
        bot.listening_info.pop(guild_id, None)
        await ctx.send(embed=create_embed(title="👋 Left Voice", description=f"Disconnected from {channel_name}.", color=Color.blue()))
        logger.info(f"Bot left voice channel in guild {guild_id}")
    else:
        await ctx.send(embed=create_embed(title="🔇 Not Connected", description="I'm not currently in a voice channel in this server.", color=Color.orange()))

# --- Add !listen and !correct placeholders ---
@bot.command(name="listen", help="Listens for speech in the voice channel. [WIP]")
@commands.is_owner() # Example: Restrict usage
async def listen(ctx: commands.Context):
     await ctx.send("Voice listening and speech recognition is not yet implemented.")
     logger.warning("!listen command called but not implemented.")

@bot.command(name="correct", help="Admin: Add a correction for common mistakes. [WIP]")
@commands.has_permissions(manage_messages=True) # Example permission
async def correct(ctx: commands.Context, wrong: str, *, correct_term: str):
     await ctx.send(f"Correction feature (`{wrong}` -> `{correct_term}`) is not yet implemented.")
     logger.warning("!correct command called but not implemented.")


# ======================
# BOT RUN
# ======================
if __name__ == "__main__":
    if DISCORD_TOKEN:
        try:
            logger.info("Attempting to start bot...")
            # Consider uvloop for performance: pip install uvloop
            # asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            bot.run(DISCORD_TOKEN, log_handler=None) # Use root logger configured above
        except discord.LoginFailure:
            logger.critical("❌ FATAL ERROR: Invalid Discord Token. Please check your DISCORD_TOKEN environment variable.")
        except Exception as e:
            logger.critical(f"❌ FATAL ERROR: Bot failed to start: {e}", exc_info=True)
    else:
        # This case should theoretically be caught earlier, but double-check.
        logger.critical("❌ FATAL ERROR: DISCORD_TOKEN not found. Bot cannot start.")
