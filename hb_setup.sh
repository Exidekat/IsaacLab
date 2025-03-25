#!/bin/bash

# Function to check for command existence
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Install Homebrew if not installed
if ! command_exists brew; then
    echo "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# Install Rosetta 2 for compatibility with x86_64 architecture
if [ "$(uname -m)" = "arm64" ]; then
    echo "Installing Rosetta 2..."
    sudo softwareupdate --install-rosetta --agree-to-license
fi

# Install Docker if not installed
if ! command_exists docker; then
    echo "Installing Docker..."
    brew install --cask docker
    # Start Docker
    open /Applications/Docker.app
    echo "Please ensure Docker is running before proceeding."
    read -p "Press [Enter] to continue..."
fi

# Install Git if not installed
if ! command_exists git; then
    echo "Installing Git..."
    brew install git
fi

# Build and run the Docker container
echo "Building and starting the Isaac Lab Docker container..."
./docker/container.py start

# Provide instructions to enter the container
echo "To enter the running container, use the following command:"
echo "./docker/container.py enter"

echo "Setup complete."

