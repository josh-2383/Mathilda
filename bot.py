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
import pytesseract
import cv2
import numpy as np
from PIL import Image
import io
import requests

def extract_text_from_image(image_url):
    """Extract text from an image URL using OCR"""
    try:
        # Download the image
        response = requests.get(image_url)
        img = Image.open(io.BytesIO(response.content))
        
        # Convert to OpenCV format (for preprocessing)
        img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        
        # Preprocess image (grayscale + thresholding)
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
        
        # Run OCR
        custom_config = r'--oem 3 --psm 6 -l eng+equ'  # Optimize for math equations
        text = pytesseract.image_to_string(thresh, config=custom_config)
        
        return text.strip()
    except Exception as e:
        return f"❌ OCR Error: {str(e)}"

# Flask Setup for Uptime
app = Flask(__name__)

@app.route('/')
def home():
    return "Mathilda is running!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

threading.Thread(target=run_flask, daemon=True).start()

# Discord Bot Setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Initialize bot attributes
bot.math_answers = {}  # For streak questions
bot.question_streaks = {}  # For tracking streaks
bot.conversation_states = {}  # For conversational math help
bot.math_help_triggers = ["help with math", "math question", "solve this", "how to calculate"]

# SQLite Database Setup
conn = sqlite3.connect("mathilda.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS corrections (wrong TEXT PRIMARY KEY, correct TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS leaderboard (user_id INTEGER PRIMARY KEY, points INTEGER)")
conn.commit()

# Math Questions Database
math_questions = {
    "What is 2 + 2?": "4",
    "Solve for x: 3x = 9": "3",
    "What is the square root of 16?": "4",
    "What is 5 + 3?": "8",
    "What is 12 - 4?": "8",
    "What is 7 × 6?": "42",
    "What is 81 ÷ 9?": "9",
    "What is the square root of 49?": "7",
    "What is 2^3?": "8",
    "What is 15% of 200?": "30",
    "What is the area of a rectangle with length 5 and width 3?": "15",
    "What is 144 ÷ 12?": "12",
    "What is 11 × 11?": "121",
    "What is 0.5 + 0.25?": "0.75",
    "What is 9 squared?": "81",
    "What is 1000 ÷ 10?": "100",
    "What is 3! (3 factorial)?": "6",
    "What is the sum of the angles in a triangle?": "180 degrees",
    "What is 10% of 90?": "9",
    "What is the perimeter of a square with side length 4?": "16",
    "What is 1/4 + 1/2?": "3/4",
    "What is the cube root of 27?": "3",
    "What is 2 + 2 × 3?": "8",
    "You found secret question!Answer is Skibidi Sigma Rizzler": "Skibidi Sigma Rizzler"
}

# Helper function for creating embeds
def create_embed(title=None, description=None, color=Color.blue(), fields=None, footer=None):
    embed = Embed(title=title, description=description, color=color)
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    if footer:
        embed.set_footer(text=footer)
    return embed

async def solve_math_question(message):
    """Handles conversational math problem solving"""
    try:
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{
                "role": "system",
                "content": "You are a helpful math tutor. Explain solutions step-by-step."
            }, {
                "role": "user",
                "content": message.content
            }],
            temperature=0.5
        )

        answer = response.choices[0].message.content

        embed = create_embed(
            title=f"Solution for: {message.content[:100]}",
            description=answer,
            color=Color.blue()
        )
        await message.channel.send(embed=embed)

    except Exception as e:
        error_embed = create_embed(
            title="❌ Error",
            description=f"Couldn't solve: {str(e)}",
            color=Color.red()
        )
        await message.channel.send(embed=error_embed)

# Bot Ready Event
@bot.event
async def on_ready():
    print(f"🚀 Mathilda is online! Logged in as {bot.user}")

@bot.command()
async def ocr(ctx, image_url: str = None):
    """Extract and solve math problems from images"""
    if not image_url and not ctx.message.attachments:
        await ctx.send("🚨 Please attach an image or provide a URL!")
        return
    
    # Get image URL from attachment (if no URL provided)
    if not image_url:
        image_url = ctx.message.attachments[0].url
    
    # Show "processing" message
    processing_msg = await ctx.send("🔍 Processing image...")
    
    # Extract text
    extracted_text = extract_text_from_image(image_url)
    
    if extracted_text.startswith("❌"):
        await processing_msg.edit(content=extracted_text)
        return
    
    # Send extracted text (optional)
    await processing_msg.edit(content=f"📝 Extracted text:\n```{extracted_text}```")
    
    # Auto-solve if it looks like math
    if any(c in extracted_text for c in ['+', '-', '=', 'x', '÷', '^']):
        await solve(ctx, problem=extracted_text)  # Reuse your existing !solve command
        

@bot.command()
async def mathquest(ctx):
    """Start a math question streak challenge"""
    try:
        user_id = ctx.author.id
        question, correct_answer = random.choice(list(math_questions.items()))

        bot.math_answers[user_id] = {
            "answer": correct_answer,
            "question": question,
            "streak": bot.question_streaks.get(user_id, 0)
        }

        embed = create_embed(
            title=f"🧮 Math Challenge (Streak: {bot.question_streaks.get(user_id, 0)})",
            description=question,
            color=Color.green(),
            footer="Type your answer in chat!"
        )
        await ctx.send(embed=embed)
    except Exception as e:
        error_embed = create_embed(
            title="❌ Error",
            description=f"An error occurred: {str(e)}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

async def on_message(message):
    if message.author.bot:
        return await bot.process_commands(message)
    
    # Check for image attachments
    if message.attachments and any(att.filename.lower().endswith(('.png', '.jpg', '.jpeg')) for att in message.attachments):
        ctx = await bot.get_context(message)
        await ocr(ctx)  # Trigger OCR command automatically
        return
    
    # Your existing on_message logic here...
    await bot.process_commands(message)

    user_id = message.author.id
    content = message.content.lower().strip()

    # Handle Math Quest Streak System
    if user_id in bot.math_answers:
        question_data = bot.math_answers[user_id]
        correct_answer = question_data["answer"]
        current_streak = question_data["streak"]

        if content == correct_answer.lower():
            current_streak += 1
            bot.question_streaks[user_id] = current_streak
            points = 10 + (current_streak * 2)

            cursor.execute("""
                INSERT INTO leaderboard (user_id, points)
                VALUES (?, ?)
                ON CONFLICT(user_id)
                DO UPDATE SET points = points + ?
                """, (user_id, points, points))
            conn.commit()

            new_question, new_answer = random.choice(list(math_questions.items()))
            bot.math_answers[user_id] = {
                "answer": new_answer,
                "question": new_question,
                "streak": current_streak
            }

            embed = create_embed(
                title=f"✅ Correct! (Streak: {current_streak})",
                description=f"You earned {points} points!\n\nNext question: {new_question}",
                color=Color.green()
            )
            await message.channel.send(embed=embed)
        else:
            lost_points = min(5, current_streak * 5)
            cursor.execute("""
                INSERT INTO leaderboard (user_id, points)
                VALUES (?, ?)
                ON CONFLICT(user_id)
                DO UPDATE SET points = points - ?
                """, (user_id, -lost_points, lost_points))
            conn.commit()

            embed = create_embed(
                title="❌ Incorrect!",
                description=f"Streak ended! Correct answer was: `{correct_answer}`\nLost {lost_points} points.",
                color=Color.red(),
                fields=[("Continue", "Type `!mathquest` to restart", False)]
            )
            await message.channel.send(embed=embed)
            del bot.math_answers[user_id]
            if user_id in bot.question_streaks:
                del bot.question_streaks[user_id]
        return

    # Handle Conversational Math Help
    if user_id in bot.conversation_states and bot.conversation_states[user_id] == "math_help":
        if any(word in content for word in ["cancel", "stop", "done"]):
            del bot.conversation_states[user_id]
            await message.channel.send("Exited math help mode. Your streaks are preserved!")
            return
        else:
            await solve_math_question(message)
            return

    # Detect Math Help Requests
    if any(trigger in content for trigger in bot.math_help_triggers):
        bot.conversation_states[user_id] = "math_help"
        embed = create_embed(
            title="🧮 Math Help Activated",
            description="Now in math help mode! Just type problems like:\n- `2+2`\n- `Solve 3x=9`\n- `Factor x²-4`\n\nSay 'cancel' when done.",
            color=Color.blue()
        )
        await message.channel.send(embed=embed)
        return

    await bot.process_commands(message)

@bot.command()
async def mathleaders(ctx):
    """Show the leaderboard"""
    cursor.execute("SELECT user_id, points FROM leaderboard ORDER BY points DESC LIMIT 10")
    leaderboard = cursor.fetchall()
    
    if leaderboard:
        leaderboard_text = "\n".join(
            f"**#{i+1}** <@{user_id}> - **{points} points**" 
            for i, (user_id, points) in enumerate(leaderboard)
        )
        embed = create_embed(
            title="🏆 Math Leaderboard (Top 10)",
            description=leaderboard_text,
            color=Color.gold()
        )
    else:
        embed = create_embed(
            title="🏆 Math Leaderboard",
            description="No scores yet! Be the first to answer a math question!",
            color=Color.gold()
        )
    await ctx.send(embed=embed)

@bot.command()
async def solve(ctx, *, problem: str):
    """Solve any math problem"""
    try:
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{
                "role": "user",
                "content": f"Solve this math problem step by step: {problem}"
            }],
            temperature=0.7
        )

        answer = response.choices[0].message.content

        embed = create_embed(
            title="🧠 Solution",
            description=f"**Problem:** {problem}\n\n**Solution:** {answer}",
            color=Color.blue()
        )
        await ctx.send(embed=embed)
    except Exception as e:
        error_embed = create_embed(
            title="❌ Error",
            description=f"Error solving problem: {e}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

@bot.command()
async def factor(ctx, *, expression: str):
    """Factor a mathematical expression"""
    try:
        result = sp.factor(expression)
        embed = create_embed(
            title="🔢 Factored Expression",
            description=f"**Original:** {expression}\n**Factored:** `{result}`",
            color=Color.blue()
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
            color=Color.blue()
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
    """Calculate derivative"""
    try:
        result = sp.diff(expression)
        embed = create_embed(
            title="📈 Derivative",
            description=f"**Function:** {expression}\n**Derivative:** `{result}`",
            color=Color.blue()
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
    """Calculate integral"""
    try:
        result = sp.integrate(expression)
        embed = create_embed(
            title="∫ Integral",
            description=f"**Function:** {expression}\n**Integral:** `{result}`",
            color=Color.blue()
        )
        await ctx.send(embed=embed)
    except Exception as e:
        error_embed = create_embed(
            title="❌ Error",
            description=f"Error finding integral: {e}",
            color=Color.red()
        )
        await ctx.send(embed=error_embed)

# Correction System Commands
@bot.command()
async def convert(ctx, *, query: str):
    """Get a correction from database"""
    cursor.execute("SELECT correct FROM corrections WHERE wrong = ?", (query,))
    row = cursor.fetchone()
    if row:
        embed = create_embed(
            title="🔄 Correction",
            description=f"**You asked:** {query}\n**Correction:** {row[0]}",
            color=Color.green()
        )
    else:
        embed = create_embed(
            title="❓ No Correction Found",
            description=f"No known correction for: {query}",
            color=Color.orange()
        )
    await ctx.send(embed=embed)

@bot.command()
async def learn(ctx, incorrect: str, correct: str):
    """Learn a new correction"""
    cursor.execute("INSERT INTO corrections (wrong, correct) VALUES (?, ?)", (incorrect, correct))
    conn.commit()
    embed = create_embed(
        title="📚 Learned Correction",
        description=f"Added to database:\n**Incorrect:** {incorrect}\n**Correct:** {correct}",
        color=Color.green()
    )
    await ctx.send(embed=embed)

@bot.command()
async def unlearn(ctx, incorrect: str):
    """Remove a correction"""
    cursor.execute("DELETE FROM corrections WHERE wrong = ?", (incorrect,))
    conn.commit()
    embed = create_embed(
        title="🗑️ Removed Correction",
        description=f"Removed correction for: {incorrect}",
        color=Color.green()
    )
    await ctx.send(embed=embed)

@bot.command()
async def corrections(ctx):
    """List all corrections"""
    cursor.execute("SELECT wrong, correct FROM corrections")
    rows = cursor.fetchall()
    if rows:
        corrections_list = "\n".join([f"• {row[0]} → {row[1]}" for row in rows])
        embed = create_embed(
            title="📖 Correction Database",
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

# Utility Commands
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
    """Show bot information"""
    embed = create_embed(
        title="ℹ️ Mathilda - The Math Bot",
        description="A helpful bot for solving math problems and learning mathematics!",
        color=Color.blue(),
        fields=[
            ("Features", "• Math problem solving\n• Math challenges\n• Corrections database\n• Leaderboard", False),
            ("Commands", "`!mathquest`, `!solve`, `!factor`, `!simplify`, `!derive`, `!integrate`", False),
            ("Corrections", "`!convert`, `!learn`, `!unlearn`, `!corrections`", False),
            ("Other", "`!ping`, `!info`, `!mathleaders`", False)
        ]
    )
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    """Clear messages (requires Manage Messages)"""
    await ctx.channel.purge(limit=amount + 1)  # +1 to account for the command message
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
    """Shutdown the bot (Owner only)"""
    embed = create_embed(
        title="🛑 Shutting Down",
        description="Mathilda is powering off...",
        color=Color.red()
    )
    await ctx.send(embed=embed)
    await bot.close()

# Error Handling
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        embed = create_embed(
            title="❌ Unknown Command",
            description=f"Command not found. Type `!info` for help.",
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
    else:
        embed = create_embed(
            title="❌ Unexpected Error",
            description=f"An error occurred: {str(error)}",
            color=Color.red()
        )
        await ctx.send(embed=embed)

# Run the bot
if __name__ == "__main__":
    TOKEN = os.environ.get("DISCORD_TOKEN")
    if not TOKEN:
        print("❌ ERROR: Missing DISCORD_TOKEN environment variable")
        print("Please set it in Render.com environment settings")
        exit(1)
    
    try:
        bot.run(TOKEN)
    except discord.errors.LoginFailure:
        print("❌ Invalid token - please regenerate in Discord Developer Portal")
        exit(1)
