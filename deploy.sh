#!/bin/bash
# Server Deployment Script for VidyaAI Backend with Google Forms Integration

set -e  # Exit on any error

echo "🚀 Starting VidyaAI Backend Deployment"

# Configuration
PROJECT_NAME="vidya_ai_backend"
SERVICE_USER="vidyaai"
APP_DIR="/opt/vidyaai/backend"
CREDENTIALS_FILE="vidyaai-forms-integrations-0270b6b160e0.json"

echo "📋 Deployment Configuration:"
echo "  - Project: $PROJECT_NAME"
echo "  - App Directory: $APP_DIR"
echo "  - Credentials File: $CREDENTIALS_FILE"

# Function to check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        echo "❌ Please run as root or with sudo"
        exit 1
    fi
}

# Function to create service user
create_service_user() {
    if id "$SERVICE_USER" &>/dev/null; then
        echo "✅ User $SERVICE_USER already exists"
    else
        echo "👤 Creating service user $SERVICE_USER"
        useradd -r -s /bin/false -d $APP_DIR $SERVICE_USER
    fi
}

# Function to setup directories
setup_directories() {
    echo "📁 Setting up directories"
    mkdir -p $APP_DIR
    mkdir -p $APP_DIR/logs
    mkdir -p $APP_DIR/credentials
    chown -R $SERVICE_USER:$SERVICE_USER $APP_DIR
}

# Function to install dependencies
install_dependencies() {
    echo "📦 Installing system dependencies"
    apt-get update
    apt-get install -y python3 python3-pip python3-venv nginx postgresql-client
}

# Function to setup Python environment
setup_python_env() {
    echo "🐍 Setting up Python environment"
    cd $APP_DIR
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
}

# Function to setup credentials securely
setup_credentials() {
    echo "🔐 Setting up Google Forms credentials"

    if [ ! -f "$CREDENTIALS_FILE" ]; then
        echo "❌ Credentials file $CREDENTIALS_FILE not found!"
        echo "Please ensure $CREDENTIALS_FILE is in the current directory"
        exit 1
    fi

    # Copy credentials to secure location
    cp "$CREDENTIALS_FILE" "$APP_DIR/credentials/"
    chown $SERVICE_USER:$SERVICE_USER "$APP_DIR/credentials/$CREDENTIALS_FILE"
    chmod 600 "$APP_DIR/credentials/$CREDENTIALS_FILE"

    echo "✅ Credentials file secured at $APP_DIR/credentials/$CREDENTIALS_FILE"
}

# Function to create environment file
create_env_file() {
    echo "⚙️ Creating environment configuration"

    cat > $APP_DIR/.env << EOF
# Database Configuration
DATABASE_URL=\${DATABASE_URL}

# AWS S3 Configuration
AWS_ACCESS_KEY_ID=\${AWS_ACCESS_KEY_ID}
AWS_SECRET_ACCESS_KEY=\${AWS_SECRET_ACCESS_KEY}
AWS_S3_BUCKET=\${AWS_S3_BUCKET}
AWS_REGION=\${AWS_REGION}

# OpenAI Configuration
OPENAI_API_KEY=\${OPENAI_API_KEY}

# Deepgram Configuration
DEEPGRAM_API_KEY=\${DEEPGRAM_API_KEY}

# Google Forms Credentials
GOOGLE_CLOUD_CREDENTIALS_FILE=$APP_DIR/credentials/$CREDENTIALS_FILE

# Stripe Configuration
STRIPE_PUBLISHABLE_KEY=\${STRIPE_PUBLISHABLE_KEY}
STRIPE_SECRET_KEY=\${STRIPE_SECRET_KEY}
STRIPE_WEBHOOK_SECRET=\${STRIPE_WEBHOOK_SECRET}

# Application Settings
ENVIRONMENT=production
DEBUG=false
EOF

    chown $SERVICE_USER:$SERVICE_USER $APP_DIR/.env
    chmod 600 $APP_DIR/.env

    echo "✅ Environment file created at $APP_DIR/.env"
    echo "📝 Please update the environment variables with your actual values"
}

# Function to create systemd service
create_systemd_service() {
    echo "🔧 Creating systemd service"

    cat > /etc/systemd/system/vidyaai-backend.service << EOF
[Unit]
Description=VidyaAI Backend API
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR
Environment=PATH=$APP_DIR/venv/bin
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=3

# Security settings
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=$APP_DIR
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable vidyaai-backend

    echo "✅ Systemd service created and enabled"
}

# Function to setup nginx
setup_nginx() {
    echo "🌐 Setting up Nginx reverse proxy"

    cat > /etc/nginx/sites-available/vidyaai-backend << EOF
server {
    listen 80;
    server_name your-domain.com;  # Replace with your domain

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # Handle CORS
        add_header Access-Control-Allow-Origin *;
        add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS";
        add_header Access-Control-Allow-Headers "Authorization, Content-Type";

        # Handle preflight requests
        if (\$request_method = 'OPTIONS') {
            return 204;
        }
    }
}
EOF

    ln -sf /etc/nginx/sites-available/vidyaai-backend /etc/nginx/sites-enabled/
    nginx -t
    systemctl restart nginx

    echo "✅ Nginx configured and restarted"
}

# Function to run database migrations
run_migrations() {
    echo "🗄️ Running database migrations"
    cd $APP_DIR
    source venv/bin/activate
    alembic upgrade head
    echo "✅ Database migrations completed"
}

# Function to start services
start_services() {
    echo "🚀 Starting services"
    systemctl start vidyaai-backend
    systemctl status vidyaai-backend --no-pager -l
    echo "✅ VidyaAI Backend service started"
}

# Function to test deployment
test_deployment() {
    echo "🧪 Testing deployment"

    # Wait for service to start
    sleep 5

    # Test health endpoint
    if curl -f http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ Health check passed"
    else
        echo "❌ Health check failed"
        systemctl status vidyaai-backend
    fi

    # Test Google Forms service
    echo "🔍 Testing Google Forms integration..."
    echo "Manual test required: Make API call to /api/assignments/{id}/generate-google-form"
}

# Main deployment function
main() {
    echo "🎯 Starting VidyaAI Backend Deployment"

    check_root
    create_service_user
    setup_directories
    install_dependencies
    setup_python_env
    setup_credentials
    create_env_file
    create_systemd_service
    setup_nginx
    run_migrations
    start_services
    test_deployment

    echo ""
    echo "🎉 Deployment completed successfully!"
    echo ""
    echo "📋 Next steps:"
    echo "1. Update environment variables in $APP_DIR/.env"
    echo "2. Update your domain in /etc/nginx/sites-available/vidyaai-backend"
    echo "3. Set up SSL certificate (recommended: certbot)"
    echo "4. Test Google Forms integration with your credentials"
    echo ""
    echo "🔧 Useful commands:"
    echo "  - Check service status: systemctl status vidyaai-backend"
    echo "  - View logs: journalctl -u vidyaai-backend -f"
    echo "  - Restart service: systemctl restart vidyaai-backend"
    echo "  - Check credentials: ls -la $APP_DIR/credentials/"
}

# Run main function
main "$@"