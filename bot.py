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

# ======================
# DATABASE SETUP
# ======================
def init_database():
    """Initialize database with all required tables and columns"""
    conn = sqlite3.connect('mathilda.db', timeout=10)
    cursor = conn.cursor()
    
    # Create tables with IF NOT EXISTS
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS leaderboard (
        user_id INTEGER PRIMARY KEY,
        points INTEGER DEFAULT 0,
        highest_streak INTEGER DEFAULT 0,
        total_correct INTEGER DEFAULT 0,
        last_active TEXT
    )""")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS question_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        question TEXT,
        answer TEXT,
        was_correct BOOLEAN,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS corrections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        wrong TEXT,
        correct TEXT,
        added_by INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Add any missing columns to existing tables
    cursor.execute("PRAGMA table_info(leaderboard)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'highest_streak' not in columns:
        cursor.execute("ALTER TABLE leaderboard ADD COLUMN highest_streak INTEGER DEFAULT 0")
    
    if 'total_correct' not in columns:
        cursor.execute("ALTER TABLE leaderboard ADD COLUMN total_correct INTEGER DEFAULT 0")
    
    if 'last_active' not in columns:
        cursor.execute("ALTER TABLE leaderboard ADD COLUMN last_active TEXT")
    
    conn.commit()
    return conn, cursor

try:
    conn, cursor = init_database()
    print("✅ Database initialized successfully")
except sqlite3.Error as e:
    print(f"❌ Database initialization failed: {e}")
    raise

# ======================
# FLASK WEB SERVER
# ======================
app = Flask(__name__)

@app.route('/')
def home():
    return "Mathilda is running!"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 8080)))

threading.Thread(target=run_flask, daemon=True).start()

# ======================
# DISCORD BOT SETUP
# ======================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Bot state management
bot.math_answers = {}
bot.question_streaks = {}
bot.conversation_states = {}  # Now stores dicts instead of strings
bot.user_cooldowns = {}

# Math help triggers
bot.math_help_triggers = [
    "help with math", 
    "math question", 
    "solve this", 
    "how to calculate",
    "math help",
    "solve for",
    "how do I solve"
]

# ======================
# MATH QUESTION DATABASE
# ======================
math_questions = {
    # ... [keep your existing math questions dictionary] ...
}

# ======================
# HELPER FUNCTIONS
# ======================
def create_embed(title=None, description=None, color=Color.blue(), 
                fields=None, footer=None, thumbnail=None, image=None):
    """Create rich embed with multiple formatting options"""
    embed = Embed(title=title, description=description, color=color)
    
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    
    if footer:
        embed.set_footer(text=footer)
        
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
        
    if image:
        embed.set_image(url=image)
        
    return embed

def update_leaderboard(user_id, points_change=0, streak_update=0):
    """Update leaderboard with atomic operations"""
    now = datetime.now().isoformat()
    
    try:
        cursor.execute("""
        INSERT INTO leaderboard (user_id, points, highest_streak, total_correct, last_active)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) 
        DO UPDATE SET 
            points = points + excluded.points,
            highest_streak = MAX(highest_streak, excluded.highest_streak),
            total_correct = total_correct + excluded.total_correct,
            last_active = excluded.last_active
        """, (
            user_id, 
            points_change, 
            streak_update,
            int(points_change > 0),
            now
        ))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Database error in update_leaderboard: {e}")
        conn.rollback()

def log_question(user_id, question, answer, correct):
    """Record question attempt in history"""
    try:
        cursor.execute("""
        INSERT INTO question_history (user_id, question, answer, was_correct)
        VALUES (?, ?, ?, ?)
        """, (user_id, question, answer, int(correct)))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Database error in log_question: {e}")
        conn.rollback()

# ======================
# CORE COMMANDS
# ======================
@bot.event
async def on_ready():
    """Bot startup handler"""
    print(f"🚀 Mathilda is online! Logged in as {bot.user}")
    await bot.change_presence(activity=discord.Game(name="!help for commands"))

@bot.command()
async def mathquest(ctx):
    """Start a math question streak challenge with cooldown"""
    user_id = ctx.author.id
    
    # Cooldown check (10 seconds)
    last_used = bot.user_cooldowns.get(user_id, 0)
    if time.time() - last_used < 10:
        remaining = 10 - int(time.time() - last_used)
        await ctx.send(f"⏳ Please wait {remaining} seconds before starting a new challenge!")
        return
    
    bot.user_cooldowns[user_id] = time.time()
    
    try:
        # Select random question
        question, correct_answer = random.choice(list(math_questions.items()))
        current_streak = bot.question_streaks.get(user_id, 0)
        
        # Store current challenge
        bot.math_answers[user_id] = {
            "answer": correct_answer,
            "question": question,
            "streak": current_streak
        }
        
        # Create embed response
        embed = create_embed(
            title=f"🧮 Math Challenge (Streak: {current_streak})",
            description=question,
            color=Color.green(),
            footer="Type your answer in chat!",
            thumbnail=ctx.author.avatar.url
        )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        error_embed = create_embed(
            title="❌ Error",
            description=f"An error occurred: {str(e)}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

@bot.command()
async def solve(ctx, *, problem: str):
    """Solve any math problem with step-by-step explanation"""
    try:
        # Call OpenAI API
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{
                "role": "system",
                "content": """You are a helpful math tutor. Explain solutions clearly with steps.
                For equations, show the solving process. For word problems, explain the reasoning."""
            }, {
                "role": "user",
                "content": f"Solve this math problem: {problem}"
            }],
            temperature=0.7
        )

        answer = response.choices[0].message.content
        
        # Format response
        embed = create_embed(
            title="🧠 Math Solution",
            description=f"**Problem:** {problem}\n\n**Solution:** {answer}",
            color=Color.green(),
            footer=f"Requested by {ctx.author.name}"
        )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        error_embed = create_embed(
            title="❌ Error",
            description=f"Error solving problem: {e}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

# ======================
# MATH OPERATION COMMANDS
# ======================
@bot.command()
async def factor(ctx, *, expression: str):
    """Factor a mathematical expression"""
    try:
        result = sp.factor(expression)
        embed = create_embed(
            title="🔢 Factored Expression",
            description=f"**Original:** {expression}\n**Factored:** `{result}`",
            color=Color.blue(),
            footer=f"Requested by {ctx.author.name}"
        )
        await ctx.send(embed=embed)
    except Exception as e:
        error_embed = create_embed(
            title="❌ Error",
            description=f"Error factoring expression: {e}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

@bot.command()
async def simplify(ctx, *, expression: str):
    """Simplify a mathematical expression"""
    try:
        result = sp.simplify(expression)
        embed = create_embed(
            title="➗ Simplified Expression",
            description=f"**Original:** {expression}\n**Simplified:** `{result}`",
            color=Color.blue(),
            footer=f"Requested by {ctx.author.name}"
        )
        await ctx.send(embed=embed)
    except Exception as e:
        error_embed = create_embed(
            title="❌ Error",
            description=f"Error simplifying expression: {e}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

@bot.command()
async def derive(ctx, *, expression: str):
    """Calculate derivative of expression"""
    try:
        result = sp.diff(expression)
        embed = create_embed(
            title="📈 Derivative",
            description=f"**Function:** {expression}\n**Derivative:** `{result}`",
            color=Color.blue(),
            footer=f"Requested by {ctx.author.name}"
        )
        await ctx.send(embed=embed)
    except Exception as e:
        error_embed = create_embed(
            title="❌ Error",
            description=f"Error finding derivative: {e}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

@bot.command()
async def integrate(ctx, *, expression: str):
    """Calculate integral of expression"""
    try:
        result = sp.integrate(expression)
        embed = create_embed(
            title="∫ Integral",
            description=f"**Function:** {expression}\n**Integral:** `{result}`",
            color=Color.blue(),
            footer=f"Requested by {ctx.author.name}"
        )
        await ctx.send(embed=embed)
    except Exception as e:
        error_embed = create_embed(
            title="❌ Error",
            description=f"Error finding integral: {e}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

# ======================
# CORRECTION SYSTEM
# ======================
@bot.command()
async def convert(ctx, *, query: str):
    """Get a correction from database"""
    try:
        cursor.execute("SELECT correct FROM corrections WHERE wrong = ?", (query,))
        row = cursor.fetchone()
        
        if row:
            embed = create_embed(
                title="🔄 Correction Found",
                description=f"**You asked:** {query}\n**Correction:** {row[0]}",
                color=Color.green()
            )
        else:
            embed = create_embed(
                title="❓ No Correction Found",
                description=f"No known correction for: {query}\nUse `!learn {query} correction` to add one",
                color=Color.orange()
            )
        await ctx.send(embed=embed)
    except sqlite3.Error as e:
        error_embed = create_embed(
            title="❌ Database Error",
            description=f"Couldn't retrieve correction: {str(e)}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

@bot.command()
async def learn(ctx, incorrect: str, correct: str):
    """Learn a new correction"""
    try:
        cursor.execute(
            "INSERT INTO corrections (wrong, correct, added_by) VALUES (?, ?, ?)",
            (incorrect, correct, ctx.author.id)
        )
        conn.commit()
        
        embed = create_embed(
            title="📚 Learned New Correction",
            description=f"Added to database:\n**Incorrect:** {incorrect}\n**Correct:** {correct}",
            color=Color.green(),
            footer=f"Added by {ctx.author.name}"
        )
        await ctx.send(embed=embed)
    except sqlite3.Error as e:
        error_embed = create_embed(
            title="❌ Database Error",
            description=f"Couldn't save correction: {str(e)}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

@bot.command()
async def unlearn(ctx, incorrect: str):
    """Remove a correction (mod only)"""
    if not ctx.author.guild_permissions.manage_messages:
        await ctx.send("🚨 You need Manage Messages permission to use this!")
        return
        
    try:
        cursor.execute("DELETE FROM corrections WHERE wrong = ?", (incorrect,))
        conn.commit()
        
        embed = create_embed(
            title="🗑️ Removed Correction",
            description=f"Removed entry for: {incorrect}",
            color=Color.green()
        )
        await ctx.send(embed=embed)
    except sqlite3.Error as e:
        error_embed = create_embed(
            title="❌ Database Error",
            description=f"Couldn't remove correction: {str(e)}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

@bot.command()
async def corrections(ctx):
    """List all corrections in database"""
    try:
        cursor.execute("SELECT wrong, correct FROM corrections ORDER BY timestamp DESC LIMIT 20")
        rows = cursor.fetchall()
        
        if rows:
            corrections_list = "\n".join([f"• **{row[0]}** → {row[1]}" for row in rows])
            embed = create_embed(
                title="📖 Recent Corrections (20)",
                description=corrections_list,
                color=Color.blue()
            )
        else:
            embed = create_embed(
                title="📖 Correction Database",
                description="No corrections stored yet.",
                color=Color.blue()
            )
        await ctx.send(embed=embed)
    except sqlite3.Error as e:
        error_embed = create_embed(
            title="❌ Database Error",
            description=f"Couldn't retrieve corrections: {str(e)}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

# ======================
# STATS & LEADERBOARD
# ======================
@bot.command()
async def mathleaders(ctx):
    """Show the math leaderboard"""
    try:
        cursor.execute("""
        SELECT user_id, points, highest_streak 
        FROM leaderboard 
        ORDER BY points DESC 
        LIMIT 10
        """)
        leaderboard = cursor.fetchall()
        
        if leaderboard:
            leaderboard_text = "\n".join(
                f"**#{i+1}** <@{row[0]}> - **{row[1]} pts** (Best streak: {row[2]})"
                for i, row in enumerate(leaderboard))
            
            embed = create_embed(
                title="🏆 Math Leaderboard (Top 10)",
                description=leaderboard_text,
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
        error_embed = create_embed(
            title="❌ Database Error",
            description=f"Couldn't retrieve leaderboard: {str(e)}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

@bot.command()
async def mystats(ctx):
    """Show your math statistics"""
    user_id = ctx.author.id
    
    try:
        cursor.execute("""
        SELECT points, highest_streak, total_correct, last_active
        FROM leaderboard
        WHERE user_id = ?
        """, (user_id,))
        
        stats = cursor.fetchone()
        
        if stats:
            points, highest_streak, total_correct, last_active = stats
            
            # Get total questions attempted
            cursor.execute("""
            SELECT COUNT(*) FROM question_history
            WHERE user_id = ?
            """, (user_id,))
            total_attempted = cursor.fetchone()[0]
            
            accuracy = (total_correct / total_attempted * 100) if total_attempted > 0 else 0
            
            embed = create_embed(
                title=f"📊 {ctx.author.name}'s Math Stats",
                color=Color.blue(),
                fields=[
                    ("🏅 Points", str(points), True),
                    ("🔥 Best Streak", str(highest_streak), True),
                    ("✅ Correct Answers", str(total_correct), True),
                    ("📝 Total Attempted", str(total_attempted), True),
                    ("🎯 Accuracy", f"{accuracy:.1f}%", True),
                    ("⏱️ Last Active", last_active.split('.')[0] if last_active else "Never", True)
                ],
                thumbnail=ctx.author.avatar.url
            )
        else:
            embed = create_embed(
                title=f"📊 {ctx.author.name}'s Stats",
                description="You haven't answered any math questions yet!\nUse `!mathquest` to get started.",
                color=Color.blue()
            )
        
        await ctx.send(embed=embed)
    except sqlite3.Error as e:
        error_embed = create_embed(
            title="❌ Database Error",
            description=f"Couldn't retrieve stats: {str(e)}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

# ======================
# UTILITY COMMANDS
# ======================
@bot.command()
async def ping(ctx):
    """Check bot latency"""
    embed = create_embed(
        title="🏓 Pong!",
        description=f"Latency: {round(bot.latency * 1000)}ms",
        color=Color.blue()
    )
    await ctx.send(embed=embed)

@bot.command()
async def info(ctx):
    """Show bot information and commands"""
    embed = create_embed(
        title="ℹ️ Mathilda - The Math Bot",
        description="A helpful bot for solving math problems and learning mathematics!",
        color=Color.blue(),
        fields=[
            ("📚 Features", """
            • Math problem solving
            • Math challenges with streaks
            • Corrections database
            • Leaderboard & statistics
            """, False),
            
            ("🔢 Math Commands", """
            `!mathquest` - Start math challenge
            `!solve [problem]` - Solve any math problem
            `!factor [expr]` - Factor expression
            `!simplify [expr]` - Simplify expression
            `!derive [expr]` - Calculate derivative
            `!integrate [expr]` - Calculate integral
            """, False),
            
            ("🏆 Stats", """
            `!mathleaders` - Show leaderboard
            `!mystats` - Your statistics
            """, False),
            
            ("📖 Corrections", """
            `!convert [term]` - Get correction
            `!learn [wrong] [correct]` - Add correction
            `!corrections` - List corrections
            """, False),
            
            ("⚙️ Utilities", """
            `!ping` - Check latency
            `!info` - This menu
            `!help` - Command help
            """, False)
        ],
        thumbnail=bot.user.avatar.url
    )
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    """Clear messages (mod only)"""
    await ctx.channel.purge(limit=amount + 1)  # +1 to account for command
    
    embed = create_embed(
        title="🧹 Messages Cleared",
        description=f"Cleared {amount} messages.",
        color=Color.green()
    )
    msg = await ctx.send(embed=embed)
    await asyncio.sleep(5)
    await msg.delete()

@bot.command()
@commands.is_owner()
async def shutdown(ctx):
    """Shutdown the bot (owner only)"""
    embed = create_embed(
        title="🛑 Shutting Down",
        description="Mathilda is powering off...",
        color=Color.red()
    )
    await ctx.send(embed=embed)
    conn.close()
    await bot.close()

# ======================
# MESSAGE HANDLER - FIXED VERSION
# ======================
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    ctx = await bot.get_context(message)
    user_id = message.author.id
    content = message.content.lower().strip()

    # First check if this is a help request
    if any(trigger in content for trigger in bot.math_help_triggers):
        # If currently in mathquest, preserve the state
        if user_id in bot.math_answers:
            bot.conversation_states[user_id] = {
                "mode": "math_help",
                "saved_mathquest": bot.math_answers[user_id]
            }
            del bot.math_answers[user_id]  # Temporarily remove from math answers
        else:
            bot.conversation_states[user_id] = {"mode": "math_help"}
            
        embed = create_embed(
            title="🧮 Math Help Activated",
            description="""Now in math help mode! 
            \nJust type problems like:
            - `2+2`
            - `Solve 3x=9`
            - `Factor x²-4`
            \nSay 'cancel' when done.""",
            color=Color.blue()
        )
        await message.channel.send(embed=embed)
        return

    # Handle math help mode
    if user_id in bot.conversation_states and bot.conversation_states[user_id].get("mode") == "math_help":
        if any(word in content for word in ["cancel", "stop", "done"]):
            # Restore mathquest state if it existed
            if "saved_mathquest" in bot.conversation_states[user_id]:
                bot.math_answers[user_id] = bot.conversation_states[user_id]["saved_mathquest"]
                await message.channel.send("Exited math help mode. Returning to your math quest!")
            else:
                await message.channel.send("Exited math help mode.")
            del bot.conversation_states[user_id]
            return
        else:
            await solve_math_question(message)
            return

    # Handle Math Quest answers (only if not in help mode)
    if user_id in bot.math_answers:
        question_data = bot.math_answers[user_id]
        correct_answer = question_data["answer"]
        current_streak = question_data["streak"]
        
        if content == correct_answer.lower():
            # Correct answer handling
            current_streak += 1
            points = 10 + (current_streak * 2)
            
            update_leaderboard(user_id, points, current_streak)
            log_question(user_id, question_data["question"], content, True)
            
            new_question, new_answer = random.choice(list(math_questions.items()))
            bot.math_answers[user_id] = {
                "answer": new_answer,
                "question": new_question,
                "streak": current_streak
            }
            bot.question_streaks[user_id] = current_streak
            
            embed = create_embed(
                title=f"✅ Correct! (Streak: {current_streak})",
                description=f"""You earned {points} points!
                \n**Next question:** {new_question}""",
                color=Color.green()
            )
            await message.channel.send(embed=embed)
            
        else:
            lost_points = min(5, current_streak * 2)
            update_leaderboard(user_id, -lost_points)
            log_question(user_id, question_data["question"], content, False)
            
            embed = create_embed(
                title="❌ Incorrect!",
                description=f"""Streak ended! 
                \n**Correct answer was:** `{correct_answer}`
                \nLost {lost_points} points.
                \nType `!mathquest` to restart""",
                color=Color.red()
            )
            await message.channel.send(embed=embed)
            
            del bot.math_answers[user_id]
            if user_id in bot.question_streaks:
                del bot.question_streaks[user_id]
                
        return
    
    await bot.process_commands(message)

async def solve_math_question(message):
    """Helper function to solve math questions in help mode"""
    try:
        ctx = await bot.get_context(message)
        await solve(ctx, problem=message.content)
    except Exception as e:
        error_embed = create_embed(
            title="❌ Error",
            description=f"Error solving problem: {e}",
            color=Color.red()
        )
        await message.channel.send(embed=error_embed)

# ======================
# ERROR HANDLER
# ======================
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        embed = create_embed(
            title="❌ Unknown Command",
            description=f"Type `!help` for available commands",
            color=Color.red()
        )
        await ctx.send(embed=embed)
        
    elif isinstance(error, commands.MissingPermissions):
        embed = create_embed(
            title="❌ Permission Denied",
            description="You don't have permission to use this command.",
            color=Color.red()
        )
        await ctx.send(embed=embed)
        
    elif isinstance(error, commands.BadArgument):
        embed = create_embed(
            title="❌ Invalid Argument",
            description=str(error),
            color=Color.red()
        )
        await ctx.send(embed=embed)
        
    else:
        embed = create_embed(
            title="❌ Unexpected Error",
            description=f"```{str(error)}```",
            color=Color.red()
        )
        await ctx.send(embed=embed)

# ======================
# BOT EXECUTION
# ======================
if __name__ == "__main__":
    TOKEN = os.environ.get("DISCORD_TOKEN")
    if not TOKEN:
        print("❌ ERROR: Missing DISCORD_TOKEN environment variable")
        exit(1)
        
    try:
        bot.run(TOKEN)
    except discord.errors.LoginFailure:
        print("❌ Invalid token - please check your DISCORD_TOKEN")
    finally:
        conn.close()
