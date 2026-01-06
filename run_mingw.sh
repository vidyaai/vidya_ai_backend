. ./vai_venv/Scripts/activate

# Suppress GLib-GIO warnings about UWP apps (harmless Windows-specific noise)
export G_MESSAGES_DEBUG=""

python src/main.py