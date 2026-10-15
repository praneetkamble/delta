import sys

import pytest

from delta.adapters import AdapterError, get_adapter
from delta.adapters.mock import MockAdapter
from delta.adapters.windows import WindowsAdapter, safe_launch_target
from delta.config import Config


def test_get_adapter_gives_mock_off_windows(tmp_path):
    a = get_adapter(Config({"data_dir": str(tmp_path)}))
    assert a.name == ("windows" if sys.platform == "win32" else "mock")


@pytest.mark.skipif(sys.platform == "win32", reason="only meaningful off Windows")
def test_windows_adapter_imports_but_refuses_to_run_off_windows():
    with pytest.raises(AdapterError):
        WindowsAdapter()
    with pytest.raises(AdapterError):
        get_adapter(Config({"adapter": "windows"}))


@pytest.mark.parametrize("target,ok", [
    ("chrome", True), ("code", True), ("spotify:", True), ("ms-settings:", True), (r"C:\Program Files\App\app.exe", True), ("my app", True),
    ("calc & del /q *", False), ("calc | more", False), ("x > y", False), ("%COMSPEC%", False), ('evil"', False), ("a^b", False), ("", False), ("a;b", False), ("$(whoami)", False),
])
def test_windows_launch_target_filter(target, ok):
    assert safe_launch_target(target) is ok


def test_mock_adapter_records_calls_and_state(tmp_path):
    a = MockAdapter(trash_dir=tmp_path / "t")
    a.set_volume(150)
    a.set_muted(True)
    a.set_brightness(-5)
    assert a.volume == 100 and a.muted and a.brightness == 0
    f = tmp_path / "x.txt"
    f.write_text("1")
    a.trash(f)
    assert not f.exists() and (tmp_path / "t" / "x.txt").exists()
    f.write_text("2")
    a.trash(f)
    assert len(list((tmp_path / "t").iterdir())) == 2          # name clash in the bin doesn't overwrite
    assert [c[0] for c in a.calls] == ["set_volume", "set_muted", "set_brightness", "trash", "trash"]


def test_every_abstract_method_is_implemented_by_both_adapters():
    from delta.adapters.base import Adapter
    abstract = Adapter.__abstractmethods__
    for cls in (MockAdapter, WindowsAdapter):
        assert not (abstract - set(dir(cls))), cls
        assert not getattr(cls, "__abstractmethods__", frozenset()), cls   # instantiable once on the right OS


def test_base_adapter_psutil_info_works_for_real(tmp_path):
    class Probe(MockAdapter):
        cpu_percent = MockAdapter.__mro__[1].cpu_percent
        memory = MockAdapter.__mro__[1].memory
        disks = MockAdapter.__mro__[1].disks
        processes = MockAdapter.__mro__[1].processes
    p = Probe(trash_dir=tmp_path)
    assert 0 <= p.cpu_percent() <= 100 * 512
    assert p.memory()["total"] > 0
    assert isinstance(p.disks(), list)          # may be empty inside some containers
    assert p.processes(3)
