"""Check the new Pose+BiLSTM pipeline against a saved video.

Usage: .venv\\Scripts\\python.exe TEST_VIDEO.py path\\to\\video.mp4
Optional: --sample-fps 7 --threshold 0.80 --confirmations 3
"""
import argparse
from pathlib import Path

import cv2

from fallguard.detector import Detector
from fallguard.cctv import FallTracker


def main():
    parser = argparse.ArgumentParser(description='FallGuard YOLO Pose + BiLSTM video test')
    parser.add_argument('video', type=Path)
    parser.add_argument('--sample-fps', type=float, default=7.0)
    parser.add_argument('--threshold', type=float, default=0.80)
    parser.add_argument('--confirmations', type=int, default=3)
    args = parser.parse_args()
    if not args.video.is_file():
        parser.error('Video file not found: ' + str(args.video))
    if not 0.1 <= args.sample_fps <= 60:
        parser.error('sample-fps must be between 0.1 and 60')
    if not 0 < args.threshold < 1 or not 1 <= args.confirmations <= 20:
        parser.error('Invalid threshold/confirmations')
    reader = cv2.VideoCapture(str(args.video))
    if not reader.isOpened():
        parser.error('Cannot decode video')
    fps = reader.get(cv2.CAP_PROP_FPS)
    if not 1 <= fps <= 240:
        fps = 30
    print(f'Input: {args.video} | video FPS={fps:.2f} | sample-fps={args.sample_fps:.2f}', flush=True)
    model, tracker = Detector(), FallTracker()
    model.reset()
    frames = 0
    analysed = 0
    next_sample = 0.0
    events = []
    try:
        while True:
            ok, frame = reader.read()
            if not ok:
                break
            timestamp = frames / fps
            frames += 1
            if timestamp + 1e-5 < next_sample:
                continue
            next_sample = timestamp + 1.0 / args.sample_fps
            height, width = frame.shape[:2]
            ratio = min(1., 960 / max(height, width))
            if ratio < 1:
                frame = cv2.resize(frame, (round(width * ratio), round(height * ratio)))
            result = model.predict(frame)
            tracks = tracker.update(result['detections'], args.threshold, args.confirmations,
                                    timestamp, model.score_sequences)
            analysed += 1
            if analysed % 25 == 0:
                scores = [(x['id'], x['fall_score']) for x in tracks]
                print(f'{timestamp:7.2f}s | samples={analysed} | tracked={len(tracks)} | scores={scores}', flush=True)
            for item in tracks:
                if item['newAlert']:
                    event = dict(time_seconds=round(timestamp, 2), person_id=item['id'],
                                 fall_score=item['fall_score'])
                    events.append(event)
                    print('FALL ALERT:', event, flush=True)
    finally:
        reader.release()
    print('RESULT:', {'frames_read': frames, 'sampled_pose_frames': analysed, 'alerts': events}, flush=True)
    if analysed < 32:
        print('NOTE: fewer than 32 pose observations, BiLSTM could not classify this clip.', flush=True)
    print('CAUTION: this pipeline runs 32 consecutive pose samples, whereas training sampled'
          ' 32 frames across each entire video. Validation on your target camera is necessary.', flush=True)


if __name__ == '__main__':
    main()
