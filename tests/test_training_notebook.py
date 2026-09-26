"""Check notebook code without Colab, downloads, training or a real model."""
import gc
import json
import unittest
import weakref
from pathlib import Path


NOTEBOOK = Path(__file__).parents[1] / "training/YOLO_기자재_학습_Colab.ipynb"


class TrainingNotebookTest(unittest.TestCase):
    def code_cells(self):
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        return ["".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"]

    def test_python_cells_compile(self):
        for index, cell in enumerate(self.code_cells()):
            # Colab shell magic is not Python; all remaining source must parse.
            source = "\n".join(line for line in cell.splitlines() if not line.startswith("!"))
            compile(source, f"colab-cell-{index}", "exec")

    def test_field_images_are_streamed_without_retaining_results(self):
        cell = next(code for code in self.code_cells() if "TEST_IMAGES =" in code)
        references = []
        closed = []

        class Result:
            pass

        def results():
            try:
                for _ in range(100):
                    # At most the last result may still be in the consumer.
                    self.assertLessEqual(sum(ref() is not None for ref in references), 1)
                    result = Result()
                    references.append(weakref.ref(result))
                    yield result
                    result = None
            finally:
                closed.append(True)

        class Model:
            def predict(self, **options):
                self.options = options
                return results()

        model = Model()
        namespace = {"best_model": model, "print": lambda *args: None}
        exec(compile(cell, "field-images-cell", "exec"), namespace)
        gc.collect()
        self.assertTrue(model.options["stream"])
        self.assertEqual(namespace["image_count"], 100)
        self.assertEqual(closed, [True])
        self.assertTrue(all(ref() is None for ref in references))


if __name__ == "__main__":
    unittest.main()
