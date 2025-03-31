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
import os
import discord
import os
import os
import vosk
import os
import os
import discord
from flask import Flask
import threading

app = Flask(__name__)

@app.route('/')
def home():
    return "Mathilda is running!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)  # Render requires this

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()  # Start Flask in the background

    import discord
    import os

    print("✅ Bot is starting...")

    TOKEN = os.getenv("TOKEN")
    if not TOKEN:
        print("❌ ERROR: Discord bot token is missing!")
        exit(1)

    print("✅ Token found, proceeding...")

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"🚀 Mathilda is online! Logged in as {client.user}")

    client.run(TOKEN)
    
print("✅ Bot is starting...")  # Debug log

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    print("❌ ERROR: Discord bot token is missing!")
    exit(1)

print("✅ Token found, proceeding...")  # Debug log

intents = discord.Intents.default()  
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"🚀 Mathilda is online! Logged in as {client.user}")

client.run(TOKEN)  # <== This runs the bot

print("✅ Bot is starting...")  # Debug log

# Check environment variables
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    print("❌ ERROR: Discord bot token is missing!")
    exit(1)

print("✅ Token found, proceeding...")  # Debug log

from flask import Flask

print("Mathilda is starting...")

app = Flask(__name__)

@app.route("/")
def home():
    return "Mathilda bot is running!"

# Get the port from the environment, default to 8080
port = int(os.environ.get("PORT", 8080))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=port)
    
model_path = os.path.join(os.getcwd(), "vosk-model-small-en-us-0.15")
if not os.path.exists(model_path):
    print(f"ERROR: Model path '{model_path}' does not exist. Check if it's uploaded correctly.")
else:
    print("Model folder found. Proceeding with Vosk initialization.")

vosk_model = vosk.Model(model_path)

model_path = "/home/runner/workspace/vosk-model-small-en-us-0.15"

if not os.path.exists(model_path):
    print(f"ERROR: Model path '{model_path}' does not exist. Check if it's uploaded correctly.")
else:
    print("Model folder found. Proceeding with Vosk initialization.")
    
token = os.getenv("TOKEN")  # Ensure this is correct
if token is None:
    print("Error: TOKEN environment variable is not set")
    exit(1)

intents = discord.Intents.default()
intents.typing = False  
intents.presences = False  

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'Logged in as {client.user}')

client.run(token)
from flask import Flask  
from threading import Thread  

app = Flask(__name__)  

@app.route("/")  
def home():  
    return "I am alive!"  

def run():  
    app.run(host="0.0.0.0", port=8080)  

def keep_alive():  
    t = Thread(target=run)  
    t.start()  
    
async def solve_with_chatgpt(expression):
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))  # Load API key securely

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",  # Change if using another model
            messages=[{"role": "user", "content": f"Solve: {expression}"}]
        )

        return response.choices[0].message.content.strip()

from flask import Flask
import threading

app = Flask(__name__)

@app.route("/")
def home():
    return "I'm alive!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

# Run Flask in a separate thread
threading.Thread(target=run_flask, daemon=True).start()

        
# Discord Bot Setup
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
bot.math_answers = {}  # Dictionary to store users' answers

# SQLite Setup (Stores corrections)
conn = sqlite3.connect("learnings.db")
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS corrections (wrong TEXT PRIMARY KEY, correct TEXT)")
conn.commit()

# SQLite Leaderboard
conn_leaderboard = sqlite3.connect("mathquest.db")
cursor_leaderboard = conn_leaderboard.cursor()
cursor_leaderboard.execute("CREATE TABLE IF NOT EXISTS leaderboard (user_id INTEGER PRIMARY KEY, points INTEGER)")
conn_leaderboard.commit()

# Load Vosk model
vosk_model = vosk.Model("/home/runner/workspace/vosk-model-small-en-us-0.15")

# List of valid bot commands
valid_commands = [
    "solve", "solveollama", "scanandsolve", "factor", "simplify", "derive", "integrate", "convert",
    "learn", "unlearn", "corrections", "ping", "commands", "info", "clear", "shutdown", "mathquest", "mathleaders"
]

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
    {"question": "You Have found the super secret Question ,Answer is Skibidi Toilet.", "answer": "Skibidi Toilet"}
]
bot.math_answers = {}  # Dictionary to store math answers


async def ask_question(ctx, user_id):
    """Asks a random math question and handles the response."""
    question_data = random.choice(math_puzzles)
    question, answer = question_data["question"], question_data["answer"]

    await ctx.send(f"❓ **Math Question:** {question}\n⏳ You have 15 seconds to answer!")

    def check(m):
        return m.author.id == user_id and m.channel == ctx.channel

    try:
        msg = await bot.wait_for("message", timeout=15.0, check=check)
        if msg.content.strip() == answer:
            cursor_leaderboard.execute(
                "INSERT INTO leaderboard (user_id, points) VALUES (?, 1) ON CONFLICT(user_id) DO UPDATE SET points = points + 1",
                (user_id,))
            conn_leaderboard.commit()
            await ctx.send(f"✅ Correct! +1 point.")
        else:
            await ctx.send(f"❌ Incorrect. The correct answer was `{answer}`.")
    except asyncio.TimeoutError:
        await ctx.send(f"⌛ Time's up! The correct answer was `{answer}`.")

@bot.command()
async def mathquest(ctx):
    """Asks a random math question and stores the answer for checking."""
    user_id = ctx.author.id

    # Select a random math question
    question_data = random.choice(math_puzzles)
    question, answer = question_data["question"], int(question_data["answer"])  # Ensure answer is an integer

    # Store the correct answer for checking later
    bot.math_answers[user_id] = {"answer": answer, "points_correct": 10, "points_wrong": -5}

    # Create an embed message
    embed = discord.Embed(
        title="🧠 Math Quest Challenge!",
        description=f"❓ **Question:** {question}\n\n⏳ *You have 15 seconds to answer!*",
        color=discord.Color.blue()
    )
    embed.set_footer(text="Type your answer in the chat!")

    await ctx.send(embed=embed)

@bot.event
async def on_message(message):
    if message.author.bot:
        return  # Ignore messages from bots

    user_id = message.author.id
    if user_id in bot.math_answers:
        try:
            user_answer = int(message.content.strip())  # Convert user input to an integer
            correct_answer = bot.math_answers[user_id]["answer"]
            points_correct = bot.math_answers[user_id]["points_correct"]
            points_wrong = bot.math_answers[user_id]["points_wrong"]

            if user_answer == correct_answer:
                # Award points for correct answer
                cursor_leaderboard.execute(
                    "INSERT INTO leaderboard (user_id, points) VALUES (?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET points = points + ?",
                    (user_id, points_correct, points_correct)
                )
                conn_leaderboard.commit()

                embed = discord.Embed(
                    title="✅ Correct Answer!",
                    description=f"🎉You earned **{points_correct}** points!",
                    color=discord.Color.green()
                )
                embed.set_footer(text="Great job! Keep going!")
            else:
                # Deduct points for incorrect answer
                cursor_leaderboard.execute(
                    "INSERT INTO leaderboard (user_id, points) VALUES (?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET points = points - ?",
                    (user_id, points_wrong, abs(points_wrong))
                )
                conn_leaderboard.commit()

                embed = discord.Embed(
                    title="❌ Wrong Answer!",
                    description=f"The correct answer was `{correct_answer}`.\nYou lost **{abs(points_wrong)} points**.",
                    color=discord.Color.red()
                )
                embed.set_footer(text="Don't give up! Try again!")

            await message.channel.send(embed=embed)
            del bot.math_answers[user_id]  # Remove the question after answering

        except ValueError:
            pass  # Ignore non-integer messages

    await bot.process_commands(message)  # Ensure commands still work



@bot.command()
async def mathleaders(ctx):
    cursor_leaderboard.execute("SELECT user_id, points FROM leaderboard ORDER BY points DESC LIMIT 5")
    leaderboard_text = "\n".join(f"**#{i + 1}** <@{user_id}> - **{points} points**" for i, (user_id, points) in
                                 enumerate(cursor_leaderboard.fetchall()))
    await ctx.send(leaderboard_text or "🏆 No scores yet!")


@bot.command()
async def solve(ctx, *, expression: str):
    try:
        # Replace ^ with ** to handle exponents correctly
        expression = expression.replace("^", "**")

        # Ensure multiplication is explicit (e.g., "2(3+4)" -> "2*(3+4)")
        expression = expression.replace(")(", ")*(")  # Handle cases like (2+3)(4+5)
        expression = expression.replace(") ", ")*")  # Handle cases like (2+3) 4
        expression = expression.replace(" (", "*(")  # Handle cases like 4 (2+3)

        # Evaluate the expression safely
        result = eval(expression, {"__builtins__": None}, {})

        await ctx.send(f"🧮 **Solution:** `{expression} = {result}`")
    except Exception as e:
       await ctx.send(f"error:{str(e)}")    


@bot.command(name="solveollama")  # Ensures the command is recognized
async def solveollama(ctx, *, expression):
            result = await solve_with_chatgpt(expression)
            await ctx.send(f"🧮 Solution: {result}")


@bot.command()
async def convert(ctx, *, expression: str):
    result = await solve_with_ollama(f"Convert: {expression}")
    await ctx.send(f"🔄 **Conversion Result:** {result}")


@bot.command()
async def derive(ctx, *, expression: str):
    result = await solve_with_ollama(f"Find the derivative of: {expression}")
    await ctx.send(f"📈 **Derivative:** {result}")

async def solve_with_ollama(expression):
    """Sends a math problem to Ollama's Qwen-7B model and returns the solution."""
    response = ollama.chat(model="qwen:7b", messages=[{"role": "user", "content": f"Solve: {expression}"}])
    return response['message']['content'] if 'message' in response else "Error: No response from Ollama."


@bot.command()
async def integrate(ctx, *, expression: str):
    result = await solve_with_ollama(f"Find the integral of: {expression}")
    await ctx.send(f"∫ **Integral:** {result}")


@bot.command()
async def scanandsolve(ctx):
    if not ctx.message.attachments:
        await ctx.send("📷 Attach an image with a math problem.")
        return
    response = requests.get(ctx.message.attachments[0].url)
    img = Image.open(io.BytesIO(response.content))
    extracted_text = pytesseract.image_to_string(img)
    result = await solve_with_chatgpt(extracted_text) if extracted_text else "No text detected."
    await ctx.send(f"📖 **Extracted Text:** `{extracted_text}`\n🧮 **Solution:** {result}")


@bot.command()
async def commands(ctx):
    command_list = "\n".join([f"!{cmd}" for cmd in valid_commands])
    await ctx.send(f"📜 **Available Commands:**\n{command_list}")
    
@bot.command()
async def clear(ctx, amount: int = 5):
    """Deletes a specified number of messages (default: 5)."""
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧹 Cleared {amount} messages!", delete_after=3)

@bot.command()
async def info(ctx):
    """Provides information about Mathilda."""
    await ctx.send("🤖 **Mathilda - The Math Discord Bot**\nSolves math problems, recognizes text from images, and learns from mistakes!")

@bot.command()
async def shutdown(ctx):
    """Shuts down the bot (Requires owner permission)."""
    if ctx.author.id == YOUR_DISCORD_ID:  # Replace with your Discord ID
        await ctx.send("🔴 Shutting down...")
        await bot.close()
    else:
        await ctx.send("❌ You don't have permission to shut me down!")

@bot.command()
async def ping(ctx):
    """Shows bot latency."""
    latency = round(bot.latency * 1000)  # Convert to milliseconds
    await ctx.send(f"🏓 Pong! `{latency}ms`")

@bot.command()
async def simplify(ctx, *, expression: str):
    """Simplifies a mathematical expression."""
    try:
        import sympy
        simplified_expr = sympy.simplify(expression)
        await ctx.send(f"🧮 **Simplified Expression:** `{simplified_expr}`")
    except Exception as e:
        await ctx.send(f"⚠️ Error: {str(e)}")

@bot.command()
async def factor(ctx, *, expression: str):
    """Factors a mathematical expression."""
    try:
        import sympy
        factored_expr = sympy.factor(expression)
        await ctx.send(f"🧮 **Factored Expression:** `{factored_expr}`")
    except Exception as e:
        await ctx.send(f"⚠️ Error: {str(e)}")


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")



bot.run(os.getenv("TOKEN"))
