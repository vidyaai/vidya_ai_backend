# Configuration & API keys
import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")

# Model Configuration
MODEL_NAME = "gpt-4o-mini"  # or "gpt-4" for better quality
TEMPERATURE = 0.7

# Deepgram Configuration
DEEPGRAM_MODEL = "nova-2"  # Latest model
DEEPGRAM_LANGUAGE = "en"
DEEPGRAM_SMART_FORMAT = True
DEEPGRAM_PUNCTUATE = True
DEEPGRAM_PARAGRAPHS = True

# OpenAI Configuration for transcript cleanup
OPENAI_MODEL = "gpt-4o"  # for transcript cleaning
OPENAI_TEMPERATURE = 0.3

# Directory Configuration
INPUT_DIR = "input"
OUTPUT_DIR = "output"
TEMP_DIR = "temp"

# Validate required keys
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found in environment variables")

# Tavily key is optional - web search will be skipped if not available
if not TAVILY_API_KEY:
    print(
        "⚠️  Warning: TAVILY_API_KEY not found - web search augmentation will not be available"
    )

# Deepgram key is optional - only required if using video transcription
if not DEEPGRAM_API_KEY:
    print(
        "⚠️  Warning: DEEPGRAM_API_KEY not found - video transcription will not be available"
    )
