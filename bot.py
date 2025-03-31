import discord
from discord.ext import commands
import sqlite3
import ollama
import requests
import pytesseract
from PIL import Image
import io
import speech_recognition as sr
import asyncio
import vosk
import json
import random
import openai
import os
from flask import Flask
import threading

# Flask Setup for Uptime
app = Flask(__name__)

@app.route('/')
def home():
    return "Mathilda is running!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)  # Required for Render

threading.Thread(target=run_flask, daemon=True).start()

# Discord Bot Setup
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
bot.math_answers = {}  # Stores math answers for MathQuest

# SQLite Setup (Stores corrections and leaderboard)
conn = sqlite3.connect("mathilda.db")
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS corrections (wrong TEXT PRIMARY KEY, correct TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS leaderboard (user_id INTEGER PRIMARY KEY, points INTEGER)")
conn.commit()

# Load Vosk Model
model_path = "vosk-model-small-en-us-0.15"
if not os.path.exists(model_path):
    print(f"ERROR: Model path '{model_path}' does not exist.")
else:
    vosk_model = vosk.Model(model_path)

# Math Puzzles for MathQuest
math_puzzles = [
    {"question": "What is 12 × 8?", "answer": "96"},
    {"question": "Solve for x: 2x + 5 = 15", "answer": "5"},
    {"question": "What is the square root of 144?", "answer": "12"},
    {"question": "Find the missing number: 2, 4, 8, 16, __?", "answer": "32"},
    {"question": "What is 3^3?", "answer": "27"},
    {"question": "What is 7 × 6?", "answer": "42"},
    {"question": "Solve for x: x/3 = 7", "answer": "21"},
    {"question": "What is the perimeter of a square with side length 5?", "answer": "20"},
    {"question": "What is the area of a rectangle with length 10 and width 4?", "answer": "40"},
    {"question": "What is 15% of 200?", "answer": "30"},
    {"question": "Solve for x: 3x - 9 = 12", "answer": "7"},
    {"question": "What is the cube root of 27?", "answer": "3"},
    {"question": "What is 9 squared?", "answer": "81"},
    {"question": "Convert 3/4 to a decimal.", "answer": "0.75"},
    {"question": "Find the next number: 1, 1, 2, 3, 5, 8, __?", "answer": "13"},
    {"question": "Solve for x: 4x = 32", "answer": "8"},
    {"question": "What is 100 divided by 4?", "answer": "25"},
    {"question": "What is the median of 3, 5, 7, 9, 11?", "answer": "7"},
    {"question": "What is the sum of the angles in a triangle?", "answer": "180"},
    {"question": "What is 8 factorial (8!)?", "answer": "40320"},
    {"question": "What is the hypotenuse of a right triangle with legs 6 and 8?", "answer": "10"},
    {"question": "What is the value of π (pi) to 2 decimal places?", "answer": "3.14"},
    {"question": "What is the derivative of x²?", "answer": "2x"},
    {"question": "What is the integral of 2x?", "answer": "x² + C"},
    {"question": "Solve: 5 + 3 × 2", "answer": "11"},
    {"question": "Find x: 3(x - 4) = 12", "answer": "8"},
    {"question": "Secret Question! Answer is Skibidi Toilet.", "answer": "Skibidi Toilet"}
]

@bot.event
async def on_ready():
    print(f"🚀 Mathilda is online! Logged in as {bot.user}")

@bot.command()
async def mathquest(ctx):
    user_id = ctx.author.id
    question_data = random.choice(math_puzzles)
    bot.math_answers[user_id] = question_data["answer"]
    await ctx.send(f"❓ **Math Question:** {question_data['question']}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    user_id = message.author.id
    if user_id in bot.math_answers and message.content.strip() == bot.math_answers[user_id]:
        cursor.execute("INSERT INTO leaderboard (user_id, points) VALUES (?, 1) ON CONFLICT(user_id) DO UPDATE SET points = points + 10", (user_id,))
        conn.commit()
        await message.channel.send("✅ Correct! +10 points.")
        del bot.math_answers[user_id]
    await bot.process_commands(message)

@bot.command()
async def mathleaders(ctx):
    cursor.execute("SELECT user_id, points FROM leaderboard ORDER BY points DESC LIMIT 5")
    leaderboard_text = "\n".join(f"**#{i+1}** <@{user_id}> - **{points} points**" for i, (user_id, points) in enumerate(cursor.fetchall()))
    await ctx.send(leaderboard_text or "🏆 No scores yet!")

bot.run(os.getenv("TOKEN"))

=======
import os
import openai
import discord
from discord.ext import commands
import sympy as sp
import asyncio
import sqlite3
import random
from datetime import datetime

TOKEN = os.getenv("DISCORD_TOKEN")

# Enable required intents
intents = discord.Intents.default()
intents.message_content = True  # This must be enabled for commands to work

# Create the bot with intents
bot = commands.Bot(command_prefix="!", intents=intents)

# Event when bot is ready
@bot.event
async def on_ready():
    print(f'✅ Logged in as {bot.user}')

# SQLite database setup for learning corrections
conn = sqlite3.connect("corrections.db")
c = conn.cursor()
c.execute("""
    CREATE TABLE IF NOT EXISTS corrections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        incorrect TEXT,
        correct TEXT
    )
""")
conn.commit()

# Utility function to fetch corrections
def get_correction(query):
    c.execute("SELECT correct FROM corrections WHERE incorrect = ?", (query,))
    row = c.fetchone()
    return row[0] if row else None

openai.api_key = os.getenv("OPENAI_API_KEY")

@bot.command()
async def solve(ctx, *, problem: str):
    try:
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        response = client.chat.completions.create(
            model="gpt-4",  
            messages=[{"role": "user", "content": problem}],
            temperature=0.7
        )

        answer = response.choices[0].message.content
        await ctx.send(f"Solution: {answer}")
    except Exception as e:
        await ctx.send(f"Error: {e}")

@bot.command()
async def factor(ctx, *, expression: str):
    try:
        result = sp.factor(expression)
        await ctx.send(f"Factored form: `{result}`")
    except Exception as e:
        await ctx.send(f"Error: {e}")

@bot.command()
async def simplify(ctx, *, expression: str):
    try:
        result = sp.simplify(expression)
        await ctx.send(f"Simplified: `{result}`")
    except Exception as e:
        await ctx.send(f"Error: {e}")

@bot.command()
async def derive(ctx, *, expression: str):
    try:
        result = sp.diff(expression)
        await ctx.send(f"Derivative: `{result}`")
    except Exception as e:
        await ctx.send(f"Error: {e}")

@bot.command()
async def integrate(ctx, *, expression: str):
    try:
        result = sp.integrate(expression)
        await ctx.send(f"Integral: `{result}`")
    except Exception as e:
        await ctx.send(f"Error: {e}")

@bot.command()
async def convert(ctx, *, query: str):
    correction = get_correction(query)
    if correction:
        await ctx.send(f"Correction: `{correction}`")
    else:
        await ctx.send("No known correction.")

@bot.command()
async def learn(ctx, incorrect: str, correct: str):
    c.execute("INSERT INTO corrections (incorrect, correct) VALUES (?, ?)", (incorrect, correct))
    conn.commit()
    await ctx.send("Correction learned!")

@bot.command()
async def unlearn(ctx, incorrect: str):
    c.execute("DELETE FROM corrections WHERE incorrect = ?", (incorrect,))
    conn.commit()
    await ctx.send("Correction removed!")

@bot.command()
async def corrections(ctx):
    c.execute("SELECT incorrect, correct FROM corrections")
    rows = c.fetchall()
    if rows:
        corrections_list = "\n".join([f"{row[0]} -> {row[1]}" for row in rows])
        await ctx.send(f"Corrections:\n```{corrections_list}```")
    else:
        await ctx.send("No corrections stored.")

# General Commands
@bot.command()
async def ping(ctx):
    await ctx.send(f"Pong! {round(bot.latency * 1000)}ms")

@bot.command()
async def commands(ctx):
    command_list = "\n".join([
        "!solve", "!factor", "!simplify", "!derive", "!integrate",
        "!convert", "!learn", "!unlearn", "!corrections", "!ping", "!commands",
        "!info", "!clear", "!shutdown", "!mathquest", "!mathleaders"
    ])
    await ctx.send(f"Available Commands:\n```{command_list}```")

@bot.command()
async def info(ctx):
    await ctx.send("Mathilda - The Math Solving Bot! Created to assist with various math problems.")

@bot.command()
async def clear(ctx, amount: int = 5):
    await ctx.channel.purge(limit=amount)
    await ctx.send(f"Cleared {amount} messages.")

@bot.command()
async def shutdown(ctx):
    await ctx.send("Shutting down...")
    await bot.close()

# MathQuest Feature
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
    "What is 2 + 2 × 3?": "8"
}  # ✅ No trailing comma at the end


@bot.command()
async def mathquest(ctx):
    question, answer = random.choice(list(math_questions.items()))
    embed = discord.Embed(title="Math Quest!", description=question, color=discord.Color.blue())
    await ctx.send(embed=embed)

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        response = await bot.wait_for("message", timeout=15.0, check=check)
        if response.content.strip() == answer:
            await ctx.send("Correct! 🎉")
        else:
            await ctx.send(f"Incorrect. The answer was `{answer}`.")
    except asyncio.TimeoutError:
        await ctx.send(f"Time's up! The answer was `{answer}`.")

@bot.command()
async def mathleaders(ctx):
    await ctx.send("Leaderboard feature coming soon!")

# Load bot token from environment
TOKEN = os.getenv("DISCORD_TOKEN")

if TOKEN is None or TOKEN == "TOKEN":
    raise ValueError("DISCORD_TOKEN environment variable is not set or incorrect!")

print(f"Loaded Token: {TOKEN[:5]}... (hidden for security)")  # Debugging line

bot.run(TOKEN)

