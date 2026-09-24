import importlib.util,json,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('corpus',Path('tools/check_sigma_corpus.py'));corpus=importlib.util.module_from_spec(spec);spec.loader.exec_module(corpus)
class CorpusTests(unittest.TestCase):
    def test_reports_success_and_rejection_without_installation(self):
        binding=json.loads(Path('examples/sigma/binding.json').read_text())
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'good.yml').write_text(Path('examples/sigma/shell.yml').read_text());(root/'bad.yml').write_text('title: missing detection\n')
            result=corpus.inspect(root,binding)
            self.assertEqual((result['total'],result['compiled'],result['rejected']),(2,1,1));self.assertEqual(len(list(root.iterdir())),2)
    def test_empty_corpus_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):corpus.inspect(d,{})
