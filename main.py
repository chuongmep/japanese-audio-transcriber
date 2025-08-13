import sys
import os
import whisper
import multiprocessing
from pydub import AudioSegment
import simpleaudio as sa
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QFileDialog,
    QListWidget, QHBoxLayout, QLabel, QMessageBox
)
from PySide6.QtCore import QThread, Signal

# Ensure safe multiprocessing start method on macOS
multiprocessing.set_start_method('spawn', force=True)

class TranscribeWorker(QThread):
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, model, audio_path):
        super().__init__()
        self.model = model
        self.audio_path = audio_path
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        try:
            if self._is_running:
                result = self.model.transcribe(
                    self.audio_path, language="ja", word_timestamps=True
                )
                segments = result.get("segments", [])
                self.finished.emit(segments)
        except Exception as e:
            self.error.emit(str(e))

class AudioTranscriber(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Japanese Audio Transcriber")
        self.resize(900, 400)

        # Layout
        layout = QHBoxLayout()
        self.setLayout(layout)

        # Left: Controls
        control_layout = QVBoxLayout()
        layout.addLayout(control_layout)

        self.load_btn = QPushButton("Load Audio")
        self.load_btn.clicked.connect(self.load_audio)
        control_layout.addWidget(self.load_btn)

        self.transcribe_btn = QPushButton("Transcribe")
        self.transcribe_btn.clicked.connect(self.transcribe_audio)
        self.transcribe_btn.setEnabled(False)
        control_layout.addWidget(self.transcribe_btn)

        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self.play_audio)
        self.play_btn.setEnabled(False)
        control_layout.addWidget(self.play_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_audio)
        self.stop_btn.setEnabled(False)
        control_layout.addWidget(self.stop_btn)

        self.status_label = QLabel("")
        control_layout.addWidget(self.status_label)

        # Right: Transcription list
        self.transcription_list = QListWidget()
        self.transcription_list.itemClicked.connect(self.jump_to_word)
        layout.addWidget(self.transcription_list)

        # Internal state
        self.audio_path = None
        self.audio_segment = None
        self.play_obj = None
        self.segments = []
        self.worker = None
        self.model = None

        # Load Whisper model
        self.status_label.setText("Loading Whisper model...")
        QApplication.processEvents()
        try:
            self.model = whisper.load_model("small")
            self.status_label.setText("Whisper model loaded.")
            self.transcribe_btn.setEnabled(True)
        except Exception as e:
            self.status_label.setText(f"Error loading model: {e}")

    def load_audio(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Select Audio", "", "Audio Files (*.mp3 *.wav)"
        )
        if file_name:
            try:
                self.audio_path = file_name
                self.audio_segment = AudioSegment.from_file(file_name)
                self.status_label.setText(f"Loaded audio: {os.path.basename(file_name)}")
                self.play_btn.setEnabled(True)
                self.stop_btn.setEnabled(True)
            except Exception as e:
                self.status_label.setText(f"Error loading audio: {e}")

    def transcribe_audio(self):
        if not self.audio_path or not self.model:
            self.status_label.setText("Audio or model not loaded.")
            return

        self.transcribe_btn.setEnabled(False)
        self.play_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.load_btn.setEnabled(False)

        self.status_label.setText("Transcribing...")
        QApplication.processEvents()

        self.worker = TranscribeWorker(self.model, self.audio_path)
        self.worker.finished.connect(self.on_transcription_done)
        self.worker.error.connect(self.on_transcription_error)
        self.worker.start()

    def on_transcription_done(self, segments):
        self.segments = segments
        self.transcription_list.clear()
        for seg in self.segments:
            self.transcription_list.addItem(f"{seg['text']} ({seg['start']:.2f} - {seg['end']:.2f})")
        self.status_label.setText("Transcription done!")
        self.transcribe_btn.setEnabled(True)
        self.play_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self.load_btn.setEnabled(True)

    def on_transcription_error(self, message):
        self.status_label.setText(f"Transcription error: {message}")
        self.transcribe_btn.setEnabled(True)
        self.play_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self.load_btn.setEnabled(True)

    def play_audio(self, start_ms=0):
        if self.audio_segment:
            try:
                # Ensure any existing playback is stopped
                self.stop_audio()
                segment_to_play = self.audio_segment[start_ms:]
                self.play_obj = sa.play_buffer(
                    segment_to_play.raw_data,
                    num_channels=segment_to_play.channels,
                    bytes_per_sample=segment_to_play.sample_width,
                    sample_rate=segment_to_play.frame_rate
                )
                # Re-enable the list after playback starts
                self.transcription_list.setEnabled(True)
            except Exception as e:
                self.status_label.setText(f"Audio playback error: {e}")
                self.transcription_list.setEnabled(True)

    def stop_audio(self):
        if self.play_obj and self.play_obj.is_playing():
            try:
                self.play_obj.stop()
                self.play_obj = None
            except Exception as e:
                self.status_label.setText(f"Audio stop error: {e}")
        self.play_obj = None

    def jump_to_word(self, item):
        try:
            # Disable the list to prevent rapid clicks
            self.transcription_list.setEnabled(False)
            text = item.text()
            # Extract start time from text like "text (start - end)"
            start_time_str = text.split("(")[-1].split("-")[0].strip()
            start_time = float(start_time_str)
            start_ms = int(start_time * 1000)
            self.stop_audio()
            self.play_audio(start_ms)
        except (IndexError, ValueError) as e:
            self.status_label.setText(f"Jump error: Invalid time format")
            self.transcription_list.setEnabled(True)
        except Exception as e:
            self.status_label.setText(f"Jump error: {e}")
            self.transcription_list.setEnabled(True)

    def closeEvent(self, event):
        reply = QMessageBox.question(
            self, 'Quit', 'Are you sure you want to exit?',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.stop_audio()
            if self.worker and self.worker.isRunning():
                self.worker.stop()
                self.worker.wait()
            event.accept()
        else:
            event.ignore()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AudioTranscriber()
    window.show()
    sys.exit(app.exec())