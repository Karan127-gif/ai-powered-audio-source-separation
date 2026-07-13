import torch
import librosa
import numpy as np
import soundfile as sf
from model import MultiStemUNet
from pathlib import Path

# --- CONFIG ---
SR = 22050
DURATION = 4.0  # Should match your training duration
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
MODEL_PATH = "multistem_unet.pth"  # The "Final Product" file
INPUT_SONG = "test_song.wav"      # Put a song name here to test
OUTPUT_DIR = "separated_stems"

def preprocess(audio_path):
    # Load audio and ensure it's stereo 22k
    y, _ = librosa.load(audio_path, sr=SR, mono=False)
    if y.ndim == 1: y = np.stack([y, y])
    
    # Convert to Spectrogram (Matching your SuperDataset logic)
    stft = librosa.stft(y[0], n_fft=1024, hop_length=256) # Using left channel for simplicity or repeat logic
    mag = (librosa.amplitude_to_db(np.abs(stft), ref=np.max) + 80) / 80
    
    # Add batch and channel dims for the model: [1, 2, Freq, Time]
    # Note: Adjust these dimensions based on your specific MultiStemUNet input requirements
    tensor = torch.from_numpy(mag).float().unsqueeze(0).unsqueeze(0) 
    return tensor.to(DEVICE), np.angle(stft)

def save_stem(mag, phase, name):
    # Convert back from DB/Normalized to Magnitude
    mag = (mag * 80) - 80
    mag = librosa.db_to_amplitude(mag)
    
    # Reconstruct audio using original phase
    stft_recon = mag * np.exp(1j * phase)
    y_out = librosa.istft(stft_recon, hop_length=256)
    
    output_path = Path(OUTPUT_DIR) / f"{name}.wav"
    sf.write(output_path, y_out, SR)
    print(f"✅ Saved: {output_path}")

def separate():
    Path(OUTPUT_DIR).mkdir(exist_ok=True)
    
    # 1. Load Model
    model = MultiStemUNet(out_channels=4).to(DEVICE)
    model.load_state_dict(torch.load(MODEL_PATH, map_location=DEVICE))
    model.eval() # Set to evaluation mode!
    
    print(f"🚀 Processing: {INPUT_SONG}...")
    
    # 2. Process Input
    with torch.no_grad():
        input_tensor, original_phase = preprocess(INPUT_SONG)
        
        # 3. Forward Pass
        # output shape: [1, 4, 2, Freq, Time] -> (Stems, Channels, F, T)
        outputs = model(input_tensor) 
        
        # 4. Save each stem
        stem_names = ['vocals', 'drums', 'bass', 'other']
        for i, name in enumerate(stem_names):
            # Extract the magnitude for this stem
            stem_mag = outputs[0, i, 0].cpu().numpy() 
            save_stem(stem_mag, original_phase, name)

if __name__ == "__main__":
    if Path(INPUT_SONG).exists():
        separate()
    else:
        print(f"❌ Error: Place a file named '{INPUT_SONG}' in this folder.")