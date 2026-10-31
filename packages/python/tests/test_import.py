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

            assert cragkit.__version__ == "1.0.0rc1"
            assert cragkit._ENGINE_VERSION == "1.0.0-rc.1"
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
        self.assertEqual(result.stdout, "1.0.0rc1\n")
        self.assertEqual(result.stderr, "")

    def test_engine_default_and_explicit_historical_identity(self):
        from cragkit import _ENGINE_VERSION
        from cragkit.contracts import Versions

        self.assertEqual(_ENGINE_VERSION, "1.0.0-rc.1")
        self.assertEqual(Versions().engine, _ENGINE_VERSION)
        self.assertEqual(Versions(engine="0.0.0").engine, "0.0.0")


if __name__ == "__main__":
    unittest.main()
