import os
import tempfile
import unittest
from pathlib import Path

from ..requirements import iter_glob_all_requirement_names, iter_requirement_names


class RequirementsTest(unittest.TestCase):
    def test_iter_requirement_names(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(
                b"""\
--index-url foo
a

# comment
B # inline comment
c==2
"""
            )
            f.close()
            self.assertEqual(
                ["a", "b", "c"], list(iter_requirement_names(Path(f.name)))
            )

    def test_iter_glob_all_requirement_names(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pd = Path(d)

            (pd / "a").mkdir()
            (pd / "test").mkdir()
            (pd / "tbat").mkdir()

            (pd / "requirements.txt").write_text("x\n")
            (pd / "a" / "requirements.txt").write_text("a==1\n")
            (pd / "test" / "requirements.txt").write_text("b==1\n")
            (pd / "tbat" / "requirements.txt").write_text("c==1\n")
            prev = os.getcwd()
            try:
                os.chdir(d)
                self.assertEqual(
                    ["b", "c", "x"],
                    sorted(
                        iter_glob_all_requirement_names("*.txt,t*/requirements.txt,")
                    ),
                )
            finally:
                os.chdir(prev)
