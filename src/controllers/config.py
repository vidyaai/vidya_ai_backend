import os
import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
import boto3
from botocore.client import Config as BotoConfig

try:
    from deepgram import DeepgramClient  # type: ignore
except Exception:  # pragma: no cover - optional dependency at import time
    DeepgramClient = None  # type: ignore


# Basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Paths
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

# Use OS temp directory for all runtime artifacts
TMP_ROOT = os.path.join(tempfile.gettempdir(), "vidyai_backend")

video_path = os.path.join(TMP_ROOT, "videos")
frames_path = os.path.join(TMP_ROOT, "frames")
output_path = os.path.join(TMP_ROOT, "output")

for path in [video_path, frames_path, output_path]:
    os.makedirs(path, exist_ok=True)


# Thread executors
download_executor = ThreadPoolExecutor(max_workers=3)
formatting_executor = ThreadPoolExecutor(max_workers=3)
upload_executor = ThreadPoolExecutor(max_workers=3)


# Env and S3
load_dotenv()

AWS_S3_BUCKET = os.environ.get("AWS_S3_BUCKET", "")
AWS_S3_REGION = os.environ.get("AWS_S3_REGION", "us-east-1")
AWS_S3_ENDPOINT = os.environ.get("AWS_S3_ENDPOINT", "")
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")


def create_s3_client():
    session = boto3.session.Session()
    if AWS_S3_ENDPOINT:
        return session.client(
            "s3",
            region_name=AWS_S3_REGION,
            endpoint_url=AWS_S3_ENDPOINT,
            config=BotoConfig(s3={"addressing_style": "virtual"}),
        )
    return session.client("s3", region_name=AWS_S3_REGION)


s3_client = None
try:
    if AWS_S3_BUCKET:
        s3_client = create_s3_client()
        logger.info(f"S3 client initialized for bucket: {AWS_S3_BUCKET}")
    else:
        logger.warning("AWS_S3_BUCKET not set. S3 features disabled.")
except Exception as e:
    logger.error(f"Failed to initialize S3 client: {e}")
    s3_client = None

# Deepgram client
deepgram_client = None
try:
    if DEEPGRAM_API_KEY and DeepgramClient is not None:
        deepgram_client = DeepgramClient(DEEPGRAM_API_KEY)
        logger.info("Deepgram client initialized.")
    elif not DEEPGRAM_API_KEY:
        logger.warning("DEEPGRAM_API_KEY not set. Deepgram features disabled.")
    else:
        logger.warning("Deepgram SDK not available. Install deepgram-sdk to enable.")
except Exception as e:
    logger.error(f"Failed to initialize Deepgram client: {e}")
    deepgram_client = None
