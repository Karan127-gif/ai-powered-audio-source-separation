import os
import numpy as np
import torch
import librosa
import soundfile as sf
from scipy.ndimage import median_filter
from config import SAMPLE_RATE, N_FFT, HOP_LENGTH, OUTPUT_DIR, STEM_NAMES

# dB range used during training (train.py: (amplitude_to_db(..., ref=max) + 80) / 80)
DB_RANGE = 80.0

# ── AI Brain Diagnostic Calibration (from on-device test, Figure 4.3) ─────────
# These values were measured by running the model on a real test track:
#   Stem Name | Mean Energy | Max Activation
#   Vocals    |   0.3761    |    0.6960
#   Drums     |   0.0380    |    0.4836   ← model least confident here
#   Bass      |   0.0679    |    0.6997
#   Other     |   0.5179    |    0.9253   ← model most confident here
#
# Usage:
#   DIAG_MEAN_ENERGY  → used to compute inverse-energy gain correction per stem
#                        (stems with low energy get proportionally more boost)
#   DIAG_MAX_ACT      → used as a mask confidence multiplier
#                        (higher activation = model is more certain → sharper mask)
# Order: [vocals, drums, bass, other]  (matches STEM_NAMES index)
DIAG_MEAN_ENERGY = np.array([0.3761, 0.0380, 0.0679, 0.5179], dtype=np.float32)
DIAG_MAX_ACT     = np.array([0.6960, 0.4836, 0.6997, 0.9253], dtype=np.float32)

# Target: normalise so all stems aim for the same perceived output energy.
# Gain correction = mean(all energies) / stem_energy  (capped to avoid over-boost)
_mean_energy_all = float(DIAG_MEAN_ENERGY.mean())          # ≈ 0.25
DIAG_GAIN_CORRECTION = np.clip(
    _mean_energy_all / (DIAG_MEAN_ENERGY + 1e-6), 0.5, 4.0
)
# Result:  Vocals≈0.67×  Drums≈6.6×(capped→4.0)  Bass≈3.7×  Other≈0.49×(capped→0.5)
# This is ADDITIONAL to the loudness normalisation — applied as spectral mask scaling.



def _to_db_norm(magnitude):
    """
    Convert linear magnitude spectrogram to the same dB-normalised form
    used by train.py's to_spec():
        mag = (amplitude_to_db(abs_stft, ref=np.max) + 80) / 80
    Returns values in [0, 1].
    """
    ref = float(magnitude.max()) + 1e-8
    db = librosa.amplitude_to_db(magnitude, ref=ref)   # in [-DB_RANGE, 0]
    db_norm = (db + DB_RANGE) / DB_RANGE               # in [0, 1]
    return np.clip(db_norm, 0.0, 1.0).astype(np.float32)


def get_device():
    # Always use CPU for maximum compatibility (no GPU required)
    return 'cpu'


def separate_audio(audio_path, model, selected_stems=None, progress_cb=None):
    """
    Separate audio into stems using:
      1. Chunked model inference (matches training segment length)
      2. Wiener filter mask refinement  — industry-standard post-filter
      3. HPSS-guided vocal cleanup      — physically removes percussive bleed
      4. Per-stem spectral cleanup      — bandpass, noise gate, de-crackle

    Args:
        audio_path:     path to input (WAV / MP3 / FLAC / OGG)
        model:          loaded MultiStemUNet in eval mode
        selected_stems: list of stem indices {0=vocals,1=drums,2=bass,3=other}
                        None → all 4
        progress_cb:    callable(percent:int, message:str)

    Returns:
        results      – { stem_name → np.ndarray float32 (2, N) }
        output_paths – { stem_name → absolute wav path }
    """
    if selected_stems is None:
        selected_stems = list(range(len(STEM_NAMES)))

    def _cb(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    # ── 1. Load audio ──────────────────────────────────────────────────────────
    _cb(5, "Loading audio file…")
    try:
        audio, sr = librosa.load(audio_path, sr=SAMPLE_RATE, mono=False)
    except Exception as e:
        raise RuntimeError(f"Cannot read audio file: {e}")

    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=0)
    elif audio.shape[0] > 2:
        audio = audio[:2]
    n_samples = audio.shape[1]

    # ── 2. STFT ─────────────────────────────────────────────────────────────────
    _cb(10, "Computing spectrograms…")
    stfts      = [librosa.stft(audio[ch], n_fft=N_FFT, hop_length=HOP_LENGTH)
                  for ch in range(2)]
    magnitudes = np.stack([np.abs(s) for s in stfts], axis=0)   # (2, F, T) linear
    phases     = np.stack([np.angle(s) for s in stfts], axis=0) # (2, F, T)
    _, freq_bins, total_frames = magnitudes.shape

    # dB-normalise to match training input format
    db_norm = _to_db_norm(magnitudes)                            # (2, F, T) in [0,1]

    # ── 3. HPSS on the mix — used later to gate the vocal stem ────────────────
    _cb(15, "Running harmonic-percussive separation…")
    # Use the average of both channels for HPSS (mono is sufficient)
    mix_mono_stft = (stfts[0] + stfts[1]) / 2.0                 # (F, T) complex
    mix_mono_mag  = np.abs(mix_mono_stft)
    # margin > 1 → more aggressive separation between harmonic and percussive
    H_mag, P_mag = librosa.decompose.hpss(mix_mono_mag, kernel_size=31, margin=2.0)
    # Soft harmonic mask: 1 where harmonic dominates, 0 where percussive dominates
    total_hp  = H_mag + P_mag + 1e-8
    harm_mask = H_mag / total_hp                                 # (F, T) in [0,1]
    perc_mask = P_mag / total_hp                                 # (F, T) in [0,1]
    # Smooth masks to avoid tearing artifacts
    harm_mask = median_filter(harm_mask, size=(1, 11)).astype(np.float32)
    perc_mask = median_filter(perc_mask, size=(1, 11)).astype(np.float32)

    device = next(model.parameters()).device

    # ── 4. Overlap-add chunked model inference ─────────────────────────────────
    _cb(20, "Preparing model inference…")
    # 344 frames ≈ 4.0 s at hop=256, sr=22050 — matches SuperDataset training len
    CHUNK = 344
    HOP_C = CHUNK // 2                                           # 50 % overlap

    hann   = np.hanning(CHUNK).astype(np.float32)
    pad_l  = HOP_C
    pad_r  = CHUNK
    db_pad = np.pad(db_norm, ((0, 0), (0, 0), (pad_l, pad_r))) # (2, F, T_pad)
    T_pad  = db_pad.shape[2]

    # Accumulate RAW model masks (before Wiener refinement)
    acc_masks  = np.zeros((4, 2, freq_bins, T_pad), dtype=np.float32)
    acc_weight = np.zeros(T_pad, dtype=np.float32)

    starts   = list(range(0, T_pad - CHUNK + 1, HOP_C))
    n_chunks = len(starts)

    for ci, start in enumerate(starts):
        _cb(22 + int(48 * ci / max(n_chunks, 1)),
            f"Separating chunk {ci + 1}/{n_chunks}…")

        end       = start + CHUNK
        chunk_db  = db_pad[:, :, start:end]                     # (2, F, CHUNK)
        chunk_t   = torch.tensor(chunk_db, dtype=torch.float32).unsqueeze(0).to(device)

        with torch.no_grad():
            out = model(chunk_t)                                 # (1,4,2,F,CHUNK)

        out_np = out.squeeze(0).cpu().numpy()                    # (4,2,F,CHUNK)

        # Recover soft ratio masks from model output
        # model returns masks * db_input  →  mask = output / db_input
        chunk_db_exp = chunk_db[np.newaxis, :, :, :]            # (1,2,F,CHUNK)
        raw_masks    = out_np / np.maximum(chunk_db_exp, 1e-6)  # (4,2,F,CHUNK)
        raw_masks    = np.clip(raw_masks, 0.0, 1.0)

        # ── Sigmoid mask sharpening scaled by Max Activation (Diagnostic ref) ─
        # Base alpha=6.0; multiply by MaxAct so stems the model is MORE confident
        # about (e.g. Other=0.9253, Bass=0.6997) get sharper boundaries, while
        # the least-confident stem (Drums=0.4836) stays softer to avoid artifacts.
        # DIAG_MAX_ACT shape: (4,) — broadcast over (4,2,F,CHUNK)
        alpha_per_stem = 6.0 * DIAG_MAX_ACT[:, np.newaxis, np.newaxis, np.newaxis]
        sigmoid_masks  = 1.0 / (1.0 + np.exp(-alpha_per_stem * (raw_masks - 0.5)))
        denom   = sigmoid_masks.sum(axis=0, keepdims=True) + 1e-8
        masks_s = sigmoid_masks / denom                          # normalised, sum=1

        # Temporal smoothing of each mask via median filter along time axis
        # (size=5 frames ≈ 50 ms) — eliminates isolated spectral spikes/crackle
        for s in range(4):
            for ch in range(2):
                masks_s[s, ch] = median_filter(masks_s[s, ch], size=(1, 5))

        # Hann window + overlap-add accumulation
        acc_masks[:, :, :, start:end] += masks_s * hann[np.newaxis, np.newaxis, np.newaxis, :]
        acc_weight[start:end]         += hann

    # ── 5. Normalise accumulated masks ────────────────────────────────────────
    _cb(72, "Normalising masks…")
    raw_final = acc_masks[:, :, :, pad_l: pad_l + total_frames] # (4,2,F,T)
    weight    = np.maximum(acc_weight[pad_l: pad_l + total_frames], 1e-8)
    raw_final = raw_final / weight[np.newaxis, np.newaxis, np.newaxis, :]
    raw_final = np.clip(raw_final, 0.0, 1.0)

    # ── 6. Iterative 2-Pass Wiener Filter (Ref [15] Liutkus & Badeau) ─────────
    # Pass 1: coarse Wiener masks from model output
    # Pass 2: re-estimate using Pass-1 stem magnitudes as stronger priors
    # Two passes converge to a much sharper mask than a single pass.
    _cb(76, "Wiener filter pass 1…")
    mix_power   = magnitudes ** 2                                # (2,F,T)
    noise_floor = mix_power.mean(axis=2, keepdims=True) * 0.005 # tighter noise floor
    noise_floor = noise_floor * np.ones_like(magnitudes)

    # --- Pass 1 ---
    stem_mags_p1 = np.zeros((4, 2, freq_bins, total_frames), dtype=np.float32)
    for s in range(4):
        for ch in range(2):
            stem_mags_p1[s, ch] = raw_final[s, ch] * magnitudes[ch]
    stem_power_p1  = stem_mags_p1 ** 2
    sum_power_p1   = stem_power_p1.sum(axis=0) + noise_floor
    w_masks_p1     = stem_power_p1 / (sum_power_p1[np.newaxis] + 1e-8)
    w_masks_p1     = np.clip(w_masks_p1, 0.0, 1.0)

    # --- Pass 2: use Pass-1 stem estimates as refined priors ---
    _cb(79, "Wiener filter pass 2 (iterative refinement)…")
    stem_mags_p2 = np.zeros((4, 2, freq_bins, total_frames), dtype=np.float32)
    for s in range(4):
        for ch in range(2):
            stem_mags_p2[s, ch] = w_masks_p1[s, ch] * magnitudes[ch]
    stem_power_p2  = stem_mags_p2 ** 2
    # Tighten noise floor further in pass 2 — priors are now more reliable
    noise_floor_p2 = mix_power.mean(axis=2, keepdims=True) * 0.002
    noise_floor_p2 = noise_floor_p2 * np.ones_like(magnitudes)
    sum_power_p2   = stem_power_p2.sum(axis=0) + noise_floor_p2
    w_masks_p2     = stem_power_p2 / (sum_power_p2[np.newaxis] + 1e-8)
    w_masks_p2     = np.clip(w_masks_p2, 0.0, 1.0)

    # ── 7. HPSS guidance — stronger weighting after 2-pass Wiener ────────────
    _cb(82, "Applying HPSS guidance…")
    VOCAL_IDX = 0
    DRUM_IDX  = 1
    harm_3d   = harm_mask[np.newaxis, :, :]                     # (1,F,T)
    perc_3d   = perc_mask[np.newaxis, :, :]                     # (1,F,T)

    # Vocal: 50% Wiener + 50% HPSS harmonic (stronger harmonic bias → less drum bleed)
    w_masks_p2[VOCAL_IDX] = (0.50 * w_masks_p2[VOCAL_IDX]
                             + 0.50 * w_masks_p2[VOCAL_IDX] * harm_3d)

    # Drums: 50% Wiener + 50% HPSS percussive (stronger percussive bias)
    w_masks_p2[DRUM_IDX]  = (0.50 * w_masks_p2[DRUM_IDX]
                             + 0.50 * w_masks_p2[DRUM_IDX] * perc_3d)

    # Re-normalise — energy conservation across all stems
    mask_sum    = w_masks_p2.sum(axis=0, keepdims=True) + 1e-8
    final_masks = w_masks_p2 / mask_sum

    # ── 8. Reconstruct audio with Griffin-Lim phase (Ref: Future Scope) ───────
    # For vocals and bass: Griffin-Lim reconstructs a consistent phase from the
    # estimated magnitude, eliminating the "watery/metallic" artifact caused by
    # reusing the mixture phase. For drums/other the mixture phase is fine.
    _cb(84, "Reconstructing stems…")
    mix_peak = float(np.abs(audio).max()) + 1e-8

    # Stems that benefit from Griffin-Lim phase reconstruction.
    # Bass is low-pass filtered to 400 Hz and is mono-compatible — mixture phase
    # works fine there and skipping GL saves significant processing time.
    GRIFFIN_LIM_STEMS = {'vocals'}
    GL_ITER = 10   # 10 iterations: excellent quality, ~35% faster than 16

    results = {}
    for idx in selected_stems:
        stem_name = STEM_NAMES[idx]
        stem_mask = final_masks[idx]                             # (2,F,T)

        stem_audio_ch = []
        for ch in range(2):
            stem_mag = stem_mask[ch] * magnitudes[ch]           # estimated magnitude

            if stem_name in GRIFFIN_LIM_STEMS:
                # Griffin-Lim: iteratively estimate a consistent phase from the
                # masked magnitude — produces much cleaner, artifact-free audio
                ch_audio = _griffin_lim(stem_mag, N_FFT, HOP_LENGTH,
                                        n_iter=GL_ITER, length=n_samples)
            else:
                # Mixture phase reuse is fine for drums/other (mostly percussive)
                stem_complex = stem_mag * np.exp(1j * phases[ch])
                ch_audio     = librosa.istft(stem_complex,
                                             hop_length=HOP_LENGTH,
                                             length=n_samples)
            stem_audio_ch.append(ch_audio.astype(np.float32))

        stem_stereo = np.stack(stem_audio_ch, axis=0)           # (2,N)

        # ── Per-stem spectral post-processing ─────────────────────────────
        stem_stereo = _post_process_stem(stem_name, stem_stereo, SAMPLE_RATE)

        # ── Diagnostic energy calibration ─────────────────────────────────
        # Use DIAG_GAIN_CORRECTION to compensate for the model's natural energy
        # imbalance measured in the AI Brain Diagnostic (Figure 4.3).
        # Drums (energy=0.038) gets ~4× boost, Bass (0.068) gets ~3.7×, etc.
        diag_gain = float(DIAG_GAIN_CORRECTION[idx])
        stem_stereo = stem_stereo * diag_gain

        # Loudness normalisation: target 95% of mix peak
        stem_peak = float(np.abs(stem_stereo).max()) + 1e-8
        gain      = min((mix_peak * 0.95) / stem_peak, 6.0)
        stem_stereo = stem_stereo * gain

        # Final hard-limiter — prevent clipping
        final_peak = float(np.abs(stem_stereo).max())
        if final_peak > 0.99:
            stem_stereo = stem_stereo * (0.97 / final_peak)

        results[stem_name] = stem_stereo

    # ── 9. Save WAV files ─────────────────────────────────────────────────────
    _cb(95, "Saving WAV files…")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    base_name    = os.path.splitext(os.path.basename(audio_path))[0]
    output_paths = {}
    for stem_name, stem_audio in results.items():
        out_path = os.path.join(OUTPUT_DIR, f"{base_name}_{stem_name}.wav")
        sf.write(out_path, stem_audio.T, SAMPLE_RATE)
        output_paths[stem_name] = out_path

    _cb(100, "Done!")
    return results, output_paths


def _griffin_lim(magnitude: np.ndarray, n_fft: int, hop_length: int,
                 n_iter: int = 16, length: int = None) -> np.ndarray:
    """
    Griffin-Lim phase reconstruction (Ref: Griffin & Lim, 1984).

    Instead of reusing the mixture phase (which causes watery/metallic artifacts
    when magnitude is very different from the mix), this function iteratively
    estimates a self-consistent phase purely from the target magnitude.

    Warm-start: initialise with random phase so convergence is fast.
    n_iter=16 gives excellent quality with acceptable processing time.

    Returns: reconstructed time-domain audio (float32, 1-D).
    """
    # Random-phase initialisation for fast convergence
    phase = np.exp(2j * np.pi * np.random.default_rng(seed=0).random(magnitude.shape))
    complex_spec = magnitude * phase

    for _ in range(n_iter):
        # iSTFT → STFT cycle
        wav = librosa.istft(complex_spec, hop_length=hop_length, length=length)
        complex_spec = librosa.stft(wav, n_fft=n_fft, hop_length=hop_length)
        # Keep target magnitude, update phase from signal estimate
        phase = np.exp(1j * np.angle(complex_spec))
        complex_spec = magnitude * phase

    # Final iSTFT with converged phase
    return librosa.istft(complex_spec, hop_length=hop_length,
                         length=length).astype(np.float32)


def _post_process_stem(stem_name: str, audio: np.ndarray, sr: int) -> np.ndarray:
    """
    Per-stem spectral cleanup.
    audio shape: (2, N) float32
    Focus: remove noise, outliers, and cross-stem bleed specific to each stem.
    """
    from scipy.signal import filtfilt
    out_channels = []
    for ch in range(audio.shape[0]):
        y = audio[ch]

        if stem_name == 'vocals':
            S   = librosa.stft(y, n_fft=N_FFT, hop_length=HOP_LENGTH)
            mag = np.abs(S)
            phs = np.angle(S)

            # 1) Smooth out spectral outliers / crackles:
            #    clip any bin above 99th percentile of its own column's energy.
            col_p99 = np.percentile(mag, 99, axis=0, keepdims=True)
            mag     = np.minimum(mag, col_p99)

            # 2) Median-filter along frequency axis — removes isolated spectral spikes
            mag = median_filter(mag, size=(3, 1))

            # 3) Spectral noise gate: estimate per-bin noise floor from the
            #    quietest 10 % of frames and apply a smooth Wiener-style gain.
            frame_nrg   = mag.mean(axis=0)                           # (T,)
            noise_thresh = np.percentile(frame_nrg, 10)
            noise_frames = mag[:, frame_nrg <= noise_thresh]
            noise_floor  = (noise_frames.mean(axis=1, keepdims=True) * 3.0
                            if noise_frames.shape[1] > 0
                            else mag.min(axis=1, keepdims=True) * 3.0)
            snr      = np.maximum(mag - noise_floor, 0) / (mag + 1e-8)
            gate     = np.clip(snr * 4.0, 0.0, 1.0)                 # 0→1 gate
            mag      = mag * gate

            # 4) Harmonic-emphasis: median-filter along time (31 frames) to
            #    suppress percussive transients (drum hits bleeding into vocals)
            harm_mag = median_filter(mag, size=(1, 31))
            mag      = 0.80 * harm_mag + 0.20 * mag

            # 5) High-pass at 80 Hz — removes bass rumble
            y = librosa.istft(mag * np.exp(1j * phs),
                              hop_length=HOP_LENGTH, length=len(y))
            b, a = _butter_filter(80, sr, btype='high')
            y    = filtfilt(b, a, y).astype(np.float32)

            # 6) Frame-level noise gate: mute very quiet frames (< 1.5 % peak RMS)
            y = _frame_noise_gate(y, sr, threshold_ratio=0.015)

        elif stem_name == 'drums':
            # High-pass at 50 Hz — removes sub-bass rumble
            b, a = _butter_filter(50, sr, btype='high')
            y    = filtfilt(b, a, y).astype(np.float32)
            # Remove very quiet frames (< 2 % of peak) — cleans up bleed
            y = _frame_noise_gate(y, sr, threshold_ratio=0.02, frame_ms=10)

        elif stem_name == 'bass':
            # Low-pass at 400 Hz — keeps only the low end; removes vocals/drums
            b, a = _butter_filter(400, sr, btype='low')
            y    = filtfilt(b, a, y).astype(np.float32)

        elif stem_name == 'other':
            S   = librosa.stft(y, n_fft=N_FFT, hop_length=HOP_LENGTH)
            mag = np.abs(S)
            phs = np.angle(S)

            # 1) Clip outlier spikes — prevents crackle
            clip_val = np.percentile(mag, 99)
            mag      = np.clip(mag, 0, clip_val)

            # 2) Soft-suppress the vocal frequency band (200–4000 Hz)
            freqs      = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)
            vocal_gain = np.ones(len(freqs), dtype=np.float32)
            for fi, f in enumerate(freqs):
                if 200 <= f <= 4000:
                    t = (f - 200) / (4000 - 200)
                    vocal_gain[fi] = 1.0 - 0.60 * np.sin(np.pi * t) ** 2
            mag = mag * vocal_gain[:, np.newaxis]

            # 3) Spectral noise gate
            frame_nrg    = mag.mean(axis=0)
            noise_thresh  = np.percentile(frame_nrg, 15)
            noise_frames  = mag[:, frame_nrg <= noise_thresh]
            noise_floor   = (noise_frames.mean(axis=1, keepdims=True) * 2.5
                             if noise_frames.shape[1] > 0
                             else mag.min(axis=1, keepdims=True) * 2.5)
            snr      = np.maximum(mag - noise_floor, 0) / (mag + 1e-8)
            gate     = np.clip(snr * 3.0, 0.0, 1.0)
            mag      = mag * gate

            y = librosa.istft(mag * np.exp(1j * phs),
                              hop_length=HOP_LENGTH, length=len(y))
            y = _frame_noise_gate(y, sr, threshold_ratio=0.025)

        out_channels.append(y.astype(np.float32))
    return np.stack(out_channels, axis=0)


def _frame_noise_gate(y: np.ndarray, sr: int,
                      frame_ms: int = 20,
                      threshold_ratio: float = 0.02) -> np.ndarray:
    """
    Wideband noise gate: zero-out frames whose RMS < threshold_ratio × peak RMS.
    Uses a 5-frame look-ahead soft-hold to avoid abrupt cuts on transients.
    """
    frame_len = int(sr * frame_ms / 1000)
    if frame_len < 1 or len(y) == 0:
        return y
    peak_rms    = float(np.sqrt(np.mean(y ** 2))) + 1e-8
    gate_thresh = peak_rms * threshold_ratio
    out         = y.copy()
    n_frames    = (len(y) + frame_len - 1) // frame_len
    rms_vals    = []
    for i in range(n_frames):
        seg = y[i * frame_len: (i + 1) * frame_len]
        rms_vals.append(float(np.sqrt(np.mean(seg ** 2))))
    # 3-frame lookahead hold: keep a frame open if any of next 3 frames are loud
    gate_open = [False] * n_frames
    for i in range(n_frames):
        look = rms_vals[i: i + 4]
        if max(look) >= gate_thresh:
            gate_open[i] = True
    for i in range(n_frames):
        if not gate_open[i]:
            out[i * frame_len: (i + 1) * frame_len] = 0.0
    return out


def _butter_filter(cutoff_hz: float, sr: int, btype: str, order: int = 5):
    """Design a Butterworth filter. Returns (b, a) coefficients."""
    from scipy.signal import butter
    nyq = sr / 2.0
    return butter(order, cutoff_hz / nyq, btype=btype)
