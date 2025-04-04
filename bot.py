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
# LOGGING SETUP (Optional but recommended)
# ======================
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
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
    logger.warning("⚠️ WARNING: Missing OPENAI_API_KEY environment variable. !solve command will not work.")
    # Don't exit, maybe user doesn't need !solve

# ======================
# LIKELY REQUIREMENTS (for requirements.txt)
# ======================
# discord.py>=2.0.0
# openai>=1.0.0
# sympy
# Flask
# python-dotenv (if using a .env file locally)
# Pillow        # <--- ADD for OCR
# pytesseract   # <--- ADD for OCR
# requests      # <--- ADD for OCR (or ensure it's there)

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
        conn = sqlite3.connect(DB_NAME, timeout=10)
        cursor = conn.cursor()
        logger.info("Attempting to initialize database...")

        # Use TEXT primary key for user_id for better Discord ID compatibility
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS leaderboard (
            user_id TEXT PRIMARY KEY,
            points INTEGER DEFAULT 0,
            highest_streak INTEGER DEFAULT 0,
            total_correct INTEGER DEFAULT 0,
            last_active TEXT
        )""")
        logger.info("Checked/Created leaderboard table.")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS question_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            question TEXT,
            answer TEXT,
            was_correct BOOLEAN,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        logger.info("Checked/Created question_history table.")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wrong TEXT,
            correct TEXT,
            added_by TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        logger.info("Checked/Created corrections table.")

        # Add any missing columns to existing tables robustly
        table_info = cursor.execute("PRAGMA table_info(leaderboard)").fetchall()
        columns = [col[1] for col in table_info]

        if 'highest_streak' not in columns:
            cursor.execute("ALTER TABLE leaderboard ADD COLUMN highest_streak INTEGER DEFAULT 0")
            logger.info("Added missing column 'highest_streak' to leaderboard.")
        if 'total_correct' not in columns:
            cursor.execute("ALTER TABLE leaderboard ADD COLUMN total_correct INTEGER DEFAULT 0")
            logger.info("Added missing column 'total_correct' to leaderboard.")
        if 'last_active' not in columns:
            cursor.execute("ALTER TABLE leaderboard ADD COLUMN last_active TEXT")
            logger.info("Added missing column 'last_active' to leaderboard.")

        # Ensure user_id is TEXT if it was previously INTEGER (optional migration)
        # This is more complex, requires data migration, skipped for simplicity unless needed.

        conn.commit()
        logger.info("✅ Database initialized successfully")
        return conn, cursor
    except sqlite3.Error as e:
        logger.error(f"❌ Database initialization/migration failed: {e}")
        if conn:
            conn.rollback() # Rollback changes if error occurred mid-transaction
        raise # Re-raise the exception to halt execution if DB fails
    # No finally conn.close() here, keep connection open while bot runs

try:
    conn, cursor = init_database()
except Exception as e:
    logger.critical(f"❌ Halting execution due to database initialization failure: {e}")
    exit(1)

# ======================
# FLASK WEB SERVER (for hosting platforms like Replit/Render)
# ======================
app = Flask(__name__)

@app.route('/')
def home():
    return "Mathilda is running!"

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    try:
        # Use 'waitress' or 'gunicorn' for production instead of Flask's dev server
        # from waitress import serve
        # serve(app, host="0.0.0.0", port=port)
        app.run(host="0.0.0.0", port=port) # Keep dev server for simplicity here
        logger.info(f"Flask server started on port {port}")
    except Exception as e:
        logger.error(f"❌ Flask server failed to start: {e}")

# Run Flask in a separate thread
flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

# ======================
# DISCORD BOT SETUP
# ======================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True # Needed for fetching member info like avatars/names reliably
bot = commands.Bot(command_prefix="!", intents=intents)

# Bot state management
bot.math_answers = {} # Stores current math quest {user_id: {"question": str, "answer": str, "streak": int}}
bot.question_streaks = {} # Stores only the streak {user_id: int}, potentially redundant with math_answers but kept for now
bot.conversation_states = {} # Stores dicts: {user_id: {"mode": "math_help", "saved_mathquest": Optional[dict]}}

# Math help triggers
bot.math_help_triggers = [
    "help with math", "math question", "solve this", "how to calculate",
    "math help", "solve for", "how do i solve", "calculate"
]

# ======================
# MATH QUESTION DATABASE (Consider moving to DB or JSON)
# ======================
# Answers are generally lowercased for easier comparison where applicable
# Numerical answers kept as strings for initial flexibility
math_questions = {
    # Basic Arithmetic
    "What is 2 + 2?": "4",
    "What is 15 - 7?": "8",
    "What is 6 × 9?": "54",
    "What is 144 ÷ 12?": "12",
    "What is 3^4?": "81",
    "What is √144?": "12", # Could also accept sqrt(144)
    "What is 5! (factorial)?": "120",
    "What is 15% of 200?": "30", # Could also accept 30.0
    "What is 0.25 as a fraction?": "1/4",
    "What is 3/4 + 1/2?": "5/4 or 1.25 or 1 1/4",
    "What is 2^10?": "1024",
    "What is the next prime number after 7?": "11",
    "What is 1.5 × 2.5?": "3.75",
    "What is 1000 ÷ 8?": "125",
    "What is 17 × 3?": "51",

    # Algebra
    "Solve for x: 3x + 5 = 20": "5 or x=5",
    "Factor x² - 9": "(x+3)(x-3) or (x-3)(x+3)", # Sympy should handle order
    "Simplify 2(x + 3) + 4x": "6x + 6",
    "Solve for y: 2y - 7 = 15": "11 or y=11",
    "Expand (x + 2)(x - 3)": "x**2 - x - 6 or x^2 - x - 6", # Use ** for sympy
    "What is the slope of y = 2x + 5?": "2",
    "Solve the system: x + y = 5, x - y = 1": "x=3, y=2 or (3, 2)", # Needs careful parsing
    "Simplify (x³ * x⁵) / x²": "x**6 or x^6",
    "Solve the quadratic: x² - 5x + 6 = 0": "x=2, x=3 or x=3, x=2 or 2, 3 or 3, 2",
    "What is the vertex of y = x² - 4x + 3?": "(2, -1)",

    # Geometry (using approx values, consider accepting ranges or pi)
    "Area of circle with radius 5 (use pi ≈ 3.14159)": "78.54", # Tolerant float compare needed
    "Circumference of circle with diameter 10 (use pi ≈ 3.14159)": "31.42", # Tolerant float compare needed
    "Volume of cube with side length 3": "27",
    "Length of hypotenuse for right triangle with legs 3 and 4": "5", # Rephrased pythagorean
    "Sum of interior angles of a hexagon (degrees)": "720",
    "Area of triangle with base 6 height 4": "12",
    "Surface area of sphere with radius 2 (use pi ≈ 3.14159)": "50.27", # Tolerant float compare needed
    "Volume of cylinder with radius 3 height 5 (use pi ≈ 3.14159)": "141.37", # Tolerant float compare needed
    "Diagonal length of a 5 by 12 rectangle": "13",
    "Measure of one exterior angle of a regular octagon (degrees)": "45",

    # Calculus
    "Derivative of x³ w.r.t x": "3*x**2 or 3*x^2",
    "Integral of 2x dx": "x**2 or x^2", # Ignoring + C for simplicity
    "Derivative of sin(x) w.r.t x": "cos(x)",
    "Limit as x→0 of (sin x)/x": "1",
    "Integral of e^x dx": "exp(x) or e**x or e^x", # Ignoring + C

    # Word Problems
    "If 5 apples cost $2.50, what is the price per apple in dollars?": "0.50 or 0.5",
    "A train travels 300 km in 2 hours. What is its average speed in km/h?": "150", # Ignoring units for now
    "A rectangle has an area of 24 sq units and length 6 units. What is its width?": "4",
    "What is the final price of a $50 item after a 20% discount?": "40 or $40",
    "If 3 pencils cost $1.20, how much do 5 pencils cost in dollars?": "2.00 or 2",

    # Fun/Easter Eggs
    "What is the answer to life, the universe, and everything?": "42",
    "secret question - type skibidi sigma rizzler": "skibidi sigma rizzler"
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
            # Ensure value is string and not empty
            field_value = str(value) if value is not None else "N/A"
            if not field_value: field_value = "N/A" # Prevent empty field errors
            embed.add_field(name=name, value=field_value, inline=inline)
    if footer:
        embed.set_footer(text=footer)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if image:
        embed.set_image(url=image)
    return embed

def update_leaderboard(user_id: str, points_change: int = 0, correct_answer: bool = False, current_streak: int = 0):
    """Update leaderboard stats for a user. Handles INSERT or UPDATE."""
    now = datetime.now().isoformat(sep=' ', timespec='seconds') # More readable format
    user_id_str = str(user_id) # Ensure user ID is string

    try:
        cursor.execute("SELECT points, highest_streak, total_correct FROM leaderboard WHERE user_id = ?", (user_id_str,))
        result = cursor.fetchone()

        new_total_correct = (result[2] if result else 0) + (1 if correct_answer else 0)
        new_highest_streak = max(result[1] if result else 0, current_streak)
        new_points = (result[0] if result else 0) + points_change

        cursor.execute("""
        INSERT INTO leaderboard (user_id, points, highest_streak, total_correct, last_active)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET
            points = excluded.points,
            highest_streak = excluded.highest_streak,
            total_correct = excluded.total_correct,
            last_active = excluded.last_active
        """, (
            user_id_str,
            new_points,
            new_highest_streak,
            new_total_correct,
            now
        ))
        conn.commit()
        logger.debug(f"Leaderboard updated for {user_id_str}: pts_change={points_change}, correct={correct_answer}, streak={current_streak}")
    except sqlite3.Error as e:
        logger.error(f"Database error in update_leaderboard for {user_id_str}: {e}")
        conn.rollback() # Rollback on error

def log_question(user_id: str, question: str, user_answer: str, correct: bool):
    """Record a question attempt in the history table."""
    user_id_str = str(user_id) # Ensure user ID is string
    try:
        cursor.execute("""
        INSERT INTO question_history (user_id, question, answer, was_correct)
        VALUES (?, ?, ?, ?)
        """, (user_id_str, question, user_answer, int(correct)))
        conn.commit()
        logger.debug(f"Question logged for {user_id_str}: correct={correct}")
    except sqlite3.Error as e:
        logger.error(f"Database error in log_question for {user_id_str}: {e}")
        conn.rollback()

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
    possible_answers = [ans.strip() for ans in correct_ans_norm.split(' or ')]
    if user_ans_norm in possible_answers:
        return True

    # 2. Try numerical comparison (for single answers or if direct match failed)
    try:
        user_num = float(user_ans_norm)
        # Check against all possible answers if they are numeric
        for possible in possible_answers:
            try:
                correct_num = float(possible)
                if math.isclose(user_num, correct_num, rel_tol=tolerance, abs_tol=tolerance):
                    return True
            except ValueError:
                continue # This possible answer wasn't a number
    except ValueError:
        pass # User answer wasn't a number, proceed to other checks

    # 3. Try Sympy comparison for algebraic equivalence (if answers seem algebraic)
    # This is experimental and might be slow or error-prone
    try:
        # Heuristic: Check if answers likely contain variables or math functions
        # Make more robust: check for letters and common math symbols
        contains_letter = any(c.isalpha() for c in user_ans_norm)
        contains_symbol = any(c in user_ans_norm for c in '()^*/+-')
        looks_algebraic_user = contains_letter and contains_symbol

        # Check if *any* of the possible answers look algebraic
        looks_algebraic_correct = False
        for possible in possible_answers:
            if any(c.isalpha() for c in possible) and any(c in possible for c in '()^*/+-'):
                 looks_algebraic_correct = True
                 break

        if looks_algebraic_user and looks_algebraic_correct:
            # Check against all possible answers using Sympy
            for possible in possible_answers:
                 try:
                     # Use evaluate=False to prevent immediate simplification like '1+1' becoming '2'
                     # Replace common '^' with '**' for sympy compatibility
                     user_expr_sympy = user_ans_norm.replace('^', '**')
                     possible_expr_sympy = possible.replace('^', '**')

                     sym_user = sp.parse_expr(user_expr_sympy, evaluate=False)
                     sym_correct = sp.parse_expr(possible_expr_sympy, evaluate=False)

                     # simplify(expr1 - expr2) == 0 is a robust check for equality
                     if sp.simplify(sym_user - sym_correct) == 0:
                         return True
                 except (sp.SympifyError, SyntaxError, TypeError):
                     # Ignore if parsing fails for this specific pair
                     logger.debug(f"Sympy parsing failed for pair: '{user_ans_norm}', '{possible}'")
                     continue # If parsing fails for user or correct answer, skip sympy check for this pair
    except Exception as e: # Catch any unexpected sympy error
         logger.warning(f"Sympy comparison encountered an error: {e}")
         pass # Fallback to string comparison

    # 4. Final check - if we got here, none of the flexible methods matched.
    # The initial direct check `user_ans_norm in possible_answers` handles exact string matches.
    return False


# ======================
# CORE COMMANDS
# ======================
@bot.event
async def on_ready():
    """Bot startup handler"""
    logger.info(f"🚀 Mathilda is online! Logged in as {bot.user}")
    await bot.change_presence(activity=discord.Game(name="!help for commands"))

@bot.command(name="mathquest", help="Starts a math question streak challenge.")
@commands.cooldown(1, 10, commands.BucketType.user) # 1 use per 10 seconds per user
async def mathquest(ctx):
    """Start a math question streak challenge with cooldown."""
    user_id = str(ctx.author.id) # Use string IDs

    # If user is mid-conversation (e.g. math help), maybe prevent starting quest?
    if user_id in bot.conversation_states:
        await ctx.send(f"⚠️ Please finish your current math help session (type 'cancel') before starting a new quest.")
        return

    try:
        # Select random question
        question, correct_answer = random.choice(list(math_questions.items()))
        # Get current streak from memory (or default to 0)
        # Note: Highest streak is stored in DB, current session streak is here
        current_streak = bot.question_streaks.get(user_id, 0)

        # Store current challenge info
        bot.math_answers[user_id] = {
            "answer": correct_answer, # Store the original answer string
            "question": question,
            "streak": current_streak  # Store streak at the time question was asked
        }
        logger.info(f"Math quest started for {user_id}. Q: {question} A: {correct_answer}")

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

@bot.command(name="solve", help="Solves a math problem using AI (if configured). Usage: !solve <problem>")
async def solve(ctx, *, problem: str):
    """Solve any math problem with step-by-step explanation using OpenAI."""
    if not OPENAI_API_KEY:
        await ctx.send(embed=create_embed(
            title="❌ AI Feature Disabled",
            description="The OpenAI API key is not configured. This command is unavailable.",
            color=Color.orange()
        ))
        return

    try:
        # Add a thinking message
        thinking_msg = await ctx.send(embed=create_embed(
            title="🧠 Thinking...",
            description="Solving your problem, please wait.",
            color=Color.light_grey()
        ))

        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo", # Or "gpt-4" if available/needed
            messages=[{
                "role": "system",
                "content": """You are Mathilda, a friendly and precise math tutor bot.
                Explain solutions clearly, showing step-by-step working.
                For equations, show the solving process.
                For word problems, explain the setup and reasoning.
                Format answers clearly using markdown (like **bold**, `code for equations`).
                Keep explanations concise but thorough."""
            }, {
                "role": "user",
                "content": f"Solve and explain this math problem: {problem}"
            }],
            temperature=0.5, # Lower temp for more deterministic math answers
            max_tokens=1000
        )

        answer = response.choices[0].message.content

        # Delete "Thinking..." message
        await thinking_msg.delete()

        # Format response in embed
        # Check if answer is too long for embed description
        if len(answer) > 3900: # Embed description limit is 4096, leave some room
             answer_part1 = answer[:3900]
             answer_part2 = answer[3900:]
             embed = create_embed(
                 title="💡 Math Solution (Part 1)",
                 description=f"**Problem:**\n{problem}\n\n**Solution:**\n{answer_part1}",
                 color=Color.green(),
                 footer=f"Solved for {ctx.author.name} (continued...)"
             )
             await ctx.send(embed=embed)
             # Send remaining parts
             for i in range(0, len(answer_part2), 3900):
                 part = answer_part2[i:i+3900]
                 embed_cont = create_embed(
                     title=f"💡 Math Solution (Part {i//3900 + 2})",
                     description=part,
                     color=Color.green()
                 )
                 await ctx.send(embed=embed_cont)

        else:
            embed = create_embed(
                title="💡 Math Solution",
                description=f"**Problem:**\n{problem}\n\n**Solution:**\n{answer}",
                color=Color.green(),
                footer=f"Solved for {ctx.author.name}"
            )
            await ctx.send(embed=embed)

        logger.info(f"Solved problem for {ctx.author.id}: {problem[:50]}...") # Log snippet

    except openai.AuthenticationError:
         logger.error("OpenAI Authentication Error. Check your API Key.")
         # Delete thinking message if possible
         try: await thinking_msg.delete()
         except: pass
         await ctx.send(embed=create_embed(
             title="❌ AI Error",
             description="Authentication failed. Please check the OpenAI API key configuration.",
             color=Color.red()
         ))
    except Exception as e:
        logger.error(f"Error solving problem with OpenAI: {e}", exc_info=True)
        # Delete thinking message if possible
        try: await thinking_msg.delete()
        except: pass
        error_embed = create_embed(
            title="❌ Error",
            description=f"Sorry, I encountered an error trying to solve that: {e}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

# ======================
# MATH OPERATION COMMANDS (Sympy)
# ======================
async def sympy_command_helper(ctx, operation, expression: str, title: str, result_prefix: str):
    """Helper function for sympy commands"""
    try:
        # Replace common user inputs if needed, e.g., ^ to **
        expression_sympy = expression.replace('^', '**')
        result = operation(expression_sympy)
        embed = create_embed(
            title=f"{title}",
            description=f"**Original:**\n`{expression}`\n\n**{result_prefix}:**\n`{result}`",
            color=Color.blue(),
            footer=f"Calculated for {ctx.author.name}"
        )
        await ctx.send(embed=embed)
        logger.info(f"{title} calculated for {ctx.author.id}: {expression} -> {result}")
    except (sp.SympifyError, TypeError, SyntaxError) as e:
         logger.warning(f"Sympy input error ({title}) for {ctx.author.id}: {expression} | Error: {e}")
         error_embed = create_embed(
             title="❌ Invalid Input",
             description=f"Couldn't parse the expression: `{expression}`\nError: {e}\nPlease check the format (e.g., use `*` for multiplication, `**` for powers).",
             color=Color.orange()
         )
         await ctx.send(embed=error_embed)
    except Exception as e:
        logger.error(f"Error during sympy {title} for {ctx.author.id}: {expression} | Error: {e}", exc_info=True)
        error_embed = create_embed(
            title="❌ Calculation Error",
            description=f"An error occurred during calculation: {e}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

@bot.command(name="factor", help="Factors a mathematical expression. Usage: !factor <expression>")
async def factor(ctx, *, expression: str):
    """Factor a mathematical expression using sympy"""
    await sympy_command_helper(ctx, sp.factor, expression, "🔢 Factored Expression", "Factored")

@bot.command(name="simplify", help="Simplifies a mathematical expression. Usage: !simplify <expression>")
async def simplify(ctx, *, expression: str):
    """Simplify a mathematical expression using sympy"""
    await sympy_command_helper(ctx, sp.simplify, expression, "➗ Simplified Expression", "Simplified")

@bot.command(name="derive", help="Calculates the derivative. Usage: !derive <expression> [w.r.t variable]")
async def derive(ctx, *, expression: str):
    """Calculate derivative of expression using sympy"""
    # Basic variable detection (optional, assumes 'x' if not specified)
    # More complex parsing could allow specifying the variable
    await sympy_command_helper(ctx, sp.diff, expression, "📈 Derivative", "Derivative")

@bot.command(name="integrate", help="Calculates the indefinite integral. Usage: !integrate <expression> [w.r.t variable]")
async def integrate(ctx, *, expression: str):
    """Calculate indefinite integral of expression using sympy"""
    # Basic variable detection (optional, assumes 'x' if not specified)
    await sympy_command_helper(ctx, sp.integrate, expression, "∫ Integral", "Integral")


# ======================
# CORRECTION SYSTEM
# ======================
@bot.command(name="convert", aliases=["correct"], help="Looks up a correction. Usage: !convert <term>")
async def convert(ctx, *, query: str):
    """Get a correction from the database (case-insensitive lookup)."""
    try:
        # Use LOWER() for case-insensitive matching on the 'wrong' column
        cursor.execute("SELECT correct FROM corrections WHERE LOWER(wrong) = ?", (query.lower(),))
        row = cursor.fetchone()

        if row:
            embed = create_embed(
                title="🔄 Correction Found",
                description=f"**Term:** {query}\n**Correction:** {row[0]}",
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
    except sqlite3.Error as e:
        logger.error(f"Database error retrieving correction for '{query}': {e}")
        error_embed = create_embed(
            title="❌ Database Error",
            description=f"Couldn't retrieve correction: {str(e)}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

@bot.command(name="learn", help="Teach the bot a new correction. Usage: !learn \"<wrong term>\" \"<correct term>\"")
async def learn(ctx, incorrect: str, correct: str):
    """Learn a new correction. Stores the original case provided."""
    user_id_str = str(ctx.author.id)
    # Basic validation
    if not incorrect or not correct:
        await ctx.send("Usage: `!learn \"<wrong term>\" \"<correct term>\"` (ensure terms are quoted if they contain spaces)")
        return

    try:
        # Check if 'wrong' term already exists (case-insensitive)
        cursor.execute("SELECT 1 FROM corrections WHERE LOWER(wrong) = ?", (incorrect.lower(),))
        exists = cursor.fetchone()
        if exists:
            await ctx.send(embed=create_embed(
                title="⚠️ Already Exists",
                description=f"A correction for `{incorrect}` (case-insensitive) already exists. Use `!unlearn` first if you want to replace it.",
                color=Color.orange()
            ))
            return

        # Store the terms exactly as provided by the user
        cursor.execute(
            "INSERT INTO corrections (wrong, correct, added_by) VALUES (?, ?, ?)",
            (incorrect, correct, user_id_str)
        )
        conn.commit()

        embed = create_embed(
            title="📚 Learned New Correction",
            description=f"Added to database:\n**Incorrect:** {incorrect}\n**Correct:** {correct}",
            color=Color.green(),
            footer=f"Added by {ctx.author.name}"
        )
        await ctx.send(embed=embed)
        logger.info(f"Correction learned from {user_id_str}: '{incorrect}' -> '{correct}'")
    except sqlite3.Error as e:
        logger.error(f"Database error saving correction from {user_id_str}: '{incorrect}' -> '{correct}' | Error: {e}")
        conn.rollback()
        error_embed = create_embed(
            title="❌ Database Error",
            description=f"Couldn't save correction: {str(e)}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

@bot.command(name="unlearn", help="Removes a correction (Mods only). Usage: !unlearn <wrong term>")
@commands.has_permissions(manage_messages=True) # Example permission
async def unlearn(ctx, *, incorrect: str):
    """Remove a correction (case-insensitive lookup). Requires 'Manage Messages' permission."""
    try:
        # Use LOWER() for case-insensitive matching and store result before commit
        cursor.execute("SELECT COUNT(*) FROM corrections WHERE LOWER(wrong) = ?", (incorrect.lower(),))
        count_before = cursor.fetchone()[0]

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

        cursor.execute("DELETE FROM corrections WHERE LOWER(wrong) = ?", (incorrect.lower(),))
        conn.commit()
        # Verify deletion happened (optional, conn.total_changes can be tricky with concurrent ops)

        embed = create_embed(
            title="🗑️ Removed Correction",
            description=f"Removed {count_before} entry/entries matching: `{incorrect}`",
            color=Color.green(),
            footer=f"Action by {ctx.author.name}"
        )
        logger.info(f"Correction unlearned by {ctx.author.id}: '{incorrect}' ({count_before} entries)")
        await ctx.send(embed=embed)

    except sqlite3.Error as e:
        logger.error(f"Database error removing correction '{incorrect}' by {ctx.author.id}: {e}")
        conn.rollback()
        error_embed = create_embed(
            title="❌ Database Error",
            description=f"Couldn't remove correction: {str(e)}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

@bot.command(name="corrections", help="Lists recently added corrections.")
async def corrections(ctx, limit: int = 15):
    """List the most recent corrections added to the database."""
    if limit > 50 or limit < 1:
        await ctx.send("Please provide a limit between 1 and 50.")
        return
    try:
        cursor.execute("SELECT wrong, correct FROM corrections ORDER BY timestamp DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()

        if rows:
            # Use f-string formatting within join for cleaner code
            corrections_list = "\n".join([f"• **`{row[0]}`** → `{row[1]}`" for row in rows])
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
    except sqlite3.Error as e:
        logger.error(f"Database error retrieving corrections list: {e}")
        error_embed = create_embed(
            title="❌ Database Error",
            description=f"Couldn't retrieve corrections: {str(e)}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

# ======================
# STATS & LEADERBOARD
# ======================
@bot.command(name="mathleaders", aliases=["mleaders"], help="Shows the math quest leaderboard.")
async def mathleaders(ctx, limit: int = 10):
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
        cursor.execute("""
        SELECT user_id, points, highest_streak
        FROM leaderboard
        ORDER BY points DESC
        LIMIT ?
        """, (limit,))
        leaderboard_data = cursor.fetchall()

        if leaderboard_data:
            leaderboard_text = []
            rank = 1
            for row in leaderboard_data:
                user_id_str, points, highest_streak = row
                # Try to fetch member to display name, fallback to ID
                try:
                    # Use fetch_member for potentially uncached members
                    member = await ctx.guild.fetch_member(int(user_id_str))
                    display_name = member.display_name
                except (discord.NotFound, ValueError): # Handle invalid ID or member not found
                    display_name = f"User ID {user_id_str}"
                except discord.Forbidden: # Handle missing permissions
                    display_name = f"User ID {user_id_str} (name hidden)"
                except Exception as e: # Catch other potential errors during fetch
                    logger.warning(f"Could not fetch member {user_id_str} for leaderboard: {e}")
                    display_name = f"User ID {user_id_str}"

                leaderboard_text.append(
                    f"**#{rank}** {display_name} - **{points} pts** (Best Streak: {highest_streak})"
                )
                rank += 1

            embed = create_embed(
                title=f"🏆 Math Leaderboard (Top {len(leaderboard_data)})",
                description="\n".join(leaderboard_text),
                color=Color.gold()
            )
        else:
            embed = create_embed(
                title="🏆 Math Leaderboard",
                description="No scores yet! Be the first with `!mathquest`",
                color=Color.gold()
            )
        await ctx.send(embed=embed)
    except sqlite3.Error as e:
        logger.error(f"Database error retrieving leaderboard: {e}")
        error_embed = create_embed(
            title="❌ Database Error",
            description=f"Couldn't retrieve leaderboard: {str(e)}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)


@bot.command(name="mystats", aliases=["mstats"], help="Shows your math quest statistics.")
async def mystats(ctx):
    """Show your personal math statistics."""
    user_id_str = str(ctx.author.id) # Use string IDs

    try:
        # Fetch stats from leaderboard table
        cursor.execute("""
        SELECT points, highest_streak, total_correct, last_active
        FROM leaderboard
        WHERE user_id = ?
        """, (user_id_str,))
        stats = cursor.fetchone()

        if stats:
            points, highest_streak, total_correct, last_active_str = stats

            # Get total questions attempted from history
            cursor.execute("SELECT COUNT(*) FROM question_history WHERE user_id = ?", (user_id_str,))
            total_attempted = cursor.fetchone()[0]

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
    except sqlite3.Error as e:
        logger.error(f"Database error retrieving stats for {user_id_str}: {e}")
        error_embed = create_embed(
            title="❌ Database Error",
            description=f"Couldn't retrieve your stats: {str(e)}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

# ======================
# OCR COMMAND (NEW)
# ======================
@bot.command(name="ocr", help="Reads text from an image. Usage: !ocr [solve=False] (attach image)")
@commands.cooldown(1, 15, commands.BucketType.user) # Cooldown: 1 use per 15 sec per user
async def ocr(ctx, solve_directly: bool = False):
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
    if attachment.size > 8_000_000: # 8 MB limit example
        embed = create_embed(
            title="❌ Image Too Large",
            description=f"Please attach an image smaller than 8 MB.",
            color=Color.red()
        )
        await ctx.send(embed=embed)
        return

    processing_msg = await ctx.send(embed=create_embed(
        title="⏳ Processing Image...",
        description="Reading text from the image, please wait.",
        color=Color.light_grey(),
        thumbnail=attachment.url # Show thumbnail while processing
    ))

    try:
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

        await processing_msg.delete() # Delete the "Processing" message

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
             # Call the existing solve command's logic
            logger.info(f"OCR -> Solving directly for user {ctx.author.id}")
            solve_command = bot.get_command('solve')
            if solve_command and OPENAI_API_KEY: # Ensure solve command exists and API key is present
                 await solve_command.callback(ctx, problem=extracted_text)
            elif not OPENAI_API_KEY:
                 await ctx.send(embed=create_embed(
                     title="❌ AI Feature Disabled",
                     description="Cannot solve directly as the OpenAI API key is not configured.",
                     color=Color.orange()
                 ))
            else:
                 logger.error("Could not find the 'solve' command callback function for OCR.")
                 await ctx.send("Internal error: Solve functionality not available.")

        else:
             # Display extracted text
            embed = create_embed(
                title="📄 OCR Result",
                description=f"**Extracted Text:**\n```\n{extracted_text}\n```\n"
                            f"You can copy this text or run `!ocr true` (with the image) to solve directly.",
                color=Color.blue(),
                footer=f"Requested by {ctx.author.name}",
                thumbnail=attachment.url # Show the image thumbnail
            )
            # Handle potentially long text for embed description
            if len(embed.description) > 4096:
                 embed.description = embed.description[:4090] + "\n... (truncated)"
            await ctx.send(embed=embed)

    except pytesseract.TesseractNotFoundError:
        logger.error("❌ Tesseract is not installed or not in PATH.") # Log for debugging
        try: await processing_msg.delete()
        except: pass
        embed = create_embed(
            title="❌ OCR Engine Error",
            description="Tesseract OCR engine not found or configured correctly on the server. Please contact the bot owner.",
            color=Color.red()
        )
        await ctx.send(embed=embed)
    except Image.UnidentifiedImageError:
        logger.warning(f"OCR failed for user {ctx.author.id}: Unidentified image format.")
        try: await processing_msg.delete()
        except: pass
        embed = create_embed(
            title="❌ Image Format Error",
            description="Could not process the attached image. Please ensure it's a standard format (PNG, JPG, etc.) and not corrupted.",
            color=Color.red()
        )
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"❌ OCR processing error for user {ctx.author.id}: {e}", exc_info=True) # Log full traceback
        try: await processing_msg.delete()
        except: pass
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
async def ping(ctx):
    """Check bot latency"""
    latency = bot.latency * 1000 # Latency in milliseconds
    embed = create_embed(
        title="🏓 Pong!",
        description=f"Websocket Latency: {latency:.2f} ms", # Format to 2 decimal places
        color=Color.teal() # Changed color
    )
    await ctx.send(embed=embed)

@bot.command(name="info", aliases=["about"], help="Shows information about the bot.")
async def info(ctx):
    """Show bot information and command categories"""
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
            ("🤝 Support & Source", """
            • Need help? Ask in the support channel! (if applicable)
            • [Source Code](https://github.com/your-repo) (Replace with actual link if public)
            """, False) # Add link if open source
        ],
        thumbnail=bot.user.display_avatar.url # Use display_avatar
    )
    embed.set_footer(text=f"Running discord.py v{discord.__version__}")
    await ctx.send(embed=embed)

@bot.command(name="clear", aliases=["purge"], help="Clears a specified number of messages (Mods only). Usage: !clear [amount=5]")
@commands.has_permissions(manage_messages=True)
@commands.guild_only() # Makes sense to only use in guilds
async def clear(ctx, amount: int = 5):
    """Clear messages (requires Manage Messages permission)."""
    if amount < 1 or amount > 100:
        await ctx.send("Please specify an amount between 1 and 100.")
        return

    try:
        deleted = await ctx.channel.purge(limit=amount + 1) # +1 to delete the command message itself
        logger.info(f"{ctx.author} cleared {len(deleted)-1} messages in channel {ctx.channel.id}")

        # Send confirmation message and delete after a few seconds
        confirm_embed = create_embed(
            title="🧹 Messages Cleared",
            description=f"Successfully cleared {len(deleted)-1} messages.", # Report actual number deleted
            color=Color.green()
        )
        await ctx.send(embed=confirm_embed, delete_after=5.0) # delete_after requires seconds
    except discord.Forbidden:
        logger.warning(f"Missing permissions to clear messages in {ctx.channel.id}")
        await ctx.send("I don't have the required permissions (`Manage Messages`) to delete messages in this channel.")
    except Exception as e:
        logger.error(f"Error during message clearing in {ctx.channel.id}: {e}")
        await ctx.send(f"An error occurred while trying to clear messages: {e}")


@bot.command(name="shutdown")
@commands.is_owner() # Restrict to bot owner specified in bot setup or code
async def shutdown(ctx):
    """Shuts down the bot (Owner only)."""
    embed = create_embed(
        title="🛑 Shutting Down",
        description=f"{bot.user.name} is powering off...",
        color=Color.dark_red()
    )
    await ctx.send(embed=embed)
    logger.info(f"Shutdown command received from owner {ctx.author}. Shutting down.")
    # Close DB connection gracefully before exiting
    if conn:
        conn.close()
        logger.info("Database connection closed.")
    await bot.close()

# ======================
# MESSAGE HANDLER (Handles Math Quest answers & Math Help mode)
# ======================
@bot.event
async def on_message(message):
    # Ignore bots (including self)
    if message.author.bot:
        return

    # Ignore DMs for certain interactions if needed (adjust as necessary)
    # if not message.guild: # If message is not in a guild (server)
    #     # logger.debug(f"Ignoring DM from {message.author.id}")
    #     # Allow processing commands if desired in DMs
    #     # await bot.process_commands(message)
    #     return

    ctx = await bot.get_context(message) # Get context for potential command processing
    user_id = str(message.author.id) # Use string IDs
    content_lower = message.content.lower().strip()

    # --- Math Help Mode Activation ---
    # Check if the message triggers math help mode and isn't a command invocation
    # Also check if the user is NOT currently in a math quest answer state
    if not ctx.valid and any(trigger in content_lower for trigger in bot.math_help_triggers) and user_id not in bot.math_answers:
        # Check if already in math help mode (shouldn't happen often, but safety)
        if user_id in bot.conversation_states and bot.conversation_states[user_id].get("mode") == "math_help":
             await message.channel.send(embed=create_embed(
                description="You're already in math help mode! Just send your problems or type `cancel`.",
                color=Color.orange()
             ), delete_after=10)
             return # Don't restart the mode

        # Enter math help mode
        bot.conversation_states[user_id] = {"mode": "math_help"}
        logger.info(f"User {user_id} entered math help mode.")
        embed = create_embed(
            title="🧮 Math Help Activated",
            description=("I'm ready to help! Send me your math problems one by one (e.g., `solve x+5=10`, `factor x^2-1`).\n"
                         "Type `cancel` or `stop` when you're finished."),
            color=Color.blue(),
            footer="Simply type your math query."
        )
        await message.channel.send(embed=embed)
        return # Stop further processing for this message

    # --- Handle Messages While in Math Help Mode ---
    if user_id in bot.conversation_states and bot.conversation_states[user_id].get("mode") == "math_help":
        if content_lower in ["cancel", "stop", "done", "exit"]:
            del bot.conversation_states[user_id] # Exit math help mode
            logger.info(f"User {user_id} exited math help mode.")
            await message.channel.send(embed=create_embed(
                title="✅ Math Help Deactivated",
                description="Exited math help mode. You can use other commands now.",
                color=Color.greyple() # Adjusted color
            ))
            # If we implement pausing quests, restore quest state here:
            # if "saved_mathquest" in state_data: bot.math_answers[user_id] = state_data["saved_mathquest"]
            return # Stop further processing

        # If it's not a cancel command, treat it as a math problem to solve
        # We don't want to trigger other commands while in help mode.
        logger.debug(f"Math help mode: User {user_id} sent problem: {message.content}")
        await solve_math_question(message) # Use the helper to call !solve logic
        return # Stop further processing

    # --- Handle Math Quest Answers ---
    # Check only if the user has an active question *and* is not in another conversation mode
    if user_id in bot.math_answers and user_id not in bot.conversation_states:
        question_data = bot.math_answers[user_id]
        expected_answer = question_data["answer"]
        question_text = question_data["question"]
        current_streak = question_data["streak"] # Streak *before* this answer

        # Use the improved answer checking function
        is_correct = is_answer_correct(message.content, expected_answer)

        if is_correct:
            # Correct Answer Logic
            current_streak += 1
            bot.question_streaks[user_id] = current_streak # Update live streak count
            points_earned = 10 + (current_streak * 2) # Example scoring

            update_leaderboard(user_id, points_change=points_earned, correct_answer=True, current_streak=current_streak)
            log_question(user_id, question_text, message.content, True)
            logger.info(f"User {user_id} answered correctly. Streak: {current_streak}. Points: +{points_earned}")

            # Ask next question immediately
            # Ensure the next question isn't the same as the last one (simple check)
            new_question, new_answer = random.choice(list(math_questions.items()))
            while new_question == question_text:
                new_question, new_answer = random.choice(list(math_questions.items()))

            bot.math_answers[user_id] = {
                "answer": new_answer,
                "question": new_question,
                "streak": current_streak # Store the *new* current streak
            }
            logger.debug(f"Asking next question to {user_id}. Q: {new_question} A: {new_answer}")

            embed = create_embed(
                title=f"✅ Correct! Streak: {current_streak}",
                description=f"You earned **{points_earned}** points!\n\n**Next question:**\n{new_question}",
                color=Color.green()
            )
            await message.channel.send(embed=embed)

        else:
            # Incorrect Answer Logic
            # Reset streak in memory
            if user_id in bot.question_streaks:
                del bot.question_streaks[user_id]

            # Calculate penalty (optional, e.g., lose points based on streak)
            points_lost = 5 # Simpler fixed penalty
            update_leaderboard(user_id, points_change=-points_lost, correct_answer=False, current_streak=0) # Pass 0 for current streak on incorrect
            log_question(user_id, question_text, message.content, False)
            logger.info(f"User {user_id} answered incorrectly. Streak broken. Points: -{points_lost}")

            # Remove from active answers
            del bot.math_answers[user_id]

            embed = create_embed(
                title="❌ Incorrect!",
                description=f"Streak ended!\nThe correct answer was: `{expected_answer}`\nYou lost {points_lost} points.",
                color=Color.red(),
                footer="Type !mathquest to start a new challenge."
            )
            await message.channel.send(embed=embed)

        return # Answer processed, stop further message handling

    # --- Process regular commands if none of the above handled the message ---
    # Only process if it's a valid command and not handled by other logic
    if not ctx.valid:
         # If the message wasn't a command, wasn't math help activation,
         # wasn't a math help response, and wasn't a math quest answer,
         # then do nothing further with it.
         # logger.debug(f"Ignoring non-command message from {user_id}: {message.content[:50]}...")
         return

    logger.debug(f"Processing command for {user_id}: {message.content}")
    await bot.process_commands(message)


async def solve_math_question(message):
    """Helper function to call the solve command logic for math help mode."""
    try:
        # We need a context object to call the command
        ctx = await bot.get_context(message)
        # We directly call the function bound to the 'solve' command
        solve_command = bot.get_command('solve')
        if solve_command:
            # Check if AI is enabled before attempting
            if OPENAI_API_KEY:
                 await solve_command.callback(ctx, problem=message.content)
            else:
                 # Send specific message if AI is disabled
                 await ctx.send(embed=create_embed(
                     title="❌ AI Feature Disabled",
                     description="The OpenAI API key is not configured. Cannot solve automatically in help mode.",
                     color=Color.orange()
                 ))
        else:
             logger.error("Could not find the 'solve' command callback function.")
             await message.channel.send("Internal error: Solve functionality not available.")
    except Exception as e:
        logger.error(f"Error calling solve logic from on_message: {e}", exc_info=True)
        error_embed = create_embed(
            title="❌ Error",
            description=f"Sorry, I encountered an error trying to process that: {e}",
            color=Color.red()
        )
        await message.channel.send(embed=error_embed)

# ======================
# ERROR HANDLER
# ======================
@bot.event
async def on_command_error(ctx, error):
    """Handles errors globally for commands."""
    embed = None
    log_level = logging.WARNING # Default log level for handled errors

    # Check if the error originates from the original error
    # This helps in cases where discord.py wraps errors (e.g., in CheckFailure)
    original_error = getattr(error, "original", error)

    if isinstance(error, commands.CommandNotFound):
        log_level = logging.DEBUG
        logger.debug(f"CommandNotFound: '{ctx.message.content}' by {ctx.author}")
        # Optional: Send a suggestion? e.g., "Did you mean `!solve`?"
        # await ctx.send(f"Unknown command: `{ctx.invoked_with}`. Use `!help`.", delete_after=10)
        return # Usually best to ignore silently

    elif isinstance(error, commands.CommandOnCooldown):
        embed = create_embed(
            title="⏳ Command on Cooldown",
            description=f"Slow down! Please wait **{error.retry_after:.1f} seconds** before using `{ctx.command.name}` again.",
            color=Color.light_grey()
        )
        # Optional: delete the error message after cooldown expires?
        # try: await ctx.send(embed=embed, delete_after=error.retry_after)
        # except: await ctx.send(embed=embed) # Fallback if delete fails


    elif isinstance(error, commands.MissingPermissions):
        perms = ', '.join(f"`{perm}`" for perm in error.missing_permissions)
        embed = create_embed(
            title="🚫 Permission Denied",
            description=f"You need the following permission(s) to use this command: {perms}.",
            color=Color.red()
        )

    elif isinstance(error, commands.BotMissingPermissions):
        perms = ', '.join(f"`{perm}`" for perm in error.missing_permissions)
        embed = create_embed(
            title="🤖 Bot Missing Permissions",
            description=f"I don't have the required permission(s) to perform this action: {perms}. Please ask a server admin to grant them.",
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

    elif isinstance(error, commands.GuildOnly): # Should be caught by the check itself, but safety
         embed = create_embed(title="🖥️ Server Only", description="This command can only be used within a server.", color=Color.orange())


    elif isinstance(error, commands.CheckFailure): # Generic check failure (like guild_only, custom checks)
        # Try to provide more specific feedback if possible, otherwise generic message
        embed = create_embed(title="🚫 Check Failed", description="You do not meet the requirements to run this command in this context.", color=Color.red())

    # --- Specific Error Checks (e.g., from libraries) ---
    elif isinstance(original_error, pytesseract.TesseractNotFoundError):
         # This specific error is handled within the !ocr command now, but keep as fallback
         log_level = logging.ERROR
         logger.error("TesseractNotFoundError reached global handler (should be caught in command).")
         embed = create_embed(title="❌ OCR Engine Error", description="Tesseract OCR not found or configured.", color=Color.red())

    elif isinstance(original_error, openai.AuthenticationError):
         # This specific error is handled within the !solve command now, but keep as fallback
         log_level = logging.ERROR
         logger.error("OpenAI AuthenticationError reached global handler (should be caught in command).")
         embed = create_embed(title="❌ AI Auth Error", description="OpenAI Authentication failed.", color=Color.red())

    else:
        # Handle truly unexpected errors
        log_level = logging.ERROR # Log unexpected errors seriously
        logger.error(f"Unhandled error in command '{ctx.command.qualified_name if ctx.command else 'None'}': {error}", exc_info=True) # Log traceback
        embed = create_embed(
            title="💥 Unexpected Error",
            description=f"An unexpected error occurred. The developers have been notified.\n```py\n{type(original_error).__name__}: {original_error}\n```",
            color=Color.dark_red()
        )

    if embed:
        try:
            # Send error message (don't use delete_after for most errors unless it's cooldown)
            await ctx.send(embed=embed)
        except discord.errors.Forbidden:
             logger.warning(f"Cannot send error message to channel {ctx.channel.id}, missing permissions.")
             try: # Try sending to user DM as last resort
                 await ctx.author.send("I encountered an error trying to respond in the channel, possibly due to missing permissions.")
             except: pass # Ignore if DM fails too
        except Exception as e:
             logger.error(f"Failed to send error embed: {e}")

    # Log the original error context regardless of whether embed was sent
    logger.log(log_level, f"Command error ({type(original_error).__name__}) triggered by {ctx.author} ({ctx.author.id}) in channel {ctx.channel.id} (Guild: {ctx.guild.id if ctx.guild else 'DM'}): {original_error}")


# ======================
# BOT EXECUTION
# ======================
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        # Already logged and exited at the top if critical
        pass
    else:
        try:
            logger.info("Starting Mathilda Bot...")
            # Start the bot
            # Consider using discord.utils.setup_logging() for more advanced discord.py logging
            bot.run(DISCORD_TOKEN, log_handler=None) # Use default handling or configure separately

        except discord.errors.LoginFailure:
            logger.critical("❌ Invalid Discord Token - Authentication failed.")
        except discord.errors.PrivilegedIntentsRequired:
             logger.critical("❌ Privileged Intents (Members) are required but not enabled in the Developer Portal!")
        except Exception as e:
            logger.critical(f"❌ An error occurred during bot execution: {e}", exc_info=True)
        finally:
            # This block executes when bot.run() finishes (normally or via error/shutdown)
            # Ensure DB connection is closed if it's still open
            if conn:
                try:
                    conn.close()
                    logger.info("Database connection closed during final shutdown.")
                except Exception as e:
                    logger.error(f"Error closing database connection: {e}")
            logger.info("Mathilda Bot has shut down.")
