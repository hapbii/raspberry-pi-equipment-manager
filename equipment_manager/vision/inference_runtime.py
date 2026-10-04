"""Configure per-model CPU resources before the first inference."""
from __future__ import annotations

from pathlib import Path

from ..resources import release_error_frames


def prepare_predictor(model, model_path: Path, prediction_args: dict, threads: int) -> None:
    """Load once and keep configured resources on this model's predictor."""
    import torch

    predictor = model._smart_load('predictor')(
        overrides={**model.overrides, **prediction_args}, _callbacks=model.callbacks,
    )
    predictor.setup_model(model=model.model, verbose=False)
    auto_backend = predictor.model
    backend = getattr(auto_backend, 'backend', auto_backend)
    if getattr(auto_backend, 'ncnn', False) or getattr(backend, 'net', None) is not None:
        _configure_ncnn(backend, model_path, threads)
    # select_device('cpu') resets this during setup_model. Set it afterward.
    torch.set_num_threads(threads)
    model.predictor = predictor


def _configure_ncnn(backend, model_path: Path, threads: int) -> None:
    """Replace only this backend's net, without monkey-patching global ncnn.Net.

    NCNN layers cache thread counts when loaded. Changing an already loaded
    net's option is insufficient, so load a configured replacement once, then
    release the initial default net. Subsequent scans reuse the replacement.
    """
    import ncnn

    old_net = backend.net
    if old_net.opt.num_threads == threads:
        return
    param = model_path if model_path.is_file() else next(model_path.glob('*.param'), None)
    if param is None or not param.with_suffix('.bin').is_file():
        raise RuntimeError('NCNN의 .param·.bin 파일 쌍을 찾을 수 없습니다.')
    net = ncnn.Net()
    try:
        net.opt.num_threads = threads
        for name in ('use_vulkan_compute', 'use_fp16_storage', 'use_fp16_packed', 'use_fp16_arithmetic'):
            setattr(net.opt, name, getattr(old_net.opt, name))
        if net.load_param(str(param)) != 0 or net.load_model(str(param.with_suffix('.bin'))) != 0:
            raise RuntimeError('NCNN 모델의 CPU 실행 설정에 실패했습니다.')
    except BaseException as exc:
        release_error_frames(exc)
        net.clear()
        raise
    backend.net = net
    old_net.clear()
