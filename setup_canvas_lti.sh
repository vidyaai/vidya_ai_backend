#!/bin/bash

# Canvas LTI Integration Setup Script
# This script sets up the Canvas LTI integration for Vidya AI

echo "🎓 Vidya AI Canvas LTI Integration Setup"
echo "========================================"
echo ""

# Check if running from backend directory
if [ ! -f "requirements.txt" ]; then
    echo "❌ Error: Please run this script from the vidya_ai_backend directory"
    exit 1
fi

# Step 1: Check if RSA keys exist
echo "📋 Step 1: Checking RSA keys..."
if [ -f "private.key" ] && [ -f "public.key" ]; then
    echo "✅ RSA keys already exist"
else
    echo "🔑 Generating RSA key pair..."
    openssl genrsa -out private.key 2048
    openssl rsa -in private.key -pubout -out public.key
    echo "✅ RSA keys generated"
fi
echo ""

# Step 2: Check Python dependencies
echo "📋 Step 2: Checking Python dependencies..."
if python -c "import pylti1p3" 2>/dev/null; then
    echo "✅ pylti1p3 already installed"
else
    echo "📦 Installing Python dependencies..."
    pip install pylti1p3==3.2.0 PyJWT==2.10.1 cryptography==44.0.0 canvasapi==3.3.0
    echo "✅ Dependencies installed"
fi
echo ""

# Step 3: Check LTI config files
echo "📋 Step 3: Checking LTI configuration files..."
if [ ! -f "lti_config.development.json" ]; then
    echo "❌ lti_config.development.json not found"
    echo "   This file should already exist. If not, create it manually."
else
    echo "✅ lti_config.development.json exists"
fi

if [ ! -f "lti_config.production.json" ]; then
    echo "❌ lti_config.production.json not found"
    echo "   This file should already exist. If not, create it manually."
else
    echo "✅ lti_config.production.json exists"
fi
echo ""

# Step 4: Check .gitignore
echo "📋 Step 4: Checking .gitignore..."
if grep -q "private.key" .gitignore; then
    echo "✅ private.key is in .gitignore"
else
    echo "⚠️  Warning: private.key not in .gitignore"
    echo "   Add 'private.key' to .gitignore manually"
fi
echo ""

# Step 5: Check database migration
echo "📋 Step 5: Database migration status..."
if [ -d "alembic/versions" ]; then
    echo "✅ Alembic configured"
    echo "   Run: alembic revision --autogenerate -m 'Add CanvasLTISession'"
    echo "   Then: alembic upgrade head"
else
    echo "❌ Alembic not configured"
fi
echo ""

# Step 6: Environment variables
echo "📋 Step 6: Checking environment variables..."
if [ -f ".env" ]; then
    echo "✅ .env file exists"
    
    # Check required variables
    if grep -q "API_BASE_URL" .env; then
        echo "✅ API_BASE_URL is set"
    else
        echo "⚠️  API_BASE_URL not found in .env"
    fi
    
    if grep -q "FRONTEND_URL" .env; then
        echo "✅ FRONTEND_URL is set"
    else
        echo "⚠️  FRONTEND_URL not found in .env"
    fi
else
    echo "❌ .env file not found"
    echo "   Create .env file with required variables"
fi
echo ""

# Step 7: Test endpoints
echo "📋 Step 7: Testing LTI endpoints (requires server running)..."
echo "   To test endpoints, start your server and run:"
echo "   curl http://localhost:8000/lti/config.xml"
echo "   curl http://localhost:8000/lti/jwks"
echo ""

# Step 8: ngrok setup for development
echo "📋 Step 8: ngrok setup (for development testing)..."
if command -v ngrok &> /dev/null; then
    echo "✅ ngrok is installed"
    echo "   To expose your local server: ngrok http 8000"
else
    echo "⚠️  ngrok not found"
    echo "   Install: brew install ngrok (macOS) or download from ngrok.com"
fi
echo ""

# Summary
echo "========================================"
echo "✅ Setup Complete!"
echo ""
echo "📚 Next Steps:"
echo "1. Configure Canvas Developer Key:"
echo "   - Go to Canvas Admin → Developer Keys"
echo "   - Create new LTI Key"
echo "   - Get Client ID and Deployment ID"
echo ""
echo "2. Update lti_config.development.json:"
echo "   - Add Client ID and Deployment ID"
echo "   - Update Canvas instance URL"
echo ""
echo "3. Start servers:"
echo "   - Backend: python src/main.py"
echo "   - Frontend: cd ../vidya_ai_frontend && yarn dev"
echo "   - ngrok: ngrok http 8000 (for development)"
echo ""
echo "4. Install app in Canvas course:"
echo "   - Course Settings → Apps → + App"
echo "   - Configuration Type: By Client ID"
echo "   - Enter Client ID"
echo ""
echo "5. Test the integration:"
echo "   - Create Assignment in Canvas"
echo "   - Look for 'Create using Vidya AI' option"
echo ""
echo "📖 For detailed testing instructions, see:"
echo "   CANVAS_LTI_TESTING_GUIDE.md"
echo ""
echo "🔗 For implementation details, see:"
echo "   CANVAS_LTI_IMPLEMENTATION.md"
echo ""
