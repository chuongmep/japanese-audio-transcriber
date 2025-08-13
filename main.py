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
from PySide6.QtCore import QThread, Signal, QTimer
from deep_translator import GoogleTranslator

# Ensure safe multiprocessing start method on macOS
multiprocessing.set_start_method('spawn', force=True)


class TranscribeWorker(QThread):
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, model, audio_path):
        super().__init__()
        self.model = model
        self.audio_path = audio_path

    def run(self):
        try:
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
        self.resize(1000, 400)

        layout = QHBoxLayout()
        self.setLayout(layout)

        # Left panel: Controls + Japanese list
        left_layout = QVBoxLayout()
        layout.addLayout(left_layout)

        self.load_btn = QPushButton("Load Audio")
        self.load_btn.clicked.connect(self.load_audio)
        left_layout.addWidget(self.load_btn)

        self.transcribe_btn = QPushButton("Transcribe")
        self.transcribe_btn.clicked.connect(self.transcribe_audio)
        left_layout.addWidget(self.transcribe_btn)

        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self.play_audio)
        left_layout.addWidget(self.play_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_audio)
        left_layout.addWidget(self.stop_btn)

        self.status_label = QLabel("")
        left_layout.addWidget(self.status_label)

        # Two columns for sentences and translations
        list_layout = QHBoxLayout()
        left_layout.addLayout(list_layout)

        self.ja_list = QListWidget()
        self.ja_list.itemClicked.connect(self.jump_to_word)
        list_layout.addWidget(self.ja_list)

        self.vi_list = QListWidget()
        list_layout.addWidget(self.vi_list)

        # Internal state
        self.audio_path = None
        self.audio_segment = None
        self.play_obj = None
        self.segments = []
        self.worker = None
        self.current_playback_start = 0

        self.update_timer = QTimer()
        self.update_timer.setInterval(100)
        self.update_timer.timeout.connect(self.update_current_sentence)

        self.status_label.setText("Loading Whisper model...")
        QApplication.processEvents()
        try:
            self.model = whisper.load_model("small")
            self.status_label.setText("Whisper model loaded.")
        except Exception as e:
            self.status_label.setText(f"Error loading model: {e}")
            self.model = None

        self.translator = GoogleTranslator(source='ja', target='vi')

    def load_audio(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Select Audio", "", "Audio Files (*.mp3 *.wav)"
        )
        if file_name:
            try:
                self.audio_path = file_name
                self.audio_segment = AudioSegment.from_file(file_name)
                self.status_label.setText(f"Loaded audio: {os.path.basename(file_name)}")
            except Exception as e:
                self.status_label.setText(f"Error loading audio: {e}")

    def transcribe_audio(self):
        if not self.audio_path or not self.model:
            self.status_label.setText("Audio or model not loaded.")
            return

        self.status_label.setText("Transcribing...")
        QApplication.processEvents()

        self.worker = TranscribeWorker(self.model, self.audio_path)
        self.worker.finished.connect(self.on_transcription_done)
        self.worker.error.connect(self.on_transcription_error)
        self.worker.start()

    def on_transcription_done(self, segments):
        self.segments = []
        self.ja_list.clear()
        self.vi_list.clear()

        for seg in segments:
            # Skip empty Japanese sentences
            if not seg['text'].strip():
                continue

            self.segments.append(seg)  # keep segment in internal list

            # Japanese sentence with timestamp
            self.ja_list.addItem(f"{seg['text']} ({seg['start']:.2f}-{seg['end']:.2f})")

            # Vietnamese translation, can be empty
            try:
                viet = self.translator.translate(seg['text'])
            except Exception:
                viet = ""
            self.vi_list.addItem(viet)

    def on_transcription_error(self, message):
        self.status_label.setText(f"Transcription error: {message}")

    def play_audio(self, start_ms=0):
        if self.audio_segment:
            try:
                segment_to_play = self.audio_segment[start_ms:]
                self.play_obj = sa.play_buffer(
                    segment_to_play.raw_data,
                    num_channels=segment_to_play.channels,
                    bytes_per_sample=segment_to_play.sample_width,
                    sample_rate=segment_to_play.frame_rate
                )
                self.current_playback_start = start_ms
                self.update_timer.start()
            except Exception as e:
                self.status_label.setText(f"Audio playback error: {e}")

    def stop_audio(self):
        if self.play_obj:
            try:
                self.play_obj.stop()
            except Exception as e:
                self.status_label.setText(f"Audio stop error: {e}")
        self.update_timer.stop()

    def jump_to_word(self, item):
        try:
            idx = self.ja_list.currentRow()
            start_time = float(self.segments[idx]['start'])
            start_ms = int(start_time * 1000)
            self.stop_audio()
            self.play_audio(start_ms)
        except Exception as e:
            self.status_label.setText(f"Jump error: {e}")

    def update_current_sentence(self):
        if not self.play_obj or not self.audio_segment:
            return
        if self.play_obj.is_playing():
            self.current_playback_start += self.update_timer.interval()
        current_sec = self.current_playback_start / 1000.0
        for i, seg in enumerate(self.segments):
            if seg['start'] <= current_sec <= seg['end']:
                self.ja_list.setCurrentRow(i)
                self.vi_list.setCurrentRow(i)
                break

    def closeEvent(self, event):
        reply = QMessageBox.question(
            self, 'Quit', 'Are you sure you want to exit?',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.stop_audio()
            if self.worker and self.worker.isRunning():
                self.worker.terminate()
                self.worker.wait()
            event.accept()
        else:
            event.ignore()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AudioTranscriber()
    window.show()
    sys.exit(app.exec())
