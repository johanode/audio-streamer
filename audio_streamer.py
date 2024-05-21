import json
import numpy as np
import sounddevice as sd
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
import time
import ntplib
from datetime import datetime, timedelta
import soundfile as sf
import os

class TimeSynchronizer:
    def __init__(self, ntp_server="pool.ntp.org"):
        self.ntp_time, self.system_start_time = self.sync_with_ntp(ntp_server)

    def sync_with_ntp(self, ntp_server):
        client = ntplib.NTPClient()
        try:
            response = client.request(ntp_server, version=3)
            system_start_time = time.time()
            ntp_time = datetime.utcfromtimestamp(response.tx_time)            
            print("NTP Sync successful. NTP time: {}".format(ntp_time))
            return ntp_time, system_start_time
        except Exception as e:
            print("Failed to sync with NTP server: ",e)
            fallback_time = datetime.utcnow()
            system_start_time = time.time()
            print("Using system UTC time as fallback: {}".format(fallback_time))
            return fallback_time, system_start_time

    def get_current_time(self):
        """Calculate current UTC time using the initial NTP sync and system uptime."""
        elapsed_time = time.time() - self.system_start_time
        current_utc_time = self.ntp_time + timedelta(seconds=elapsed_time)
        return current_utc_time

class AudioStreamer:
    def __init__(self, config=None):
        try:
            self.time_sync = TimeSynchronizer()
            
            if config:
                self.config = config        
            else:
                self.load_config('config.json')
            
            self.filepath = self.config['audio_file_path']            
            os.makedirs(self.filepath, exist_ok=True)
                        
            self.setup_audio()            
            self.audio_buffer = np.empty((0, self.config['channels']), np.float32)
            self.feature_data = {}
            
            self.file_start_time = None
            self.feature_start_time = None    
            self.current_audio_id = None
            
            self.iot_client = None
            self.setup_iot_client()
                
        except Exception as e:
            print("Failed to initialize AudioStreamer: {}".format(e))

    def load_config(self, path):
        try:
            with open(path, 'r') as file:
                self.config = json.load(file)  
        except FileNotFoundError:
            print("Configuration file not found: {}".format(path))
        except json.JSONDecodeError:
            print("Error decoding JSON from the configuration file: {}".format(path))

    def setup_audio(self):
        # Map MIME type to file extension, defaulting to 'wav' if MIME is not recognized
        mime_to_extension = {
            'audio/wav': 'wav',
            'audio/ogg': 'ogg',
            'audio/mpeg': 'mp3',
            'audio/flac': 'flac'
            }
        extension_to_mime = {v: k for k, v in mime_to_extension.items()}
        
        # Determine the correct audio extension
        default_audio_extension = 'wav'
        if 'extension' in self.config:
            if self.config['extension'] in extension_to_mime:
                self.audio_extension = self.config['extension']                
            else:   
                self.audio_extension = default_audio_extension
                print("{} is not a valid extension, extension set to {}.".format(self.config['extension'], default_audio_extension))
        elif 'mime' in self.config:
            self.audio_extension = mime_to_extension.get(self.config['mime'], default_audio_extension)
        else:
            self.audio_extension = default_audio_extension  # Default to 'wav' if no extension or MIME type is specified
        
        # Set mime
        self.config['mime'] = extension_to_mime.get(self.audio_extension, None)
            
            
    def setup_iot_client(self):
        iot = self.config.get('aws', None)        
        if iot:
            # Check for all required keys
            required_keys = ['client_id', 'endpoint', 'root_ca', 'private_key', 'certificate']
            missing_keys = [key for key in required_keys if key not in iot or not iot[key]]
            if missing_keys:
                # If there are missing keys, handle the error appropriately
                print("Missing required configuration keys for AWS IoT: {}".format(missing_keys))
                return  # Exit the function if configuration is incomplete

            try:
                self.iot_client = AWSIoTMQTTClient(iot['client_id'])
                self.iot_client.configureEndpoint(iot['endpoint'], 8883)
                self.iot_client.configureCredentials(
                    iot['root_ca'],
                    iot['private_key'],
                    iot['certificate']
                )
                if self.iot_client.connect():
                    print("Connected to {}".format(iot['endpoint']))
                else:
                    print("Failied to connected to {}".format(iot['endpoint']))
            except Exception as e:
                print("Failed to setup iot client: ", e)

    def audio_callback(self, indata, frames, time_info, status):
        #if status:
        #    print("Status: ", status)
        
        current_time = self.time_sync.get_current_time()        
        self.manage_audio_buffer(indata, time_info)
        
        if (current_time - self.feature_start_time).total_seconds() >= self.config['feature_time']:
            self.process_feature(current_time)
            self.feature_start_time = current_time

        if (current_time - self.file_start_time).total_seconds() >= self.config['audio_time']:
            #current_buffer = self.audio_buffer
            #self.audio_buffer = np.empty((0, self.config['channels']), np.float32)
            self.save_audio()
            self.file_start_time = current_time
            
    def manage_audio_buffer(self, indata, time_info):  
        # Append new data to the buffer    
        self.audio_buffer = np.vstack((self.audio_buffer, indata))        
        
        #current_time = time_info['inputBufferAdcTime']  # or 'outputBufferDacTime' if output timing is relevant
        
        # Remove old data if buffer is longer than the recording interval
        max_length = int(self.config['samplerate'] * self.config['audio_time'])  # 30 seconds of audio        
        if self.audio_buffer.shape[0] > max_length:
            self.audio_buffer = self.audio_buffer[-max_length:]

    def process_feature(self, current_time):
        # Process the last 3 seconds of audio data
        feature_length = int(self.config['samplerate'] * self.config['feature_time'])  # 3 seconds
        recent_audio = self.audio_buffer[-feature_length:] if self.audio_buffer.shape[0] >= feature_length else self.audio_buffer        
        features = [{'feature' : 'std', 'value' : float(np.std(recent_audio))}]
        self.post_to_iot(features, current_time)        
        #self.feature_start_time = self.time_sync.get_current_time()

    def post_to_iot(self, features, current_time):
        self.update_audio_id()
        
        payload = {
            'timestamp': current_time.isoformat(),
            'device_id' : self.config.get('device_id', 'na'),
            'features': features,
            'audio_file_id': self.current_audio_id,
            'meta' : self.config.get('meta', {}) 
        }
        if self.iot_client:
            try:
                topic = self.config['aws'].get('topic', 'data')
                self.iot_client.publish(topic, json.dumps(payload), 1)
                print("Posted to IoT: ", payload)
            except Exception as e:
                print("Failed to post to IoT: ", e)
                self.save_locally(payload)
        else: 
            #print("IoT client not initialized, saving payload locally.")
            self.save_locally(payload)
            print("Saved locally: ", payload)
            
    def save_locally(self, payload):
        audio_file_id = payload['audio_file_id']
        if audio_file_id not in self.feature_data:  
            # Writes features to file for all previous audio_file_ids             
            self.write_features_to_file()            
            
            # Initialize data storage for the new audio file ID
            self.feature_data[audio_file_id] = {
                'messages': [],
                'device_id': payload['device_id'],
                'meta': payload['meta'],
                'timestamp': payload['timestamp']
            }
        
        # Append the features to the existing list for this audio_file_id
        self.feature_data[audio_file_id]['messages'].append(payload)
            
         
    def write_features_to_file(self):
        file_ids_to_process = list(self.feature_data.keys())  # Safe copy of keys to iterate over
        for audio_file_id in file_ids_to_process:          
            feature_data = self.feature_data.pop(audio_file_id, None)
            
            if feature_data is None:
                continue
            
            # Create a directory for the saved data if it doesn't exist
            local_save_path = self.filepath
            os.makedirs(local_save_path, exist_ok=True)
    
            # Construct the payload
            payload = {
                'device_id': feature_data['device_id'],
                'audio_file_id': audio_file_id,
                'meta': feature_data['meta'],
                'data': {},
                'timestamp': feature_data['timestamp']
            }
                    
            #topic = self.config['aws'].get('topic', 'data')
            
            #feature_types = set()            
            for message in feature_data['messages']:                
                for feature in message['features']:                    
                    feature_name = feature['feature']
                    #feature_types.add(feature_name)
                    if feature_name not in payload['data']:
                        payload['data'][feature_name] = []
                    payload['data'][feature_name].append({
                        'timestamp' : message['timestamp'],
                        'value' : feature['value']
                        })
    
            # Create a filename based on the current time and audio file ID
            filename = "{}.json".format(audio_file_id)
            filepath = os.path.join(local_save_path, filename)
    
            # Save the payload to a JSON file
            with open(filepath, 'w') as f:
                json.dump(payload, f, indent=4)
            print("Payload saved locally to {}".format(filepath))
                

    def update_audio_id(self):
        formatted_date = self.file_start_time.strftime('%Y%m%dT%H%M%S')
        self.current_audio_id = "audio_{}".format(formatted_date)
                                                                      
        
    def save_audio(self):
        if not self.audio_buffer.size:
            return
        try:
            self.update_audio_id()
           
            # Construct the full path for the audio file
            filename = os.path.join(self.filepath, "{}.{}".format(self.current_audio_id, self.audio_extension))
            
            sf.write(filename, self.audio_buffer, self.config['samplerate'])
            print("Audio saved as {}".format(filename))
        except Exception as e:
            print("Failed to save audio: {}".format(e))
        #finally:
        #    self.audio_buffer = np.empty((0, self.config['channels']), np.float32)
        #    self.file_start_time = self.time_sync.get_current_time()        
        
    def cleanup(self):
        self.save_audio()
        self.write_features_to_file()
        
    def start_streaming(self):
            
        current_time = self.time_sync.get_current_time()
        print("Current UTC Time:", current_time)

        self.file_start_time = current_time
        self.feature_start_time = current_time
        
        try:
            with sd.InputStream(callback=self.audio_callback,
                                channels=self.config['channels'],
                                samplerate=self.config['samplerate']):
                print("Streaming started. Press Ctrl+C to stop.")
                while True:
                    time.sleep(0.1)
        except KeyboardInterrupt:
            print("Streaming stopped by user.")
            self.cleanup()            
        except Exception as e:
            self.cleanup()
            print("An error ocurred:", e)



if __name__ == "__main__":
    streamer = AudioStreamer()
    try:
        streamer.start_streaming()
    except KeyboardInterrupt:
        print("Streaming stopped by user.")
