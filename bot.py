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
        looks_algebraic = any(c in user_ans_norm for c in 'xyzabcdefghijklmnopqrstuvw()^*/+-') and \
                          any(c in correct_ans_norm for c in 'xyzabcdefghijklmnopqrstuvw()^*/+-')

        if looks_algebraic:
            # Check against all possible answers using Sympy
            for possible in possible_answers:
                 try:
                     # Use evaluate=False to prevent immediate simplification like '1+1' becoming '2'
                     sym_user = sp.parse_expr(user_ans_norm, evaluate=False)
                     sym_correct = sp.parse_expr(possible, evaluate=False)

                     # simplify(expr1 - expr2) == 0 is a robust check for equality
                     if sp.simplify(sym_user - sym_correct) == 0:
                         return True
                 except (sp.SympifyError, SyntaxError, TypeError):
                     continue # If parsing fails for user or correct answer, skip sympy check for this pair
    except Exception as e: # Catch any unexpected sympy error
         logger.warning(f"Sympy comparison failed: {e}")
         pass # Fallback to string comparison

    # 4. Fallback: Direct string comparison (already checked for ' or ', but double check)
    # This covers cases missed by numeric/sympy, like "1/4" or "(2, -1)"
    # We already checked user_ans_norm against possible_answers at the start.
    # If we reached here, none of the flexible checks worked.
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
        embed = create_embed(
            title="💡 Math Solution",
            description=f"**Problem:**\n{problem}\n\n**Solution:**\n{answer}",
            color=Color.green(),
            footer=f"Solved for {ctx.author.name}"
        )
        await ctx.send(embed=embed)
        logger.info(f"Solved problem for {ctx.author.id}: {problem}")

    except openai.AuthenticationError:
         logger.error("OpenAI Authentication Error. Check your API Key.")
         await thinking_msg.delete() # Ensure thinking message is deleted on error
         await ctx.send(embed=create_embed(
             title="❌ AI Error",
             description="Authentication failed. Please check the OpenAI API key configuration.",
             color=Color.red()
         ))
    except Exception as e:
        logger.error(f"Error solving problem with OpenAI: {e}", exc_info=True)
        await thinking_msg.delete() # Ensure thinking message is deleted on error
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
        result = operation(expression)
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
             description=f"Couldn't parse the expression: `{expression}`\nError: {e}\nPlease check the format.",
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
    try:
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
            description=f"Couldn't save correction: {str(e)}\nMaybe this 'wrong' term already exists?",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

@bot.command(name="unlearn", help="Removes a correction (Mods only). Usage: !unlearn <wrong term>")
@commands.has_permissions(manage_messages=True) # Example permission
async def unlearn(ctx, *, incorrect: str):
    """Remove a correction (case-insensitive lookup). Requires 'Manage Messages' permission."""
    try:
        # Use LOWER() for case-insensitive matching
        cursor.execute("DELETE FROM corrections WHERE LOWER(wrong) = ?", (incorrect.lower(),))
        changes = conn.total_changes
        conn.commit()

        if changes > 0:
            embed = create_embed(
                title="🗑️ Removed Correction",
                description=f"Removed entry/entries matching: `{incorrect}`",
                color=Color.green(),
                footer=f"Action by {ctx.author.name}"
            )
            logger.info(f"Correction unlearned by {ctx.author.id}: '{incorrect}'")
        else:
             embed = create_embed(
                title="❓ Correction Not Found",
                description=f"No correction matching `{incorrect}` found to remove.",
                color=Color.orange(),
                 footer=f"Action by {ctx.author.name}"
            )
             logger.debug(f"Correction unlearn attempt failed (not found) by {ctx.author.id}: '{incorrect}'")
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
                member = ctx.guild.get_member(int(user_id_str)) # Convert back to int for lookup
                display_name = member.display_name if member else f"User ID {user_id_str}"
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
    except AttributeError:
         logger.warning("AttributeError in mathleaders, likely ctx.guild is None (DM?).")
         await ctx.send("Leaderboard can only be shown in a server channel.")


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
# UTILITY COMMANDS
# ======================
@bot.command(name="ping", help="Checks the bot's latency.")
async def ping(ctx):
    """Check bot latency"""
    latency = bot.latency * 1000 # Latency in milliseconds
    embed = create_embed(
        title="🏓 Pong!",
        description=f"Latency: {latency:.2f} ms", # Format to 2 decimal places
        color=Color.teal() # Changed color
    )
    await ctx.send(embed=embed)

@bot.command(name="info", aliases=["about"], help="Shows information about the bot.")
async def info(ctx):
    """Show bot information and command categories"""
    embed = create_embed(
        title=f"ℹ️ About {bot.user.name}",
        description="I'm Mathilda, your friendly neighborhood math assistant! I can help solve problems, run math challenges, and more.",
        color=Color.purple(), # Changed color
        fields=[
            ("📚 Core Features", """
            • `!mathquest`: Start timed math challenges.
            • `!solve [problem]`: Solve math problems using AI.
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

    await ctx.channel.purge(limit=amount + 1) # +1 to delete the command message itself
    logger.info(f"{ctx.author} cleared {amount} messages in channel {ctx.channel.id}")

    # Send confirmation message and delete after a few seconds
    confirm_embed = create_embed(
        title="🧹 Messages Cleared",
        description=f"Successfully cleared {amount} messages.",
        color=Color.green()
    )
    msg = await ctx.send(embed=confirm_embed, delete_after=5.0) # delete_after requires seconds

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

    # Ignore DMs for certain interactions if needed
    # if isinstance(message.channel, discord.DMChannel):
    #     # Handle DMs differently or ignore
    #     # await bot.process_commands(message) # Still process commands if allowed in DMs
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
            # Maybe send a reminder they are already in help mode
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
                color=Color.greyple()
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
            # points_lost = min(5, question_data["streak"] // 2) # Example penalty
            points_lost = 5 # Simpler fixed penalty
            update_leaderboard(user_id, points_change=-points_lost, correct_answer=False, current_streak=0)
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
    if ctx.valid:
        logger.debug(f"Processing command for {user_id}: {message.content}")
    await bot.process_commands(message)


async def solve_math_question(message):
    """Helper function to call the solve command logic for math help mode."""
    try:
        # We need a context object to call the command
        ctx = await bot.get_context(message)
        # We directly call the function bound to the 'solve' command
        # Ensure the 'solve' command function exists and is accessible
        solve_command = bot.get_command('solve')
        if solve_command:
            await solve_command.callback(ctx, problem=message.content)
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

    if isinstance(error, commands.CommandNotFound):
        # Optionally send a helpful message or just ignore
        # embed = create_embed(title="❓ Unknown Command", description=f"Command not found. Use `!help` for a list.", color=Color.orange())
        log_level = logging.DEBUG # Don't clutter logs too much for typos
        logger.debug(f"CommandNotFound: {ctx.message.content} by {ctx.author}")
        return # Avoid sending embed for simple not found errors

    elif isinstance(error, commands.CommandOnCooldown):
        embed = create_embed(
            title="⏳ Command on Cooldown",
            description=f"Please wait {error.retry_after:.1f} seconds before using `{ctx.command.name}` again.",
            color=Color.light_grey()
        )

    elif isinstance(error, commands.MissingPermissions):
        embed = create_embed(
            title="🚫 Permission Denied",
            description=f"You don't have the required permissions (`{', '.join(error.missing_permissions)}`) to use this command.",
            color=Color.red()
        )

    elif isinstance(error, commands.NotOwner):
        embed = create_embed(title="🚫 Owner Only", description="This command can only be used by the bot owner.", color=Color.dark_red())

    elif isinstance(error, commands.UserInputError): # Catches MissingRequiredArgument, BadArgument, etc.
        embed = create_embed(
            title="🤔 Invalid Usage",
            description=f"There was a problem with how you used the command.\nError: {error}\n\nUse `!help {ctx.command.qualified_name}` for usage details.",
            color=Color.orange()
        )

    elif isinstance(error, commands.NoPrivateMessage):
        embed = create_embed(title="🖥️ Server Only", description="This command cannot be used in Direct Messages.", color=Color.orange())

    elif isinstance(error, commands.CheckFailure): # Generic check failure
        embed = create_embed(title="🚫 Check Failed", description="You do not meet the requirements to run this command.", color=Color.red())

    else:
        # Handle unexpected errors
        log_level = logging.ERROR # Log unexpected errors more seriously
        logger.error(f"Unhandled error in command '{ctx.command.qualified_name if ctx.command else 'None'}': {error}", exc_info=True)
        embed = create_embed(
            title="💥 Unexpected Error",
            description=f"An unexpected error occurred. The developers have been notified (hopefully!).\n```\n{type(error).__name__}: {error}\n```",
            color=Color.dark_red()
        )

    if embed:
        try:
            await ctx.send(embed=embed)
        except discord.errors.Forbidden:
             logger.warning(f"Cannot send error message to channel {ctx.channel.id}, missing permissions.")
        except Exception as e:
             logger.error(f"Failed to send error embed: {e}")

    # Log the original error context regardless of whether embed was sent
    logger.log(log_level, f"Command error ({type(error).__name__}) triggered by {ctx.author} in channel {ctx.channel.id}: {error}")


# ======================
# BOT EXECUTION
# ======================
if __name__ == "__main__":
    try:
        logger.info("Starting Mathilda Bot...")
        bot.run(DISCORD_TOKEN, log_handler=None) # Use default logging or configure discord.py logging separately if needed
    except discord.errors.LoginFailure:
        logger.critical("❌ Invalid token - please check your DISCORD_TOKEN environment variable.")
    except Exception as e:
        logger.critical(f"❌ An error occurred during bot execution: {e}", exc_info=True)
    finally:
        # This block might not execute if bot.run() encounters certain fatal errors
        # Ensure DB connection is closed if loop ends unexpectedly
        if conn:
            conn.close()
            logger.info("Database connection closed during final shutdown.")
        logger.info("Mathilda Bot has shut down.")
