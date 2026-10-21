import importlib.util
import os
import re
import struct
import sys
import tempfile
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from hesabat import __version__, applog
from hesabat.db.connection import data_dir

HAS_YAML = importlib.util.find_spec("yaml") is not None


def slurp(path, mode="r"):
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        return f.read()


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class EnvCase(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("HESABAT_DATA_DIR")

    def tearDown(self):
        if self._old is None:
            os.environ.pop("HESABAT_DATA_DIR", None)
        else:
            os.environ["HESABAT_DATA_DIR"] = self._old


class DataDirAndLogTests(EnvCase):
    def test_data_dir_override_and_default(self):
        target = os.path.join(tempfile.mkdtemp(), "x", "data")
        os.environ["HESABAT_DATA_DIR"] = target
        self.assertEqual(data_dir(), target)
        self.assertTrue(os.path.isdir(target))                              # بيتعمل لو مش موجود
        os.environ.pop("HESABAT_DATA_DIR")
        self.assertEqual(os.path.basename(data_dir()), "HesabatStock")

    def test_log_writes(self):
        os.environ["HESABAT_DATA_DIR"] = tempfile.mkdtemp()
        applog.log("حصل خطأ تجريبي")
        text = slurp(applog.log_path())
        self.assertIn("حصل خطأ تجريبي", text)
        self.assertRegex(text, r"\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\]")

    def test_log_never_raises(self):
        blocker = os.path.join(tempfile.mkdtemp(), "file")
        open(blocker, "w").close()
        os.environ["HESABAT_DATA_DIR"] = os.path.join(blocker, "sub")       # مسار مستحيل
        applog.log("x")                                                     # مفيش استثناء

    def test_log_rotates(self):
        os.environ["HESABAT_DATA_DIR"] = tempfile.mkdtemp()
        with open(applog.log_path(), "w", encoding="utf-8") as f:
            f.write("a" * (applog.MAX_BYTES + 10))
        applog.log("جديد")
        self.assertTrue(os.path.exists(applog.log_path() + ".old"))
        self.assertLess(os.path.getsize(applog.log_path()), 1000)


class AssetTests(unittest.TestCase):
    PNG = b"\x89PNG\r\n\x1a\n"

    def test_png_icon(self):
        data = slurp(os.path.join(ROOT, "hesabat", "assets", "icon.png"), "rb")
        self.assertTrue(data.startswith(self.PNG))
        w, h, depth, ctype = struct.unpack(">IIBB", data[16:26])
        self.assertEqual((w, h, depth, ctype), (256, 256, 8, 6))            # RGBA 256

    def test_ico_icon(self):
        data = slurp(os.path.join(ROOT, "hesabat", "assets", "icon.ico"), "rb")
        reserved, kind, count = struct.unpack("<HHH", data[:6])
        self.assertEqual((reserved, kind, count), (0, 1, 6))
        sizes = []
        for i in range(count):
            w, h, _c, _r, _p, _b, length, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
            blob = data[offset:offset + length]
            self.assertEqual(len(blob), length)
            self.assertTrue(blob.startswith(self.PNG))
            pw, ph = struct.unpack(">II", blob[16:24])
            self.assertEqual((pw % 256, ph % 256), (w, h))
            sizes.append(pw)
        self.assertEqual(sizes, [16, 32, 48, 64, 128, 256])

    @staticmethod
    def _pixels(png):
        """رأس الصورة + بيانات البكسلات بعد فك الضغط. بتتجاهل أي بيانات وصفية إضافية (chunks) في الملف."""
        assert png.startswith(AssetTests.PNG)
        pos, idat, header = 8, [], b""
        while pos < len(png):
            length, tag = struct.unpack(">I4s", png[pos:pos + 8])
            body = png[pos + 8:pos + 8 + length]
            if tag == b"IHDR":
                header = body
            elif tag == b"IDAT":
                idat.append(body)
            pos += 12 + length
        return header + zlib.decompress(b"".join(idat))

    def test_png_matches_largest_ico_entry(self):
        """icon.png لازم يكون هو نفسه الصورة 256 جوه icon.ico (بيتولدوا مع بعض من tools/make_icon.py)."""
        png = slurp(os.path.join(ROOT, "hesabat", "assets", "icon.png"), "rb")
        ico = slurp(os.path.join(ROOT, "hesabat", "assets", "icon.ico"), "rb")
        count = struct.unpack("<H", ico[4:6])[0]
        length, offset = struct.unpack("<II", ico[6 + 16 * (count - 1) + 8:6 + 16 * count])
        self.assertEqual(self._pixels(ico[offset:offset + length]), self._pixels(png))

    def test_version(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")


class BuildTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("build_exe", os.path.join(ROOT, "tools", "build_exe.py"))
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_build_command(self):
        cmd = self.mod.build_command(ROOT)
        for flag in ("--onefile", "--windowed", "--noconfirm", "--icon", "--add-data", "--name"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("--name") + 1], "HesabatStock")
        self.assertTrue(os.path.exists(cmd[cmd.index("--icon") + 1]))
        src, dest = cmd[cmd.index("--add-data") + 1].split(os.pathsep)
        self.assertTrue(os.path.isdir(src))
        self.assertEqual(dest, os.path.join("hesabat", "assets"))           # نفس المسار اللي app.resource_path بيدوّر عليه
        self.assertTrue(os.path.exists(cmd[-1]) and cmd[-1].endswith("main.py"))
        self.assertGreaterEqual(cmd.count("--exclude-module"), 10)

    def test_workflow_text(self):
        wf = read(".github", "workflows", "build-windows.yml")
        for needle in ("windows-latest", "tools/build_exe.py", "--selftest", "--selftest-print", "upload-artifact",
                       "HesabatStock.exe", "workflow_dispatch"):
            self.assertIn(needle, wf)
        ignore = read(".gitignore")
        for needle in ("*.db", "backups/", "dist/"):
            self.assertIn(needle, ignore)                                    # مفيش بيانات حقيقية ترتفع بالغلط

    def test_workflow_runs_every_existing_test_module(self):
        wf = read(".github", "workflows", "build-windows.yml")
        line = re.search(r"python -m unittest (.+)", wf).group(1).split()
        for mod in line:
            self.assertTrue(os.path.exists(os.path.join(ROOT, "tests", mod + ".py")), mod)
        on_disk = {f[:-3] for f in os.listdir(os.path.join(ROOT, "tests")) if re.match(r"(test_|smoke_).+\.py$", f)}
        self.assertEqual(set(line), on_disk)                                 # مفيش اختبار منسي خارج الـ CI

    @unittest.skipUnless(HAS_YAML, "PyYAML مش متثبتة")
    def test_workflow_yaml(self):
        import yaml
        w = yaml.safe_load(read(".github", "workflows", "build-windows.yml"))
        job = w["jobs"]["build"]
        self.assertEqual(job["runs-on"], "windows-latest")
        names = [s.get("name") or s.get("uses") for s in job["steps"]]
        self.assertLess(names.index("Run tests"), names.index("Build exe"))
        self.assertLess(names.index("Build exe"), names.index("Self-test the built exe"))
        self.assertLess(names.index("Self-test the built exe"), names.index("actions/upload-artifact@v4"))

    def test_bat_and_requirements(self):
        bat = read("build_windows.bat")
        self.assertIn("tools\\build_exe.py", bat)
        self.assertIn("--selftest", bat)
        reqs = read("requirements.txt").split()
        self.assertEqual(sorted(reqs), ["PySide6", "openpyxl"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
