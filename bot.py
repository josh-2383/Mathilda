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
import io             # To handle image bytes
import requests       # To download image if needed
import functools      # For running blocking code in executor
# -------------------

# ======================
# LOGGING SETUP (Set back to INFO or keep DEBUG for testing)
# ======================
# Configure logging level and format
log_level = getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper(), logging.INFO) # Set back to INFO for production
logging.basicConfig(level=log_level, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
# Set higher level for noisy libraries if desired
logging.getLogger('discord.http').setLevel(logging.WARNING)
logging.getLogger('PIL').setLevel(logging.WARNING)
# Suppress Flask's default logger if needed (can be verbose)
logging.getLogger('werkzeug').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# ======================
# ENVIRONMENT VARIABLES (Ensure these are set!)
# ======================
# Never hardcode tokens or API keys!
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not DISCORD_TOKEN:
    logger.critical("❌ FATAL ERROR: Missing DISCORD_TOKEN environment variable")
    exit(1)
if not OPENAI_API_KEY:
    logger.warning("⚠️ WARNING: Missing OPENAI_API_KEY environment variable. !solve and !ocr true commands will not work.")
    # Don't exit, maybe user doesn't need !solve

# ======================
# LIKELY REQUIREMENTS (for requirements.txt)
# ======================
# discord.py>=2.0.0
# openai>=1.0.0
# sympy
# Flask       # Required for Render Web Service port binding
# python-dotenv (if using a .env file locally)
# Pillow        # For OCR
# pytesseract   # For OCR
# requests      # For OCR/HTTP requests
# gunicorn      # Optional: Production WSGI server (recommended over Flask dev server)
# waitress      # Optional: Alternative WSGI server
# uvloop        # Optional: Faster event loop

# TESSERACT INSTALLATION (For build.sh or system setup)
# Make sure Tesseract OCR engine is installed!
# Example for Debian/Ubuntu: apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-eng
# Optional: Set Tesseract path if needed
# pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract' # Adjust if necessary

# ======================
# DATABASE SETUP
# ======================
DB_NAME = 'mathilda.db'

def init_database():
    """Initialize database with all required tables and columns"""
    conn = None # Define conn outside try block
    try:
        logger.info(f"Connecting to database: {DB_NAME}")
        conn = sqlite3.connect(DB_NAME, timeout=10)
        # Enable WAL mode for better concurrency (optional but recommended)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON") # Ensure foreign key constraints are enforced if added later
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
        # Add index for faster lookup (optional but good practice)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_corrections_wrong_lower ON corrections (LOWER(wrong))")
        logger.debug("Checked/Created corrections table and index.")

        # --- Schema Migration: Add missing columns robustly ---
        logger.debug("Checking for missing columns in leaderboard...")
        table_info = cursor.execute("PRAGMA table_info(leaderboard)").fetchall()
        columns = [col[1].lower() for col in table_info] # Use lowercase for comparison

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
        # Close this initial connection; functions will create their own.
        conn.close()
        return True # Indicate success
    except sqlite3.Error as e:
        logger.error(f"❌ Database initialization/migration failed: {e}", exc_info=True)
        if conn:
            conn.rollback() # Rollback changes if error occurred mid-transaction
            conn.close() # Close connection on failure
        raise # Re-raise the exception to halt execution if DB fails

# --- Initialize DB on startup ---
try:
    init_database()
except Exception as db_init_err:
    logger.critical(f"❌ Halting execution due to database initialization failure: {db_init_err}")
    exit(1)
# ---------------------------------


# ======================
# FLASK WEB SERVER (Required for Render Web Service Port Binding) - CORRECTED
# ======================
app = Flask(__name__)

@app.route('/')
def home():
    # Simple health check endpoint
    return f"Mathilda Discord Bot is running! ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})"

def run_flask():
    # Render provides the port to bind to via the PORT environment variable
    port = int(os.environ.get('PORT', 8080)) # Default to 8080 if PORT not set (e.g., local dev)
    host = "0.0.0.0" # Bind to 0.0.0.0 to accept connections from Render's proxy
    try:
        # NOTE: Flask's development server (app.run) is not recommended for production.
        # Consider using a production-grade WSGI server like Gunicorn or Waitress.
        # Example with Waitress (add 'waitress' to requirements.txt):
        # from waitress import serve
        # logger.info(f"Starting Waitress server on {host}:{port}")
        # serve(app, host=host, port=port)

        # Using Flask's dev server for simplicity to meet Render's requirement:
        logger.info(f"Starting Flask development server on {host}:{port}")
        # Disable reloader and debug for production-like behavior if using app.run
        app.run(host=host, port=port, debug=False, use_reloader=False)

    except Exception as e:
        logger.error(f"❌ Flask server failed to start or crashed: {e}", exc_info=True)

# Start the Flask server in a separate thread so it doesn't block the Discord bot
# This thread MUST run for Render Web Services.
flask_thread = threading.Thread(target=run_flask, daemon=True)
# flask_thread.name = "FlaskServerThread" # Optional: Name the thread for easier debugging
flask_thread.start()
logger.info("Flask server thread started to handle web service requests.")
# --------------------------------------------------------------------------


# ======================
# DISCORD BOT SETUP
# ======================
intents = discord.Intents.default()
intents.message_content = True # REQUIRED for reading message content
intents.members = True # REQUIRED for reliable member lookups (display names, etc.) - Enable in Developer Portal!
bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=commands.DefaultHelpCommand(no_category='Commands'), # Group commands under 'Commands'
    activity=discord.Game(name="!help | Math Time!"), # Initial activity
    case_insensitive=True # Allow commands like !Ping or !solve
)

# Bot state management (in-memory)
bot.math_answers = {} # Stores current math quest {user_id: {"question": str, "answer": str, "streak": int}}
bot.question_streaks = {} # Stores only the streak {user_id: int}, potentially redundant with math_answers but kept for simplicity
bot.conversation_states = {} # Stores dicts: {user_id: {"mode": "math_help"}}

# Math help triggers (lowercase set for faster lookups)
bot.math_help_triggers = {
    "help with math", "math question", "solve this", "how to calculate",
    "math help", "solve for", "how do i solve", "calculate", "math problem"
}

# ======================
# MATH QUESTION DATABASE (Consider moving to DB or JSON)
# ======================
# Answers are generally lowercased for easier comparison where applicable
# Numerical answers kept as strings for initial flexibility
# Using ' or ' to separate valid answer formats
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
    # Truncate title and description if too long
    if title and len(title) > 256: embed.title = title[:253] + "..."
    if description and len(description) > 4096: embed.description = description[:4093] + "..."

    return embed

# --- Database Interaction Functions (using local connections) ---

def db_execute(sql, params=(), fetch_one=False, fetch_all=False, commit=False):
    """Executes a SQL query with local connection management."""
    conn = None
    cursor = None # Ensure cursor is defined
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA foreign_keys = ON") # Good practice
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
        # Improved error logging
        logger.error(f"Database error: {e.__class__.__name__} occurred while executing SQL.")
        logger.error(f"SQL: {sql}")
        logger.error(f"Params: {params}")
        logger.exception("Database error traceback:") # Log full traceback
        if conn and commit: # Only rollback if it was a commit operation that failed
            try:
                conn.rollback()
                logger.info("Transaction rolled back due to error.")
            except sqlite3.Error as rb_err:
                logger.error(f"Error during rollback: {rb_err}")
        # Re-raise or return None/False depending on desired error handling
        raise # Re-raise by default to make errors visible in command handlers
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def update_leaderboard(user_id: str, points_change: int = 0, correct_answer: bool = False, current_streak: int = 0):
    """Update leaderboard stats for a user. Handles INSERT or UPDATE."""
    now = datetime.now().isoformat(sep=' ', timespec='seconds')
    user_id_str = str(user_id)

    # Fetch current state first
    try:
        result = db_execute("SELECT points, highest_streak, total_correct FROM leaderboard WHERE user_id = ?", (user_id_str,), fetch_one=True)
    except Exception: # If fetch fails, assume user doesn't exist yet
        result = None

    new_total_correct = (result[2] if result else 0) + (1 if correct_answer else 0)
    new_highest_streak = max(result[1] if result else 0, current_streak)
    new_points = max(0, (result[0] if result else 0) + points_change) # Ensure points don't go below 0

    sql = """
        INSERT INTO leaderboard (user_id, points, highest_streak, total_correct, last_active)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET
            points = excluded.points,
            highest_streak = excluded.highest_streak,
            total_correct = excluded.total_correct,
            last_active = excluded.last_active
        """
    params = (user_id_str, new_points, new_highest_streak, new_total_correct, now)

    try:
        db_execute(sql, params, commit=True)
        logger.debug(f"Leaderboard updated for {user_id_str}: pts_change={points_change}, correct={correct_answer}, streak={current_streak}, new_pts={new_points}")
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
    user_ans_norm = user_answer.lower().strip()
    if not user_ans_norm: # Empty answer is never correct
        return False
    correct_ans_norm = correct_answer_str.lower().strip()

    # 1. Check for multiple correct answers separated by ' or '
    possible_answers = {ans.strip() for ans in correct_ans_norm.split(' or ')} # Use set for efficiency
    if user_ans_norm in possible_answers:
        return True

    # 2. Try numerical comparison (for single answers or if direct match failed)
    try:
        # Handle potential commas in user input for numbers
        user_num_str = user_ans_norm.replace(',', '')
        user_num = float(user_num_str)
        # Check against all possible answers if they are numeric
        for possible in possible_answers:
            try:
                correct_num_str = possible.replace(',', '')
                correct_num = float(correct_num_str)
                if math.isclose(user_num, correct_num, rel_tol=tolerance, abs_tol=tolerance):
                    return True
            except ValueError:
                continue # This possible answer wasn't a number
    except ValueError:
        pass # User answer wasn't a number, proceed to other checks

    # 3. Try Sympy comparison for algebraic equivalence (if answers seem algebraic)
    # This is experimental and might be slow or error-prone
    try:
        # Heuristic: Check if answers likely contain variables or math symbols
        contains_letter = any(c.isalpha() for c in user_ans_norm)
        contains_symbol = any(c in user_ans_norm for c in '()^*/+-=') # Added equals
        looks_algebraic_user = contains_letter or contains_symbol # Either letter or symbol is enough indication

        # Check if *any* of the possible answers look algebraic
        looks_algebraic_correct = False
        algebraic_possible_answers = set()
        for possible in possible_answers:
            if any(c.isalpha() for c in possible) or any(c in possible for c in '()^*/+-='):
                 looks_algebraic_correct = True
                 algebraic_possible_answers.add(possible)

        if looks_algebraic_user and looks_algebraic_correct:
            # Check against all *algebraic* possible answers using Sympy
            for possible in algebraic_possible_answers:
                 try:
                     # Use evaluate=False to prevent immediate simplification like '1+1' becoming '2'
                     # Replace common '^' with '**' for sympy compatibility
                     user_expr_sympy_str = user_ans_norm.replace('^', '**')
                     possible_expr_sympy_str = possible.replace('^', '**')

                     # Check for simple equations like x=5
                     if '=' in user_expr_sympy_str and '=' in possible_expr_sympy_str:
                         # Basic check: are they literally the same after normalization?
                         if user_expr_sympy_str == possible_expr_sympy_str:
                              return True
                         # Try parsing as Eq objects
                         try:
                             # Use transformations='all' for robust parsing
                             sym_user_eq = sp.parse_expr(user_expr_sympy_str, transformations='all', evaluate=False)
                             sym_correct_eq = sp.parse_expr(possible_expr_sympy_str, transformations='all', evaluate=False)
                             if isinstance(sym_user_eq, sp.Equality) and isinstance(sym_correct_eq, sp.Equality):
                                 # Check if equations are equivalent (e.g., solve both or simplify difference)
                                 # Check if the simplified difference of sides is zero
                                 # Use sp.expand to handle cases like 2*x = 10 vs x = 5
                                 if sp.expand(sym_user_eq.lhs - sym_user_eq.rhs - (sym_correct_eq.lhs - sym_correct_eq.rhs)) == 0:
                                      return True
                         except (sp.SympifyError, SyntaxError, TypeError, NotImplementedError):
                              pass # Ignore if Eq parsing fails
                         continue # Skip expression check if it looked like an equation


                     # Compare as expressions
                     sym_user = sp.parse_expr(user_expr_sympy_str, transformations='all', evaluate=False)
                     sym_correct = sp.parse_expr(possible_expr_sympy_str, transformations='all', evaluate=False)

                     # simplify(expr1 - expr2) == 0 is a robust check for equality
                     # Use numerical check for potential float issues in sympy
                     # Use expand before simplify for better comparison
                     diff = sp.simplify(sp.expand(sym_user - sym_correct))
                     # Check if difference is numerically close to zero
                     if diff.is_number and math.isclose(float(diff), 0, abs_tol=tolerance):
                         return True
                     # Check if difference simplifies symbolically to zero
                     elif diff == 0:
                          return True

                 except (sp.SympifyError, SyntaxError, TypeError, NotImplementedError) as sym_err:
                     # Ignore if parsing or simplification fails for this specific pair
                     logger.debug(f"Sympy comparison failed for pair ('{user_ans_norm}', '{possible}'): {sym_err}")
                     continue
    except Exception as e: # Catch any unexpected sympy error
         logger.warning(f"Sympy comparison encountered an unexpected error: {e}", exc_info=True)
         pass # Fallback to string comparison

    # 4. Final check - if we got here, none of the flexible methods matched.
    return False


# ======================
# CORE COMMANDS
# ======================
@bot.event
async def on_ready():
    """Bot startup handler"""
    logger.info(f"🚀 {bot.user.name} (ID: {bot.user.id}) is online!")
    logger.info(f"Using discord.py version {discord.__version__}")
    logger.info(f"Command prefix: '{bot.command_prefix}'")
    logger.info(f"Case Insensitive: {bot.case_insensitive}")
    logger.info(f"Connected to {len(bot.guilds)} guilds.")
    # Update presence
    await bot.change_presence(activity=discord.Game(name="!help | Math Time!"))

@bot.command(name="mathquest", help="Starts a math question streak challenge.")
@commands.cooldown(1, 10, commands.BucketType.user) # 1 use per 10 seconds per user
async def mathquest(ctx: commands.Context): # Add type hint
    """Start a math question streak challenge with cooldown."""
    user_id = str(ctx.author.id) # Use string IDs

    # If user is mid-conversation (e.g. math help), prevent starting quest
    if user_id in bot.conversation_states:
        await ctx.send(embed=create_embed(
            title="⚠️ Action Paused",
            description="Please finish your current math help session (type `cancel`) before starting a new quest.",
            color=Color.orange()
        ))
        ctx.command.reset_cooldown(ctx) # Reset cooldown if user couldn't start
        return

    try:
        # Select random question
        question, correct_answer = random.choice(list(math_questions.items()))
        # Get current streak from memory (or default to 0)
        current_streak = bot.question_streaks.get(user_id, 0)

        # Store current challenge info
        bot.math_answers[user_id] = {
            "answer": correct_answer, # Store the original answer string
            "question": question,
            "streak": current_streak  # Store streak at the time question was asked
        }
        logger.info(f"Math quest started for {user_id} ({ctx.author.name}). Q: {question[:50]}... A: {correct_answer}")

        # Create embed response
        embed = create_embed(
            title=f"🧮 Math Challenge (Streak: {current_streak})",
            description=f"**Question:**\n{question}",
            color=Color.green(),
            footer="Type your answer in chat!",
            thumbnail=ctx.author.display_avatar.url # Use display_avatar
        )
        await ctx.send(embed=embed)

    except Exception as e:
        logger.error(f"Error in mathquest command: {e}", exc_info=True)
        error_embed = create_embed(
            title="❌ Error",
            description=f"An unexpected error occurred while starting the challenge: {e}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

@bot.command(name="solve", help="Solves a math problem using AI (if configured).\nUsage: !solve <problem>")
@commands.cooldown(1, 8, commands.BucketType.user) # Cooldown for AI command
async def solve(ctx: commands.Context, *, problem: str): # Add type hint
    """Solve any math problem with step-by-step explanation using OpenAI."""
    if not OPENAI_API_KEY:
        await ctx.send(embed=create_embed(
            title="❌ AI Feature Disabled",
            description="The OpenAI API key is not configured. This command is unavailable.",
            color=Color.orange()
        ))
        return

    # Prevent extremely long inputs (optional)
    if len(problem) > 1500:
        await ctx.send(embed=create_embed(
            title="❌ Input Too Long",
            description="Your problem description is too long. Please keep it under 1500 characters.",
            color=Color.red()
        ))
        return

    thinking_msg = None # Initialize in case of early error
    try:
        # Add a thinking message
        thinking_msg = await ctx.send(embed=create_embed(
            title="🧠 Thinking...",
            description=f"Solving `{problem[:100]}{'...' if len(problem)>100 else ''}`...",
            color=Color.light_grey()
        ))

        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        # Run blocking network call in executor thread
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model="gpt-3.5-turbo", # Or "gpt-4" if available/needed
            messages=[{
                "role": "system",
                "content": """You are Mathilda, a friendly and precise math tutor bot.
                Explain solutions clearly, showing step-by-step working.
                For equations, show the solving process.
                For word problems, explain the setup and reasoning.
                Format answers clearly using markdown (like **bold**, `code for equations`). Use LaTeX for complex formulas if possible, like $$x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}$$.
                Keep explanations concise but thorough."""
            }, {
                "role": "user",
                "content": f"Solve and explain this math problem: {problem}"
            }],
            temperature=0.5, # Lower temp for more deterministic math answers
            max_tokens=1200 # Limit response length
        )

        answer = response.choices[0].message.content.strip()

        # Delete "Thinking..." message
        # Use try/except as message might be deleted by user or other issues
        try:
            if thinking_msg: await thinking_msg.delete()
        except discord.HTTPException:
            logger.warning("Could not delete 'Thinking...' message.")


        # --- Send Response (Handle potential length issues) ---
        max_len = 4000 # Embed description limit is 4096, leave buffer
        base_desc = f"**Problem:**\n`{problem}`\n\n**Solution:**\n"
        # Calculate remaining space considering the base description
        remaining_len = max_len - (len(base_desc) + 20) # Add buffer for title/footer/etc.

        if len(answer) <= remaining_len:
            # Send single embed if short enough
             embed = create_embed(
                title="💡 Math Solution",
                description=base_desc + answer,
                color=Color.green(),
                footer=f"Solved for {ctx.author.name}"
            )
             await ctx.send(embed=embed)
        else:
             # Split long messages more robustly
             parts = []
             current_part = "" # Start with empty part
             first_part = True # Flag for first part

             # Use a more reliable splitting method if needed, e.g., textwrap
             # Basic splitting by paragraph/line:
             split_points = answer.split('\n\n') # Prefer splitting by paragraph

             current_section_index = 0
             while current_section_index < len(split_points):
                  section = split_points[current_section_index]
                  part_limit = remaining_len if first_part else 4096 # First part has less space

                  # If a section itself is too long, split it by lines
                  if len(section) > part_limit:
                       lines = section.split('\n')
                       temp_section = ""
                       inserted = False
                       for line_index, line in enumerate(lines):
                           # Check if adding line exceeds limit for current part (can be first or subsequent)
                           temp_limit = remaining_len if first_part and not current_part else 4096
                           if len(temp_section) + len(line) + 1 > temp_limit:
                               # Insert the completed chunk *before* the current section index in the original list
                               split_points.insert(current_section_index, temp_section)
                               section = "\n".join(lines[line_index:]) # Remainder becomes the new current section
                               inserted = True
                               break # Move to process the newly inserted chunk
                           else:
                               temp_section += ("\n" if temp_section else "") + line
                       if inserted:
                           # Re-evaluate the current index as we inserted before it
                           continue # Go back to start of while loop for the inserted section
                       else:
                           # Section fits even after line splitting (unlikely but possible)
                           section = temp_section

                  # Check if adding the current section exceeds limit for the *current part being built*
                  current_part_limit = remaining_len if first_part else 4096
                  if len(current_part) + len(section) + 2 > current_part_limit:
                      # Add the completed part to the list
                      if current_part.strip():
                         parts.append(current_part.strip())
                      # Start new part with the current section
                      current_part = section
                      first_part = False # Subsequent parts have full space
                  else:
                       # Add separator (paragraph or line break)
                       sep = "\n\n" if current_part and '\n\n' in answer else "\n"
                       current_part += (sep if current_part else "") + section

                  current_section_index += 1 # Move to the next original section


             if current_part.strip(): # Add the last part if it has content
                  parts.append(current_part.strip())

             # Send the parts
             num_parts = len(parts)
             for i, part_content in enumerate(parts):
                 title = f"💡 Math Solution (Part {i+1}/{num_parts})"
                 footer = f"Solved for {ctx.author.name}" if i == num_parts - 1 else None # Footer on last part
                 # Add base description only to the very first part
                 desc_content = (base_desc + part_content) if i == 0 else part_content

                 embed = create_embed(
                      title=title, description=desc_content, color=Color.green(), footer=footer
                 )
                 # Ensure description isn't somehow still too long after splitting
                 if len(embed.description) > 4096:
                      logger.warning(f"Embed part {i+1} still too long, truncating.")
                      embed.description = embed.description[:4093] + "..."
                 await ctx.send(embed=embed)


        logger.info(f"Solved problem for {ctx.author.id} ({ctx.author.name}): {problem[:50]}...") # Log snippet

    except openai.AuthenticationError:
         logger.error("OpenAI Authentication Error. Check your API Key.")
         # Corrected delete attempt:
         if thinking_msg:
             try: await thinking_msg.delete()
             except discord.HTTPException: pass
         await ctx.send(embed=create_embed(
             title="❌ AI Error",
             description="Authentication failed. Please check the OpenAI API key configuration.",
             color=Color.red()
         ))
    except openai.RateLimitError:
         logger.warning("OpenAI Rate Limit Error.")
         # Corrected delete attempt:
         if thinking_msg:
             try: await thinking_msg.delete()
             except discord.HTTPException: pass
         await ctx.send(embed=create_embed(
             title="❌ AI Error",
             description="The AI service is currently busy or rate limited. Please try again later.",
             color=Color.orange()
         ))
    except Exception as e:
        logger.error(f"Error solving problem with OpenAI: {e}", exc_info=True)
        # Corrected delete attempt:
        if thinking_msg:
            try: await thinking_msg.delete()
            except discord.HTTPException: pass
        error_embed = create_embed(
            title="❌ Error",
            description=f"Sorry, I encountered an error trying to solve that: {e}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

# ======================
# MATH OPERATION COMMANDS (Sympy)
# ======================
async def sympy_command_helper(ctx: commands.Context, operation, expression: str, title: str, result_prefix: str):
    """Helper function for sympy commands"""
    try:
        # Replace common user inputs if needed, e.g., ^ to **
        expression_sympy = expression.replace('^', '**')
        # Run potentially blocking sympy operation in executor
        loop = asyncio.get_running_loop()
        # Use partial to pass the operation and expression
        func = functools.partial(operation, expression_sympy)
        result = await loop.run_in_executor(None, func)

        # Format result - convert sympy objects to string
        result_str = str(result)

        embed = create_embed(
            title=f"{title}",
            description=f"**Original:**\n`{expression}`\n\n**{result_prefix}:**\n`{result_str}`",
            color=Color.blue(),
            footer=f"Calculated for {ctx.author.name}"
        )
        await ctx.send(embed=embed)
        logger.info(f"{title} calculated for {ctx.author.id} ({ctx.author.name}): {expression} -> {result_str}")
    except (sp.SympifyError, TypeError, SyntaxError) as e:
         logger.warning(f"Sympy input error ({title}) for {ctx.author.id} ({ctx.author.name}): {expression} | Error: {e}")
         error_embed = create_embed(
             title="❌ Invalid Input",
             description=f"Couldn't parse the expression: `{expression}`\n**Error:** {e}\nPlease check the format (e.g., use `*` for multiplication, `**` for powers).",
             color=Color.orange()
         )
         await ctx.send(embed=error_embed)
    except Exception as e:
        logger.error(f"Error during sympy {title} for {ctx.author.id} ({ctx.author.name}): {expression} | Error: {e}", exc_info=True)
        error_embed = create_embed(
            title="❌ Calculation Error",
            description=f"An error occurred during calculation: {e}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

@bot.command(name="factor", help="Factors a mathematical expression.\nUsage: !factor <expression>")
async def factor(ctx: commands.Context, *, expression: str): # Add type hint
    """Factor a mathematical expression using sympy"""
    await sympy_command_helper(ctx, sp.factor, expression, "🔢 Factored Expression", "Factored")

@bot.command(name="simplify", help="Simplifies a mathematical expression.\nUsage: !simplify <expression>")
async def simplify(ctx: commands.Context, *, expression: str): # Add type hint
    """Simplify a mathematical expression using sympy"""
    await sympy_command_helper(ctx, sp.simplify, expression, "➗ Simplified Expression", "Simplified")

@bot.command(name="derive", help="Calculates the derivative.\nUsage: !derive <expression> [w.r.t variable]")
async def derive(ctx: commands.Context, *, expression: str): # Add type hint
    """Calculate derivative of expression using sympy"""
    await sympy_command_helper(ctx, sp.diff, expression, "📈 Derivative", "Derivative")

@bot.command(name="integrate", help="Calculates the indefinite integral.\nUsage: !integrate <expression> [w.r.t variable]")
async def integrate(ctx: commands.Context, *, expression: str): # Add type hint
    """Calculate indefinite integral of expression using sympy"""
    await sympy_command_helper(ctx, sp.integrate, expression, "∫ Integral", "Integral")


# ======================
# CORRECTION SYSTEM
# ======================
@bot.command(name="convert", aliases=["correct"], help="Looks up a correction.\nUsage: !convert <term>")
async def convert(ctx: commands.Context, *, query: str): # Add type hint
    """Get a correction from the database (case-insensitive lookup)."""
    if not query: return # Ignore empty query
    try:
        # Use LOWER() for case-insensitive matching on the 'wrong' column
        result = db_execute("SELECT correct FROM corrections WHERE LOWER(wrong) = ?", (query.lower(),), fetch_one=True)
        if result:
            embed = create_embed(
                title="🔄 Correction Found",
                description=f"**Term:** {query}\n**Correction:** {result[0]}",
                color=Color.green()
            )
            logger.debug(f"Correction found for '{query}' for user {ctx.author.id}")
        else:
            embed = create_embed(
                title="❓ No Correction Found",
                description=f"No known correction for: `{query}`\nUse `!learn \"{query}\" \"correction\"` to add one.",
                color=Color.orange()
            )
            logger.debug(f"Correction not found for '{query}' for user {ctx.author.id}")
        await ctx.send(embed=embed)
    except Exception as e: # Catch errors from db_execute
        error_embed = create_embed(
            title="❌ Database Error",
            description=f"Couldn't retrieve correction: {str(e)}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)


@bot.command(name="learn", help="Teach the bot a new correction.\nUsage: !learn \"<wrong term>\" \"<correct term>\"")
async def learn(ctx: commands.Context, incorrect: str, correct: str): # Add type hint
    """Learn a new correction. Stores the original case provided."""
    user_id_str = str(ctx.author.id)
    # Basic validation
    if not incorrect or not correct:
        await ctx.send("Usage: `!learn \"<wrong term>\" \"<correct term>\"` (ensure terms are quoted if they contain spaces)")
        return
    if len(incorrect) > 200 or len(correct) > 500:
        await ctx.send("Correction terms are too long (max 200 for 'wrong', 500 for 'correct').")
        return

    try:
        # Check if 'wrong' term already exists (case-insensitive)
        existing = db_execute("SELECT correct FROM corrections WHERE LOWER(wrong) = ?", (incorrect.lower(),), fetch_one=True)
        if existing:
            await ctx.send(embed=create_embed(
                title="⚠️ Already Exists",
                description=f"A correction for `{incorrect}` (case-insensitive) already exists:\n`{existing[0]}`\nUse `!unlearn` first if you want to replace it.",
                color=Color.orange()
            ))
            return

        # Store the terms exactly as provided by the user
        db_execute(
            "INSERT INTO corrections (wrong, correct, added_by) VALUES (?, ?, ?)",
            (incorrect, correct, user_id_str),
            commit=True
        )

        embed = create_embed(
            title="📚 Learned New Correction",
            description=f"Added to database:\n**Incorrect:** {incorrect}\n**Correct:** {correct}",
            color=Color.green(),
            footer=f"Added by {ctx.author.name}"
        )
        await ctx.send(embed=embed)
        logger.info(f"Correction learned from {user_id_str} ({ctx.author.name}): '{incorrect}' -> '{correct}'")
    except sqlite3.IntegrityError: # Should be caught by the check above, but as safety
         logger.warning(f"IntegrityError on learn for {user_id_str}, likely race condition or failed check: '{incorrect}'")
         await ctx.send(embed=create_embed(
                title="⚠️ Already Exists",
                description=f"A correction for `{incorrect}` was added just now by someone else or an error occurred.",
                color=Color.orange()
            ))
    except Exception as e: # Catch errors from db_execute
        error_embed = create_embed(
            title="❌ Database Error",
            description=f"Couldn't save correction: {str(e)}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)


@bot.command(name="unlearn", help="Removes a correction (Mods only).\nUsage: !unlearn <wrong term>")
@commands.has_permissions(manage_messages=True) # Example permission
@commands.guild_only()
async def unlearn(ctx: commands.Context, *, incorrect: str): # Add type hint
    """Remove a correction (case-insensitive lookup). Requires 'Manage Messages' permission."""
    if not incorrect: return # Ignore empty input
    try:
        # Check count first
        count_result = db_execute("SELECT COUNT(*) FROM corrections WHERE LOWER(wrong) = ?", (incorrect.lower(),), fetch_one=True)
        count_before = count_result[0] if count_result else 0

        if count_before == 0:
             embed = create_embed(
                title="❓ Correction Not Found",
                description=f"No correction matching `{incorrect}` found to remove.",
                color=Color.orange(),
                 footer=f"Action by {ctx.author.name}"
            )
             logger.debug(f"Correction unlearn attempt failed (not found) by {ctx.author.id}: '{incorrect}'")
             await ctx.send(embed=embed)
             return

        # Perform deletion
        db_execute("DELETE FROM corrections WHERE LOWER(wrong) = ?", (incorrect.lower(),), commit=True)

        embed = create_embed(
            title="🗑️ Removed Correction",
            description=f"Removed {count_before} entry/entries matching: `{incorrect}`",
            color=Color.green(),
            footer=f"Action by {ctx.author.name}"
        )
        logger.info(f"Correction unlearned by {ctx.author.id} ({ctx.author.name}): '{incorrect}' ({count_before} entries)")
        await ctx.send(embed=embed)

    except Exception as e: # Catch errors from db_execute
        error_embed = create_embed(
            title="❌ Database Error",
            description=f"Couldn't remove correction: {str(e)}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)


@bot.command(name="corrections", help="Lists recently added corrections.\nUsage: !corrections [limit=15]")
async def corrections(ctx: commands.Context, limit: int = 15): # Add type hint
    """List the most recent corrections added to the database."""
    if limit > 50 or limit < 1:
        await ctx.send("Please provide a limit between 1 and 50.")
        return

    try:
        rows = db_execute("SELECT wrong, correct FROM corrections ORDER BY timestamp DESC LIMIT ?", (limit,), fetch_all=True)

        if rows:
            # Use f-string formatting within join for cleaner code
            corrections_list = "\n".join([f"• **`{row[0]}`** → `{row[1]}`" for row in rows])
            # Handle potentially long list for embed description
            if len(corrections_list) > 4000:
                corrections_list = corrections_list[:4000] + "\n... (list truncated)"

            embed = create_embed(
                title=f"📖 Recent Corrections (Last {len(rows)})",
                description=corrections_list,
                color=Color.blue()
            )
        else:
            embed = create_embed(
                title="📖 Correction Database",
                description="No corrections stored yet. Use `!learn` to add some!",
                color=Color.blue()
            )
        await ctx.send(embed=embed)
    except Exception as e: # Catch errors from db_execute
        error_embed = create_embed(
            title="❌ Database Error",
            description=f"Couldn't retrieve corrections: {str(e)}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)


# ======================
# STATS & LEADERBOARD
# ======================
@bot.command(name="mathleaders", aliases=["mleaders"], help="Shows the math quest leaderboard.\nUsage: !mathleaders [limit=10]")
async def mathleaders(ctx: commands.Context, limit: int = 10): # Add type hint
    """Show the math leaderboard based on points."""
    if limit > 25 or limit < 1:
        await ctx.send("Please provide a limit between 1 and 25.")
        return

    # Ensure command is run in a guild context
    if not ctx.guild:
        logger.warning("mathleaders command used outside of a guild (in DMs?).")
        await ctx.send("Leaderboard can only be shown in a server channel.")
        return

    try:
        # Select user_id and other stats, order by points
        sql = """
            SELECT user_id, points, highest_streak
            FROM leaderboard
            WHERE points > 0 -- Optionally filter out zero-point users
            ORDER BY points DESC
            LIMIT ?
            """
        leaderboard_data = db_execute(sql, (limit,), fetch_all=True)

        if leaderboard_data:
            leaderboard_lines = []
            member_fetch_tasks = [] # For potentially fetching members concurrently

            # First pass: try getting from cache
            cached_members = {}
            user_ids_to_fetch = []
            rank_counter = 1
            for row in leaderboard_data:
                 user_id_int = int(row[0])
                 member = ctx.guild.get_member(user_id_int)
                 if member:
                      cached_members[user_id_int] = member.display_name
                 else:
                      # Schedule fetch only if not cached (and within reasonable limit)
                      if rank_counter <= 15: # Fetch limit to avoid too many API calls
                           user_ids_to_fetch.append(user_id_int)
                 rank_counter += 1


            # Fetch non-cached members concurrently
            fetched_members = {}
            if user_ids_to_fetch:
                 logger.debug(f"Fetching {len(user_ids_to_fetch)} members for leaderboard.")
                 # Using fetch_members is more efficient for multiple IDs if available
                 # However, fetch_member in a loop with gather is also viable
                 fetch_tasks = [ctx.guild.fetch_member(uid) for uid in user_ids_to_fetch]
                 fetched_members_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

                 for result in fetched_members_results:
                      if isinstance(result, discord.Member):
                           fetched_members[result.id] = result.display_name
                      elif isinstance(result, Exception):
                           # Log fetch error, but don't stop the leaderboard
                           logger.warning(f"Failed to fetch a member for leaderboard: {result}")


            # Second pass: build the leaderboard string
            rank = 1
            for row in leaderboard_data:
                user_id_str, points, highest_streak = row
                user_id_int = int(user_id_str)

                display_name = cached_members.get(user_id_int) or \
                               fetched_members.get(user_id_int) or \
                               f"User ID {user_id_str}" # Fallback

                leaderboard_lines.append(
                    f"**#{rank}** {display_name} - **{points} pts** (Streak: {highest_streak})"
                )
                rank += 1

            embed = create_embed(
                title=f"🏆 Math Leaderboard (Top {len(leaderboard_data)})",
                description="\n".join(leaderboard_lines),
                color=Color.gold()
            )
        else:
            embed = create_embed(
                title="🏆 Math Leaderboard",
                description="No scores yet! Be the first with `!mathquest`",
                color=Color.gold()
            )
        await ctx.send(embed=embed)
    except Exception as e: # Catch errors from db_execute or discord API
        logger.error(f"Error retrieving leaderboard: {e}", exc_info=True)
        error_embed = create_embed(
            title="❌ Error",
            description=f"Couldn't retrieve leaderboard: {str(e)}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)


@bot.command(name="mystats", aliases=["mstats"], help="Shows your math quest statistics.")
async def mystats(ctx: commands.Context): # Add type hint
    """Show your personal math statistics."""
    user_id_str = str(ctx.author.id) # Use string IDs
    try:
        # Fetch stats from leaderboard table
        stats = db_execute("SELECT points, highest_streak, total_correct, last_active FROM leaderboard WHERE user_id = ?", (user_id_str,), fetch_one=True)

        if stats:
            points, highest_streak, total_correct, last_active_str = stats

            # Get total questions attempted from history
            hist_count_result = db_execute("SELECT COUNT(*) FROM question_history WHERE user_id = ?", (user_id_str,), fetch_one=True)
            total_attempted = hist_count_result[0] if hist_count_result else 0

            accuracy = (total_correct / total_attempted * 100) if total_attempted > 0 else 0.0
            last_active_display = last_active_str if last_active_str else "Never"

            embed = create_embed(
                title=f"📊 {ctx.author.display_name}'s Math Stats", # Use display_name
                color=Color.purple(), # Changed color
                fields=[
                    ("🏅 Points", str(points), True),
                    ("🔥 Best Streak", str(highest_streak), True),
                    ("✅ Correct Answers", str(total_correct), True),
                    ("📝 Total Attempted", str(total_attempted), True),
                    ("🎯 Accuracy", f"{accuracy:.1f}%", True),
                    ("⏱️ Last Active", last_active_display, True)
                ],
                thumbnail=ctx.author.display_avatar.url # Use display_avatar
            )
        else:
            embed = create_embed(
                title=f"📊 {ctx.author.display_name}'s Stats",
                description="You haven't answered any math questions yet!\nUse `!mathquest` to get started.",
                color=Color.blue(),
                thumbnail=ctx.author.display_avatar.url
            )
        await ctx.send(embed=embed)
    except Exception as e: # Catch errors from db_execute
        logger.error(f"Database error retrieving stats for {user_id_str}: {e}", exc_info=True)
        error_embed = create_embed(
            title="❌ Database Error",
            description=f"Couldn't retrieve your stats: {str(e)}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

# ======================
# OCR COMMAND
# ======================
@bot.command(name="ocr", help="Reads text from an image.\nUsage: !ocr [solve=False] (attach image)")
@commands.cooldown(1, 15, commands.BucketType.user) # Cooldown: 1 use per 15 sec per user
async def ocr(ctx: commands.Context, solve_directly: bool = False): # Add type hint
    """
    Reads text from an attached image using OCR.

    Args:
        solve_directly (bool): If True, attempts to solve the extracted text using the !solve command. Defaults to False.
    """
    if not ctx.message.attachments:
        embed = create_embed(
            title="❌ No Image Attached",
            description="Please attach an image to your message when using the `!ocr` command.",
            color=Color.red()
        )
        await ctx.send(embed=embed)
        return

    attachment = ctx.message.attachments[0]

    # Basic check for image content type (more robust checks might be needed)
    if not attachment.content_type or not attachment.content_type.startswith('image/'):
        embed = create_embed(
            title="❌ Invalid File Type",
            description=f"Please attach a valid image file (e.g., PNG, JPG). Detected type: `{attachment.content_type}`",
            color=Color.red()
        )
        await ctx.send(embed=embed)
        return

    # Check file size (optional, prevents processing huge images)
    max_size = 8 * 1024 * 1024 # 8 MB limit
    if attachment.size > max_size:
        embed = create_embed(
            title="❌ Image Too Large",
            description=f"Please attach an image smaller than {max_size // 1024 // 1024} MB.",
            color=Color.red()
        )
        await ctx.send(embed=embed)
        return

    processing_msg = None # Initialize
    try:
        processing_msg = await ctx.send(embed=create_embed(
            title="⏳ Processing Image...",
            description="Reading text from the image, please wait.",
            color=Color.light_grey(),
            thumbnail=attachment.url # Show thumbnail while processing
        ))

        # Read the image bytes from the attachment
        image_bytes = await attachment.read()
        img = Image.open(io.BytesIO(image_bytes))

        # --- Run OCR in an executor to avoid blocking the bot ---
        loop = asyncio.get_running_loop()
        # Use functools.partial to pass arguments to the blocking function
        # Specify language ('eng') - add more languages if needed and installed (e.g., 'eng+fra')
        func = functools.partial(pytesseract.image_to_string, img, lang='eng')
        extracted_text = await loop.run_in_executor(None, func)
        # --- End of non-blocking execution ---

        try:
            if processing_msg: await processing_msg.delete() # Delete the "Processing" message
        except discord.HTTPException: pass # Ignore if message already deleted

        if not extracted_text or extracted_text.isspace():
            embed = create_embed(
                title="⚠️ OCR Result",
                description="Could not detect any text in the image.",
                color=Color.orange(),
                thumbnail=attachment.url
            )
            await ctx.send(embed=embed)
            return

        extracted_text = extracted_text.strip()
        logger.info(f"OCR successful for user {ctx.author.id}. Extracted: '{extracted_text[:100]}...'")


        if solve_directly:
             # Call the existing solve command's logic using invoke
            logger.info(f"OCR -> Solving directly for user {ctx.author.id} ({ctx.author.name})")
            solve_command = bot.get_command('solve')
            if solve_command:
                 if OPENAI_API_KEY: # Check again if key exists
                     # Create a new context-like object if needed, or just use current ctx
                     # Using current ctx is fine here as user invoked !ocr
                     await ctx.invoke(solve_command, problem=extracted_text)
                 else:
                     # Send specific message if AI is disabled when trying to solve
                     await ctx.send(embed=create_embed(
                         title="❌ AI Feature Disabled",
                         description="Cannot solve directly as the OpenAI API key is not configured.",
                         color=Color.orange()
                     ))
            else:
                 logger.error("Could not find the 'solve' command object for OCR.")
                 await ctx.send("Internal error: Solve functionality not available.")

        else:
             # Display extracted text
            desc = f"**Extracted Text:**\n```\n{extracted_text}\n```\n" \
                   f"You can copy this or run `!ocr true` (with the image) to solve directly."
            # Handle potentially long text for embed description
            if len(desc) > 4096:
                 desc = desc[:4090] + "\n... (truncated)```" # Ensure code block is closed

            embed = create_embed(
                title="📄 OCR Result",
                description=desc,
                color=Color.blue(),
                footer=f"Requested by {ctx.author.name}",
                thumbnail=attachment.url # Show the image thumbnail
            )
            await ctx.send(embed=embed)

    except pytesseract.TesseractNotFoundError:
        logger.error("❌ Tesseract is not installed or not in PATH.") # Log for debugging
        # Corrected delete attempt:
        if processing_msg:
            try: await processing_msg.delete()
            except discord.HTTPException: pass
        embed = create_embed(
            title="❌ OCR Engine Error",
            description="Tesseract OCR engine not found or configured correctly on the server. Please contact the bot owner.",
            color=Color.red()
        )
        await ctx.send(embed=embed)
    except Image.UnidentifiedImageError:
        logger.warning(f"OCR failed for user {ctx.author.id}: Unidentified image format.")
        # Corrected delete attempt:
        if processing_msg:
            try: await processing_msg.delete()
            except discord.HTTPException: pass
        embed = create_embed(
            title="❌ Image Format Error",
            description="Could not process the attached image. Please ensure it's a standard format (PNG, JPG, etc.) and not corrupted.",
            color=Color.red()
        )
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"❌ OCR processing error for user {ctx.author.id}: {e}", exc_info=True) # Log full traceback
        # Corrected delete attempt:
        if processing_msg:
            try: await processing_msg.delete()
            except discord.HTTPException: pass
        embed = create_embed(
            title="❌ Error Processing Image",
            description=f"An unexpected error occurred during OCR: {e}",
            color=Color.red()
        )
        await ctx.send(embed=embed)

# ======================
# UTILITY COMMANDS
# ======================
@bot.command(name="ping", help="Checks the bot's latency.")
async def ping(ctx: commands.Context): # Add type hint
    """Check bot latency"""
    start_time = time.monotonic()
    # Edit initial message for more accurate REST latency measure
    message = await ctx.send(embed=create_embed(title="🏓 Pinging...", color=Color.light_grey()))
    end_time = time.monotonic()
    rest_latency = (end_time - start_time) * 1000
    ws_latency = bot.latency * 1000 # Latency in milliseconds

    embed = create_embed(
        title="🏓 Pong!",
        description=f"Websocket Latency: **{ws_latency:.2f} ms**\n"
                    f"REST Latency: **{rest_latency:.2f} ms**", # Renamed for clarity
        color=Color.teal() # Changed color
    )
    try:
        await message.edit(embed=embed)
    except discord.HTTPException:
         # Message might have been deleted, send new one
         await ctx.send(embed=embed)


@bot.command(name="info", aliases=["about"], help="Shows information about the bot.")
async def info(ctx: commands.Context): # Add type hint
    """Show bot information and command categories"""
    # Get owner info if possible
    try:
        app_info = await bot.application_info()
        owner = app_info.owner
        owner_name = owner.name if owner else "Not available"
    except Exception as e:
        logger.warning(f"Could not fetch application info: {e}")
        owner_name = "Error fetching"


    embed = create_embed(
        title=f"ℹ️ About {bot.user.name}",
        description="I'm Mathilda, your friendly neighborhood math assistant! I can help solve problems, run math challenges, read math from images, and more.",
        color=Color.purple(), # Changed color
        fields=[
            ("📚 Core Features", """
            • `!mathquest`: Start timed math challenges.
            • `!solve [problem]`: Solve math problems using AI.
            • `!ocr [solve=True]`: Read math from an image (attach image).
            • `!factor`, `!simplify`, `!derive`, `!integrate`: Perform symbolic math operations.
            • `!convert`, `!learn`, `!corrections`: Manage a term correction database.
            • `!mathleaders`, `!mystats`: View leaderboards and personal stats.
            """, False),
            ("⚙️ Utility Commands", """
            • `!ping`: Check bot response time.
            • `!info`: Show this information panel.
            • `!help`: Show detailed command help.
            • `!clear [num]`: Clear messages (Mod only).
            """, False),
            ("🧑‍💻 Owner", owner_name, True),
            ("⚙️ Version", f"discord.py v{discord.__version__}", True),
            ("📊 Guilds", str(len(bot.guilds)), True),
             # Add more stats if desired (e.g., uptime, total users seen)
            ("🤝 Support & Source", """
            • Need help? Ask the owner or check the support server (if any).
            • [Source Code](https://github.com/your-repo) (Replace if public)
            """, False) # Add link if open source
        ],
        thumbnail=bot.user.display_avatar.url # Use display_avatar
    )
    await ctx.send(embed=embed)

@bot.command(name="clear", aliases=["purge"], help="Clears messages (Mods only).\nUsage: !clear [amount=5]")
@commands.has_permissions(manage_messages=True)
@commands.bot_has_permissions(manage_messages=True) # Check if bot has perms too
@commands.guild_only() # Makes sense to only use in guilds
async def clear(ctx: commands.Context, amount: int = 5): # Add type hint
    """Clear messages (requires Manage Messages permission for user and bot)."""
    if amount < 1 or amount > 100:
        await ctx.send("Please specify an amount between 1 and 100.")
        return

    try:
        # Use bulk=True for potentially faster deletion of recent messages
        deleted = await ctx.channel.purge(limit=amount + 1, check=None, bulk=True)
        logger.info(f"{ctx.author} cleared {len(deleted)-1} messages in channel {ctx.channel.id} (Guild: {ctx.guild.id})")

        # Send confirmation message and delete after a few seconds
        confirm_embed = create_embed(
            title="🧹 Messages Cleared",
            description=f"Successfully cleared {len(deleted)-1} messages.", # Report actual number deleted
            color=Color.green()
        )
        await ctx.send(embed=confirm_embed, delete_after=5.0) # delete_after requires seconds
    # Error handling moved to on_command_error for MissingPermissions/BotMissingPermissions
    except Exception as e:
        logger.error(f"Error during message clearing in {ctx.channel.id}: {e}", exc_info=True)
        await ctx.send(f"An error occurred while trying to clear messages: {e}")


@bot.command(name="shutdown")
@commands.is_owner() # Restrict to bot owner specified in bot setup or code
async def shutdown(ctx: commands.Context): # Add type hint
    """Shuts down the bot (Owner only)."""
    embed = create_embed(
        title="🛑 Shutting Down",
        description=f"{bot.user.name} is powering off...",
        color=Color.dark_red()
    )
    await ctx.send(embed=embed)
    logger.info(f"Shutdown command received from owner {ctx.author}. Shutting down.")
    # Gracefully close connections or save state if needed before closing
    # (DB connections are handled locally now)
    await bot.close()

# ======================
# MESSAGE HANDLER (Handles Math Quest answers & Math Help mode) - FINAL FINAL CORRECTED
# ======================
@bot.event
async def on_message(message: discord.Message): # Add type hint
    # 1. Ignore bots (including self)
    if message.author.bot:
        # logger.debug(f"Message {message.id} ignored: Author is bot.") # Keep logs less noisy
        return

    # 2. Ignore DMs if desired (most commands have @commands.guild_only() anyway)
    # if not message.guild:
    #     return

    # 3. Perform custom logic checks *before* command processing
    user_id = str(message.author.id) # Use string IDs
    content_lower = message.content.lower().strip() if message.content else "" # Handle potential empty content

    # --- Math Help Mode Activation ---
    ctx_check = await bot.get_context(message) # Get context once for checks

    is_math_help_trigger = any(trigger in content_lower for trigger in bot.math_help_triggers) if content_lower else False
    user_in_math_answers = user_id in bot.math_answers

    # Check triggers only if NOT a valid command and user is NOT already answering a math quest
    if not ctx_check.valid and not user_in_math_answers and is_math_help_trigger:
        # Check if already in math help mode
        if user_id in bot.conversation_states and bot.conversation_states[user_id].get("mode") == "math_help":
             # logger.debug(f"Message {message.id}: User already in help mode.")
             return # Already in mode, handled. Stop further processing.

        # Enter math help mode
        bot.conversation_states[user_id] = {"mode": "math_help"}
        logger.info(f"User {user_id} ({message.author.name}) entered math help mode.")
        embed = create_embed(
            title="🧮 Math Help Activated",
            description=("I'm ready to help! Send me your math problems one by one (e.g., `solve x+5=10`, `factor x^2-1`).\n"
                         "Type `cancel` or `stop` when you're finished."),
            color=Color.blue(),
            footer="Simply type your math query."
        )
        await message.channel.send(embed=embed)
        return # Help mode activated, handled. Stop further processing.

    # --- Handle Messages While in Math Help Mode ---
    if user_id in bot.conversation_states and bot.conversation_states[user_id].get("mode") == "math_help":
        # logger.debug(f"Message {message.id}: Entering Math Help Response block.")
        if content_lower in ["cancel", "stop", "done", "exit"]:
            # logger.debug(f"Message {message.id}: Detected help mode cancel word.")
            del bot.conversation_states[user_id] # Exit math help mode
            logger.info(f"User {user_id} ({message.author.name}) exited math help mode.")
            await message.channel.send(embed=create_embed(
                title="✅ Math Help Deactivated",
                description="Exited math help mode. You can use other commands now.",
                color=Color.greyple() # Adjusted color
            ))
            return # Exited help mode, handled. Stop further processing.

        # If not a cancel command, treat it as math problem
        logger.debug(f"Message {message.id}: Treating as math problem in help mode.")
        # Use a helper that invokes the !solve command correctly
        await solve_math_question_from_help(message)
        return # Problem sent to solver, handled. Stop further processing.

    # --- Handle Math Quest Answers ---
    if user_id in bot.math_answers and user_id not in bot.conversation_states:
        # logger.debug(f"Message {message.id}: Entering Math Quest Answer block.")
        question_data = bot.math_answers[user_id]
        expected_answer = question_data["answer"]
        question_text = question_data["question"]
        current_streak = question_data["streak"] # Streak *before* this answer

        # Use the improved answer checking function
        is_correct = is_answer_correct(message.content, expected_answer)
        # logger.debug(f"Message {message.id}: Math quest answer check. Correct: {is_correct}")

        # --- Correct Answer ---
        if is_correct:
            current_streak += 1
            bot.question_streaks[user_id] = current_streak
            points_earned = 10 + (current_streak * 2)

            loop = asyncio.get_running_loop()
            # Use functools.partial to pass args to executor functions
            update_func = functools.partial(update_leaderboard, user_id, points_earned, True, current_streak)
            log_func = functools.partial(log_question, user_id, question_text, message.content, True)
            await loop.run_in_executor(None, update_func)
            await loop.run_in_executor(None, log_func)
            logger.info(f"User {user_id} ({message.author.name}) answered correctly. Streak: {current_streak}. Points: +{points_earned}")

            new_question, new_answer = random.choice(list(math_questions.items()))
            while new_question == question_text: # Avoid immediate repeat
                new_question, new_answer = random.choice(list(math_questions.items()))

            bot.math_answers[user_id] = {
                "answer": new_answer, "question": new_question, "streak": current_streak
            }
            # logger.debug(f"Asking next question to {user_id}. Q: {new_question[:50]}... A: {new_answer}")

            embed = create_embed(
                title=f"✅ Correct! Streak: {current_streak}",
                description=f"You earned **{points_earned}** points!\n\n**Next question:**\n{new_question}",
                color=Color.green()
            )
            await message.channel.send(embed=embed)

        # --- Incorrect Answer ---
        else:
            if user_id in bot.question_streaks: del bot.question_streaks[user_id]
            points_lost = 5
            loop = asyncio.get_running_loop()
            # Use functools.partial here too
            update_func = functools.partial(update_leaderboard, user_id, -points_lost, False, 0)
            log_func = functools.partial(log_question, user_id, question_text, message.content, False)
            await loop.run_in_executor(None, update_func)
            await loop.run_in_executor(None, log_func)
            logger.info(f"User {user_id} ({message.author.name}) answered incorrectly. Streak broken. Points: -{points_lost}")

            del bot.math_answers[user_id] # Remove from active answers

            embed = create_embed(
                title="❌ Incorrect!",
                description=f"Streak ended!\nThe correct answer was: `{expected_answer}`\nYou lost {points_lost} points.",
                color=Color.red(),
                footer="Type !mathquest to start a new challenge."
            )
            await message.channel.send(embed=embed)

        return # IMPORTANT: Math quest answer handled. Stop further processing (incl. command processing).

    # 4. If none of the custom logic handlers returned, process commands.
    # This allows regular commands like !ping, !solve etc. to work
    # if they weren't intercepted by the logic above.
    # It's crucial that bot.process_commands IS called for non-intercepted messages.
    # Note: Removed debug logging here as it might be confusing. The key is process_commands below.
    await bot.process_commands(message) # <--- PROCESS COMMANDS IF NOT HANDLED ABOVE


async def solve_math_question_from_help(message: discord.Message):
    """Helper function to invoke the solve command logic for math help mode."""
    try:
        # Create a context object for the message to invoke the command
        ctx = await bot.get_context(message)
        # Ensure context is valid enough to invoke (e.g., has author, channel)
        if not ctx.channel or not ctx.author:
             logger.warning("Could not create valid context for help mode solve.")
             return

        solve_command = bot.get_command('solve')
        if solve_command:
            if OPENAI_API_KEY: # Check if AI is enabled
                 # Use invoke to properly handle checks, cooldowns, and error handling
                 # This will also trigger on_command_error if solve raises an error
                 logger.debug(f"Invoking !solve for help mode. Problem: {message.content[:50]}...")
                 await ctx.invoke(solve_command, problem=message.content)
                 logger.debug(f"!solve invocation complete for help mode.")
            else:
                 logger.warning("Attempted help mode solve, but OpenAI key is missing.")
                 await ctx.send(embed=create_embed(
                     title="❌ AI Feature Disabled",
                     description="The OpenAI API key is not configured. Cannot solve automatically in help mode.",
                     color=Color.orange()
                 ))
        else:
             logger.error("Could not find the 'solve' command object for help mode.")
             await message.channel.send("Internal error: Solve functionality not available.")
    # Let on_command_error handle errors raised by ctx.invoke
    except commands.CommandInvokeError as e:
         # If invoke causes an error, let on_command_error handle it
         logger.warning(f"CommandInvokeError during help mode solve: {e.original}")
         # on_command_error should catch the original error
    except Exception as e:
        # Catch errors during context creation or command finding *before* invoke
        logger.error(f"Error trying to invoke solve logic from help mode: {e}", exc_info=True)
        error_embed = create_embed(
            title="❌ Error",
            description=f"Sorry, I encountered an error trying to process that in help mode: {e}",
            color=Color.red()
        )
        try:
             await message.channel.send(embed=error_embed)
        except discord.HTTPException: pass # Ignore if sending fails


# ======================
# ERROR HANDLER
# ======================
@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError): # Add type hints
    """Handles errors globally for commands."""
    embed = None
    log_level = logging.WARNING # Default log level for handled errors

    # Check if the error originates from the original error
    original_error = getattr(error, "original", error)

    # --- User-Facing Errors (Generally show an embed) ---
    if isinstance(error, commands.CommandNotFound):
        log_level = logging.DEBUG
        logger.debug(f"CommandNotFound: '{ctx.message.content}' by {ctx.author}")
        # await ctx.send(f"Unknown command: `{ctx.invoked_with}`. Use `!help`.", delete_after=10)
        return # Ignore silently for less spam

    elif isinstance(error, commands.CommandOnCooldown):
        embed = create_embed(
            title="⏳ Command on Cooldown",
            description=f"Slow down! Please wait **{error.retry_after:.1f} seconds** before using `{ctx.command.name}` again.",
            color=Color.light_grey()
        )
        # Send and delete after cooldown
        try:
             # Only send if context message still exists
             if ctx.message:
                 await ctx.send(embed=embed, delete_after=error.retry_after)
        except (discord.Forbidden, discord.NotFound): pass
        except Exception as e: logger.warning(f"Failed to send/delete cooldown message: {e}")
        return # Don't log cooldowns as warnings/errors

    elif isinstance(error, commands.MissingPermissions):
        perms = ', '.join(f"`{perm.replace('_', ' ').title()}`" for perm in error.missing_permissions)
        embed = create_embed(
            title="🚫 Permission Denied",
            description=f"You need the following permission(s) to use this command: {perms}.",
            color=Color.red()
        )

    elif isinstance(error, commands.BotMissingPermissions):
        perms = ', '.join(f"`{perm.replace('_', ' ').title()}`" for perm in error.missing_permissions)
        embed = create_embed(
            title="🤖 Bot Missing Permissions",
            description=f"I don't have the required permission(s) to perform this action: {perms}.\nPlease ask a server admin to grant them.",
            color=Color.red()
        )

    elif isinstance(error, commands.NotOwner):
        embed = create_embed(title="🚫 Owner Only", description="This command can only be used by the bot owner.", color=Color.dark_red())

    elif isinstance(error, commands.UserInputError): # Catches MissingRequiredArgument, BadArgument, ConversionError etc.
        embed = create_embed(
            title="🤔 Invalid Usage",
            description=f"There was a problem with how you used the command.\n**Error:** {error}\n\nUse `!help {ctx.command.qualified_name}` for usage details.",
            color=Color.orange()
        )

    elif isinstance(error, commands.NoPrivateMessage):
        embed = create_embed(title="🖥️ Server Only", description="This command cannot be used in Direct Messages.", color=Color.orange())

    elif isinstance(error, commands.CheckFailure): # Generic check failure (like guild_only, custom checks)
        # Try to provide more specific feedback if possible, otherwise generic message
        logger.warning(f"CheckFailure for command '{ctx.command.qualified_name}' by {ctx.author}: {error}")
        embed = create_embed(title="🚫 Check Failed", description="You do not meet the requirements to run this command in this context.", color=Color.red())

    # --- Specific Library/Internal Errors (May need specific handling or just log) ---
    elif isinstance(original_error, pytesseract.TesseractNotFoundError):
         log_level = logging.ERROR
         logger.error("TesseractNotFoundError reached global handler (should be caught in command).")
         embed = create_embed(title="❌ OCR Engine Error", description="Tesseract OCR not found or configured.", color=Color.red())

    elif isinstance(original_error, openai.AuthenticationError):
         log_level = logging.ERROR
         logger.error("OpenAI AuthenticationError reached global handler (should be caught in command).")
         embed = create_embed(title="❌ AI Auth Error", description="OpenAI Authentication failed.", color=Color.red())
    elif isinstance(original_error, openai.RateLimitError):
         log_level = logging.WARNING
         logger.warning("OpenAI RateLimitError reached global handler (should be caught in command).")
         embed = create_embed(title="❌ AI Error", description="OpenAI rate limited. Please try again later.", color=Color.orange())
    elif isinstance(original_error, sqlite3.Error):
         log_level = logging.ERROR
         # Error details already logged in db_execute, just show generic message
         embed = create_embed(title="❌ Database Error", description="A database error occurred while processing your command.", color=Color.dark_red())

    # --- Truly Unexpected Errors ---
    else:
        log_level = logging.ERROR # Log unexpected errors seriously
        logger.error(f"Unhandled error in command '{ctx.command.qualified_name if ctx.command else 'None'}': {error}", exc_info=True) # Log traceback
        embed = create_embed(
            title="💥 Unexpected Error",
            description=f"An unexpected error occurred. The developers have been notified.\n```py\n{type(original_error).__name__}: {original_error}\n```",
            color=Color.dark_red()
        )

    # --- Logging and Sending ---
    # Log the error context if it wasn't a silent error like CommandNotFound or Cooldown
    if not isinstance(error, (commands.CommandNotFound, commands.CommandOnCooldown)):
         guild_info = f"Guild: {ctx.guild.id}" if ctx.guild else "DM"
         logger.log(log_level, f"Command error ({type(original_error).__name__}) triggered by {ctx.author} ({ctx.author.id}) in channel {ctx.channel.id} ({guild_info}): {original_error}")

    # Send error message embed if created
    if embed:
        try:
            await ctx.send(embed=embed)
        except discord.errors.Forbidden:
             logger.warning(f"Cannot send error message to channel {ctx.channel.id}, missing permissions.")
             try: # Try sending to user DM as last resort
                 await ctx.author.send(f"I encountered an error trying to respond in the channel (`{ctx.channel.name}`), possibly due to missing permissions. The error was: `{type(original_error).__name__}`")
             except discord.HTTPException: pass # Ignore if DM fails too
        except Exception as e:
             logger.error(f"Failed to send error embed: {e}", exc_info=True)


# ======================
# BOT EXECUTION (Using asyncio.run)
# ======================
async def main():
    """Main async function to setup and run the bot."""
    if not DISCORD_TOKEN:
        logger.critical("DISCORD_TOKEN not set. Exiting.")
        return # Exit if token is missing

    try:
        logger.info(f"Starting {bot.user.name if bot.user else 'Mathilda Bot'}...")
        # Initialize database before starting bot (ensure tables exist)
        try:
            init_database() # Run initialization check
        except Exception as db_init_err:
             logger.critical(f"❌ Halting execution due to database initialization failure: {db_init_err}")
             exit(1) # Use exit() here as we are not in the main async loop yet

        # Start the bot - this is blocking until the bot stops
        # Recommended way to run the bot within an async context
        async with bot:
            await bot.start(DISCORD_TOKEN)

    except discord.errors.LoginFailure:
        logger.critical("❌ Invalid Discord Token - Authentication failed.")
    except discord.errors.PrivilegedIntentsRequired:
         logger.critical("❌ Privileged Intents (Members/Message Content) are required but not enabled in the Developer Portal!")
         logger.critical("   Go to your bot application -> Bot -> Privileged Gateway Intents -> Enable SERVER MEMBERS INTENT and MESSAGE CONTENT INTENT.")
    except KeyboardInterrupt:
         logger.info("Shutdown requested via KeyboardInterrupt.")
    except Exception as e:
        logger.critical(f"❌ An error occurred during bot execution: {e}", exc_info=True)
    finally:
        # This block executes when bot loop finishes or is cancelled
        if not bot.is_closed():
             logger.info("Closing bot connection...")
             await bot.close() # Ensure bot is closed if loop exited unexpectedly
        logger.info("Mathilda Bot has shut down.")

if __name__ == "__main__":
    try:
        # Set uvloop as the event loop policy if available (optional performance boost)
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        logger.info("Using uvloop event loop policy.")
    except ImportError:
        logger.info("uvloop not found, using default asyncio event loop.")
        pass # uvloop is optional

    # Run the main async function
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Main loop interrupted by KeyboardInterrupt.")
