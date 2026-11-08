from pathlib import Path
import tempfile
import unittest

from evaluate.score import run


class EvaluationTests(unittest.TestCase):
    def test_local_scorer_reads_runs_and_writes_separate_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = root / "runs"
            runs.mkdir()
            (runs / "answer.txt").write_text("answer", encoding="utf-8")
            scorer = root / "score.py"
            scorer.write_text(
                "def score(root, output):\n"
                "    answer = (root / 'answer.txt').read_text(encoding='utf-8')\n"
                "    destination = root / output\n"
                "    destination.mkdir()\n"
                "    (destination / 'result.txt').write_text(answer, encoding='utf-8')\n"
                "    return answer\n", encoding="utf-8")
            self.assertEqual(run(scorer, runs), "answer")
            self.assertEqual((runs / "scores/result.txt").read_text(), "answer")
            with self.assertRaises(FileExistsError):
                run(scorer, runs)
            for outside in ("..", ".", "../outside"):
                with self.assertRaises(ValueError):
                    run(scorer, runs, outside)


if __name__ == "__main__":
    unittest.main()
