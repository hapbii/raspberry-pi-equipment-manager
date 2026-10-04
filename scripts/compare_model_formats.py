"""Compare PT and NCNN on identical, single-object YOLO validation images.

Each backend runs in a separate process so loaded models do not share memory.
Camera and JPEG decoding are excluded from prediction latency. RSS includes the
Python/Ultralytics runtime; it is not the total memory of the loan web service.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path


def iou(a, b):
    area = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    union = max(0, a[2]-a[0])*max(0, a[3]-a[1]) + max(0, b[2]-b[0])*max(0, b[3]-b[1]) - area
    return area / union if union else 0.0


def temperature():
    path = Path('/sys/class/thermal/thermal_zone0/temp')
    try:
        return float(path.read_text()) / 1000
    except (OSError, ValueError):
        return None


def parse_args():
    parser = argparse.ArgumentParser(description='같은 사진으로 PT·NCNN의 속도·메모리·인식 결과 비교')
    parser.add_argument('--pt', type=Path, required=True)
    parser.add_argument('--ncnn', type=Path, required=True)
    parser.add_argument('--dataset', type=Path, required=True, help='images/val, labels/val, classes.txt가 있는 폴더')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--imgsz', type=int, default=320)
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--conf', type=float, default=0.60)
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--worker', choices=['pt', 'ncnn'], help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.imgsz < 160 or args.imgsz % 32 or args.threads < 1 or args.repeats < 1 or not 0 < args.conf < 1:
        parser.error('imgsz는 160 이상/32의 배수, threads·repeats는 양수, conf는 0~1 사이여야 합니다.')
    for name in ['pt','ncnn','dataset','output']:
        setattr(args, name, getattr(args, name).resolve())
    if not args.pt.is_file() or not args.ncnn.is_dir():
        parser.error('PT 파일과 NCNN 폴더를 확인하세요.')
    return args


def worker(args):
    config_dir = args.output/'ultralytics-settings'
    config_dir.mkdir(parents=True,exist_ok=True)
    os.environ['YOLO_CONFIG_DIR'] = str(config_dir)
    for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']:
        os.environ[key] = str(args.threads)
    import psutil
    process = psutil.Process()
    baseline = process.memory_info().rss
    # Retain aggregates, not one sample per 50ms for the entire test duration.
    observations = dict(rss_peak=baseline, temperature_start=None,
                        temperature_end=None, temperature_peak=None)
    stop = threading.Event()

    def sample():
        while not stop.wait(0.05):
            observations['rss_peak'] = max(observations['rss_peak'], process.memory_info().rss)
            t = temperature()
            if t is not None:
                if observations['temperature_start'] is None:
                    observations['temperature_start'] = t
                observations['temperature_end'] = t
                observations['temperature_peak'] = max(observations['temperature_peak'] or t, t)

    monitor = threading.Thread(target=sample, daemon=True)
    monitor.start()
    try:
        import_start = time.perf_counter()
        import cv2
        import torch
        import ultralytics
        from ultralytics import YOLO
        torch.set_num_threads(args.threads)
        torch.set_num_interop_threads(1)
        cv2.setNumThreads(args.threads)
        import_ms = (time.perf_counter()-import_start)*1000
        paths = sorted((args.dataset/'images/val').glob('*.jpg'))
        assert paths, '검증 JPG가 없습니다.'
        names = (args.dataset/'classes.txt').read_text(encoding='utf-8-sig').splitlines()
        prediction_args = dict(imgsz=args.imgsz, conf=args.conf, iou=0.7, max_det=5,
                               device='cpu', rect=False, batch=1, verbose=False, save=False)
        if args.worker=='ncnn':
            import ncnn
            native_net = ncnn.Net
            def configured_net():
                net = native_net()
                # NCNN caches thread counts when loading layers; configure this
                # before load_param/load_model rather than changing it afterward.
                net.opt.num_threads = args.threads
                return net
            ncnn.Net = configured_net
        start = time.perf_counter()
        model = YOLO(str(args.pt if args.worker=='pt' else args.ncnn), task='detect')
        # Configure NCNN's native threads before timed inference, as torch threads
        # alone do not restrict NCNN. Support both Ultralytics backend layouts.
        model.predictor = model._smart_load('predictor')(
            overrides={**model.overrides, **prediction_args}, _callbacks=model.callbacks)
        model.predictor.setup_model(model=model.model, verbose=False)
        auto = model.predictor.model
        backend = getattr(auto, 'backend', auto)
        # Ultralytics select_device('cpu') resets Torch's thread count during
        # setup_model. Reapply the requested limit after backend setup.
        torch.set_num_threads(args.threads)
        runtime_options = {}
        if args.worker=='ncnn':
            net = backend.net
            net.opt.num_threads = args.threads
            for key in ['num_threads','use_vulkan_compute','use_fp16_storage','use_fp16_arithmetic','use_fp16_packed']:
                runtime_options[key] = getattr(net.opt,key)
            assert net.opt.num_threads == args.threads
        model_load_ms = (time.perf_counter()-start)*1000
        assert list(auto.names.values()) == names, '모델 클래스 순서가 데이터셋과 다릅니다.'
        # imdecode supports Unicode image paths on Windows too.
        import numpy as np
        def read_image(path):
            frame = cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR)
            assert frame is not None, path
            return frame
        first = read_image(paths[0])
        start = time.perf_counter()
        model.predict(source=first, **prediction_args)
        first_prediction_ms = (time.perf_counter()-start)*1000
        for _ in range(3):
            model.predict(source=first, **prediction_args)
        assert torch.get_num_threads() == args.threads, 'Torch 스레드 설정이 변경됐습니다.'
        del first
        rss_warm = process.memory_info().rss
        rows = []
        seconds = []
        cpu_before = sum(process.cpu_times()[:2])
        cpu_wall = time.perf_counter()
        for repeat in range(args.repeats):
            order = list(paths)
            random.Random(42+repeat).shuffle(order)
            for path in order:
                frame = read_image(path)
                h,w = frame.shape[:2]
                label = (args.dataset/'labels/val'/path.with_suffix('.txt').name).read_text().splitlines()
                assert len(label)==1, '각 사진에 하나의 정답 물체가 있어야 합니다.'
                cls,x,y,bw,bh = map(float,label[0].split())
                expected = int(cls)
                assert cls == expected and 0 <= expected < len(names)
                target = [(x-bw/2)*w,(y-bh/2)*h,(x+bw/2)*w,(y+bh/2)*h]
                start = time.perf_counter()
                result = model.predict(source=frame, **prediction_args)[0]
                elapsed = time.perf_counter()-start
                seconds.append(elapsed)
                prediction, confidence, box = None,None,None
                if result.boxes is not None and len(result.boxes):
                    idx = int(result.boxes.conf.argmax().item())
                    prediction = int(result.boxes.cls[idx].item())
                    confidence = float(result.boxes.conf[idx].item())
                    box = result.boxes.xyxy[idx].tolist()
                overlap = iou(box,target) if box else 0.0
                rows.append(dict(repeat=repeat,image=path.name,expected=expected,predicted=prediction,
                                 confidence=confidence,box=box,iou=overlap,latency_ms=elapsed*1000,
                                 class_correct=prediction==expected,box_correct=prediction==expected and overlap>=0.5))
                del result, frame
            print(f'{args.worker}: repeat {repeat+1}/{args.repeats} finished',flush=True)
        wall = time.perf_counter()-cpu_wall
        cpu = sum(process.cpu_times()[:2])-cpu_before
        first_rows = [r for r in rows if r['repeat']==0]
        classes = {}
        for index,name in enumerate(names):
            selected = [r for r in first_rows if r['expected']==index]
            classes[name] = dict(images=len(selected),class_correct=sum(r['class_correct'] for r in selected),
                                 box_correct=sum(r['box_correct'] for r in selected))
        memory = process.memory_info()
        files = [args.pt] if args.worker=='pt' else [p for p in args.ncnn.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
        values = sorted(s*1000 for s in seconds)
        summary = dict(backend=args.worker,images=len(paths),calls=len(rows),classes=names,
                       class_correct=sum(r['class_correct'] for r in first_rows),
                       box_correct=sum(r['box_correct'] for r in first_rows),
                       no_detection=sum(r['predicted'] is None for r in first_rows),per_class=classes,
                       mean_ms=statistics.mean(values),median_ms=statistics.median(values),
                       p95_ms=values[min(len(values)-1,int(0.95*len(values)))],
                       import_ms=import_ms,model_load_ms=model_load_ms,first_prediction_ms=first_prediction_ms,
                       rss_before_import_mb=baseline/1024**2,rss_warm_mb=rss_warm/1024**2,
                       rss_final_mb=memory.rss/1024**2,rss_peak_sampled_mb=max(observations['rss_peak'],memory.rss)/1024**2,
                       cpu_percent_one_core=100*cpu/wall,cpu_seconds=cpu,
                       temperature_start_c=observations['temperature_start'],
                       temperature_end_c=observations['temperature_end'],
                       temperature_peak_c=observations['temperature_peak'],
                       model_bytes=sum(p.stat().st_size for p in files),
                       machine=platform.machine(),platform=platform.platform(),python=platform.python_version(),
                       torch=torch.__version__,ultralytics=ultralytics.__version__,
                       torch_threads=torch.get_num_threads(),
                       ncnn_runtime_options=runtime_options)
        args.output.mkdir(parents=True,exist_ok=True)
        (args.output/f'{args.worker}.json').write_text(json.dumps(dict(summary=summary,rows=rows),indent=2),encoding='utf-8')
    finally:
        stop.set()
        monitor.join(timeout=1)


def main():
    args = parse_args()
    if args.worker:
        worker(args)
        return
    args.output.mkdir(parents=True,exist_ok=True)
    if any((args.output/f'{b}.json').exists() for b in ['pt','ncnn']):
        raise SystemExit('기존 결과를 보존하려면 새 출력 폴더를 지정하세요.')
    common = ['--pt',str(args.pt),'--ncnn',str(args.ncnn),'--dataset',str(args.dataset),
              '--output',str(args.output),'--imgsz',str(args.imgsz),'--threads',str(args.threads),
              '--conf',str(args.conf),'--repeats',str(args.repeats)]
    for backend in ['pt','ncnn']:
        subprocess.run([sys.executable,str(Path(__file__).resolve()),*common,'--worker',backend],check=True)
    pt,nc = [json.loads((args.output/f'{b}.json').read_text()) for b in ['pt','ncnn']]
    left,right = [{r['image']:r for r in result['rows'] if r['repeat']==0} for result in [pt,nc]]
    assert left.keys()==right.keys()
    disagreements = [name for name in left if left[name]['predicted']!=right[name]['predicted']]
    score_deltas = [abs(left[name]['confidence']-right[name]['confidence']) for name in left
                    if left[name]['confidence'] is not None and right[name]['confidence'] is not None]
    report = dict(settings=dict(imgsz=args.imgsz,threads=args.threads,conf=args.conf,iou=0.7,max_det=5,
                               repeats=args.repeats,rect=False,device='cpu',warmup_calls=4),
                  pt=pt['summary'],ncnn=nc['summary'],prediction_disagreements=disagreements,
                  max_confidence_delta=max(score_deltas,default=None),
                  speed_ratio_pt_over_ncnn=pt['summary']['median_ms']/nc['summary']['median_ms'],
                  dataset_hashes={name:hashlib.sha256((args.dataset/'images/val'/name).read_bytes()).hexdigest() for name in left},
                  limits=['Same room/date validation; not an independent field test.',
                          'Sequential PT then NCNN; thermal state and other running services can affect latency.',
                          'RSS includes Python and Ultralytics imports; loan web service memory and camera are not included.',
                          'CPU percent is process CPU seconds / wall seconds * 100; 200% means two busy cores.',
                          'Sampled peak RSS and CPU temperature are observations, not exact allocation maxima.'])
    (args.output/'comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    with (args.output/'predictions.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f)
        writer.writerow(['image','expected','pt_class','ncnn_class','pt_conf','ncnn_conf','pt_iou','ncnn_iou'])
        for name in sorted(left):
            a,b=left[name],right[name]
            writer.writerow([name,a['expected'],a['predicted'],b['predicted'],a['confidence'],b['confidence'],a['iou'],b['iou']])
    lines=['# PT / NCNN 비교 결과','',f"장치: {report['pt']['platform']}",
           f'입력 {args.imgsz}, CPU 스레드 {args.threads}, 신뢰도 {args.conf}, 사진 {len(left)}장 × {args.repeats}회','',
           '| 항목 | best.pt | NCNN |','|---|---:|---:|']
    for title,key,unit in [('추론 중앙값','median_ms','ms'),('추론 평균','mean_ms','ms'),('느린 5% 기준','p95_ms','ms'),
                           ('예열 후 메모리','rss_warm_mb','MiB'),('관측 최대 메모리','rss_peak_sampled_mb','MiB'),
                           ('모델 로딩','model_load_ms','ms'),('첫 추론','first_prediction_ms','ms')]:
        lines.append(f"| {title} | {report['pt'][key]:.2f} {unit} | {report['ncnn'][key]:.2f} {unit} |")
    for title,key in [('품목 정답','class_correct'),('품목+박스 IoU≥0.5 정답','box_correct'),('인식 없음','no_detection')]:
        lines.append(f"| {title} | {report['pt'][key]}/{len(left)} | {report['ncnn'][key]}/{len(left)} |")
    lines.extend(['',f"PT 시간 / NCNN 시간: {report['speed_ratio_pt_over_ncnn']:.2f}. 1보다 크면 NCNN이 빠릅니다.",
                  f'최고 신뢰도 후보 품목이 달라진 사진: {len(disagreements)}장.',
                  '', 'CPU·온도·파일 용량·클래스별 결과는 comparison.json을 확인하세요.',
                  '카메라 촬영과 JPEG 읽기는 추론 시간에서 제외했습니다. 현재 서비스 전체의 대여 처리 시간을 뜻하지 않습니다.',
                  '측정은 PT → NCNN 순서이며, 같은 교실·날짜의 검증 사진을 사용했습니다. 실제 신규 촬영 사진도 시험해야 합니다.'])
    (args.output/'비교결과.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('COMPARISON_SAVED',args.output/'comparison.json')


if __name__=='__main__':
    main()
