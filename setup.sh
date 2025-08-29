echo "Setting up the backend..."
echo "Assuming you have python3.13 installed"

python3.13 -m venv vai_venv
.\vai_venv\Scripts\activate
pip install -r requirements.txt

echo "Backend setup complete"

echo "Creating .env file"
touch .env
echo "OPENAI_API_KEY=" >> .env
echo "AWS_S3_BUCKET=" >> .env
echo "AWS_S3_REGION=" >> .env
echo "AWS_ACCESS_KEY_ID=" >> .env
echo "AWS_SECRET_ACCESS_KEY=" >> .env
echo "FIREBASE_CONFIG=" >> .env
echo "DEEPGRAM_API_KEY=" >> .env
echo "Update the .env file with your credentials"

echo "To start the backend, run: python src/main.py"
echo "To stop the backend, press Ctrl+C"
echo "To deactivate the virtual environment, run: deactivate"
echo "To activate the virtual environment, run: source vai_venv/Scripts/activate"
echo "To deactivate the virtual environment, run: deactivate"
