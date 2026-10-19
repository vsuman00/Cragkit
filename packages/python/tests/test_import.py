import subprocess
import sys
import textwrap
import unittest


class CoreImportTests(unittest.TestCase):
    def test_installed_import_has_no_external_dependencies_or_io(self):
        script = textwrap.dedent(
            """
            import importlib.abc
            import importlib.util
            import os
            import sys

            spec = importlib.util.find_spec("cragkit")
            assert spec is not None and spec.origin is not None, "Install cragkit first"
            import_files = {
                os.path.realpath(spec.origin),
                os.path.realpath(importlib.util.cache_from_source(spec.origin)),
            }

            class DependencyGuard(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    root = fullname.split(".")[0]
                    if root != "cragkit" and root not in sys.stdlib_module_names:
                        raise AssertionError(f"Unexpected dependency import: {fullname}")

            def guard_io(event, args):
                if event.startswith("socket.") or event in {
                    "subprocess.Popen", "os.system", "os.posix_spawn", "os.fork",
                    "os.exec", "os.mkdir", "os.remove", "os.rename", "os.rmdir",
                    "os.truncate", "os.chmod", "os.chown", "os.link", "os.symlink",
                }:
                    raise AssertionError(f"Import attempted I/O: {event}")
                if event == "open":
                    filename, mode, flags = args
                    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
                    if flags & write_flags:
                        raise AssertionError("Import attempted a filesystem write")
                    if not isinstance(filename, str) or os.path.realpath(filename) not in import_files:
                        raise AssertionError("Import attempted a non-module file read")

            sys.meta_path.insert(0, DependencyGuard())
            sys.addaudithook(guard_io)

            import cragkit

            assert cragkit.__version__ == "0.0.0"
            assert cragkit.__all__ == ["__version__"]
            print(cragkit.__version__)
            """
        )
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", script],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "0.0.0\n")
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
