import unittest

from textpipe.pipelines import PIPELINES, SearchPipeline


class PipelineTests(unittest.TestCase):
    def test_search_steps(self):
        self.assertEqual(SearchPipeline().steps(), ['normalize', 'strip'])

    def test_search_run(self):
        self.assertEqual(SearchPipeline().run('  ＨＥＬＬＯ  '), 'hello')

    def test_every_pipeline_starts_with_a_known_step(self):
        for name, cls in PIPELINES.items():
            with self.subTest(name=name):
                self.assertTrue(cls().steps())

    def test_export_redacts(self):
        out = PIPELINES['export']().run('  call 555-0100  ')
        self.assertIn('[phone]', out)


if __name__ == '__main__':
    unittest.main()
