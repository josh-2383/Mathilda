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

