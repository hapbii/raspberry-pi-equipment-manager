import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from equipment_manager.vision.inference_runtime import prepare_predictor


class Net:
    def __init__(self, threads=4, status=0):
        self.opt = SimpleNamespace(num_threads=threads, use_vulkan_compute=False,
                                   use_fp16_storage=True, use_fp16_packed=True, use_fp16_arithmetic=True)
        self.loaded_threads = []
        self.closed = False
        self.status = status

    def load_param(self, path):
        self.loaded_threads.append(self.opt.num_threads)
        return self.status

    def load_model(self, path):
        self.loaded_threads.append(self.opt.num_threads)
        return self.status

    def clear(self):
        self.closed = True


def fake_model(backend, torch):
    class Predictor:
        def __init__(self, **kwargs):
            self.options = kwargs
            self.model = SimpleNamespace(backend=backend)

        def setup_model(self, **kwargs):
            torch.set_num_threads(8)

    return SimpleNamespace(_smart_load=lambda key: Predictor, overrides={}, callbacks={},
                           model='unused', predictor=None)


class InferenceRuntimeTest(unittest.TestCase):
    def test_pt_reapplies_threads_after_ultralytics_device_setup(self):
        torch = Mock()
        model = fake_model(SimpleNamespace(), torch)
        with patch.dict(sys.modules, {'torch': torch}):
            prepare_predictor(model, Path('best.pt'), {'device': 'cpu'}, 2)
        self.assertEqual([call.args[0] for call in torch.set_num_threads.call_args_list], [8, 2])
        self.assertIsNotNone(model.predictor)

    def test_ncnn_layers_load_with_requested_threads_and_initial_net_is_released(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            (folder/'model.ncnn.param').touch()
            (folder/'model.ncnn.bin').touch()
            old, replacement, torch = Net(), Net(), Mock()
            backend = SimpleNamespace(net=old)
            model = fake_model(backend, torch)
            factory = Mock(return_value=replacement)
            with patch.dict(sys.modules, {'torch': torch, 'ncnn': SimpleNamespace(Net=factory)}):
                prepare_predictor(model, folder, {'device': 'cpu'}, 2)
            self.assertEqual(replacement.loaded_threads, [2, 2])
            self.assertIs(backend.net, replacement)
            self.assertTrue(old.closed)
            self.assertFalse(replacement.closed)
            factory.assert_called_once_with()

    def test_failed_ncnn_replacement_releases_new_net_and_keeps_original(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            (folder/'model.ncnn.param').touch()
            (folder/'model.ncnn.bin').touch()
            old, failed, torch = Net(), Net(status=-1), Mock()
            backend = SimpleNamespace(net=old)
            model = fake_model(backend, torch)
            with patch.dict(sys.modules, {'torch': torch, 'ncnn': SimpleNamespace(Net=lambda: failed)}):
                with self.assertRaisesRegex(RuntimeError, 'CPU'):
                    prepare_predictor(model, folder, {}, 2)
            self.assertTrue(failed.closed)
            self.assertFalse(old.closed)
            self.assertIs(backend.net, old)
            self.assertIsNone(model.predictor)

    def test_already_configured_ncnn_does_not_allocate_another_net(self):
        torch, net = Mock(), Net(threads=2)
        factory = Mock()
        model = fake_model(SimpleNamespace(net=net), torch)
        with patch.dict(sys.modules, {'torch': torch, 'ncnn': SimpleNamespace(Net=factory)}):
            prepare_predictor(model, Path('unused'), {}, 2)
        factory.assert_not_called()
        self.assertFalse(net.closed)


if __name__ == '__main__':
    unittest.main()
