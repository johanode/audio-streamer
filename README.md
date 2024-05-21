# audio-streamer
AudioStreamer is a versatile Python application designed to stream audio data in real-time, process it, and optionally send it to AWS IoT for further analysis and storage. The project can run locally for development and testing or be configured to work with AWS IoT for a more integrated solution.

## Getting Started

These instructions will get you a copy of the project up and running on your local machine for development and testing purposes.

### Prerequisites

You need Python 3.5 or newer installed on your system along with the following Python libraries:

```bash
pip install numpy sounddevice soundfile ntplib
```
For AWS IoT integration, you will also need:
```bash
pip install AWSIoTPythonSDK
```

### Installation
```bash
git clone https://github.com/yourusername/sudio-streamer.git
cd audio-streamer
pip install -r requirements.txt
```

### Running the Examples

To start streaming audio data locally, run:
```bash
python example.py
```
Streaming with AWS IoT, make sure you have configured your aws_iot.json correctly:
```bash
python example_aws.py
```

