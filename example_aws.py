#!/usr/bin/env python3
from audio_streamer import AudioStreamer
import json
import os

# Optional audio setup arguments
args = {}

# Specify filepath to config files
filepath = ''

# Read the existing configuration
config_path = os.path.join(filepath, 'config.json')
with open(config_path, 'r') as file:
    config = json.load(file)
    
# Read the AWS IoT configuration
aws_path = os.path.join(filepath, 'aws_iot.json')
with open(aws_path, 'r') as file:
    config['aws'] = json.load(file)  
    
# Update the configuration with args
config.update(args)

# Initialize the AudioStreamer with the updated configuration
streamer = AudioStreamer(config)

try:
    streamer.start_streaming()
except KeyboardInterrupt:
    print("Streaming stopped by user.")
